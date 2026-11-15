"""Kinema movies: storage, isolation from anime, sync & alerts, UI."""
import time
from datetime import datetime, timedelta

import pytest

from tests.conftest import add_anime, pump, wait_until

DAY = 86400


def _date(days_from_now: int) -> str:
    return (datetime.now() + timedelta(days=days_from_now)).strftime("%Y-%m-%d")


def fake_movie(mid, **kw):
    d = {
        "id": mid, "title": kw.pop("title", f"Film {mid}"), "original_title": f"Film {mid}",
        "status": kw.pop("status", "Released"), "runtime": kw.pop("runtime", 120),
        "release_date": kw.pop("release_date", "2024-03-01"),
        "poster_path": kw.pop("poster", f"/p{mid}.jpg"), "backdrop_path": f"/b{mid}.jpg",
        "overview": "A plot.", "vote_average": 7.5, "popularity": 50,
        "genres": [{"name": "Drama"}], "production_companies": [{"name": "Studio"}],
        "videos": {"results": kw.pop("videos", [])},
        "credits": {"cast": [{"name": "Lead", "character": "Hero"}]},
        "release_dates": {"results": [{"iso_3166_1": "US", "release_dates": kw.pop("rel", [
            {"type": 3, "release_date": "2024-03-01T00:00:00Z"}])}]},
        "watch/providers": {"results": {"US": kw.pop("providers", {})}},
        "belongs_to_collection": kw.pop("collection", None),
    }
    d.update(kw)
    return d


@pytest.fixture
def tmdb_fake(monkeypatch):
    """Control TMDB responses: state['movies'][id] = details dict."""
    from core import tmdb
    state = {"movies": {}, "search": [], "collections": {}}
    monkeypatch.setattr(tmdb, "movie_details", lambda mid: state["movies"].get(int(mid)))
    monkeypatch.setattr(tmdb, "search", lambda q, kind="multi", page=1: list(state["search"]))
    monkeypatch.setattr(tmdb, "trending", lambda kind="all", window="week", page=1: list(state["search"]))
    monkeypatch.setattr(tmdb, "collection", lambda cid: state["collections"].get(int(cid)))
    monkeypatch.setattr(tmdb, "has_credentials", lambda: True)
    return state


def add_movie(db, state, mid, status="planned", **kw):
    from core.providers import movie_row
    state["movies"][mid] = fake_movie(mid, **kw)
    return db.save_tmdb_title(movie_row(state["movies"][mid]), status)


# ── storage & isolation ───────────────────────────────────────────────────────

def test_save_is_idempotent_and_drops_provider_extras(db, tmdb_fake):
    a = add_movie(db, tmdb_fake, 1, collection={"id": 9, "name": "Saga"},
                  videos=[{"site": "YouTube", "key": "T1", "type": "Trailer"},
                          {"site": "YouTube", "key": "T2", "type": "Teaser"}])
    b = add_movie(db, tmdb_fake, 1, status="completed")
    assert a == b
    row = db.get_anime_by_id(a)
    assert row["media_type"] == "movie" and row["watch_status"] == "completed"
    assert row["trailer_id"] == "T1" and [v["id"] for v in row["videos"]] == ["T2"]
    assert "_collection" not in row and row["completed_at"]


def test_movies_never_leak_into_anime(db, tmdb_fake):
    anime = add_anime(db, "Anime", "completed")
    add_movie(db, tmdb_fake, 2, status="completed")
    assert [a["id"] for a in db.get_all_anime(watch_status="completed")] == [anime]
    assert db.get_stats()["completed"] == 1
    assert [r["romaji_title"] for r in db.search_titles("Film", "movie")] == ["Film 2"]
    assert all(r.get("media_type") != "movie" for r in db.search_anime("Film"))


def test_movie_stats(db, tmdb_fake):
    add_movie(db, tmdb_fake, 3, status="planned")
    w = add_movie(db, tmdb_fake, 4, status="completed", runtime=150)
    r = db.start_rewatch(w)
    db.finish_rewatch(r, 1)
    s = db.get_movie_stats()
    assert s == {"watchlist": 1, "watched": 1, "hours": 5, "this_year": 1}


# ── sync & alerts ─────────────────────────────────────────────────────────────

def _kinds(db):
    return {n["kind"] for n in db.get_active_notifications("movie_streaming")} | \
           {n["kind"] for n in db.get_active_notifications("movie_theaters")} | \
           {n["kind"] for n in db.get_active_notifications("upcoming_date")} | \
           {n["kind"] for n in db.get_active_notifications("upcoming_trailer")}


def test_streaming_and_theaters_alerts(db, tmdb_fake):
    from core.kinema_sync import KinemaSync
    add_movie(db, tmdb_fake, 10, providers={"flatrate": [{"provider_name": "Netflix", "display_priority": 1}]})
    add_movie(db, tmdb_fake, 11, status="planned", release_date=_date(-1),
              rel=[{"type": 3, "release_date": _date(-1) + "T00:00:00Z"}])
    res = KinemaSync(db).sync_movies()
    msgs = {n["kind"]: n["message"] for n in res["notifications"]}
    assert "Netflix" in msgs["movie_streaming"]
    assert "in theaters" in msgs["movie_theaters"]
    before = db._get_conn().execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    KinemaSync(db).sync_movies()
    assert db._get_conn().execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == before


