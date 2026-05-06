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

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QCoreApplication
from PyQt6.QtGui import QFont, QIcon

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
        db = DatabaseManager()
    except Exception as e:
        QMessageBox.critical(None, "Database Error", f"Failed to initialize database:\n{e}")
        sys.exit(1)

    from ui.main_window import MainWindow
    window = MainWindow(db)
    window.show()

    exit_code = app.exec()
    db.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()