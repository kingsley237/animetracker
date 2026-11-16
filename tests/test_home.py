"""Phase 4 - one app: Up Next across libraries, Home, unified search."""
import time
from datetime import datetime, timedelta

from tests.conftest import add_anime, pump, wait_until


def _date(d):
    return (datetime.now() + timedelta(days=d)).strftime("%Y-%m-%d")


def _library(db, monkeypatch):
    from tests.test_tv import fake_show
    from core import tmdb
    from core.kinema_sync import fetch_tv_full, save_tv_full
    now = int(time.time())
    ids = {
        "anime_new": add_anime(db, "Fresh Anime", "watching", status="RELEASING", total_episodes=12,
                               next_episode_num=4, next_episode_at=now + 3 * 86400),
        "anime_done": add_anime(db, "Caught Up", "watching", status="RELEASING", total_episodes=12,
                                next_episode_num=2, next_episode_at=now + 2 * 86400),
    }
    for ep in (1, 2):
        db.set_episode_watched(ids["anime_new"], ep, True)
    db.set_episode_watched(ids["anime_done"], 1, True)
    d, pages = fake_show(5, {1: [_date(-20), _date(-13), _date(5)]})
    monkeypatch.setattr(tmdb, "tv_details", lambda sid: d)
    monkeypatch.setattr(tmdb, "get_many", lambda reqs: [pages.get(int(p.split("/")[4])) for p, _ in reqs])
    row, eps = fetch_tv_full(5)
    ids["tv"] = save_tv_full(db, row, eps, "watching")
    db.set_tv_episode_watched(ids["tv"], 1, 1, True)
    return ids


def test_up_next_across_libraries(db, monkeypatch):
    from core import up_next as un
    ids = _library(db, monkeypatch)
    cw = un.continue_watching(db)
    assert [c["id"] for c in cw][:1] == [ids["anime_new"]]          # new episode first
    assert {c["id"] for c in cw} == {ids["anime_new"], ids["tv"]}    # caught-up anime isn't listed
    tv = next(c for c in cw if c["media"] == "tv")
    assert tv["label"].startswith("S01E02")
    up = un.coming_up(db)
    assert [u["id"] for u in up] == [ids["anime_done"], ids["anime_new"], ids["tv"]]   # by date
    un.mark_next(db, tv)
    assert db.tv_progress(ids["tv"])["watched"] == 2


def test_unified_search_finds_all_types(db, monkeypatch):
    from ui.home_page import HomePage
    ids = _library(db, monkeypatch)
    hits = HomePage.find(db, "show")
    assert ids["tv"] in [h["id"] for h in hits]
    assert {h["id"] for h in HomePage.find(db, "anime")} == {ids["anime_new"]}


def test_home_page_and_ctrl_k(qapp, db, monkeypatch):
    from ui.main_window import MainWindow
    for name in ("_check_connection", "_check_anilist_status", "_check_tmdb_status", "_check_for_updates",
                 "_setup_anilist_session", "_maybe_show_onboarding", "_scan_sequels",
                 "_sync_metadata", "_refresh_upcoming", "_refresh_airing", "_scan_notifications",
                 "_sync_movies", "_refresh_open_anime"):
        monkeypatch.setattr(MainWindow, name, lambda self, *a, **k: None)
    ids = _library(db, monkeypatch)
    win = MainWindow(db)
    win.setGeometry(0, 0, 1600, 1000)
    win.show()
    win._open_search()                                   # Ctrl+K
    home = win._home_page
    assert win.current_page == "home" and win.stack.currentWidget() is home
    assert wait_until(lambda: home.hero.item is not None)
    assert home.hero.item["id"] == ids["anime_new"]       # spotlight: the new episode
    assert home.cw_rail.row.count() == 2                  # the TV show + stretch
    assert home.week.count() == 8                         # 7 days + Later
    home.hero.watched.emit(home.hero.item)                # one-click Watched
    assert win.db.get_watched_count(ids["anime_new"]) == 3
    home.search.setText("Fresh")
    assert wait_until(lambda: home.results.isVisible() and home._last_results)
    home._open_first()
    assert win.current_page == "library" and win.detail_panel.isVisible()
    win.close()
    win.deleteLater()
    pump(50)
    import core.anilist_auth as auth
    auth._auth_instance = None
