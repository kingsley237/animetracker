"""Notifications while Raikō is closed + taskbar badge (no real tasks/registry/toasts)."""
import sys

from tests.conftest import add_anime, pump, wait_until


def _alert(db, aid, fp, kind="episode_aired"):
    db.upsert_notification({"fingerprint": fp, "kind": kind, "anime_id": aid, "anilist_id": None,
                            "title": "New episode", "message": "Ep 5 is out."})


def test_only_new_events_notify_once_and_baseline_on_enable(db, monkeypatch):
    import core.background_check as bc
    shown = []
    monkeypatch.setattr(bc, "show", lambda items: shown.append([n["fingerprint"] for n in items]) or len(items))
    monkeypatch.setattr(bc, "_schtasks", lambda *a: True)
    monkeypatch.setattr(bc, "register", lambda: None)
    monkeypatch.setattr(sys, "platform", "win32")
    a = add_anime(db, "Show", "watching")
    _alert(db, a, "old-1")                         # already known when the feature is switched on
    assert bc.enable(db, 3) and bc.enabled() and bc.interval_hours() == 3
    assert bc.pending(db) == []                    # baseline: no flood
    _alert(db, a, "new-1")
    _alert(db, a, "inapp-only", kind="incomplete_completion")
    assert bc.notify_new(db) == 1 and shown == [["new-1"]]
    assert bc.notify_new(db) == 0                  # never twice
    bc.disable()
    assert not bc.enabled()


def test_task_runs_check_hidden_with_wake_and_logon(monkeypatch):
    import core.background_check as bc
    xml = bc._task_xml(6)
    assert "<Interval>PT6H</Interval>" in xml and "<LogonTrigger>" in xml
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml and "<Hidden>true</Hidden>" in xml
    assert "--check" in xml and "<ExecutionTimeLimit>PT5M</ExecutionTimeLimit>" in xml


def test_toast_text_keeps_accents():
    import core.background_check as bc
    x = bc._toast_xml("Raikō", "Frieren — Episode 5 & more", "raiko://open/7")
    assert "Raikō" in x and "&amp; more" in x and 'launch="raiko://open/7"' in x


def test_notification_link_parsing(monkeypatch):
    import main
    monkeypatch.setattr(sys, "argv", ["Raiko.exe", "raiko://open/97/"])
    assert main._open_target() == "open:97"
    monkeypatch.setattr(sys, "argv", ["Raiko.exe"])
    assert main._open_target() == "show"
    monkeypatch.setattr(sys, "argv", ["Raiko.exe", "raiko://open/abc"])
    assert main._open_target() == "show"


def test_open_from_notification_and_badge(qapp, db, monkeypatch):
    from ui.main_window import MainWindow
    for name in ("_check_connection", "_check_anilist_status", "_check_tmdb_status", "_check_for_updates",
                 "_setup_anilist_session", "_scan_sequels", "_maybe_show_onboarding",
                 "_sync_metadata", "_refresh_upcoming", "_refresh_airing", "_scan_notifications",
                 "_sync_movies", "_refresh_open_anime", "_refresh_catalog"):
        monkeypatch.setattr(MainWindow, name, lambda self, *a, **k: None)
    a = add_anime(db, "Show", "watching")
    win = MainWindow(db)
    win.show()
    from PyQt6.QtGui import QIcon, QPixmap, QColor
    px = QPixmap(64, 64)
    px.fill(QColor("#222"))
    win.setWindowIcon(QIcon(px))
    win._update_badge()
    assert win._badge_n == 0
    _alert(db, a, "x-1")
    _alert(db, a, "x-2", kind="movie_digital")
    win._update_badge()
    assert win._badge_n == 2
    win.handle_external(f"open:{a}")
    assert wait_until(lambda: win.detail_panel.isVisible()) and win.selected_anime_id == a
    for n in db.get_active_notifications("episode_aired") + db.get_active_notifications("movie_digital"):
        db.dismiss_notification(n["id"])
    win._update_badge()
    assert win._badge_n == 0
    win.close()
    win.deleteLater()
    pump(50)
    import core.anilist_auth as auth
    auth._auth_instance = None
