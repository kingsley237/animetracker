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


def _sched(ep, total, pop, mid=500, color="#f1a143", when=None):
    import time as _t
    return {"episode": ep, "airingAt": when or int(_t.time()), "media": {
        "id": mid, "title": {"english": f"Show {mid}", "romaji": ""}, "popularity": pop, "episodes": total,
        "status": "RELEASING", "format": "TV", "isAdult": False, "averageScore": 84,
        "coverImage": {"large": "c", "color": color}, "bannerImage": "b", "trailer": {"id": "tr", "site": "youtube"},
        "characters": {"nodes": [{"name": {"full": f"Hero {i}"}, "image": {"large": f"img{i}"}} for i in range(6)]}}}


def test_anime_events_premiere_farewell_and_yours_first(db, monkeypatch):
    from core import anime_events
    from tests.conftest import add_anime
    add_anime(db, "Mine", "watching", anilist_id=7)
    monkeypatch.setattr(anime_events, "_schedule", lambda a, b: [
        _sched(1, 12, 300_000, mid=1), _sched(5, 12, 900_000, mid=2),     # big premiere; mid-season episode
        _sched(24, 24, 40_000, mid=7)])                                   # finale of a show you watch
    ev = anime_events.detect(db)
    assert ev["kind"] == "farewell" and ev["anilist_id"] == 7 and ev["lib_id"]   # yours beats more popular
    assert len(ev["portraits"]) == 5 and ev["greeting"] == "Thank you, Show 7"
    monkeypatch.setattr(anime_events, "_schedule", lambda a, b: [_sched(1, 12, 300_000, mid=1),
                                                                 _sched(1, 12, 20_000, mid=3)])
    ev = anime_events.detect(db)
    assert ev["kind"] == "premiere" and ev["anilist_id"] == 1
    monkeypatch.setattr(anime_events, "_schedule", lambda a, b: [_sched(1, 12, 20_000, mid=3)])
    assert anime_events.detect(db) is None                                # not anticipated, not yours


def test_show_event_decorates_and_offers_its_colours(qapp, db, monkeypatch):
    from core import anime_events, events
    from ui.theme import ThemeManager, contrast
    from ui.themes_catalog import build
    monkeypatch.setattr(anime_events, "_schedule", lambda a, b: [_sched(1, 12, 300_000, mid=1, color="#93281a")])
    ev = anime_events.detect(db)
    day = events.today().strftime("%Y-%m-%d")
    ev["date"] = day
    anime_events.store(day, ev)
    assert events.active()["id"] == ev["id"]                              # beats the calendar for its day
    t, e, level = events.resolve(build("raiko_night"), "raiko_night")
    assert level == "decorations" and t.roles == build("raiko_night").roles and t.extra.get("event")
    events.set_choice(e, "full")
    t, e, level = events.resolve(build("raiko_night"), "raiko_night")
    acc = t.roles["violet"]
    assert level == "full" and contrast(acc, "#12141d") >= 3 and contrast("#0b0d12", acc) >= 4.5
    events.set_choice(e, "")
    tm = ThemeManager.get()
    tm.reapply()
    from ui.event_banner import EventBanner, _Portraits
    b = EventBanner()
    b.refresh()
    assert b.findChildren(_Portraits) and not b.isHidden()
    from ui.home_page import HomePage
    page = HomePage(db)
    s = page._event_slides(ev, [])
    assert len(s) == 1 and s[0]["badge"] == "PREMIERE DAY" and len(s[0]["portraits"]) == 5
    assert s[0]["secondary"][0].endswith("Trailer") and s[0]["primary"][0].startswith("Preview")
    anime_events.store(day, None)
    tm.reapply()
    b.deleteLater()
    page.deleteLater()
    pump(20)


def test_milestones_once_and_quiet_first_time(db):
    from core import milestones
    from tests.conftest import add_anime
    for i in range(9):
        add_anime(db, f"M{i}", "completed", media_type="movie")
    assert milestones.check(db) is None                                   # first run: quiet baseline
    add_anime(db, "M9", "completed", media_type="movie")
    assert milestones.check(db) == ("movies", 10)
    assert milestones.check(db) is None                                   # never twice


def test_holiday_and_show_share_a_day(qapp, db, monkeypatch):
    from core import anime_events, events
    from ui.theme import ThemeManager
    monkeypatch.setenv("RAIKO_DATE", "2026-10-31")
    monkeypatch.setattr(anime_events, "_schedule", lambda a, b: [_sched(1, 12, 300_000, mid=1)])
    monkeypatch.setattr(anime_events, "tmdb_art", lambda *a: {"logo": "", "backdrops": []})
    monkeypatch.setattr(anime_events, "prefetch", lambda ev: None)
    ev = anime_events.detect(db)
    ev["date"] = "2026-10-31"
    anime_events.store("2026-10-31", ev)
    evs = events.active_all()
    assert [e["id"] for e in evs] == ["halloween", ev["id"]]              # the holiday keeps the look
    tm = ThemeManager.get()
    tm.reapply()
    assert tm.event["id"] == "halloween" and len(tm.events) == 2
    from ui.event_banner import EventBanner
    b = EventBanner()
    b.refresh()
    assert len(b.findChildren(type(b._inner), "eventBannerInner")) == 1
    from PyQt6.QtWidgets import QFrame
    assert b.findChildren(QFrame, "eventBannerSep")                       # two rows
    from ui.home_page import HomePage
    page = HomePage(db)
    page._load_event_picks()
    assert len(page._events) == 2
    # the logo dresses up and names the day
    from PyQt6.QtGui import QPixmap
    from ui import event_logo
    px = event_logo.render(QPixmap(), tm.event)
    assert not px.isNull() and event_logo.subtitle(tm.event, 2026) == "Happy Halloween"
    assert event_logo.subtitle(ev, 2026).startswith("Premiere")
    anime_events.store("2026-10-31", None)
    tm.reapply()
    b.deleteLater()
    page.deleteLater()
    pump(20)


def test_moments_once_each(qapp, db):
    from PyQt6.QtWidgets import QMainWindow, QWidget
    from core import events
    from ui.event_message import EventMoment, show_moment
    win = QMainWindow()
    win.setCentralWidget(QWidget())
    win.resize(1000, 700)
    ev = events.EVENTS[0]
    m = show_moment(win, ev)
    assert isinstance(m, EventMoment) and m.card.width() > 0
    m.card.grab()                                                         # paints without error
    m.close_moment()
    assert show_moment(win, ev) is None                                   # once
    m2 = show_moment(win, ev, force=True)                                 # re-open from the banner
    assert m2 is not None
    m2.close_moment()
    win.deleteLater()
    pump(20)
