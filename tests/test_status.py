"""Status switcher rules (movies, TV, anime) + Videos & music tabs."""
from datetime import datetime, timedelta

from tests.conftest import add_anime, pump, wait_until


def _d(days):
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def _tv(db, monkeypatch, seasons, status="Returning Series", ws="watching", sid=7):
    from tests.test_tv import fake_show
    from core import tmdb
    from core.kinema_sync import fetch_tv_full, save_tv_full
    d, pages = fake_show(sid, seasons, status=status)
    monkeypatch.setattr(tmdb, "tv_details", lambda _sid: d)
    monkeypatch.setattr(tmdb, "get_many", lambda reqs: [pages.get(int(p.split("/")[4])) for p, _ in reqs])
    row, eps = fetch_tv_full(sid)
    return save_tv_full(db, row, eps, ws)


def _opts(db, lid):
    from core.status_rules import options
    return {o["key"]: o for o in options(db, db.get_anime_by_id(lid))}


def test_running_tv_can_be_finished_and_reopens(db, monkeypatch):
    from core.status_rules import apply, plan, reopen_if_new_episodes
    lid = _tv(db, monkeypatch, {1: [_d(-30), _d(-23), _d(-16)]})     # running, 3 aired
    db.set_tv_episode_watched(lid, 1, 1, True)
    o = _opts(db, lid)
    assert o["completed"]["allowed"] and o["completed"]["label"] == "Finished"
    assert "2 remaining" in plan(db, db.get_anime_by_id(lid), "completed")["confirm"]
    apply(db, db.get_anime_by_id(lid), "completed")
    assert db.get_anime_by_id(lid)["watch_status"] == "completed"
    assert db.tv_progress(lid)["unwatched_aired"] == 0
    assert not reopen_if_new_episodes(db, lid)                    # nothing new yet
    db.save_tv_episodes(lid, [{"season_number": 2, "episode_number": 1, "name": "New",
                               "air_date": _d(-1), "runtime": 50}])
    assert reopen_if_new_episodes(db, lid)
    assert db.get_anime_by_id(lid)["watch_status"] == "watching"


def test_unaired_tv_only_watchlist(db, monkeypatch):
    lid = _tv(db, monkeypatch, {1: [_d(10), _d(17)]}, ws="planned")
    o = _opts(db, lid)
    assert o["planned"]["current"]
    for k in ("watching", "completed", "dropped"):
        assert not o[k]["allowed"] and "premiered" in o[k]["reason"]


def test_movie_rules(db):
    from core.status_rules import apply
    future = add_anime(db, "Future", "planned", media_type="movie", status="NOT_YET_RELEASED",
                       cinema_date=_d(40))
    o = _opts(db, future)
    assert set(o) == {"planned", "completed"} and not o["completed"]["allowed"]
    assert "Not out yet" in o["completed"]["reason"]
    out = add_anime(db, "Out", "planned", media_type="movie", status="FINISHED", cinema_date=_d(-60))
    assert _opts(db, out)["completed"]["allowed"]
    apply(db, db.get_anime_by_id(out), "completed")
    assert db.get_anime_by_id(out)["watch_status"] == "completed"
    apply(db, db.get_anime_by_id(out), "planned")
    assert db.get_anime_by_id(out)["watch_status"] == "planned"


def test_anime_rules(db):
    from core.status_rules import apply, plan
    airing = add_anime(db, "Airing", "watching", status="RELEASING", total_episodes=12, next_episode_num=5)
    o = _opts(db, airing)
    assert not o["completed"]["allowed"] and "Still airing" in o["completed"]["reason"]
    assert o["planned"]["allowed"] and o["dropped"]["allowed"]
    soon = add_anime(db, "Soon", "planned", status="NOT_YET_RELEASED")
    o = _opts(db, soon)
    assert not o["watching"]["allowed"] and not o["completed"]["allowed"] and not o["dropped"]["allowed"]
    done = add_anime(db, "Done", "watching", status="FINISHED", total_episodes=4)
    db.set_episode_watched(done, 1, True)
    p = plan(db, db.get_anime_by_id(done), "completed")
    assert p["allowed"] and "all 4 episodes" in p["confirm"]
    apply(db, db.get_anime_by_id(done), "completed")
    assert db.get_watched_count(done) == 4
    assert db.get_anime_by_id(done)["watch_status"] == "completed"


