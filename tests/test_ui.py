"""
UI smoke + regression tests (offscreen Qt, temp database, offline).

Each one guards something that actually broke during development:
stray top-level windows, the panel covering cards, sideways scrolling in
the panel, clipped episode ticks, boxed episode labels, mode-specific
panels, the Completed timeline/archive, dropped cards, rewatch surfaces,
and the trailer playlist.
"""
import time

import pytest

from tests.conftest import DAY, add_anime, pump, wait_until, watch


@pytest.fixture
def library(db):
    now = int(time.time())
    ids = {}
    for i in range(7):
        ids[f"w{i}"] = add_anime(db, f"Watching {i}", "watching", status="RELEASING",
                                 total_episodes=12, next_episode_num=6,
                                 next_episode_at=now + 3 * DAY, anilist_id=1000 + i)
        watch(db, ids[f"w{i}"], 4)
    ids["planned"] = add_anime(db, "Planned", "planned", status="NOT_YET_RELEASED",
                               total_episodes=None, anilist_id=2000,
                               trailer_id="YT", trailer_site="youtube",
                               start_ts=now + 30 * DAY, start_exact=1,
                               characters=[{"name": "Hero", "role": "Main", "image": ""}])
    for i in range(5):
        cid = add_anime(db, f"Done {i}", "completed", total_episodes=10, anilist_id=3000 + i)
        watch(db, cid, 10, start_ts=now - (40 + i * 200) * DAY)
        db.update_anime(cid, {"completed_at": now - (30 + i * 200) * DAY})
        for ep in range(1, 11):
            db.set_rating(cid, ep, 3 + ep % 4)
        ids[f"c{i}"] = cid
    drop = add_anime(db, "Dropped show", "watching", anilist_id=4000)
    watch(db, drop, 3)
    db.delete_anime(drop, drop=True, reason="Too slow")
    return ids


@pytest.fixture
def window(qapp, db, library, monkeypatch):
    from ui.main_window import MainWindow
    for name in ("_check_connection", "_check_anilist_status", "_check_for_updates",
                 "_setup_anilist_session", "_maybe_show_onboarding", "_scan_sequels",
                 "_sync_metadata", "_refresh_upcoming", "_refresh_airing", "_scan_notifications"):
        monkeypatch.setattr(MainWindow, name, lambda self, *a, **k: None)
    win = MainWindow(db)
    # The offscreen test "screen" is tiny (800x600) and the app maximises
    # itself; pin a realistic desktop size instead.
    win.showNormal()
    win.setGeometry(0, 0, 1600, 1000)
    win.show()
    assert wait_until(lambda: len(win._cards) > 0)
    pump(150)
    yield win
    win.close()
    win.deleteLater()
    pump(50)
    # The AniList auth helper is an app-wide singleton parented to the main
    # window; the real app has exactly one window, tests make several.
    import core.anilist_auth as auth
    auth._auth_instance = None


def visible_top_levels(qapp, win):
    from ui.toast import Toast
    return [w for w in qapp.topLevelWidgets()
            if w.isVisible() and w is not win and not isinstance(w, Toast)]


# ── window hygiene ────────────────────────────────────────────────────────────

def test_reload_destroys_discarded_cards(qapp, window):
    """The fix for the "88 windows" bug: cards replaced by a reload must be
    destroyed, not just detached (detached ones could pop up as windows)."""
    from PyQt6 import sip
    old_cards = list(window._cards.values())
    window._set_filter("completed")
    assert wait_until(lambda: len(window._cards) > 0)
    pump(100)
    survivors = [c for c in old_cards if not sip.isdeleted(c)]
    assert survivors == [], f"{len(survivors)} replaced cards were not destroyed"


def test_reloads_never_leave_stray_windows(qapp, window):
    for f in ("all", "completed", "planned", "watching", "all"):
        window._set_filter(f)
        assert wait_until(lambda: len(window._cards) > 0)
    window.resize(1200, 800)
    pump(200)
    window.resize(1500, 900)
    pump(200)
    assert visible_top_levels(qapp, window) == []
    # Root cause of the "88 windows" bug: cards discarded by a reload stayed
    # alive without a parent and later surfaced as their own windows.
    import gc
    from PyQt6 import sip
    from ui.anime_card import AnimeCard
    pump(100)
    gc.collect()
    orphans = [o for o in gc.get_objects()
               if isinstance(o, AnimeCard) and not sip.isdeleted(o) and o.parent() is None]
    assert orphans == [], f"{len(orphans)} discarded cards still alive"