def test_date_and_trailer_alerts_only_after_baseline(db, tmdb_fake):
    from core.kinema_sync import KinemaSync
    mid = add_movie(db, tmdb_fake, 12, status="planned")
    tmdb_fake["movies"][12] = fake_movie(12, status="Planned", release_date=_date(60),
                                         rel=[{"type": 3, "release_date": _date(60) + "T00:00:00Z"}])
    KinemaSync(db).sync_movies()                       # baseline
    assert not _kinds(db)
    tmdb_fake["movies"][12] = fake_movie(12, status="Planned", release_date=_date(75),
                                         rel=[{"type": 3, "release_date": _date(75) + "T00:00:00Z"}],
                                         videos=[{"site": "YouTube", "key": "NEW", "type": "Trailer"}])
    res = KinemaSync(db).sync_movies()
    assert {"upcoming_date", "upcoming_trailer"} <= {n["kind"] for n in res["notifications"]}
    assert db.get_anime_by_id(mid)["trailer_id"] == "NEW"


def test_watched_movies_raise_no_alerts_and_offline_keeps_data(db, tmdb_fake):
    from core.kinema_sync import KinemaSync
    mid = add_movie(db, tmdb_fake, 13, status="completed",
                    providers={"flatrate": [{"provider_name": "Netflix"}]})
    KinemaSync(db).sync_movies()
    assert not _kinds(db)
    del tmdb_fake["movies"][13]                        # "offline"
    KinemaSync(db).sync_movies()
    assert db.get_anime_by_id(mid)["romaji_title"] == "Film 13"


# ── UI ────────────────────────────────────────────────────────────────────────

@pytest.fixture
def movie_window(qapp, db, tmdb_fake, monkeypatch):
    from ui.main_window import MainWindow
    for name in ("_check_connection", "_check_anilist_status", "_check_for_updates",
                 "_setup_anilist_session", "_maybe_show_onboarding", "_scan_sequels",
                 "_sync_metadata", "_refresh_upcoming", "_refresh_airing", "_scan_notifications",
                 "_sync_movies"):
        monkeypatch.setattr(MainWindow, name, lambda self, *a, **k: None)
    add_anime(db, "Some anime", "watching", status="RELEASING")
    ids = {
        "soon": add_movie(db, tmdb_fake, 20, status="planned", release_date=_date(30)),
        "list": add_movie(db, tmdb_fake, 21, status="planned"),
        "seen": add_movie(db, tmdb_fake, 22, status="completed"),
    }
    db.update_anime(ids["soon"], {"status": "NOT_YET_RELEASED"})
    win = MainWindow(db)
    win.showNormal()
    win.setGeometry(0, 0, 1600, 1000)
    win.show()
    assert wait_until(lambda: len(win._cards) > 0)
    yield win, ids
    win.close()
    win.deleteLater()
    pump(50)
    import core.anilist_auth as auth
    auth._auth_instance = None


def test_movies_page_switches_library(movie_window):
    win, ids = movie_window
    anime_cards = set(win._cards)
    win._navigate("movies")
    assert wait_until(lambda: set(win._cards) == set(ids.values()))
    assert list(win._filter_btns) == ["all", "planned", "completed"]
    assert win._filter_btns["planned"].text() == "Watchlist"
    assert win._add_btn.text() == "+  Add Movie"
    badges = {aid: c.status_badge.text() for aid, c in win._cards.items()}
    assert badges[ids["soon"]] == "COMING SOON" and badges[ids["seen"]] == "WATCHED"
    assert not win._cards[ids["seen"]].progress_bar.isVisibleTo(win._cards[ids["seen"]])
    win._navigate("library")
    assert wait_until(lambda: set(win._cards) == anime_cards)
    assert "behind" in win._filter_btns and win._add_btn.text() == "+  Add Anime"


def test_movie_panel_modes(movie_window):
    win, ids = movie_window
    win._navigate("movies")
    assert wait_until(lambda: ids["list"] in win._cards)
    dp = win.detail_panel
    win._on_card_clicked(ids["list"])
    pump(300)
    sec = dp.movie_section
    assert sec.isVisibleTo(dp) and not dp._episodes_card.isVisibleTo(dp)
    assert not dp.status_btn.isVisibleTo(dp) and not sec.verdict_card.isVisibleTo(sec)
    assert sec.stamp.text() == "ON YOUR WATCHLIST"
    # Mark as watched from the panel -> verdict appears, card moves
    sec._mark_watched()
    pump(300)
    assert win.db.get_anime_by_id(ids["list"])["watch_status"] == "completed"
    assert sec.verdict_card.isVisibleTo(sec) and sec.stamp.text() == "✓  WATCHED"
    sec._log_rewatch()
    assert win.db.rewatch_count(ids["list"]) == 1


def test_add_movie_dialog(qapp, db, tmdb_fake):
    from core.providers import _hit
    from ui.kinema_add_dialog import MovieAddDialog
    tmdb_fake["movies"][30] = fake_movie(30, title="New Film")
    tmdb_fake["search"] = [dict(tmdb_fake["movies"][30], media_type="movie")]
    dlg = MovieAddDialog(db)
    assert wait_until(lambda: len(dlg._tiles) == 1)
    got = []
    dlg.added.connect(lambda lid, t: got.append((lid, t)))
    dlg._select(dlg._tiles[0].hit)
    dlg._add("planned")
    assert wait_until(lambda: bool(got))
    row = db.get_anime_by_id(got[0][0])
    assert row["romaji_title"] == "New Film" and row["watch_status"] == "planned"
