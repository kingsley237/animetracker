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


def add_movie_unreleased(db, state, mid, **kw):
    from core.providers import movie_row
    state["movies"][mid] = fake_movie(mid, status="Planned", **kw)
    return db.save_tmdb_title(movie_row(state["movies"][mid]), "planned")


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

def _active(db, *kinds):
    out = []
    for k in kinds:
        out += db.get_active_notifications(k)
    return out


def test_release_state():
    from core.kinema_sync import release_state
    now = int(time.time())
    assert release_state({"status": "NOT_YET_RELEASED", "cinema_date": _date(10)}, now)["state"] == "unreleased"
    assert release_state({"status": "Released", "cinema_date": _date(-10)}, now)["state"] == "cinema"
    assert release_state({"cinema_date": _date(-40), "digital_date": _date(-1)}, now)["state"] == "digital"
    assert release_state({"cinema_date": _date(-40), "digital_available": 1}, now)["state"] == "digital"


def test_out_in_hd_alerts_once_on_transition(db, tmdb_fake):
    from core.kinema_sync import KinemaSync
    mid = add_movie(db, tmdb_fake, 10, release_date=_date(-20),
                    rel=[{"type": 3, "release_date": _date(-20) + "T00:00:00Z"}])
    KinemaSync(db).sync_movies()                         # quiet baseline (in cinemas)
    assert not _active(db, "movie_digital", "movie_theaters")
    # digital date gets announced -> one heads-up
    tmdb_fake["movies"][10] = fake_movie(10, release_date=_date(-20), rel=[
        {"type": 3, "release_date": _date(-20) + "T00:00:00Z"},
        {"type": 4, "release_date": _date(5) + "T00:00:00Z"}])
    KinemaSync(db).sync_movies()
    assert [n["kind"] for n in _active(db, "movie_digital_date")] == ["movie_digital_date"]
    # it lands to rent -> exactly one "Out in HD"
    tmdb_fake["movies"][10] = fake_movie(10, release_date=_date(-20), rel=[
        {"type": 3, "release_date": _date(-20) + "T00:00:00Z"},
        {"type": 4, "release_date": _date(5) + "T00:00:00Z"}],
        providers={"rent": [{"provider_name": "Apple TV Store", "display_priority": 1}]})
    res = KinemaSync(db).sync_movies()
    hd = [n for n in res["notifications"] if n["kind"] == "movie_digital"]
    assert len(hd) == 1 and "Apple TV Store" in hd[0]["message"]
    KinemaSync(db).sync_movies()
    assert len(_active(db, "movie_digital")) == 1      # never repeated
    assert db.get_anime_by_id(mid)["digital_available"] == 1


def test_cinema_alerts_only_when_chosen(db, tmdb_fake):
    from core.app_settings import app_settings
    from core.kinema_sync import KinemaSync
    add_movie(db, tmdb_fake, 11, status="planned")
    tmdb_fake["movies"][11] = fake_movie(11, status="Planned", release_date=_date(20),
                                         rel=[{"type": 3, "release_date": _date(20) + "T00:00:00Z"}])
    KinemaSync(db).sync_movies()                          # baseline
    tmdb_fake["movies"][11] = fake_movie(11, release_date=_date(-1),
                                         rel=[{"type": 3, "release_date": _date(-1) + "T00:00:00Z"}])
    KinemaSync(db).sync_movies()
    assert not _active(db, "movie_theaters")              # default: digital only
    app_settings().setValue("movie_alert_mode", "both")
    db._get_conn().execute("UPDATE anime SET cinema_date=? WHERE tmdb_id=11", (_date(30),))
    db._get_conn().commit()
    KinemaSync(db).sync_movies()
    assert [n["kind"] for n in _active(db, "movie_theaters")] == ["movie_theaters"]
    app_settings().setValue("movie_alert_mode", "off")


def test_trailer_alert_after_baseline_and_watched_stay_quiet(db, tmdb_fake):
    from core.kinema_sync import KinemaSync
    add_movie(db, tmdb_fake, 12, status="planned")
    add_movie(db, tmdb_fake, 13, status="completed",
              providers={"flatrate": [{"provider_name": "Netflix"}]})
    KinemaSync(db).sync_movies()
    tmdb_fake["movies"][12] = fake_movie(12, videos=[{"site": "YouTube", "key": "NEW", "type": "Trailer"}])
    res = KinemaSync(db).sync_movies()
    assert [n["kind"] for n in res["notifications"]] == ["upcoming_trailer"]
    del tmdb_fake["movies"][13]                           # offline: data kept
    KinemaSync(db).sync_movies()
    assert db.get_title_by_tmdb("movie", 13)["romaji_title"] == "Film 13"


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
        "soon": add_movie_unreleased(db, tmdb_fake, 20, release_date=_date(30),
                                     rel=[{"type": 3, "release_date": _date(30) + "T00:00:00Z"}]),
        "list": add_movie(db, tmdb_fake, 21, status="planned"),
        "ready": add_movie(db, tmdb_fake, 23, status="planned",
                           providers={"rent": [{"provider_name": "Apple TV Store"}]}),
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
    assert win._add_btn.media() == "movie" and win._empty_add.media() == "movie"
    badges = {aid: c.status_badge.text() for aid, c in win._cards.items()}
    assert badges[ids["soon"]] == "COMING SOON" and badges[ids["seen"]] == "WATCHED"
    assert badges[ids["list"]] == "IN CINEMAS" and badges[ids["ready"]] == "READY TO WATCH"
    from ui.completed_view import SectionHeader
    heads = [win.grid_layout.itemAt(i).widget() for i in range(win.grid_layout.count())]
    texts = [h.text() for h in heads if hasattr(h, "text") and not isinstance(h, SectionHeader)
             and "〡" in (h.text() or "")]
    assert texts[0].startswith("〡 READY TO WATCH") and texts[1].startswith("〡 WAITING FOR HD")
    assert not win._cards[ids["seen"]].progress_bar.isVisibleTo(win._cards[ids["seen"]])
    win._navigate("library")
    assert wait_until(lambda: set(win._cards) == anime_cards)
    assert "behind" in win._filter_btns and win._add_btn.media() == "anime"


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
    assert sec.stamp.text() == "IN CINEMAS · WAITING FOR HD"
    # Mark as watched from the panel -> verdict appears, card moves
    sec._mark_watched()
    pump(300)
    assert win.db.get_anime_by_id(ids["list"])["watch_status"] == "completed"
    assert sec.verdict_card.isVisibleTo(sec) and sec.stamp.text() == "✓  WATCHED"
    sec._log_rewatch()
    assert win.db.rewatch_count(ids["list"]) == 1


def test_unreleased_cannot_be_marked_watched(movie_window):
    win, ids = movie_window
    win._navigate("movies")
    assert wait_until(lambda: ids["soon"] in win._cards)
    win._on_card_clicked(ids["soon"])
    pump(300)
    sec = win.detail_panel.movie_section
    labels = [sec.actions.itemAt(i).widget().text() for i in range(sec.actions.count())]
    assert not any("watched" in t.lower() for t in labels)
    # a film already wrongly marked watched offers the fix
    win.db.update_anime(ids["soon"], {"watch_status": "completed"})
    win._close_detail_panel()
    win.detail_panel.load_anime(win.db.get_anime_by_id(ids["soon"]))
    assert sec.stamp.text() == "NOT OUT YET"
    sec._to_watchlist()
    assert win.db.get_anime_by_id(ids["soon"])["watch_status"] == "planned"


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
