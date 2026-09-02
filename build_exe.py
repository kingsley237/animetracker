"""
Miroku — Executable Builder
=====================================
Produces a standalone executable using PyInstaller.

Windows  →  dist/Miroku/Miroku.exe   (inside a folder)
macOS    →  dist/Miroku/Miroku
Linux    →  dist/Miroku/Miroku

WHY --onedir INSTEAD OF --onefile
----------------------------------
--onefile extracts the entire app (~300 MB) to a temp folder on EVERY launch,
then Windows Defender scans every extracted file. Cold-start time: 15-45 s.

--onedir writes the files once at install time. Subsequent launches read
directly from disk without extraction. Cold-start time: 2-4 s.

To distribute: zip the dist/Miroku/ folder, or use an installer like NSIS/Inno.

Usage:
    python build_exe.py

Requirements (install once):
    pip install pyinstaller

Version is read automatically from core/updater.py — never change it here.
"""
import subprocess
import sys
import shutil
import zipfile
from pathlib import Path

ROOT   = Path(__file__).parent.resolve()
DIST   = ROOT / "dist"
BUILD  = ROOT / "build"
ICON_W = ROOT / "resources" / "miroku_app_icon.ico"
ICON_M = ROOT / "resources" / "miroku_lettermark_256.png"


def get_version() -> str:
    updater = ROOT / "core" / "updater.py"
    if not updater.exists():
        return "0.0.0"
    for line in updater.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("APP_VERSION"):
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

        # ── CRITICAL: onedir, NOT onefile ─────────────────────────────────
        # onefile extracts ~300 MB to temp on every cold start + AV scan.
        # onedir reads directly from disk — 10x faster startup on Windows.
        "--onedir",
        "--windowed",
        "--name=Miroku",
        f"--icon={icon}",

        # ── Resources ─────────────────────────────────────────────────────
        f"--add-data={ROOT / 'resources'}{sep}resources",

        # ── Required hidden imports ────────────────────────────────────────
        "--hidden-import=PyQt6.sip",
        "--hidden-import=PyQt6.QtCore",
        "--hidden-import=PyQt6.QtWidgets",
        "--hidden-import=PyQt6.QtGui",
        "--hidden-import=PyQt6.QtNetwork",
        "--hidden-import=PyQt6.QtSql",
        "--hidden-import=PyQt6.QtWebEngineWidgets",
        "--hidden-import=PyQt6.QtWebEngineCore",
        "--hidden-import=PyQt6.QtWebChannel",
        "--hidden-import=tzlocal",
        "--hidden-import=PIL",
        "--hidden-import=requests",

        # ── Collect only what is actually needed ───────────────────────────
        # Do NOT use --collect-all=PyQt6 — it bundles the entire Qt suite.
        # Do NOT use --collect-all=PyQt6.QtWebEngineWidgets — it pulls in
        # ~150 MB of extra Chromium files that are already in the Qt install.
        "--collect-submodules=PyQt6",
        "--collect-data=PyQt6",

        # ── Explicitly exclude heavy unused modules ─────────────────────────
        "--exclude-module=matplotlib",
        "--exclude-module=numpy",
        "--exclude-module=scipy",
        "--exclude-module=pandas",
        "--exclude-module=IPython",
        "--exclude-module=jupyter",
        "--exclude-module=tkinter",
        "--exclude-module=wx",
        "--exclude-module=PySide2",
        "--exclude-module=PySide6",
        "--exclude-module=PyQt5",
        "--exclude-module=test",
        "--exclude-module=unittest",

        str(ROOT / "main.py"),
    ]

    print(f"\nBuilding Miroku v{version} (onedir — fast startup)…")
    print("This takes 2-5 minutes on first run.\n")
    subprocess.check_call(cmd, cwd=str(ROOT))


def zip_for_distribution(version: str):
    """Zip the dist/Miroku folder for GitHub release attachment."""
    exe_dir = DIST / "Miroku"
    if not exe_dir.exists():
        return
    zip_path = DIST / f"Miroku-v{version}-Windows.zip"
    print(f"\nZipping {exe_dir.name}/ -> {zip_path.name}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in exe_dir.rglob("*"):
            zf.write(file, file.relative_to(DIST))
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  OK  {zip_path.name}  ({size_mb:.0f} MB)")
    return zip_path


def report(version: str):
    exe_name = "Miroku.exe" if sys.platform == "win32" else "Miroku"
    exe      = DIST / "Miroku" / exe_name

    if exe.exists():
        size_mb = sum(
            f.stat().st_size for f in (DIST / "Miroku").rglob("*") if f.is_file()
        ) / (1024 * 1024)

        print(f"\n{'='*52}")
        print(f"  OK  Build complete!")
        print(f"  DIR {DIST / 'Miroku'}")
        print(f"  EXE {exe}")
        print(f"  MB  {size_mb:.0f} MB (total folder)")
        print(f"  VER v{version}")
        print(f"{'='*52}")
        print(f"\nStartup improvement:")
        print(f"  Before (--onefile): 15-45 s cold start (full extraction every run)")
        print(f"  After  (--onedir):   2-4 s cold start  (reads from disk directly)")
        print(f"\nNext steps:")
        print(f"  1. Test: double-click dist\\Miroku\\Miroku.exe")
        print(f"  2. Distribute: zip the dist\\Miroku\\ folder")
        print(f"     OR run: python build_exe.py --zip  (auto-zips after build)")
        print(f"  3. On GitHub -> Releases -> attach the .zip file")
    else:
        print("\nWARN  Build finished but exe not found — check output above.")


if __name__ == "__main__":
    do_zip  = "--zip" in sys.argv
    version = get_version()
    print(f"\nMiroku v{version} — Build Script")
    print("=" * 52)
    ensure_pyinstaller()
    clean()
    build(version)
    if do_zip:
        zip_for_distribution(version)
    report(version)
