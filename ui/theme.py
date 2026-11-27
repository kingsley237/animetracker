"""
Raikō - theme engine (foundation).

Every colour in the app was designed for the base theme, *Raikō Night*.
A theme is a small set of **roles** (background, text, accent, gold…); each
base colour keeps its exact relationship to its role (measured in OKLab), so:

  * Raikō Night maps every colour to itself  -> the app looks identical;
  * any other theme recolours *everything* - stylesheet, widget styles,
    rich text and custom-painted components - consistently, including
    light themes (the neutral ramp from background to text is re-laid).

Hooks (installed once, by install()):
  * the app stylesheet is rendered through the mapping;
  * QWidget.setStyleSheet / QLabel.setText map colours (and remember the
    original, so a theme change can re-apply them);
  * `from ui.theme import QColor` gives a QColor that maps colours made
    from '#hex' or r,g,b(,a) - painted widgets pick the theme up on repaint.

ThemeManager.apply(theme) switches instantly (restyle + repaint).
"""
from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor as _QtColor
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

# ── colour maths (sRGB <-> OKLab) ─────────────────────────────────────────────


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def rgb_to_oklab(r: int, g: int, b: int) -> Tuple[float, float, float]:
    r, g, b = _lin(r / 255), _lin(g / 255), _lin(b / 255)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = l ** (1 / 3), m ** (1 / 3), s ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def oklab_to_rgb(L: float, a: float, b: float) -> Tuple[int, int, int]:
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return round(_gam(r) * 255), round(_gam(g) * 255), round(_gam(bb) * 255)


