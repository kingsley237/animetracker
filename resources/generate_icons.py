"""
Regenerate Miroku app icons from the lettermark SVG.

Requires PyQt6 only. This deliberately avoids CairoSVG because CairoSVG needs
native Cairo DLLs on Windows.

Inputs:
  logo_lettermark.svg  preferred source for icons
  miroku_icon.svg      fallback source kept for compatibility

Outputs:
  icon.ico             Windows executable/titlebar icon
  icon_*.png           legacy square app icons
  logo_lettermark_*.png UI/splash lettermark assets
"""
import struct
import sys
from pathlib import Path

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer


HERE = Path(__file__).parent
SVG = HERE / "logo_lettermark.svg"
FALLBACK_SVG = HERE / "miroku_icon.svg"
SIZES = [16, 24, 32, 48, 64, 128, 256, 512]
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
CONTENT_SCALE = 0.92


def _visible_bounds(image: QImage, threshold: int = 10):
    min_x = image.width()
    min_y = image.height()
    max_x = -1
    max_y = -1

    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > threshold:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

    if max_x < 0 or max_y < 0:
        return None
    return min_x, min_y, max_x - min_x + 1, max_y - min_y + 1


def _render_svg_png(source: Path, size: int) -> bytes:
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise RuntimeError(f"Could not read SVG: {source}")

    source_size = max(size * 4, 1024)
    source_image = QImage(
        QSize(source_size, source_size),
        QImage.Format.Format_ARGB32
    )
    source_image.fill(QColor(0, 0, 0, 0))

    painter = QPainter(source_image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, source_size, source_size))
    painter.end()

    bounds = _visible_bounds(source_image)
    if bounds:
        source_image = source_image.copy(*bounds)

    image = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))

    target_size = int(size * CONTENT_SCALE)
    scaled = source_image.scaled(
        target_size,
        target_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(
        (size - scaled.width()) // 2,
        (size - scaled.height()) // 2,
        scaled,
    )
    painter.end()

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def _write_ico(path: Path, png_frames: dict[int, bytes], sizes: tuple[int, ...]):
    frames = [(size, png_frames[size]) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(frames))
    directory = bytearray()
    payload = bytearray()
    offset = 6 + (16 * len(frames))

    for size, png in frames:
        width_byte = 0 if size >= 256 else size
        height_byte = 0 if size >= 256 else size
        directory.extend(struct.pack(
            "<BBBBHHII",
            width_byte,
            height_byte,
            0,      # no palette
            0,      # reserved
            1,      # color planes
            32,     # bits per pixel
            len(png),
            offset,
        ))
        payload.extend(png)
        offset += len(png)

    path.write_bytes(header + directory + payload)


def main():
    source = SVG if SVG.exists() else FALLBACK_SVG
    if not source.exists():
        print(f"Missing source SVG. Expected {SVG.name} or {FALLBACK_SVG.name}")
        sys.exit(1)

    print(f"Using source: {source.name}")
    pngs: dict[int, bytes] = {}

    for size in SIZES:
        data = _render_svg_png(source, size)
        pngs[size] = data

        icon_out = HERE / f"icon_{size}.png"
        icon_out.write_bytes(data)
        print(f"  wrote {icon_out}")

        logo_out = HERE / f"logo_lettermark_{size}.png"
        logo_out.write_bytes(data)
        print(f"  wrote {logo_out}")

    _write_ico(HERE / "icon.ico", pngs, ICO_SIZES)
    print("  wrote icon.ico")


if __name__ == "__main__":
    main()
