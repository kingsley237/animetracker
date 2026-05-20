"""
Miroku - Executable Builder
=====================================
Run this to produce a standalone executable.

Windows -> dist/Miroku.exe
macOS   -> dist/Miroku
Linux   -> dist/Miroku

Usage:
    python build_exe.py

Requirements (install once):
    pip install pyinstaller

Version is read automatically from core/updater.py - only ever
update APP_VERSION there. Never change the version here manually.
"""
import subprocess
import sys
import shutil
from pathlib import Path

ROOT   = Path(__file__).parent.resolve()
DIST   = ROOT / "dist"
BUILD  = ROOT / "build"
ICON_W = ROOT / "resources" / "icon.ico"
ICON_M = ROOT / "resources" / "icon_256.png"


def get_version() -> str:
    """Read APP_VERSION from core/updater.py - single source of truth."""
    updater = ROOT / "core" / "updater.py"
    if not updater.exists():
        return "0.0.0"
    for line in updater.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("APP_VERSION"):
            # e.g.  APP_VERSION = "2.1.1"
            return line.split("=")[1].strip().strip('"').strip("'")
    return "0.0.0"


def ensure_pyinstaller():
    try:
        import PyInstaller
        print(f"OK  PyInstaller {PyInstaller.__version__} found")
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller"]
        )


def clean():
    for d in (DIST, BUILD):
        if d.exists():
            shutil.rmtree(d)
            print(f"  Cleaned {d.name}/")


def build(version: str):
    is_win = sys.platform == "win32"
    icon   = str(ICON_W) if is_win else str(ICON_M)
    sep    = ";" if is_win else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name=Miroku",
        f"--icon={icon}",
        f"--add-data={ROOT / 'resources'}{sep}resources",
        "--hidden-import=PyQt6.sip",
        "--hidden-import=PyQt6.QtCore",
        "--hidden-import=PyQt6.QtWidgets",
        "--hidden-import=PyQt6.QtGui",
        "--hidden-import=PyQt6.QtNetwork",
        "--hidden-import=PyQt6.QtWebEngineWidgets",
        "--hidden-import=PyQt6.QtWebEngineCore",
        "--hidden-import=PyQt6.QtWebChannel",
        "--collect-all=PyQt6",
        "--collect-all=PyQt6.QtWebEngineWidgets",
        "--collect-all=PyQt6.QtWebEngineCore",
        str(ROOT / "main.py"),
    ]

    print(f"\nBuilding Miroku v{version}...")
    print("This takes 1-3 minutes on first run.\n")
    subprocess.check_call(cmd, cwd=str(ROOT))


def report(version: str):
    exe_name = "Miroku.exe" if sys.platform == "win32" else "Miroku"
    exe = DIST / exe_name
    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print(f"\n{'='*52}")
        print(f"  OK  Build complete!")
        print(f"  EXE {exe}")
        print(f"  MB  {size_mb:.1f} MB")
        print(f"  VER v{version}")
        print(f"{'='*52}")
        print(f"\nNext steps:")
        print(f"  1. Test: double-click dist\\Miroku.exe")
        print(f"  2. On GitHub -> Releases -> Draft new release")
        print(f"  3. Tag: v{version}  |  Title: Miroku v{version}")
        print(f"  4. Attach dist\\Miroku.exe -> Publish")
        print(f"\nFriends running older versions will see the update banner automatically.")
    else:
        print("\nWARN  Build finished but exe not found - check PyInstaller output above.")


if __name__ == "__main__":
    version = get_version()
    print(f"\nMiroku v{version} - Build Script")
    print("=" * 52)
    print(f"  Version source: core/updater.py -> APP_VERSION = \"{version}\"")
    print()
    ensure_pyinstaller()
    clean()
    build(version)
    report(version)
