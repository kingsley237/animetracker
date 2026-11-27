"""
Raikō - the logo, dressed for the occasion.

The glyph is re-tinted in the event's palette, wears the event's costume and
the line under the wordmark changes:

  christmas   red / pine glyph, Santa hat           "Merry Christmas"
  halloween   pumpkin / violet glyph, witch hat     "Happy Halloween"
  new_year    gold glyph, party hat                 "Happy 2027"
  season      the season's colours                  "Winter 2027 season"
  premiere    the show's colour + its lead's face   "Premiere · ONE PIECE"
  farewell    the show's colour + its lead's face   "Thank you, Frieren"

Off (or no event) gives back the original logo untouched.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor as _Raw, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

# the glyph's three arcs + its core, per event
PALETTES = {
    "christmas": ("#ff4d5e", "#ffd166", "#2fbf71", "#ffffff"),
    "halloween": ("#9b5cff", "#ff8a1f", "#a3e635", "#ffe3b0"),
    "new_year": ("#ff5fa2", "#ffd166", "#fff3c4", "#ffffff"),
    "season_winter": ("#7aa7ff", "#e0f2ff", "#a9d8ff", "#ffffff"),
    "season_spring": ("#ff7aa8", "#ffd1e3", "#b6f09c", "#fff6fa"),
    "season_summer": ("#4fd1c5", "#ffd36b", "#ff8a5c", "#fffbe6"),
    "season_fall": ("#e0603a", "#ffb15c", "#c9a227", "#fff1dc"),
}
COSTUME = {"christmas": "santa", "halloween": "witch", "new_year": "party"}


def subtitle(ev: Dict, year: int) -> str:
    k = ev.get("kind")
    if k == "premiere":
        return f"Premiere · {ev['name']}"
    if k == "farewell":
        return f"Thank you, {ev['name']}"
    eid = ev["id"]
    if eid == "christmas":
        return "Merry Christmas"
    if eid == "halloween":
        return "Happy Halloween"
    if eid == "new_year":
        return f"Happy {year + 1 if _month() == 12 else year}"
    if eid.startswith("season_"):
        return f"{eid.split('_')[1].title()} {year} season"
    return ev.get("name", "")


def _month() -> int:
    from core.events import today
    return today().month


def palette(ev: Dict) -> Tuple[str, str, str, str]:
    if ev.get("dynamic"):
        from core.events import readable_accent
        from ui.theme import hex_rgb, oklab_to_rgb, rgb_hex, rgb_to_oklab
        c = readable_accent(ev.get("color") or "#8b7bff")
        L, a, b = rgb_to_oklab(*hex_rgb(c))
        light = rgb_hex(*oklab_to_rgb(min(0.95, L + 0.18), a * 0.6, b * 0.6))
        deep = rgb_hex(*oklab_to_rgb(max(0.45, L - 0.12), a * 1.1, b * 1.1))
        return c, light, deep, "#ffffff"
    return PALETTES.get(ev["id"], ("#8b7bff", "#fbbf24", "#38bdf8", "#ffffff"))


_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs><radialGradient id="core"><stop offset="0" stop-color="{d}"/><stop offset="0.5" stop-color="{d}" stop-opacity="0.8"/>
  <stop offset="1" stop-color="{d}" stop-opacity="0"/></radialGradient></defs>
  <g fill="none" stroke-width="46" stroke-linecap="round">
    <path d="M 283.5 114.6 A 144 144 0 0 1 392.2 302.9" stroke="{a}"/>
    <path d="M 364.7 350.5 A 144 144 0 0 1 147.3 350.5" stroke="{b}"/>
    <path d="M 119.8 302.9 A 144 144 0 0 1 228.5 114.6" stroke="{c}"/>
  </g>
  {core}
</svg>"""


