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
