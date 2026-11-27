"""Event themes: dates, intensity model, banner and coach mark."""
from datetime import date

from tests.conftest import pump


def test_windows_and_new_year_wrap():
    from core import events
    assert events.active(date(2026, 12, 24))["id"] == "christmas"
    assert events.active(date(2026, 12, 31))["id"] == "new_year"
    assert events.active(date(2027, 1, 2))["id"] == "new_year"
    assert events.active(date(2026, 10, 31))["id"] == "halloween"
    assert events.active(date(2026, 11, 27)) is None
    ny = events.BY_ID["new_year"]
    assert events.season_key(ny, date(2027, 1, 1)) == events.season_key(ny, date(2026, 12, 31)) == "new_year-2026"
    up = events.upcoming(date(2026, 11, 27))
    assert [e["id"] for e, *_ in up] == ["christmas", "new_year", "halloween"]


def test_intensity_respects_an_explicit_theme(monkeypatch):
    from core import events
    from ui.themes_catalog import build
    monkeypatch.setenv("RAIKO_DATE", "2026-12-25")
    ev = events.active()
    # default look -> the full event theme
    t, e, level = events.resolve(build("raiko_night"), "raiko_night")
    assert e["id"] == "christmas" and level == "full" and t.extra["event"] == "christmas"
    assert t.roles != build("raiko_night").roles and t.extra.get("ornaments")
    # a theme you chose yourself -> it stays; only decorations are added
    own = build("sakura_dawn")
    t, e, level = events.resolve(own, "sakura_dawn")
    assert level == "decorations" and t.roles == own.roles and t.extra.get("ornaments")
    # your banner choice wins for this year; a per-event setting otherwise
    events.set_choice(ev, "off")
    assert events.resolve(own, "sakura_dawn")[2] == "off"
    events.set_choice(ev, "kept")
    events.set_setting("christmas", "full")
    assert events.resolve(own, "sakura_dawn")[2] == "full"
    events.set_setting("christmas", "auto")
    events.set_ask_first(True)
    assert events.resolve(own, "sakura_dawn")[2] == "decorations"      # 'kept' = already answered
    events.set_choice(ev, "")
    assert events.resolve(own, "sakura_dawn")[2] == "off"              # ask first: nothing until yes
    events.set_ask_first(False)


def test_banner_flows_and_coach_mark_once(qapp, monkeypatch):
    from PyQt6.QtWidgets import QMainWindow, QPushButton, QVBoxLayout, QWidget
    from core import events
    from ui.event_banner import EventBanner, show_coach_mark
    from ui.theme import ThemeManager
    monkeypatch.setenv("RAIKO_DATE", "2026-10-30")
    tm = ThemeManager.get()
    tm.save("raiko_night", "", 1.0)
    tm.reapply()
    assert tm.event["id"] == "halloween" and tm.event_level == "full"
    win = QMainWindow()
    c = QWidget()
    v = QVBoxLayout(c)
    win._settings_btn = QPushButton("Settings")
    v.addWidget(win._settings_btn)
    b = EventBanner()
    v.addWidget(b)
    win.setCentralWidget(c)
    win.resize(900, 600)
    win.show()
    b.refresh()
    assert not b.isHidden()
    b._off()
    assert tm.event_level == "off" and not tm.theme.extra.get("event")      # switched back
    b.refresh()
    assert b.isHidden()                                                     # once per event per year
    events.set_choice(tm.event, "")
    tm.reapply()
    b.refresh()
    b._pick("hw_yokai")
    assert tm.theme.id == "hw_yokai" and events.variant(tm.event) == "hw_yokai"
    events.set_choice(tm.event, "")
    b.refresh()
    b._close()                                                              # ✕: stays, coach mark once
    pump(20)
    assert events.choice(tm.event) == "kept" and show_coach_mark(win) is None
    win.close()
    monkeypatch.delenv("RAIKO_DATE")
    tm.reapply()
    assert tm.event is None
    pump(20)
