"""Miroku in the Kinema style: anime cards, Watching panel, removed screens."""
import pytest

from tests.conftest import add_anime, pump, wait_until


@pytest.fixture
def win(qapp, db, monkeypatch):
    from ui.main_window import MainWindow
    for name in ("_check_connection", "_check_anilist_status", "_check_for_updates",
                 "_setup_anilist_session", "_maybe_show_onboarding", "_scan_sequels",
                 "_sync_metadata", "_refresh_upcoming", "_refresh_airing", "_scan_notifications",
                 "_sync_movies", "_refresh_open_anime"):
        monkeypatch.setattr(MainWindow, name, lambda self, *a, **k: None)
    ids = {
        "done": add_anime(db, "Finished Show", "watching", status="FINISHED", total_episodes=3),
        "air": add_anime(db, "Airing Show", "watching", status="RELEASING", total_episodes=12,
                         next_episode_num=5, next_episode_at=2_000_000_000),
    }
    for ep in (1, 2, 3):
        db.set_episode_watched(ids["air"], ep, True)
    w = MainWindow(db)
    w.setGeometry(0, 0, 1600, 1000)
    w.show()
    assert wait_until(lambda: set(ids.values()) <= set(w._cards))
    yield w, ids
    w.close()
    w.deleteLater()
    pump(50)
    import core.anilist_auth as auth
    auth._auth_instance = None


def test_anime_cards_read_like_tv(win):
    w, ids = win
    card = w._cards[ids["air"]]
    assert card.status_badge.text() == "NEW EPISODE"            # ep 4 aired, unwatched
    assert card.ep_label.text().startswith("Next Ep 4  ·  3/12")
    assert "1 left" in card.countdown_label.text()
    assert not card.score_badge_lbl.isVisible() and not card.ep_cover_badge.isVisible()


def test_watching_panel_marks_and_completes(win):
    w, ids = win
    w._on_card_clicked(ids["done"])
    sec = w.detail_panel.watch_section
    assert sec.isVisible() and sec.main.text() == "Up next: Episode 1"
    assert not w.detail_panel._episodes_card.isVisible()
    sec._toggle(1, True)
    assert sec.main.text() == "Up next: Episode 2"
    sec._through(3)                                   # last episode of a finished show
    assert w.db.get_anime_by_id(ids["done"])["watch_status"] == "completed"
    assert not sec.isVisible()


def test_unaired_episodes_locked_with_air_time(win):
    w, ids = win
    w._on_card_clicked(ids["air"])
    sec = w.detail_panel.watch_section
    rows = [sec.eps.itemAt(i).widget() for i in range(sec.eps.count())]
    assert len(rows) == 12
    assert [r.tick.isEnabled() for r in rows][:6] == [True, True, True, True, False, False]
    assert rows[3].objectName() == "tvEpRowNext"
    assert "Episode 5 of 12 airs" in sec.next_air.text()


def test_retired_screens_are_gone():
    import importlib.util
    import ui.main_window as mw
    pages = [pid for _s, items in mw.NAV_SECTIONS for _l, _t, pid in items]
    assert not {"calendar", "stream", "hof", "stats"} & set(pages)
    for mod in ("ui.stats_page", "ui.release_calendar_page", "ui.animestream_page"):
        assert importlib.util.find_spec(mod) is None


def test_hall_of_fame_only_titles_join_completed(tmp_path):
    from core.database import DatabaseManager
    d = DatabaseManager(tmp_path / "lib.db")
    aid = add_anime(d, "Favourite", "completed", total_episodes=3)
    d._get_conn().execute("UPDATE anime SET hof_only=1 WHERE id=?", (aid,))
    d._get_conn().commit()
    assert not d.get_all_anime(watch_status="completed")
    d.close()
    d = DatabaseManager(tmp_path / "lib.db")              # next start: converted
    assert [a["id"] for a in d.get_all_anime(watch_status="completed")] == [aid]
    assert d.get_watched_count(aid) == 3
    assert list((tmp_path / "backups").glob("anime_pre_hof_*.db"))
    d.close()


def test_anime_browser_adds_watching(qapp, db, monkeypatch):
    from core import miroku_discover as md, api
    from ui.kinema_add_dialog import MovieAddDialog
    media = {"id": 77, "title": {"romaji": "Kono Anime", "english": "This Anime"},
             "status": "RELEASING", "episodes": 12, "seasonYear": 2026, "genres": ["Action"],
             "coverImage": {"large": ""}, "averageScore": 81, "format": "TV",
             "nextAiringEpisode": {"airingAt": 2_000_000_000, "episode": 5}}
    monkeypatch.setattr(md, "load_source", lambda src, db=None, kind="anime": md._hits([media]))
    monkeypatch.setattr(api, "get_metadata_batch", lambda ids, batch=5: {77: media})
    dlg = MovieAddDialog(db, kind="anime")
    assert wait_until(lambda: len(dlg._tiles) == 1)
    assert dlg.browser.btn_watchlist.text().endswith("Plan to Watch")
    got = []
    dlg.added.connect(lambda lid, t: got.append(lid))
    dlg._select(dlg._tiles[0].hit)
    assert wait_until(lambda: dlg.browser.btn_watching.isEnabled())
    assert not dlg.browser.btn_watched.isEnabled()          # still airing: can't be finished
    dlg._add("watching")
    assert wait_until(lambda: bool(got))
    row = db.get_anime_by_id(got[0])
    assert row["anilist_id"] == 77 and row["watch_status"] == "watching"
    assert row["next_episode_num"] == 5


def test_link_label_presets_fill_label_and_platform(qapp, db):
    from ui.anime_links import LinkEditDialog
    aid = add_anime(db, "X", "watching")
    dlg = LinkEditDialog(aid, db)
    btn = next(b for b in dlg._preset_btns if b.text() == "Crunchyroll")
    btn.click()
    assert dlg.label_edit.text() == "Crunchyroll"
    assert dlg.platform_combo.currentData() == "crunchyroll"
    next(b for b in dlg._preset_btns if b.text() == "Episodes").click()
    assert dlg.label_edit.text() == "Episodes"


def test_status_banners_themed_and_stacked(win):
    w, _ids = win
    w._status_banner("anilist").show_banner("The AniList API has been temporarily disabled.")
    w._status_banner("tmdb").show_banner("TMDB isn't responding properly (HTTP 503).")
    a, t = w._status_banners["anilist"], w._status_banners["tmdb"]
    assert a.is_shown() and t.is_shown() and a.parentWidget() is w.centralWidget()
    assert a.y() + a.height() <= t.y()                       # stacked, AniList above TMDB
    assert a.x() >= w.sidebar.width()                        # never over the sidebar
    w._on_went_offline()                                     # offline: services can't be judged
    assert w._status_banners["offline"].is_shown() and not a.is_shown() and not t.is_shown()
    w._on_tmdb_down("x")
    assert not t.is_shown()