def test_full_startup_sequence_opens_exactly_one_window(qapp, db, library, monkeypatch):
    """Replays main.py's startup (splash -> window -> maximise -> show) the way
    the real app does it. This is the path that produced 88 stray windows."""
    from ui.anime_card import AnimeCard
    from ui.main_window import MainWindow
    from ui.splash import SplashScreen
    for name in ("_check_connection", "_check_anilist_status", "_check_for_updates",
                 "_setup_anilist_session", "_maybe_show_onboarding"):
        monkeypatch.setattr(MainWindow, name, lambda self, *a, **k: None)
    splash = SplashScreen("test", qapp.primaryScreen())
    splash.show()
    qapp.processEvents()
    win = MainWindow(db)
    win.setGeometry(qapp.primaryScreen().availableGeometry())
    win.showMaximized()
    qapp.processEvents()
    win.show()
    splash.finish(win)
    try:
        assert wait_until(lambda: len(win._cards) > 0)
        pump(2500)          # startup timers: scans, refreshes, re-renders
        cards = [w for w in qapp.topLevelWidgets() if isinstance(w, AnimeCard) and w.isVisible()]
        assert cards == [], f"{len(cards)} library cards opened as separate windows"
    finally:
        win.close()
        win.deleteLater()
        pump(50)
        import core.anilist_auth as auth
        auth._auth_instance = None


# ── panel beside the cards ────────────────────────────────────────────────────

def _cols_used(win):
    from ui.anime_card import AnimeCard
    gl = win.grid_layout
    return {gl.getItemPosition(i)[1] for i in range(gl.count())
            if isinstance(gl.itemAt(i).widget(), AnimeCard)}


def test_panel_reflows_cards_instead_of_covering(window):
    before = window._calc_columns()
    aid = next(iter(window._cards))
    window._on_card_clicked(aid)
    pump(300)
    assert window.detail_panel.isVisible()
    vp = window.scroll_area.viewport().width()
    assert window._calc_columns() < before
    assert max(_cols_used(window)) < window._calc_columns()
    over = [(c.anime_id, c.geometry().right(), c.parentWidget().objectName()) for c in window._cards.values()
            if c.geometry().right() > vp]
    assert not over, (vp, window.grid_container.width(), over)
    window._close_detail_panel()
    pump(300)
    assert window._calc_columns() == before


# ── detail panel modes ────────────────────────────────────────────────────────

def _no_sideways_overflow(panel):
    from PyQt6.QtWidgets import QWidget
    body = panel._scroll.widget()
    vw = panel._scroll.viewport().width()
    assert body.width() == vw
    bad = [w for w in body.findChildren(QWidget) if w.isVisibleTo(body)
           and w.mapTo(body, w.rect().topRight()).x() > vw + 1]
    assert not bad, [(type(w).__name__, w.objectName()) for w in bad[:5]]


@pytest.mark.parametrize("key,expect", [
    ("w0", "watching"), ("planned", "planned"), ("c0", "completed"),
])
def test_panel_mode_sections(window, library, key, expect):
    dp = window.detail_panel
    window._on_card_clicked(library[key])
    pump(200)
    vis = lambda w: w.isVisibleTo(dp)
    assert vis(dp.planned_top) == (expect == "planned")
    assert vis(dp.completed_top) == (expect == "completed")
    assert vis(dp._rating_card) == (expect == "watching")
    assert not vis(dp.dropped_section)
    _no_sideways_overflow(dp)


def test_dropped_panel_and_card(window):
    window._navigate("dropped")
    assert wait_until(lambda: len(window._cards) == 1)
    card = next(iter(window._cards.values()))
    assert "Stopped at ep 3" in card.ep_label.text()
    assert card.status_badge.text() == "DROPPED"
    window._on_card_clicked(card.anime_id)
    pump(200)
    dp = window.detail_panel
    assert dp.dropped_section.isVisibleTo(dp)
    assert not dp._actions_card.isVisibleTo(dp) and not dp._episodes_card.isVisibleTo(dp)
    assert dp.dropped_section.stop_main.text() == "Stopped at episode 3"
    assert dp.dropped_section.reason.toPlainText() == "Too slow"
    _no_sideways_overflow(dp)


