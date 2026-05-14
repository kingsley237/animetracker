"""
AnimeTracker — Entry Point
Run: python main.py
"""
import sys, os
from pathlib import Path

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

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
    app = QApplication(sys.argv)
    app.setApplicationName("AnimeTracker")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("AnimeTracker")

    # App icon
    icon_path = ROOT / "resources" / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    try:
        from core.updater import APP_VERSION
    except Exception:
        APP_VERSION = app.applicationVersion()

    startup_screen = app.screenAt(QCursor.pos()) or app.primaryScreen()

    from ui.splash import SplashScreen
    splash = SplashScreen(APP_VERSION, startup_screen)
    splash.show()
    splash.set_status("Starting Miroku...")

    try:
        splash.set_status("Opening your library...")
        db = DatabaseManager()
    except Exception as e:
        splash.close()
        QMessageBox.critical(None, "Database Error", f"Failed to initialize database:\n{e}")
        sys.exit(1)

    splash.set_status("Building the interface...")
    from ui.main_window import MainWindow
    window = MainWindow(db)
    if startup_screen:
        window.setGeometry(startup_screen.availableGeometry())
        window.showMaximized()
    window.show()
    splash.finish(window)

    exit_code = app.exec()
    db.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
