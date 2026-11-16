"""Kinema TV shows: seasons/episodes, progress, sync & alerts, UI."""
from datetime import datetime, timedelta

import pytest

from tests.conftest import add_anime, pump, wait_until


def _date(days_from_now: int) -> str:
    return (datetime.now() + timedelta(days=days_from_now)).strftime("%Y-%m-%d")


def fake_show(sid, seasons, **kw):
    """seasons: {n: [air_date, ...]} -> TMDB details + season pages."""
    d = {
        "id": sid, "name": kw.pop("name", f"Show {sid}"), "original_name": f"Show {sid}",
        "status": kw.pop("status", "Returning Series"),
        "first_air_date": "2022-01-01", "poster_path": f"/p{sid}.jpg", "backdrop_path": f"/b{sid}.jpg",
        "overview": "A plot.", "vote_average": 8.1, "popularity": 90,
        "genres": [{"name": "Drama"}], "networks": [{"name": "Network"}],
        "episode_run_time": [50], "number_of_episodes": sum(len(v) for v in seasons.values()),
        "videos": {"results": kw.pop("videos", [])},
        "credits": {"cast": []}, "watch/providers": {"results": {}},
        "seasons": [{"season_number": n, "name": f"Season {n}", "episode_count": len(eps),
                     "air_date": eps[0] if eps else kw.get("premieres", {}).get(n)}
                    for n, eps in seasons.items()],
        "next_episode_to_air": kw.pop("next", None),
    }
    kw.pop("premieres", None)
    d.update(kw)
    pages = {n: {"episodes": [{"episode_number": i + 1, "name": f"Ep {n}.{i + 1}",
                               "air_date": a, "runtime": 50} for i, a in enumerate(eps)]}
             for n, eps in seasons.items()}
    return d, pages


@pytest.fixture
def tv_fake(monkeypatch):
    from core import tmdb
    state = {"shows": {}, "pages": {}, "calls": []}

    def get_many(reqs):
        out = []
        for path, _params in reqs:
            parts = path.strip("/").split("/")          # tv/{id}/season/{n}
            state["calls"].append(path)
            out.append(state["pages"].get((int(parts[1]), int(parts[3]))))
        return out

    monkeypatch.setattr(tmdb, "tv_details", lambda sid: state["shows"].get(int(sid)))
    monkeypatch.setattr(tmdb, "get_many", get_many)
    monkeypatch.setattr(tmdb, "has_credentials", lambda: True)

    def put(sid, seasons, **kw):
        d, pages = fake_show(sid, seasons, **kw)
        state["shows"][sid] = d
        for n, p in pages.items():
            state["pages"][(sid, n)] = p
    state["put"] = put
    return state


def add_show(db, tv_fake, sid, seasons, status="watching", **kw):
    from core.kinema_sync import fetch_tv_full, save_tv_full
    tv_fake["put"](sid, seasons, **kw)
    row, eps = fetch_tv_full(sid)
    return save_tv_full(db, row, eps, status)


def _active(db, *kinds):
    out = []
    for k in kinds:
        out += db.get_active_notifications(k)
    return out


# ── data & progress ───────────────────────────────────────────────────────────

def test_progress_next_up_and_upcoming(db, tv_fake):
    sid = add_show(db, tv_fake, 1, {1: [_date(-30), _date(-23), _date(-16)],
                                    2: [_date(-2), _date(5)]})
    p = db.tv_progress(sid)
    assert (p["total"], p["aired"], p["watched"]) == (5, 4, 0)
    assert (p["next"]["season_number"], p["next"]["episode_number"]) == (1, 1)
    assert (p["upcoming"]["season_number"], p["upcoming"]["episode_number"]) == (2, 2)

    db.set_tv_watched_through(sid, 2, 2)      # can't mark the unaired S02E02
    p = db.tv_progress(sid)
    assert p["watched"] == 4 and p["next"] is None and p["unwatched_aired"] == 0
    assert p["minutes"] == 200

    db.set_tv_season_watched(sid, 1, False)
    p = db.tv_progress(sid)
    assert p["watched"] == 1 and (p["next"]["season_number"], p["next"]["episode_number"]) == (1, 1)


def test_refresh_keeps_watched_and_ratings(db, tv_fake):
    from core.kinema_sync import fetch_tv_full
    sid = add_show(db, tv_fake, 2, {1: [_date(-10), _date(-3)]})
    db.set_tv_episode_watched(sid, 1, 1, True)
    db.set_tv_episode_rating(sid, 1, 1, 5)
    db.set_tv_season_rating(sid, 1, 4)
    _row, eps = fetch_tv_full(2)
    db.save_tv_episodes(sid, eps)
    db.save_tv_seasons(sid, _row["_seasons"])
    e = db.get_tv_episodes(sid, 1)[0]
    assert e["watched"] == 1 and e["rating"] == 5
    assert db.get_tv_seasons(sid)[0]["rating"] == 4