def hex_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def luminance(h: str) -> float:
    r, g, b = (_lin(c / 255) for c in hex_rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ── themes ────────────────────────────────────────────────────────────────────

# Roles of the base theme (Raikō Night). Neutrals are laid along bg -> text.
BASE_ROLES: Dict[str, str] = {
    "bg": "#0b0d12", "text": "#f4f5fa",
    "violet": "#8b7bff", "amber": "#fbbf24", "gold": "#f5c451", "sky": "#38bdf8",
    "green": "#34d399", "red": "#f87171", "pink": "#f472b6", "orange": "#fb923c",
}
CHROMATIC = [k for k in BASE_ROLES if k not in ("bg", "text")]
NEUTRAL_CHROMA = 0.045          # OKLab chroma below this = a neutral (greys, dark surfaces)


class Theme:
    """A set of roles (+ fonts, shapes, motion later). Missing roles fall back to the base."""

    def __init__(self, tid: str, name: str, roles: Optional[Dict[str, str]] = None, dark: bool = True,
                 fonts: Optional[Dict[str, str]] = None, extra: Optional[Dict] = None):
        self.id = tid
        self.name = name
        self.roles = {**BASE_ROLES, **(roles or {})}
        self.dark = dark
        self.fonts = fonts or {}
        self.extra = extra or {}

    @property
    def is_base(self) -> bool:
        return (self.roles == BASE_ROLES and not self.fonts and float(self.extra.get("radius", 1.0)) == 1.0
                and not any(k in self.extra for k in ("ambient", "ornaments", "mascot", "event")))


BASE = Theme("raiko_night", "Raikō Night")


@lru_cache(maxsize=None)
def _base_lab(role: str):
    return rgb_to_oklab(*hex_rgb(BASE_ROLES[role]))


def _hue_dist(lab, ref) -> float:
    _, a1, b1 = lab
    _, a2, b2 = ref
    h1, h2 = math.atan2(b1, a1), math.atan2(b2, a2)
    d = abs(h1 - h2)
    return min(d, 2 * math.pi - d)


class Mapper:
    """Maps base-theme colours (and sizes) to a theme."""

    def __init__(self, theme: Theme, font_scale: float = 1.0):
        self.theme = theme
        self.colors_identity = theme.roles == BASE_ROLES
        self.font_scale = font_scale
        self.radius = float(theme.extra.get("radius", 1.0))
        self.identity = self.colors_identity and font_scale == 1.0 and self.radius == 1.0
        self.lab = {k: rgb_to_oklab(*hex_rgb(v)) for k, v in theme.roles.items()}
        self._cache: Dict[Tuple[int, int, int], Tuple[int, int, int]] = {}

    def rgb(self, r: int, g: int, b: int) -> Tuple[int, int, int]:
        if self.colors_identity:
            return r, g, b
        key = (r, g, b)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        L, A, B = rgb_to_oklab(r, g, b)
        chroma = math.hypot(A, B)
        if chroma < NEUTRAL_CHROMA:
            # neutral: position along the base bg -> text ramp, re-laid on the theme's ramp
            bL = _base_lab("bg")[0]
            tL = _base_lab("text")[0]
            t = (L - bL) / (tL - bL) if tL != bL else 0.0
            nb, nt = self.lab["bg"], self.lab["text"]
            out_L = nb[0] + (nt[0] - nb[0]) * t
            # keep a touch of the theme's own tint (from bg at the dark end, text at the light end)
            w = max(0.0, min(1.0, t))
            out_a = nb[1] * (1 - w) + nt[1] * w + A * 0.35
            out_b = nb[2] * (1 - w) + nt[2] * w + B * 0.35
            res = oklab_to_rgb(out_L, out_a, out_b)
        else:
            role = min(CHROMATIC, key=lambda k: _hue_dist((L, A, B), _base_lab(k)))
            base = _base_lab(role)
            tgt = self.lab[role]
            bc = math.hypot(base[1], base[2]) or 1e-6
            tc_ = math.hypot(tgt[1], tgt[2])
            scale = (chroma / bc)
            th = math.atan2(tgt[2], tgt[1]) + (math.atan2(B, A) - math.atan2(base[2], base[1]))
            dL = L - base[0]
            if not self.theme.dark:
                dL = -dL * 0.6          # on light themes, darker variants become lighter tints
            res = oklab_to_rgb(tgt[0] + dL, tc_ * scale * math.cos(th), tc_ * scale * math.sin(th))
        self._cache[key] = res
        return res

    def hex(self, h: str) -> str:
        if self.colors_identity:
            return h
        return rgb_hex(*self.rgb(*hex_rgb(h)))


_HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_FONT_PX = re.compile(r"(font-size\s*:\s*)(\d+(?:\.\d+)?)px")
_RADIUS = re.compile(r"(border(?:-top|-bottom)?(?:-left|-right)?-radius\s*:\s*)(\d+(?:\.\d+)?)px")
_RGBA = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(,\s*[\d.]+\s*)?\)")


