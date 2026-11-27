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

# WebEngine MUST be imported before QApplication — Qt requirement
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
except ImportError:
    pass  # PyQt6-WebEngine not installed — trailer player will fall back to browser

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QCoreApplication
from PyQt6.QtGui import QCursor, QFont, QIcon

from core.database import DatabaseManager


def _build_app_icon() -> QIcon:
    resources = ROOT / "resources"
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 96, 128, 180, 192, 256, 512, 1024):
        path = resources / f"raiko_icon_{size}.png"
        if path.exists():
            icon.addFile(str(path))
    if icon.isNull():
        ico = resources / "raiko_app_icon.ico"
        if ico.exists():
            icon = QIcon(str(ico))
    return icon


def _install_crash_guard():
    """PyQt aborts the whole app when a Python error escapes a Qt callback.
    Log it to ~/.animetracker/error.log instead and keep running."""
    import traceback
    from datetime import datetime as _dt
    log_path = Path.home() / ".animetracker" / "error.log"

    def hook(exc_type, exc, tb):
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            # keep the log small: trim to the last ~200 KB
            if log_path.exists() and log_path.stat().st_size > 400_000:
                log_path.write_text(log_path.read_text(encoding="utf-8", errors="ignore")[-200_000:],
                                    encoding="utf-8")
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"\n[{_dt.now():%Y-%m-%d %H:%M:%S}] "
                        + "".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


INSTANCE_KEY = "raiko-main-instance"


def _send_to_running(message: str) -> bool:
    """If Raikō is already open, hand it a message ('show' / 'open:<id>')."""
    from PyQt6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if not sock.waitForConnected(400):
        return False
    sock.write(message.encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(400)
    sock.disconnectFromServer()
    return True


def _open_target() -> str:
    """raiko://open/<id> (a clicked Windows notification) -> 'open:<id>'."""
    for a in sys.argv[1:]:
        if a.lower().startswith("raiko://open/"):
            tail = a.split("://open/", 1)[1].strip("/ ")
            return f"open:{tail}" if tail.isdigit() else "show"
    return "show"


def _run_check() -> int:
    """`--check`: Windows' scheduled task. Refresh, notify, exit. Silent, no window."""
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtNetwork import QLocalSocket
    qapp = QCoreApplication(sys.argv)            # noqa: F841 - settings / sockets need it
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if sock.waitForConnected(300):
        return 0                                 # Raikō is open: it shows its own alerts
    from core import background_check as bc
    if not bc.enabled():
        return 0
    db = DatabaseManager()
    bc.register()
    bc.run_check(db)
    bc.notify_new(db)
    return 0


def main():
    _install_crash_guard()
    if "--check" in sys.argv:
        sys.exit(_run_check())
    try:
        from core.updater import APP_VERSION
    except Exception:
        APP_VERSION = "2.2.0"

    from core.app_settings import migrate_legacy_settings
    migrate_legacy_settings()

    app = QApplication(sys.argv)
    # One Raikō at a time: a second launch (or a clicked notification) is
    # handed to the window that's already open.
    if _send_to_running(_open_target()):
        sys.exit(0)
    app.setApplicationName("Miroku")
    app.setApplicationDisplayName("Raikō")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("Miroku")

    # App icon
    app_icon = _build_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    startup_screen = app.screenAt(QCursor.pos()) or app.primaryScreen()

    from ui.splash import SplashScreen
    splash = SplashScreen(APP_VERSION, startup_screen)
    if not app_icon.isNull():
        splash.setWindowIcon(app_icon)
    splash.show()
    app.processEvents()
    splash.set_status("Starting Raikō…", progress=10)

    # Stage 1 — Theme
    splash.set_status("Loading theme…", progress=25)
    from core.app_settings import resolved_theme
    from pathlib import Path as _Path
    _qss = _Path(__file__).parent / "resources" / "themes" / f"{resolved_theme()}.qss"
    if not _qss.exists():
        _qss = _Path(__file__).parent / "resources" / "themes" / "dark.qss"
    if _qss.exists():
        from ui.theme import ThemeManager
        ThemeManager.get().set_base_stylesheet(_qss.read_text(encoding="utf-8"))
        try:
            ThemeManager.get().load_saved()          # your chosen theme (Settings → Appearance)
        except Exception:
            pass

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
    window = MainWindow(
        db,
        demo_new_season="--demo-new-season" in sys.argv,
        demo_planned="--demo-planned" in sys.argv,
    )
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

    # Listen for later launches / notification clicks
    from PyQt6.QtNetwork import QLocalServer
    QLocalServer.removeServer(INSTANCE_KEY)          # stale socket after a crash
    server = QLocalServer(window)
    server.listen(INSTANCE_KEY)

    def _incoming():
        conn = server.nextPendingConnection()
        if conn is None:
            return
        conn.waitForReadyRead(400)
        window.handle_external(bytes(conn.readAll()).decode("utf-8", "ignore"))
        conn.disconnectFromServer()

    server.newConnection.connect(_incoming)
    window._instance_server = server
    first = _open_target()
    if first.startswith("open:"):
        from PyQt6.QtCore import QTimer as _QT
        _QT.singleShot(1500, lambda: window.handle_external(first))

    exit_code = app.exec()
    db.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
