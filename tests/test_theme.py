"""Theme engine: identity on the base theme, consistent recolouring, live switching."""
from tests.conftest import pump


def test_base_theme_is_identity():
    from ui.theme import BASE, Mapper, map_css
    m = Mapper(BASE)
    assert m.identity
    css = "QWidget{background:#1a1d28;color:rgba(255,255,255,0.5);border:1px solid #2a2d42;}"
    assert map_css(css, m) == css
    assert m.hex("#8b7bff") == "#8b7bff"


def test_light_theme_relays_neutrals_and_accents():
    from ui.theme import Mapper, Theme, contrast, luminance, map_css
    t = Theme("t", "Light", {"bg": "#faf7f2", "text": "#1d1a24", "violet": "#c2417a"}, dark=False)
    m = Mapper(t)
    bg, surface, text, muted = (m.hex(h) for h in ("#0b0d12", "#1a1d28", "#f4f5fa", "#9da5c0"))
    assert luminance(bg) > luminance(surface) > luminance(muted) > luminance(text)   # ramp re-laid, flipped
    assert contrast(bg, text) > 12 and contrast(bg, muted) > 4.5
    assert m.hex("#8b7bff") == "#c2417a"                                            # role colour exact
    out = map_css("a{color:#f4f5fa;background:rgba(11,13,18,0.5)}", m)
    assert "#f4f5fa" not in out and "rgba(" in out and ",0.5)" in out


def test_hooks_and_live_switch(qapp):
    from PyQt6.QtWidgets import QLabel, QPushButton
    from ui.theme import BASE, QColor, Theme, ThemeManager
    tm = ThemeManager.get()
    b = QPushButton("x")
    b.setStyleSheet("background:#8b7bff;")
    lab = QLabel()
    lab.setText("<span style='color:#8b7bff'>hi</span>")
    assert b.styleSheet() == "background:#8b7bff;"
    try:
        tm.apply(Theme("t", "T", {"violet": "#ff0000"}))
        assert "#ff0000" in b.styleSheet() and "#ff0000" in lab.text()
        assert QColor("#8b7bff").name() == "#ff0000"
        assert QColor(QColor("#8b7bff")).name() == "#ff0000"          # copies aren't mapped twice
        b2 = QPushButton("y")
        b2.setStyleSheet("color:#8b7bff;")                            # widgets made later are themed too
        assert "#ff0000" in b2.styleSheet()
    finally:
        tm.apply(BASE)
    assert b.styleSheet() == "background:#8b7bff;" and "#8b7bff" in lab.text()
    pump(10)


def test_every_theme_is_readable():
    from ui.theme import Mapper, contrast
    from ui.themes_catalog import ORDER, build
    checks = [("#f4f5fa", "#0b0d12", 7), ("#e8eaf2", "#1a1d28", 7), ("#9da5c0", "#0b0d12", 4.5),
              ("#8c93ad", "#12141d", 4.5), ("#6b7391", "#0b0d12", 3), ("#8b7bff", "#12141d", 3),
              ("#f5c451", "#0b0d12", 3), ("#fbbf24", "#0b0d12", 3), ("#38bdf8", "#0b0d12", 3),
              ("#34d399", "#0b0d12", 3), ("#f87171", "#0b0d12", 3), ("#0b0d12", "#8b7bff", 4.5),
              ("#0b0d12", "#f5c451", 4.5), ("#0b0d12", "#fbbf24", 4.5)]
    for tid in ORDER:
        m = Mapper(build(tid))
        for fg, bg, need in checks:
            assert contrast(m.hex(fg), m.hex(bg)) >= need, (tid, fg, bg)


def test_appearance_and_preview(qapp, db):
    from core.app_settings import app_settings
    from ui.appearance import AppearancePage
    from ui.theme import BASE, ThemeManager
    tm = ThemeManager.get()
    try:
        page = AppearancePage()
        page._choose("sakura_dawn")
        assert tm.theme.id == "sakura_dawn" and app_settings().value("theme_id") == "sakura_dawn"
        page._set_accent("#38bdf8")
        assert tm.theme.roles["violet"] == "#38bdf8"
        page.slider.setValue(110)
        page._set_scale()
        assert abs(tm.font_scale - 1.1) < 1e-6
        # preview another theme, then cancel -> back to Sakura exactly
        from PyQt6.QtWidgets import QMainWindow, QWidget
        from ui.theme_preview import ThemePreview
        win = QMainWindow()
        win.setCentralWidget(QWidget())
        win._navigate = lambda *_a: None
        win.resize(1000, 700)
        win.show()
        pv = ThemePreview(win, "neo_tokyo")
        pv.start()
        assert tm.theme.id == "neo_tokyo"
        pv.go(3)
        pv.end(False)
        assert tm.theme.id == "sakura_dawn" and app_settings().value("theme_id") == "sakura_dawn"
        pv2 = ThemePreview(win, "retro_vhs")
        pv2.start()
        pv2.end(True)
        assert app_settings().value("theme_id") == "retro_vhs"
        win.close()
        page.deleteLater()
    finally:
        tm.apply(BASE, 1.0)
        tm.save("raiko_night", "", 1.0)
    pump(20)
