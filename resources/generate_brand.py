"""
Regenerate Raikō brand assets from the SVG masters (PyQt6 only - no Cairo).

Masters (hand-built, Aperture concept: three arcs - Miroku indigo, Kinema
amber, TV sky - closing around a point of light):
  raiko_mark.svg     app icon (rounded square)
  raiko_glyph.svg    the mark alone, for dark surfaces (sidebar, splash, About)
  miroku_mark.svg    indigo arc lit       (anime library)
  kinema_mark.svg    amber + sky arcs lit (movies & TV library)

Outputs:
  raiko_app_icon.ico                 Windows exe / title bar (16..256)
  raiko_icon_{16..1024}.png          app icon PNGs
  raiko_glyph_{64,128,256,512}.png   bare mark
  miroku_mark_{32,64,128}.png, kinema_mark_{32,64,128}.png
  raiko_wordmark_1600x600.png        mark + "Raikō" + MIROKU · KINEMA (splash)

Run:  python resources/generate_brand.py
"""
import struct
import sys
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

HERE = Path(__file__).parent


def render(svg: Path, size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    QSvgRenderer(str(svg)).render(p, QRectF(0, 0, size, size))
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def write_ico(path: Path, images):
    """ICO with PNG-compressed entries (Vista+)."""
    data = [png_bytes(i) for i in images]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for img, blob in zip(images, data):
        w = img.width() if img.width() < 256 else 0
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(data))


def wordmark(w: int = 1600, h: int = 600) -> QImage:
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    mark = int(h * 0.62)
    x0 = int(w * 0.08)
    QSvgRenderer(str(HERE / "raiko_glyph.svg")).render(p, QRectF(x0, (h - mark) / 2, mark, mark))
    tx = x0 + mark + int(h * 0.08)
    f = QFont("Segoe UI", 10, QFont.Weight.Black)
    f.setPixelSize(int(h * 0.36))
    p.setFont(f)
    p.setPen(QColor("#f4f5fa"))
    p.drawText(QRectF(tx, h * 0.14, w - tx, h * 0.5), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Raikō")
    f2 = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
    f2.setPixelSize(int(h * 0.075))
    f2.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, h * 0.012)
    p.setFont(f2)
    y = h * 0.66
    x = tx + h * 0.02
    for text, color in (("MIROKU", "#8b7bff"), ("·", "#5c6482"), ("KINEMA", "#fbbf24")):
        p.setPen(QColor(color))
        p.drawText(QRectF(x, y, w, h * 0.12), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        x += p.fontMetrics().horizontalAdvance(text) + h * 0.04
    p.end()
    return img


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841 (fonts need it)
    for s in (16, 24, 32, 48, 64, 96, 128, 180, 192, 256, 512, 1024):
        render(HERE / "raiko_mark.svg", s).save(str(HERE / f"raiko_icon_{s}.png"))
    write_ico(HERE / "raiko_app_icon.ico", [render(HERE / "raiko_mark.svg", s) for s in (16, 24, 32, 48, 64, 128, 256)])
    for s in (64, 128, 256, 512):
        render(HERE / "raiko_glyph.svg", s).save(str(HERE / f"raiko_glyph_{s}.png"))
    for name in ("miroku_mark", "kinema_mark"):
        for s in (32, 64, 128):
            render(HERE / f"{name}.svg", s).save(str(HERE / f"{name}_{s}.png"))
    wordmark().save(str(HERE / "raiko_wordmark_1600x600.png"))
    print("brand assets written to", HERE)


if __name__ == "__main__":
    main()