def map_css(text: str, mapper: "Mapper") -> str:
    """Map every #hex and rgb()/rgba() in a stylesheet / rich-text string."""
    if mapper.identity or not text:
        return text
    if mapper.font_scale != 1.0:
        text = _FONT_PX.sub(lambda m: f"{m.group(1)}{max(7, round(float(m.group(2)) * mapper.font_scale))}px", text)
    if mapper.radius != 1.0:
        text = _RADIUS.sub(lambda m: f"{m.group(1)}{round(float(m.group(2)) * mapper.radius)}px", text)
    if mapper.colors_identity or ("#" not in text and "rgb" not in text):
        return text

    def hx(m):
        return mapper.hex("#" + m.group(1))

    def rg(m):
        r, g, b = mapper.rgb(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if m.group(4):
            return f"rgba({r},{g},{b}{m.group(4)})"
        return f"rgb({r},{g},{b})"
    return _RGBA.sub(rg, _HEX.sub(hx, text))


# ── the manager ───────────────────────────────────────────────────────────────

class ThemeManager(QObject):
    changed = pyqtSignal(object)            # Theme
    _instance: Optional["ThemeManager"] = None

    def __init__(self):
        super().__init__()
        self.theme = BASE
        self.mapper = Mapper(BASE)
        self.font_scale = 1.0
        self._base_qss = ""
        self._fonts_loaded = False
        self.saved_id = "raiko_night"
        self.event = None
        self.event_level = "off"
        self.ended_event = None

    @classmethod
    def get(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # colour helpers
    def hex(self, h: str) -> str:
        return self.mapper.hex(h)

    def css(self, s: str) -> str:
        return map_css(s, self.mapper)

    def set_base_stylesheet(self, qss: str):
        self._base_qss = qss
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(self._render_qss())

    def _render_qss(self) -> str:
        return self.css(self._base_qss) + self._font_qss()

    def load_fonts(self, theme: Optional[Theme] = None):
        """Register only the fonts this theme uses (registering a font also makes
        it a fallback for symbols, so unused fonts stay unloaded)."""
        if QApplication.instance() is None:
            return
        theme = theme or self.theme
        if not isinstance(self._fonts_loaded, dict):
            self._fonts_loaded = {}                      # family -> font id
        from PyQt6.QtGui import QFontDatabase
        folder = Path(__file__).parent.parent / "resources" / "fonts"
        wanted = {v for v in theme.fonts.values() if v}
        for fam in list(self._fonts_loaded):
            if fam not in wanted:                        # leaving a theme: unload its font
                QFontDatabase.removeApplicationFont(self._fonts_loaded.pop(fam))
        for fam in wanted:
            f = folder / f"{fam.replace(' ', '')}.ttf"
            if fam not in self._fonts_loaded and f.exists():
                self._fonts_loaded[fam] = QFontDatabase.addApplicationFont(str(f))

    def _font_qss(self) -> str:
        f = self.theme.fonts
        out = ""
        if f.get("body"):
            out += f'\nQWidget {{ font-family: "{f["body"]}", "Segoe UI", sans-serif; }}\n'
        if f.get("display"):
            out += ",\n".join(f"QLabel#{n}" for n in DISPLAY_LABELS) + \
                f' {{ font-family: "{f["display"]}", "Segoe UI", sans-serif; }}\n'
        return out

    def display_font(self) -> str:
        return self.theme.fonts.get("display") or "Segoe UI"

    def apply(self, theme: Theme, font_scale: Optional[float] = None):
        """Switch theme everywhere, now."""
        self.load_fonts(theme)
        if font_scale is not None:
            self.font_scale = font_scale
        self.theme = theme
        self.mapper = Mapper(theme, self.font_scale)
        app = QApplication.instance()
        if app is None:
            return
        from PyQt6.QtGui import QFont
        if not hasattr(self, "_orig_font"):
            self._orig_font = QFont(app.font())          # what the app started with
        if theme.fonts.get("body") or self.font_scale != 1.0:
            f = QFont(self._orig_font)
            if theme.fonts.get("body"):
                f.setFamily(theme.fonts["body"])
            f.setPointSizeF(self._orig_font.pointSizeF() * self.font_scale)
            app.setFont(f)
        else:
            app.setFont(self._orig_font)
        if self._base_qss:
            app.setStyleSheet(self._render_qss())
        for w in app.allWidgets():
            try:
                base = w.property("_rk_qss")
                if base is not None:
                    _ORIG_SET_QSS(w, self.css(base))
                if isinstance(w, QLabel):
                    bt = w.property("_rk_text")
                    if bt is not None:
                        _ORIG_SET_TEXT(w, self.css(bt))
                w.update()
            except RuntimeError:
                pass
        self.changed.emit(theme)


    # ── saved choice ─────────────────────────────────────────────────────────

    def load_saved(self):
        """Apply the theme saved in settings (call once at start-up)."""
        from core.app_settings import app_settings
        from ui.themes_catalog import build
        st = app_settings()
        tid = str(st.value("theme_id", "raiko_night") or "raiko_night")
        accent = str(st.value("theme_accent", "") or "")
        try:
            scale = float(st.value("font_scale", 1.0) or 1.0)
        except (TypeError, ValueError):
            scale = 1.0
        self.saved_id = tid
        theme = build(tid, accent)
        # events (Christmas, Halloween…) at the right intensity
        self.event, self.event_level, self.ended_event = None, "off", None
        try:
            from core import events
            theme, ev, level = events.resolve(theme, tid)
            self.event, self.event_level = ev, level
            last = str(st.value("event_last", "") or "")
            if ev is not None and level != "off":
                st.setValue("event_last", ev["id"])
            elif last:
                st.setValue("event_last", "")
                if ev is None and last in events.BY_ID:
                    self.ended_event = events.BY_ID[last]
        except Exception:
            pass
        if theme.is_base and scale == 1.0 and self.theme.is_base:
            return
        self.apply(theme, scale)

    def reapply(self):
        """Re-resolve your theme + any event (after a choice) and apply it."""
        self.load_saved()
        if self.theme.is_base:
            self.apply(self.theme, self.font_scale)

    def save(self, tid: str, accent: str = "", font_scale: float = 1.0):
        from core.app_settings import app_settings
        st = app_settings()
        st.setValue("theme_id", tid)
        st.setValue("theme_accent", accent)
        st.setValue("font_scale", font_scale)
        self.saved_id = tid


# Labels that use the theme's display font (titles, greeting, big numbers).
DISPLAY_LABELS = [
    "appLogo", "pageTitle", "detailTitle", "dialogTitle", "settingsTitle", "settingsPageTitle",
    "settingsNavBrand", "settingsAboutName", "spotlightTitle", "homeHello", "homeSection", "hallTitle",
    "hallAsk", "hallDoneRank", "hallPlaqueRank", "hallAwardName", "popTitle", "statValue",
    "statStripValue", "homeStatValue", "slideBigNumber", "recapHeadline", "tvSeasonTitle",
]


def tm() -> ThemeManager:
    return ThemeManager.get()


def C(h: str) -> str:
    """Theme-mapped '#hex' (for strings built by hand)."""
    return ThemeManager.get().hex(h)


# ── hooks ─────────────────────────────────────────────────────────────────────

_ORIG_SET_QSS = QWidget.setStyleSheet
_ORIG_SET_TEXT = QLabel.setText
_installed = False


def _themed_set_qss(self, s):
    s = s or ""
    if "#" in s or "rgb" in s:
        self.setProperty("_rk_qss", s)
        _ORIG_SET_QSS(self, ThemeManager.get().css(s))
    else:
        if self.property("_rk_qss") is not None:
            self.setProperty("_rk_qss", None)
        _ORIG_SET_QSS(self, s)


def _themed_set_text(self, s):
    s = s if isinstance(s, str) else str(s)
    if "<" in s and ("#" in s or "rgb" in s):
        self.setProperty("_rk_text", s)
        _ORIG_SET_TEXT(self, ThemeManager.get().css(s))
    else:
        if self.property("_rk_text") is not None:
            self.setProperty("_rk_text", None)
        _ORIG_SET_TEXT(self, s)


def set_raw_style(w: QWidget, css: str):
    """Style a widget with *literal* colours (not theme-mapped) - e.g. colour swatches."""
    w.setProperty("_rk_qss", None)
    _ORIG_SET_QSS(w, css)


def install():
    """Route widget styles and rich text through the theme (idempotent)."""
    global _installed
    if _installed:
        return
    QWidget.setStyleSheet = _themed_set_qss
    QLabel.setText = _themed_set_text
    _installed = True


install()


class QColor(_QtColor):
    """QColor that maps base-theme colours made from '#hex' or r,g,b(,a).
    Copies of existing QColors are not mapped again."""

    def __init__(self, *args):
        m = ThemeManager.get().mapper
        if not m.colors_identity and args:
            a0 = args[0]
            if isinstance(a0, str) and a0.startswith("#") and len(args) == 1:
                args = (m.hex(a0),)
            elif all(isinstance(x, int) for x in args) and len(args) in (3, 4):
                r, g, b = m.rgb(args[0], args[1], args[2])
                args = (r, g, b) + tuple(args[3:])
        super().__init__(*args)


def stylesheet_path() -> Path:
    return Path(__file__).parent.parent / "resources" / "themes" / "dark.qss"
