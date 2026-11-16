"""Data Doctor checks (anime, movies, TV, app) and the Open Data Doctor alerts."""
from datetime import datetime, timedelta

from tests.conftest import add_anime, pump, wait_until


def _ids(db):
    from core.data_health import Scanner
    return {i.issue_id: i for i in Scanner(db).scan()}


def _date(d):
    return (datetime.now() + timedelta(days=d)).strftime("%Y-%m-%d")


def test_anime_checks_and_fixes(db):
    over = add_anime(db, "Over", "watching", total_episodes=2, status="FINISHED")
    for ep in (1, 2, 3):
        db.set_episode_watched(over, ep, True)
    done = add_anime(db, "Done", "watching", total_episodes=2, status="FINISHED")
    for ep in (1, 2):
        db.set_episode_watched(done, ep, True)
    backlog = add_anime(db, "Backlog", "watching", total_episodes=12, status="FINISHED")
    db.set_episode_watched(backlog, 1, True)
    found = _ids(db)
    assert f"overcount_{over}" in found and f"status_mismatch_{done}" in found
    assert f"status_mismatch_{backlog}" not in found          # half-watched finished show is fine
    found[f"overcount_{over}"].fix_fn()
    found[f"status_mismatch_{done}"].fix_fn()
    found = _ids(db)
    assert f"overcount_{over}" not in found and f"status_mismatch_{done}" not in found
    assert db.get_anime_by_id(done)["watch_status"] == "completed"


def test_movie_and_tv_checks(db, monkeypatch):
    from core import tmdb
    from tests.test_movies import fake_movie
    from tests.test_tv import fake_show
    from core.providers import movie_row
    from core.kinema_sync import save_tv_full, fetch_tv_full
    m = db.save_tmdb_title(movie_row(fake_movie(5, status="Planned", release_date=_date(30),
                                                rel=[{"type": 3, "release_date": _date(30) + "T00:00:00Z"}])),
                           "completed")
    db.update_anime(m, {"status": "NOT_YET_RELEASED"})
    d, pages = fake_show(9, {1: [_date(-10), _date(4)]})
    monkeypatch.setattr(tmdb, "tv_details", lambda sid: d)
    monkeypatch.setattr(tmdb, "get_many", lambda reqs: [pages.get(int(p.split("/")[4])) for p, _ in reqs])
    row, eps = fetch_tv_full(9)
    show = save_tv_full(db, row, eps, "planned")
    db._get_conn().execute("UPDATE tv_episodes SET watched=1 WHERE anime_id=?", (show,))
    db._get_conn().commit()
    found = _ids(db)
    assert {f"movie_unreleased_{m}", f"tv_future_{show}", f"tv_planned_progress_{show}"} <= set(found)
    assert found[f"movie_unreleased_{m}"].area == "Movies"
    found[f"tv_future_{show}"].fix_fn()
    assert db.tv_progress(show)["watched"] == 1


def test_error_log_is_reported_until_reviewed(db, monkeypatch, tmp_path):
    import core.data_health as dh
    log = tmp_path / "error.log"
    log.write_text(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] Traceback (most recent call last):\n"
                   '  File "x.py", line 1, in f\nRuntimeError: boom\n', encoding="utf-8")
    monkeypatch.setattr(dh, "ERROR_LOG", log)
    found = _ids(db)
    assert "app_errors" in found and "boom" in found["app_errors"].detail
    found["app_errors"].fix_fn()
    assert "app_errors" not in _ids(db)


def test_health_check_raises_one_doctor_alert(qapp, db, monkeypatch):
    from ui.main_window import MainWindow
    for name in ("_check_connection", "_check_anilist_status", "_check_for_updates",
                 "_setup_anilist_session", "_maybe_show_onboarding", "_scan_sequels",
                 "_sync_metadata", "_refresh_upcoming", "_refresh_airing", "_scan_notifications",
                 "_sync_movies"):
        monkeypatch.setattr(MainWindow, name, lambda self, *a, **k: None)
    a = add_anime(db, "Over", "watching", total_episodes=1, status="FINISHED")
    for ep in (1, 2):
        db.set_episode_watched(a, ep, True)
    win = MainWindow(db)
    win.show()
    opened = []
    monkeypatch.setattr(win, "open_data_doctor", lambda: opened.append(1))
    win.notification_banner.open_doctor.disconnect()
    win.notification_banner.open_doctor.connect(win.open_data_doctor)
    win._health_check()
    assert wait_until(lambda: db.get_active_notifications("data_health"))
    win._health_check()                                   # same problems: no second alert
    pump(400)
    assert len(db.get_active_notifications("data_health")) == 1
    item = db.get_active_notifications("data_health")[0]
    labels = [l for l, _cb, _p in win.notification_banner._actions_for(item)]
    assert labels[0].endswith("Open Data Doctor")
    win.notification_banner._actions_for(item)[0][1]()
    assert opened == [1]
    win.close()
    win.deleteLater()
    pump(50)
    import core.anilist_auth as auth
    auth._auth_instance = None