def test_detail_panel_switcher(qapp, db, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from ui.detail_panel import DetailPanel
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    lid = _tv(db, monkeypatch, {1: [_d(-30), _d(-23)]})
    panel = DetailPanel(db)
    got = []
    panel.watch_status_changed.connect(lambda i, s: got.append(s))
    panel.load_anime(db.get_anime_by_id(lid))
    btns = panel.status_switch.buttons
    assert set(btns) == {"planned", "watching", "completed", "dropped"}
    assert btns["watching"].property("current") == "true"
    btns["completed"].click()
    assert got == ["completed"] and db.get_anime_by_id(lid)["watch_status"] == "completed"
    assert "new episodes" in panel.status_switch.hint.text().lower()
    panel.deleteLater()
    pump(20)


# ── music ─────────────────────────────────────────────────────────────────────

def test_music_pick_filters_and_ranks():
    from core.music import pick
    row = {"media_type": "anime", "english_title": "Bleach", "romaji_title": "Bleach"}
    res = [
        {"id": "a", "title": "Bleach opening 1 REACTION", "channel": "x", "secs": 300},
        {"id": "b", "title": "Naruto Opening 1", "channel": "x", "secs": 90},
        {"id": "c", "title": "Bleach Opening 1 piano cover", "channel": "x", "secs": 120},
        {"id": "d", "title": "Bleach opening 1 creditless", "channel": "fan", "secs": 92},
        {"id": "e", "title": "OPENING 1 | BLEACH | Asterisk", "channel": "VIZ", "secs": 96},
        {"id": "f", "title": "Bleach opening full 1 hour", "channel": "x", "secs": 3600},
        {"id": "g", "title": "Bleach Ending 2", "channel": "x", "secs": 90},
    ]
    assert [i["id"] for i in pick(row, "op", res)] == ["e", "d"]        # official first, noise gone
    assert [i["id"] for i in pick(row, "ed", res)] == ["g"]
    assert pick(row, "op", res)[0]["thumb"].endswith("/e/hqdefault.jpg")


def test_gallery_music_tabs(qapp, monkeypatch):
    from core import music
    from ui.video_gallery import VideoGallery
    calls = []

    def fake_find(row, tab, refresh=False):
        calls.append(tab)
        return [{"id": f"{tab}1", "site": "youtube", "kind": tab, "title": f"{tab} one", "thumb": ""}]
    monkeypatch.setattr(music, "find", fake_find)
    g = VideoGallery("No trailers.")
    g.load([{"id": "t1", "site": "youtube", "kind": "promo", "title": "Trailer", "thumb": ""}], "Show")
    g.set_media({"id": 1, "media_type": "tv", "english_title": "Show"})
    assert list(g._tab_btns) == ["trailers", "intro", "ost"] and g._items[0]["id"] == "t1"
    g.show_tab("intro")
    assert wait_until(lambda: g._items and g._items[0]["id"] == "intro1")
    g.show_tab("trailers")
    assert g._items[0]["id"] == "t1"
    g.show_tab("intro")                                   # cached: no second search
    assert calls == ["intro"] and g._items[0]["id"] == "intro1"
    g.set_media({"id": 2, "media_type": "movie", "english_title": "Film"})
    assert list(g._tab_btns) == ["trailers", "ost"] and g._tab == "trailers"
    g.set_media({"id": 3, "media_type": "anime", "english_title": "A"})
    assert list(g._tab_btns) == ["trailers", "op", "ed", "ost"]
    g.deleteLater()
    pump(20)


def test_finishing_moves_to_completed_with_undo(db, monkeypatch):
    from core.status_rules import auto_complete, sweep, undo_auto_complete
    # anime that finished airing: last episode watched -> Completed
    aid = add_anime(db, "Done", "watching", total_episodes=3)
    for n in (1, 2):
        db.set_episode_watched(aid, n, True)
    assert auto_complete(db, aid) is None                        # one left
    db.set_episode_watched(aid, 3, True)
    m = auto_complete(db, aid)
    assert m["label"] == "Completed" and m["prev"] == "watching"
    assert db.get_anime_by_id(aid)["watch_status"] == "completed"
    # Undo puts it back and isn't overruled on the next check
    undo_auto_complete(db, m)
    assert db.get_anime_by_id(aid)["watch_status"] == "watching"
    assert auto_complete(db, aid) is None
    db.set_episode_watched(aid, 3, False)                        # started over: the undo is forgotten
    assert auto_complete(db, aid) is None
    db.set_episode_watched(aid, 3, True)
    assert auto_complete(db, aid)["id"] == aid
    # still airing: caught up stays in Watching
    rid = add_anime(db, "Airing", "watching", status="RELEASING", total_episodes=12, next_episode_num=3)
    for n in (1, 2):
        db.set_episode_watched(rid, n, True)
    assert auto_complete(db, rid) is None
    # TV: an ended show fully watched -> Finished; a running one stays
    tid = _tv(db, monkeypatch, {1: [_d(-30), _d(-23)]}, status="Ended", sid=11)
    db.set_tv_episode_watched(tid, 1, 1, True)
    assert auto_complete(db, tid) is None
    db.set_tv_episode_watched(tid, 1, 2, True)
    assert auto_complete(db, tid)["label"] == "Finished"
    run = _tv(db, monkeypatch, {1: [_d(-30), _d(-23)]}, sid=12)
    db.set_tv_episode_watched(run, 1, 1, True)
    db.set_tv_episode_watched(run, 1, 2, True)
    assert auto_complete(db, run) is None
    # start-up sweep catches ones that were already finished
    old = add_anime(db, "Old", "watching", total_episodes=2)
    db.set_episode_watched(old, 1, True)
    db.set_episode_watched(old, 2, True)
    assert [m["id"] for m in sweep(db)] == [old]


def test_auto_complete_toast_and_undo_in_window(qapp, db, monkeypatch):
    from ui.main_window import MainWindow
    from ui.toast import Toast
    for name in ("_refresh_catalog", "_check_connection", "_check_anilist_status", "_check_tmdb_status",
                 "_check_for_updates", "_setup_anilist_session", "_maybe_show_onboarding", "_scan_sequels",
                 "_sync_metadata", "_refresh_upcoming", "_refresh_airing", "_scan_notifications",
                 "_sync_movies", "_refresh_open_anime", "_check_anime_event"):
        if hasattr(MainWindow, name):
            monkeypatch.setattr(MainWindow, name, lambda self, *a, **k: None)
    aid = add_anime(db, "Finale", "watching", total_episodes=2)
    db.set_episode_watched(aid, 1, True)
    win = MainWindow(db)
    db.set_episode_watched(aid, 2, True)
    win._on_episode_changed(aid)
    assert wait_until(lambda: db.get_anime_by_id(aid)["watch_status"] == "completed", 3)
    toasts = [t for t in win.findChildren(Toast) if getattr(t, "action_btn", None)]
    assert toasts and "Finale" in toasts[-1].msg.text()
    toasts[-1].action_btn.click()
    assert db.get_anime_by_id(aid)["watch_status"] == "watching"
    win.close()
    win.deleteLater()
    pump(50)
