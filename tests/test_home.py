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
    assert wait_until(lambda: bool(home.hero.slides))
    first = home.hero.slides[0]
    assert first["badge"] == "NEW EPISODE" and first["kind"] == "update"
    assert home.hero.item["id"] == ids["anime_new"]       # spotlight: the new episode
    assert home.cw_rail.row.count() == 4                  # anime, TV, caught-up anime + stretch
    assert home.week.count() == 8                         # 7 days + Later
    assert home.hero.btn1.text().startswith("✓  Watched")
    home.hero._run(1)                                     # one-click Watched
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


def test_onboarding_welcome_and_tour(qapp, db, monkeypatch):
    from core.app_settings import app_settings
    from ui.main_window import MainWindow
    for name in ("_check_connection", "_check_anilist_status", "_check_tmdb_status", "_check_for_updates",
                 "_setup_anilist_session", "_scan_sequels", "_maybe_show_onboarding",
                 "_sync_metadata", "_refresh_upcoming", "_refresh_airing", "_scan_notifications",
                 "_sync_movies", "_refresh_open_anime"):
        monkeypatch.setattr(MainWindow, name, lambda self, *a, **k: None)
    _library(db, monkeypatch)
    win = MainWindow(db)
    win.setGeometry(0, 0, 1600, 1000)
    win.show()
    win._navigate("home")
    win.start_onboarding(upgrading=True)
    heads = [l.text() for l in win._welcome.findChildren(type(win.page_title)) if l.objectName() == "welcomeHead"]
    assert heads == ["Miroku is now Raikō"]
    win._welcome.country.setCurrentIndex(win._welcome.country.findData("CM"))
    win._welcome._close(True)                                   # take the tour
    assert app_settings().value("tmdb_region") == "CM"
    assert app_settings().value("onboarding_v3_seen", False, type=bool)
    tour = win._tour
    for i in range(len(tour._steps)):
        assert tour._current == i
        pump(120)
        assert not tour._spotlight.isNull(), tour._steps[i][1]  # every step finds its target
        tour._next()
    pump(50)
    assert win.current_page == "home"
    win.close()
    win.deleteLater()
    pump(50)
    import core.anilist_auth as auth
    auth._auth_instance = None


def test_home_spotlight_when_caught_up(qapp, db, monkeypatch):
    """Nothing to continue: the spotlight shows what airs next, never an empty Home."""
    from ui.home_page import HomePage
    now = int(time.time())
    aid = add_anime(db, "Weekly Show", "watching", status="RELEASING", total_episodes=12,
                    next_episode_num=3, next_episode_at=now + 2 * 86400)
    for ep in (1, 2):
        db.set_episode_watched(aid, ep, True)
    page = HomePage(db)
    page.resize(1400, 900)
    page.show()
    page.load()
    assert wait_until(lambda: bool(page.hero.slides))
    sl = page.hero.slides[0]
    assert sl["badge"] == "NEXT TO AIR" and sl["item"]["id"] == aid
    assert page.hero.badge.text() == "NEXT TO AIR" and page.hero.btn1.text() == "See the episodes"
    assert not page.hero.btn2.isVisible()
    assert "caught up" in page.caught_up.text() and page.caught_up.isVisible()
    page.close()



def test_spotlight_tells_library_news_from_picks(qapp, db, monkeypatch):
    from ui.home_page import HomePage
    from core import up_next as un
    hit = {"media_type": "movie", "provider_id": 99, "title": "Some Film", "year": 2024, "score": 80,
           "overview": "A film.", "poster_url": "", "raw": {}, "reason": "Because you watched X"}
    monkeypatch.setattr(un, "picks", lambda db, per_kind=3: [hit])
    HomePage._PICKS.update(at=0, hits=[])
    page = HomePage(db)
    page.resize(1400, 900)
    page.show()
    opened = []
    page.open_pick.connect(lambda h: opened.append(h["provider_id"]))
    page.load()
    assert wait_until(lambda: any(s["kind"] == "pick" for s in page.hero.slides))
    pick = next(k for k, s in enumerate(page.hero.slides) if s["kind"] == "pick")
    page.hero.show_slide(pick)
    assert page.hero.badge.text() == "FOR YOU" and page.hero.reason.text() == "Because you watched X"
    assert page.hero.btn1.text() == "Preview && add"
    page.hero._run(1)
    assert opened == [99]
    assert page.pk_rail.row.count() == 2 and page.pk_rail.isVisible()
    page.close()