def render(base, ev: Dict, size: Tuple[int, int] = (48, 44), portrait: Optional[QPixmap] = None) -> QPixmap:
    """The dressed-up logo: the glyph's arcs in the event's colours, its
    costume on top; for a show, its lead character in the glyph's core."""
    from PyQt6.QtCore import QByteArray
    from PyQt6.QtSvg import QSvgRenderer
    W, H = size
    dpr = 2.0
    out = QPixmap(int(W * dpr), int(H * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)
    costume = COSTUME.get(ev["id"]) if not ev.get("dynamic") else None
    a, b, c, d = palette(ev)
    face = ev.get("dynamic") and portrait is not None and not portrait.isNull()
    core = "" if face else ('<circle cx="256" cy="256" r="80" fill="url(#core)"/>'
                            f'<circle cx="256" cy="256" r="33" fill="{d}"/>')
    svg = _SVG.replace("{a}", a).replace("{b}", b).replace("{c}", c).replace("{d}", d).replace("{core}", core)
    g = 38 if costume else 44
    gx, gy = (W - g) / 2, H - g
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(gx, gy, g, g))
    if face:
        k = g / 512
        r = QRectF(gx + (256 - 98) * k, gy + (256 - 98) * k, 196 * k, 196 * k)
        path = QPainterPath()
        path.addEllipse(r)
        p.save()
        p.setClipPath(path)
        sc = portrait.scaled(int(r.width() * dpr), int(r.width() * dpr),
                             Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        sc.setDevicePixelRatio(dpr)
        p.drawPixmap(QPointF(r.x() - (sc.width() / dpr - r.width()) / 2, r.y()), sc)
        p.restore()
        p.setPen(QPen(_Raw(d), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(r)
    if costume == "santa":
        _santa(p, gx + g * 0.58, gy + 4, g * 0.6)
    elif costume == "witch":
        _witch(p, gx + g * 0.52, gy + 6, g * 0.78)
    elif costume == "party":
        _party(p, gx + g * 0.68, gy + 6, g * 0.4)
    p.end()
    return out


def _santa(p: QPainter, x: float, y: float, w: float):
    p.save()
    p.translate(x, y)
    p.rotate(18)
    hat = QPainterPath()
    hat.moveTo(-w / 2, 0)
    hat.cubicTo(-w * 0.3, -w * 0.55, w * 0.25, -w * 0.75, w * 0.62, -w * 0.32)
    hat.lineTo(w / 2, 0)
    hat.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_Raw("#e8323f"))
    p.drawPath(hat)
    p.setBrush(_Raw("#ffffff"))
    p.drawRoundedRect(QRectF(-w * 0.58, -w * 0.06, w * 1.16, w * 0.2), w * 0.1, w * 0.1)
    p.drawEllipse(QPointF(w * 0.64, -w * 0.32), w * 0.12, w * 0.12)
    p.restore()


def _witch(p: QPainter, x: float, y: float, w: float):
    p.save()
    p.translate(x, y)
    p.rotate(-10)
    brim = QRectF(-w / 2, -w * 0.06, w, w * 0.16)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_Raw("#2b1a3d"))
    p.drawEllipse(brim)
    cone = QPainterPath()
    cone.moveTo(-w * 0.26, 0)
    cone.lineTo(w * 0.26, 0)
    cone.cubicTo(w * 0.18, -w * 0.3, w * 0.2, -w * 0.45, w * 0.36, -w * 0.62)
    cone.cubicTo(w * 0.05, -w * 0.5, -w * 0.12, -w * 0.3, -w * 0.26, 0)
    p.drawPath(cone)
    p.setBrush(_Raw("#ff8a1f"))
    p.drawRect(QRectF(-w * 0.25, -w * 0.12, w * 0.49, w * 0.08))
    p.restore()


def _party(p: QPainter, x: float, y: float, w: float):
    p.save()
    p.translate(x, y)
    p.rotate(16)
    cone = QPainterPath()
    cone.moveTo(-w / 2, 0)
    cone.lineTo(w / 2, 0)
    cone.lineTo(0, -w * 1.15)
    cone.closeSubpath()
    gr = QLinearGradient(0, 0, 0, -w)
    gr.setColorAt(0, _Raw("#f5b83d"))
    gr.setColorAt(1, _Raw("#ff5fa2"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gr)
    p.drawPath(cone)
    p.setPen(QPen(_Raw(255, 255, 255, 200), 1.2))
    for k in (0.3, 0.6):
        p.drawLine(QPointF(-w / 2 * (1 - k), -w * 1.15 * k), QPointF(w / 2 * (1 - k), -w * 1.15 * k))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_Raw("#fff3c4"))
    for i in range(5):
        a = i * math.tau / 5
        p.drawEllipse(QPointF(math.cos(a) * 2.2, -w * 1.15 + math.sin(a) * 2.2), 1.4, 1.4)
    p.restore()
