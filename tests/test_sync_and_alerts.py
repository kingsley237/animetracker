"""Metadata sync, new-season detection, videos and the completed timeline."""
import time
from datetime import datetime

import pytest

from tests.conftest import DAY, add_anime


# ── fake AniList data ─────────────────────────────────────────────────────────

def media(mid, **kw):
    m = {
        "id": mid, "idMal": kw.pop("idMal", None),
        "title": {"romaji": kw.pop("romaji", f"Show {mid}"), "english": kw.pop("english", None)},
        "coverImage": {"large": kw.pop("cover", f"https://img/{mid}.jpg"), "color": "#123456"},
        "bannerImage": kw.pop("banner", None), "description": kw.pop("description", "Plot."),
        "status": kw.pop("status", "NOT_YET_RELEASED"), "format": "TV", "source": "MANGA",
        "episodes": kw.pop("episodes", None), "duration": 24, "season": "WINTER", "seasonYear": 2027,
        "startDate": kw.pop("startDate", {"year": 2027, "month": 1, "day": None}),
        "endDate": kw.pop("endDate", {}), "nextAiringEpisode": kw.pop("nextAiringEpisode", None),
        "trailer": kw.pop("trailer", None), "averageScore": 80, "popularity": 1000,
        "genres": ["Drama"], "siteUrl": "", "studios": {"nodes": [{"name": "Studio"}]},
        "characters": {"edges": [{"role": "MAIN", "node": {"name": {"full": "Hero"}, "image": {"medium": ""}}}]},
    }
    m.update(kw)
    return m


@pytest.fixture
def anilist(monkeypatch):
    """Control what get_metadata_batch / get_sequels return."""
    state = {"meta": {}, "sequels": {}}
    import core.api as api
    monkeypatch.setattr(api, "get_metadata_batch",
                        lambda ids, batch=5: {i: state["meta"][i] for i in ids if i in state["meta"]})
    monkeypatch.setattr(api, "get_sequels",
                        lambda ids, batch=8: {i: state["sequels"].get(i, []) for i in ids})
    return state


# ── metadata sync ─────────────────────────────────────────────────────────────

def test_media_to_row_only_marks_exact_dates_exact():
    from core.metadata_sync import media_to_row
    vague = media_to_row(media(1, startDate={"year": 2027, "month": 1, "day": None}))
    exact = media_to_row(media(1, startDate={"year": 2027, "month": 1, "day": 9}))
    assert vague["start_exact"] == 0 and vague["start_ts"] is None
    assert exact["start_exact"] == 1 and exact["start_ts"]
    assert exact["characters"][0]["name"] == "Hero"


def test_first_sync_is_quiet_baseline_then_changes_notify(db, anilist):
    from core.metadata_sync import MetadataSync
    aid = add_anime(db, "Planned", "planned", anilist_id=10, status="NOT_YET_RELEASED",
                    total_episodes=None, cover_url="https://img/10.jpg")
    anilist["meta"][10] = media(10)
    r = MetadataSync(db).sync()
    assert not r["notifications"]                     # nothing "new" on the baseline
    assert db.get_anime_by_id(aid)["meta_synced_at"]

    # nothing changed -> nothing reported
    assert MetadataSync(db).sync()["changed"] == []

    # episode count + trailer + confirmed day appear
    anilist["meta"][10] = media(10, episodes=12, trailer={"id": "YT1", "site": "youtube"},
                                startDate={"year": 2027, "month": 1, "day": 9})
    r = MetadataSync(db).sync()
    kinds = {n["kind"] for n in r["notifications"]}
    assert {"upcoming_trailer", "upcoming_episodes", "upcoming_date"} <= kinds
    row = db.get_anime_by_id(aid)
    assert row["total_episodes"] == 12 and row["trailer_id"] == "YT1" and row["start_exact"] == 1


def test_new_poster_forces_redownload(db, anilist):
    from core.metadata_sync import MetadataSync
    aid = add_anime(db, "W", "watching", anilist_id=11, cover_url="https://img/old.jpg",
                    cover_local="C:/cache/old.jpg")
    anilist["meta"][11] = media(11, cover="https://img/new.jpg", status="RELEASING")
    r = MetadataSync(db).sync()
    assert aid in r["art_changed"]
    row = db.get_anime_by_id(aid)
    assert row["cover_url"] == "https://img/new.jpg" and not row["cover_local"]


def test_sync_never_wipes_existing_fields(db, anilist):
    from core.metadata_sync import MetadataSync
    aid = add_anime(db, "W", "watching", anilist_id=12, description="Keep this synopsis",
                    trailer_id="KEEP", trailer_site="youtube")
    anilist["meta"][12] = media(12, description="", trailer=None, status="RELEASING")
    MetadataSync(db).sync()
    row = db.get_anime_by_id(aid)
    assert row["description"] == "Keep this synopsis" and row["trailer_id"] == "KEEP"


# ── new-season detection ──────────────────────────────────────────────────────

def _sequel(sid, status, start=None, end=None):
    return media(sid, status=status, startDate=start or {"year": 2027, "month": 1, "day": None},
                 endDate=end or {})