# ── episode rows ──────────────────────────────────────────────────────────────

def test_episode_tick_fits_inside_row_and_locked_labels_unboxed(window, library):
    from ui.detail_panel import _EpRow, _LockedEpRow
    window._on_card_clicked(library["w0"])
    pump(200)
    rows = window.detail_panel.ep_container.findChildren(_EpRow)
    assert rows
    for r in rows:
        g = r.watch_btn.geometry()
        assert g.top() >= 0 and g.bottom() <= r.height() - 1, "tick button clipped"
    # The glyph itself must sit centred inside the button (the old bug: the
    # shared icon style's padding pushed the tick down and cut it off).
    watched = [r for r in rows if r.watch_btn.text() == "✓"]
    assert watched
    img = watched[0].watch_btn.grab().toImage()
    ys = [y for y in range(img.height()) for x in range(img.width())
          if (lambda c: c.green() > 150 and c.red() < 140 and c.green() - c.red() > 60)(img.pixelColor(x, y))]
    assert ys, "tick not rendered"
    top_gap, bottom_gap = min(ys), img.height() - 1 - max(ys)
    assert bottom_gap >= 3 and abs(top_gap - bottom_gap) <= 4, (top_gap, bottom_gap)
    for lr in window.detail_panel.ep_container.findChildren(_LockedEpRow):
        assert lr.styleSheet().startswith("QFrame#lockedEpRow"), "unscoped style boxes labels"


# ── Completed timeline / archive / rewatch ────────────────────────────────────

def test_completed_timeline_archive_and_restore(window, db):
    window._set_filter("completed")
    assert wait_until(lambda: bool(window._completed_groups))
    groups = dict(window._completed_groups)
    key = next(k for k in groups if k not in ("month", "year", "rewatching"))
    n = len(groups[key])
    window._archive_completed_group(key)
    assert wait_until(lambda: key not in window._completed_groups)
    assert db.count_archived() == n
    window._toggle_archived_view()
    assert wait_until(lambda: key in window._completed_groups)
    window._archive_completed_group(key)         # in archive view this restores
    assert wait_until(lambda: db.count_archived() == 0)


def test_rewatch_surfaces(window, db, library):
    cid = library["c0"]
    rid = db.start_rewatch(cid)
    db.set_rewatch_progress(rid, 4)
    window._set_filter("completed")
    assert wait_until(lambda: "rewatching" in window._completed_groups)
    assert window._completed_groups["rewatching"] == [cid]
    card = window._cards[cid]
    assert card.status_badge.text().startswith("↻ REWATCH 4/10")
    window._on_card_clicked(cid)
    pump(200)
    top = window.detail_panel.completed_top
    assert top.rw_active.isVisibleTo(top) and "4 / 10" in top.rw_prog_lbl.text()
    for _ in range(6):
        top._step_rewatch(1)                      # reaching the end finishes it
    assert db.get_active_rewatch(cid) is None and db.rewatch_count(cid) == 1


def test_all_view_shows_one_row_of_completed(window, db):
    from ui.completed_view import SectionHeader
    for i in range(15):                               # more than fit in one row
        add_anime(db, f"Extra {i}", "completed")
    window._set_filter("completed")
    window._set_filter("all")
    assert wait_until(lambda: len(window._cards) > 0)
    hdrs = [window.grid_layout.itemAt(i).widget() for i in range(window.grid_layout.count())]
    assert any(isinstance(h, SectionHeader) for h in hdrs), "missing 'View all' header"
    shown = [c for c in window._cards.values() if c._anime.get("watch_status") == "completed"]
    assert len(shown) == window._calc_columns()


# ── trailer playlist ──────────────────────────────────────────────────────────

def test_trailer_playlist_switching(qapp, monkeypatch):
    import ui.trailer_player as tp
    monkeypatch.setattr(tp, "_has_webengine", lambda: False)
    pl = [{"id": f"V{i}", "site": "youtube", "title": f"PV {i + 1}", "kind": "promo"} for i in range(3)]
    dlg = tp.TrailerDialog("V0", "youtube", "Show", None, playlist=pl, index=0)
    assert len(dlg._rows) == 3
    dlg._step(1)
    assert dlg._index == 1 and dlg._tid == "V1" and "2 / 3" in dlg._counter.text()
    dlg._step(-2)
    assert dlg._index == 2                        # wraps around
    dlg.done(0)