def test_tv_isolated_from_anime_and_movies(db, tv_fake):
    anime = add_anime(db, "Anime", "watching")
    add_show(db, tv_fake, 3, {1: [_date(-5)]})
    assert [a["id"] for a in db.get_all_anime(watch_status="watching")] == [anime]
    assert db.get_tv_stats()["watching"] == 1


# ── sync & alerts ─────────────────────────────────────────────────────────────

def test_new_episode_alert_once_and_quiet_baseline(db, tv_fake):
    from core.kinema_sync import KinemaSync
    sid = add_show(db, tv_fake, 4, {1: [_date(-14), _date(-7), _date(3)]})
    KinemaSync(db).sync_tv()                                  # baseline: quiet
    assert not _active(db, "tv_new_episodes")
    # the third episode airs
    tv_fake["put"](4, {1: [_date(-14), _date(-7), _date(0)]})
    KinemaSync(db).sync_tv()
    n = _active(db, "tv_new_episodes")
    assert len(n) == 1 and "S01E03" in n[0]["message"]
    KinemaSync(db).sync_tv()
    assert len(_active(db, "tv_new_episodes")) == 1           # never repeated
    assert db.tv_progress(sid)["aired"] == 3


def test_new_season_and_premiere_date_alerts(db, tv_fake):
    from core.kinema_sync import KinemaSync
    add_show(db, tv_fake, 5, {1: [_date(-100), _date(-93)]}, status="completed")
    KinemaSync(db).sync_tv()
    # Season 2 gets confirmed with no date yet
    tv_fake["put"](5, {1: [_date(-100), _date(-93)], 2: []})
    KinemaSync(db).sync_tv()
    assert [n["title"] for n in _active(db, "tv_new_season")] == ["New season"]
    # later its premiere date is set
    tv_fake["put"](5, {1: [_date(-100), _date(-93)], 2: [_date(40), _date(47)]})
    KinemaSync(db).sync_tv()
    prem = _active(db, "tv_premiere_date")
    assert len(prem) == 1 and "Season 2 premieres" in prem[0]["message"]


def test_dropped_shows_stay_quiet(db, tv_fake):
    from core.kinema_sync import KinemaSync
    add_show(db, tv_fake, 6, {1: [_date(-14), _date(3)]}, status="dropped")
    KinemaSync(db).sync_tv()
    tv_fake["put"](6, {1: [_date(-14), _date(0)], 2: []})
    KinemaSync(db).sync_tv()
    assert not _active(db, "tv_new_episodes", "tv_new_season")


def test_sync_only_refetches_seasons_that_can_change(db, tv_fake):
    from core.kinema_sync import KinemaSync
    add_show(db, tv_fake, 7, {1: [_date(-900)], 2: [_date(-500)], 3: [_date(-30), _date(6)]})
    tv_fake["calls"].clear()
    KinemaSync(db).sync_tv()
    assert tv_fake["calls"] == ["/tv/7/season/3"]


# ── UI ────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tv_window(qapp, db, tv_fake, monkeypatch):
    from ui.main_window import MainWindow
    for name in ("_check_connection", "_check_anilist_status", "_check_for_updates",
                 "_setup_anilist_session", "_maybe_show_onboarding", "_scan_sequels",
                 "_sync_metadata", "_refresh_upcoming", "_refresh_airing", "_scan_notifications",
                 "_sync_movies", "_refresh_open_anime"):
        monkeypatch.setattr(MainWindow, name, lambda self, *a, **k: None)
    add_anime(db, "Some anime", "watching", status="RELEASING")
    ids = {
        # watching, a new episode out 2 days ago, next one in 5 days
        "airing": add_show(db, tv_fake, 10, {1: [_date(-20), _date(-13), _date(-2), _date(5)]}),
        # ended show, 2 episodes
        "ended": add_show(db, tv_fake, 11, {1: [_date(-400), _date(-393)]}, status="watching"),
        "list": add_show(db, tv_fake, 12, {1: [_date(-50)]}, status="planned"),
    }
    db.update_anime(ids["ended"], {"status": "FINISHED"})
    db.set_tv_watched_through(ids["airing"], 1, 2)
    win = MainWindow(db)
    win.setGeometry(0, 0, 1600, 1000)
    win.show()
    assert wait_until(lambda: len(win._cards) > 0)
    yield win, ids
    win.close()
    win.deleteLater()
    pump(50)
    import core.anilist_auth as auth
    auth._auth_instance = None


