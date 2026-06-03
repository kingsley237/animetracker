"""
Miroku — Entry Point
Run: python main.py
"""
import sys, os
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

APP_USER_MODEL_ID = "Miroku.Desktop.App"


def _set_windows_app_id():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        shell32 = ctypes.windll.shell32
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [
            ctypes.c_wchar_p
        ]
        shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass

_set_windows_app_id()

# WebEngine MUST be imported before QApplication — Qt requirement
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
except ImportError:
    pass  # PyQt6-WebEngine not installed — trailer player will fall back to browser

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QCoreApplication
from PyQt6.QtGui import QCursor, QFont, QIcon

from core.database import DatabaseManager


def main():
    try:
        from core.updater import APP_VERSION
    except Exception:
        APP_VERSION = "2.2.0"

    from core.app_settings import migrate_legacy_settings
    migrate_legacy_settings()

    app = QApplication(sys.argv)
    app.setApplicationName("Miroku")
    app.setApplicationDisplayName("Miroku")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("Miroku")

    # App icon
    icon_path = ROOT / "resources" / "icon.ico"
    if icon_path.exists():
        app_icon = QIcon(str(icon_path))
        app.setWindowIcon(app_icon)
    else:
        app_icon = QIcon()

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    startup_screen = app.screenAt(QCursor.pos()) or app.primaryScreen()

    from ui.splash import SplashScreen
    splash = SplashScreen(APP_VERSION, startup_screen)
    splash.show()
    app.processEvents()
    splash.set_status("Starting Miroku…", progress=10)

    # Stage 1 — Theme
    splash.set_status("Loading theme…", progress=25)
    from core.app_settings import resolved_theme
    from pathlib import Path as _Path
    _qss = _Path(__file__).parent / "resources" / "themes" / f"{resolved_theme()}.qss"
    if not _qss.exists():
        _qss = _Path(__file__).parent / "resources" / "themes" / "dark.qss"
    if _qss.exists():
        app.setStyleSheet(_qss.read_text(encoding="utf-8"))

    # Stage 2 — Database
    splash.set_status("Opening your library…", progress=45)
    try:
        db = DatabaseManager()
    except Exception as e:
        splash.close()
        QMessageBox.critical(None, "Database Error", f"Failed to initialize database:\n{e}")
        sys.exit(1)

    # Stage 3 — UI modules
    splash.set_status("Loading interface…", progress=65)
    from ui.main_window import MainWindow

    # Stage 4 — Build window
    splash.set_status("Building the interface…", progress=82)
    window = MainWindow(db)
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    if startup_screen:
        window.setGeometry(startup_screen.availableGeometry())
        window.showMaximized()

    # Stage 5 — Ready
    splash.set_status("Ready.", progress=100)
    app.processEvents()

    window.show()
    splash.finish(window)

    exit_code = app.exec()
    db.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
