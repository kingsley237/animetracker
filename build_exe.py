"""
AnimeTracker — Executable Builder
=====================================
Run this once to produce a standalone executable.

Windows  → dist/AnimeTracker.exe
macOS    → dist/AnimeTracker  (or .app if you add --windowed on Mac)
Linux    → dist/AnimeTracker

Usage:
    python build_exe.py

Requirements (install once):
    pip install pyinstaller
"""
import subprocess
import sys
import shutil
from pathlib import Path

ROOT    = Path(__file__).parent.resolve()
DIST    = ROOT / "dist"
BUILD   = ROOT / "build"
ICON_W  = ROOT / "resources" / "icon.ico"
ICON_M  = ROOT / "resources" / "icon_256.png"
VERSION = "2.1.2"


def ensure_pyinstaller():
    try:
        import PyInstaller
        print(f"✓  PyInstaller {PyInstaller.__version__} found")
    except ImportError:
        print("Installing PyInstaller…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def clean():
    for d in (DIST, BUILD):
        if d.exists():
            shutil.rmtree(d)
            print(f"  Cleaned {d.name}/")


def build():
    is_win = sys.platform == "win32"
    is_mac = sys.platform == "darwin"

    icon = str(ICON_W) if is_win else str(ICON_M)

    # Separator is ; on Windows, : on Mac/Linux
    sep = ";" if is_win else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",                          # no console window
        f"--name=AnimeTracker",
        f"--icon={icon}",

        # Bundle the entire resources folder (themes, icons)
        f"--add-data={ROOT / 'resources'}{sep}resources",

        # Hidden imports PyInstaller sometimes misses with PyQt6
        "--hidden-import=PyQt6.sip",
        "--hidden-import=PyQt6.QtCore",
        "--hidden-import=PyQt6.QtWidgets",
        "--hidden-import=PyQt6.QtGui",
        "--hidden-import=PyQt6.QtNetwork",

        # Collect the whole PyQt6 package to avoid missing plugin errors
        "--collect-all=PyQt6",

        str(ROOT / "main.py"),
    ]

    print("\nBuilding executable…")
    print("This takes 1–3 minutes on first run.\n")
    subprocess.check_call(cmd, cwd=str(ROOT))


def report():
    exe_name = "AnimeTracker.exe" if sys.platform == "win32" else "AnimeTracker"
    exe = DIST / exe_name
    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print(f"\n{'='*50}")
        print(f"  ✅  Build complete!")
        print(f"  📦  {exe}")
        print(f"  📏  {size_mb:.1f} MB")
        print(f"{'='*50}")
        print("\nNext steps:")
        print("  1. Test the exe by double-clicking it")
        print("  2. Upload it to a GitHub Release as an attachment")
        print("  3. Tag the release as v2.0.0")
        print("\nYour friends download AnimeTracker.exe from the GitHub release page.")
        print("The app checks for updates automatically on each launch.")
    else:
        print("\n⚠  Build finished but exe not found — check PyInstaller output above.")


if __name__ == "__main__":
    print(f"\nAnimeTracker v{VERSION} — Build Script")
    print("=" * 50)
    ensure_pyinstaller()
    clean()
    build()
    report()