def test_tv_page_cards(tv_window):
    win, ids = tv_window
    win._navigate("tv")
    assert wait_until(lambda: set(ids.values()) <= set(win._cards))
    assert win.page_title.text() == "TV shows" and win._add_btn.media() == "tv"
    assert [b.text() for b in win._filter_btns.values()] == [
        "All", "Watching", "Watchlist", "Completed", "Dropped"]
    airing = win._cards[ids["airing"]]
    assert airing.status_badge.text() == "NEW EPISODE"
    assert "Next S01E03" in airing.ep_label.text() and "2/3" in airing.ep_label.text()
    assert "S01E04" in airing.countdown_label.text()
    assert win._cards[ids["list"]].status_badge.text() == "AIRING"


def test_tv_panel_marks_episodes_and_completes(tv_window):
    win, ids = tv_window
    win._navigate("tv")
    assert wait_until(lambda: ids["ended"] in win._cards)
    win._on_card_clicked(ids["ended"])
    sec = win.detail_panel.tv_section
    assert sec.isVisible() and sec.main.text().startswith("Up next: S01E01")
    assert sec.season_title.text() == "Season 1" and sec.eps.count() == 2
    sec._toggle(1, 1, True)
    assert sec.main.text().startswith("Up next: S01E02")
    sec._through(1, 2)                       # last episode of an ended show
    row = win.db.get_anime_by_id(ids["ended"])
    assert row["watch_status"] == "completed"
    assert sec.stamp.text() == "COMPLETED" and sec.verdict_card.isVisible()


def test_tv_panel_unaired_episode_locked(tv_window):
    win, ids = tv_window
    win._navigate("tv")
    assert wait_until(lambda: ids["airing"] in win._cards)
    win._on_card_clicked(ids["airing"])
    sec = win.detail_panel.tv_section
    rows = [sec.eps.itemAt(i).widget() for i in range(sec.eps.count())]
    assert [r.tick.isEnabled() for r in rows] == [True, True, True, False]
    assert rows[2].objectName() == "tvEpRowNext"
    assert "S01E04 airs" in sec.next_air.text()


def test_running_show_mark_completed_hidden_and_opens_next_season(tv_window, tv_fake):
    """Dexter-style: S1 fully watched, S2 airing. The panel opens on S2,
    'Mark completed' isn't offered, and marking S1 doesn't touch S2."""
    from tests.test_tv import add_show
    win, _ids = tv_window
    sid = add_show(win.db, tv_fake, 20, {1: [_date(-400), _date(-393)],
                                         2: [_date(-3), _date(4), _date(11)]})
    win.db.update_anime(sid, {"status": "RELEASING"})
    win.db.set_tv_season_watched(sid, 1, True)
    win._navigate("tv")
    assert wait_until(lambda: sid in win._cards)
    win._on_card_clicked(sid)
    sec = win.detail_panel.tv_section
    assert sec._season == 2 and sec.season_title.text() == "Season 2"
    labels = [sec.actions.itemAt(i).widget().text() for i in range(sec.actions.count())]
    assert "Mark completed" not in labels
    p = win.db.tv_progress(sid)
    assert p["watched"] == 2 and (p["next"]["season_number"], p["next"]["episode_number"]) == (2, 1)
    assert win._cards[sid].status_badge.text() in ("NEW EPISODE", "1 TO WATCH")


def test_add_running_show_seen_earlier_seasons(qapp, db, tv_fake, monkeypatch):
    from core import kinema_discover as kd
    from ui.kinema_add_dialog import MovieAddDialog
    tv_fake["put"](21, {1: [_date(-400)], 2: [_date(-300)], 3: [_date(-5), _date(2)]})
    monkeypatch.setattr(kd, "load_source", lambda src, db=None, kind="tv": kd._hits(
        [{"id": 21, "name": "Show 21", "first_air_date": "2022-01-01"}], "tv"))
    monkeypatch.setattr(kd, "genres", lambda kind="tv": [])
    dlg = MovieAddDialog(db, kind="tv")
    assert wait_until(lambda: len(dlg._tiles) == 1)
    dlg._select(dlg._tiles[0].hit)
    b = dlg.browser
    assert wait_until(lambda: b.btn_watched.isEnabled())
    assert b.btn_watched.text().endswith("Seen earlier seasons")
    got = []
    dlg.added.connect(lambda lid, t: got.append(lid))
    dlg._add("completed")
    assert wait_until(lambda: bool(got))
    row = db.get_anime_by_id(got[0])
    p = db.tv_progress(got[0])
    assert row["watch_status"] == "watching" and p["watched"] == 2
    assert (p["next"]["season_number"], p["next"]["episode_number"]) == (3, 1)