def test_announced_without_day_is_not_alerted_but_recorded(db, anilist):
    from core.notification_service import NotificationService
    pre = add_anime(db, "S1", "completed", anilist_id=100)
    anilist["sequels"][100] = [_sequel(200, "NOT_YET_RELEASED")]
    assert NotificationService(db).scan_sequels() == []
    info = db.get_anime_by_id(pre)["sequel_info"]
    assert '"phase": "announced"' in info


def test_announced_with_confirmed_day_alerts_once(db, anilist):
    from core.notification_service import NotificationService
    add_anime(db, "S1", "completed", anilist_id=100)
    anilist["sequels"][100] = [_sequel(200, "NOT_YET_RELEASED", {"year": 2027, "month": 1, "day": 9})]
    first = NotificationService(db).scan_sequels()
    again = NotificationService(db).scan_sequels()
    assert len(first) == 1 and first[0]["payload"]["phase"] == "announced"
    assert [n["id"] for n in again] == [first[0]["id"]]


def test_undated_alert_from_before_the_rule_is_withdrawn(db, anilist):
    from core.notification_service import NotificationService
    add_anime(db, "S1", "completed", anilist_id=100)
    db.upsert_notification({"fingerprint": "new-season:200:announced", "kind": "new_season",
                            "anilist_id": 200, "title": "t", "message": "m",
                            "payload": {"phase": "announced"}})
    anilist["sequels"][100] = [_sequel(200, "NOT_YET_RELEASED")]
    NotificationService(db).scan_sequels()
    assert not db.get_active_notifications("new_season")


def test_airing_alerts_and_old_complete_is_skipped(db, anilist):
    from core.notification_service import NotificationService
    a = add_anime(db, "A", "completed", anilist_id=101)
    b = add_anime(db, "B", "completed", anilist_id=102)
    old = int(time.time()) - 400 * DAY
    db._get_conn().execute("UPDATE anime SET last_watched_at=?, last_updated=? WHERE id IN (?,?)",
                           (old, old, a, b))
    db._get_conn().commit()
    anilist["sequels"][101] = [_sequel(201, "RELEASING")]
    anilist["sequels"][102] = [_sequel(202, "FINISHED", end={"year": 2020, "month": 1, "day": 1})]
    res = NotificationService(db).scan_sequels()
    assert [n["anilist_id"] for n in res] == [201]


def test_sequel_already_in_library_is_not_alerted(db, anilist):
    from core.notification_service import NotificationService
    add_anime(db, "S1", "completed", anilist_id=100)
    add_anime(db, "S2", "planned", anilist_id=200, status="RELEASING")
    anilist["sequels"][100] = [_sequel(200, "RELEASING")]
    assert NotificationService(db).scan_sequels() == []


def test_local_scan_never_returns_new_season(db):
    from core.notification_service import NotificationService
    db.upsert_notification({"fingerprint": "ns", "kind": "new_season", "title": "t", "message": "m"})
    assert all(n["kind"] != "new_season" for n in NotificationService(db).scan())


def test_copy_for_dropped_and_movie():
    from core.notification_service import new_season_copy
    _, msg = new_season_copy({"phase": "complete",
                              "sequel": {"title": "The Movie", "format": "MOVIE", "episodes": 1},
                              "prequel": {"title": "Show", "source": "dropped", "last_episode": 5}})
    assert "all 1 episodes" not in msg and "dropped Show at ep 5" in msg


# ── videos ────────────────────────────────────────────────────────────────────

def test_video_playlist_merges_and_dedupes():
    from core.videos import build_playlist, parse_jikan_videos
    mal = parse_jikan_videos({
        "promo": [{"title": "PV 1", "trailer": {"youtube_id": "A", "images": {}}},
                  {"title": "Dup", "trailer": {"youtube_id": "T", "images": {}}},
                  {"title": "Broken", "trailer": {}}],
        "music_videos": [{"title": "OP", "video": {"youtube_id": "M", "images": {}},
                          "meta": {"title": "Song", "author": "Band"}}],
    })
    pl = build_playlist({"trailer_id": "T", "trailer_site": "youtube"}, mal)
    assert [v["id"] for v in pl] == ["T", "A", "M"]
    assert pl[-1]["kind"] == "music" and "Song" in pl[-1]["title"]


def test_video_fetch_offline_returns_none():
    from core import videos
    videos._failed_at.clear()
    assert videos.fetch_mal_videos(12345) is None     # network blocked -> "couldn't ask"
    assert videos.fetch_mal_videos(None) == []


# ── completed timeline grouping ───────────────────────────────────────────────

def test_completed_grouping_and_fold_defaults():
    from ui.completed_view import default_collapsed, group_completed
    now = datetime(2026, 11, 14)
    ts = lambda y, m, d: int(datetime(y, m, d).timestamp())
    items = [{"id": 1, "completed_at": ts(2026, 11, 2)}, {"id": 2, "completed_at": ts(2026, 3, 1)},
             {"id": 3, "completed_at": ts(2025, 6, 1)}, {"id": 4, "completed_at": ts(2026, 11, 10)}]
    groups = group_completed(items, now=now, rewatching={2})
    assert [k for k, _l, _m in groups] == ["rewatching", "month", "2025"]
    assert [a["id"] for a in groups[1][2]] == [4, 1]        # newest first
    assert not default_collapsed("month") and default_collapsed("2025")
    assert not default_collapsed("rewatching")
