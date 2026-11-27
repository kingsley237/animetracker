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
    up = events.upcoming(date(2026, 11, 27), limit=10)
    assert [e["id"] for e, *_ in up][:3] == ["christmas", "new_year", "season_winter"]
    assert {e["id"] for e, *_ in up} >= {"halloween", "season_spring", "season_summer", "season_fall"}


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


def test_event_spotlight_slides_and_centrepieces(qapp, db, monkeypatch):
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QImage, QPainter
    from core import events
    from ui import decor
    from ui.home_page import HomePage
    ev = events.BY_ID["christmas"]
    page = HomePage(db)
    picks = [{"media_type": "movie", "provider_id": i, "title": f"Film {i}", "poster_url": "", "raw": {},
              "year": 1990} for i in range(3)] + [{"media_type": "movie", "provider_id": 9, "title": "Saved",
                                                    "poster_url": "", "raw": {}, "_lib_id": 42}]
    slides = page._event_slides(ev, picks)
    assert slides[0]["kind"] == "event" and slides[0]["title"] == "4 picks for Christmas"
    assert slides[0]["blurb"] == ev["tagline"] and "Next pick" in slides[0]["secondary"][0]
    assert [s["badge"] for s in slides[1:]] == ["CHRISTMAS PICK"] * 4
    assert slides[-1]["primary"][0] == "Open details"                 # already on your Watchlist
    assert page._event_slides(ev, [])[0]["title"] == "Merry Christmas"  # offline: greeting slide alone
    img = QImage(400, 300, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    for eid in ("christmas", "halloween", "new_year", "season"):
        decor.draw_hero(p, QRectF(0, 0, 400, 300), 1.3, eid)           # every centrepiece paints
    p.end()
    season = events.active(__import__("datetime").date(2026, 10, 3))
    assert season["category"] == "anime" and events.intensity(season, "raiko_night") == "decorations"
    page.deleteLater()
    pump(20)
