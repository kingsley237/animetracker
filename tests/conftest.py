"""
Shared test fixtures.

Every test runs against a fresh temporary database and a throwaway settings
file, fully offline (AniList / MyAnimeList / GitHub calls are blocked), and
Qt runs "offscreen" so no windows appear. Nothing touches the real library
in ~/.animetracker or the real Miroku settings.
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
import requests  # noqa: E402


# ── Network: blocked by default ───────────────────────────────────────────────

class NetworkBlocked(requests.ConnectionError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any real HTTP call fails fast, like being offline."""
    def _blocked(*a, **k):
        raise NetworkBlocked("network is disabled in tests")
    monkeypatch.setattr(requests.Session, "request", _blocked)
    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)
    # AniList client: return "no data" instantly instead of retrying/sleeping
    import core.api as api
    monkeypatch.setattr(api, "_post", lambda *a, **k: None)
    api._cache_clear()
    yield


# ── Settings: throwaway ini file ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    from PyQt6.QtCore import QSettings
    ini = str(tmp_path / "settings.ini")
    import core.app_settings as cs
    monkeypatch.setattr(cs, "app_settings", lambda: QSettings(ini, QSettings.Format.IniFormat))
    # existing UI tests start on the Library (the app itself opens on Home)
    QSettings(ini, QSettings.Format.IniFormat).setValue("start_page", "library")
    yield


@pytest.fixture(autouse=True)
def isolated_catalog(monkeypatch, tmp_path):
    """The search catalogue lives in a throwaway folder too."""
    import core.catalog as cat
    monkeypatch.setattr(cat, "DIR", tmp_path / "catalog")
    cat._mem.clear()
    cat._index.clear()
    yield


# ── Database ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    from core.database import DatabaseManager
    d = DatabaseManager(tmp_path / "test.db")
    yield d
    d.close()


DAY = 86400


def add_anime(db, title="Show", ws="watching", **kw):
    """Insert a library row with sensible defaults; returns its id."""
    data = {
        "romaji_title": title, "english_title": kw.pop("english_title", title),
        "watch_status": ws, "status": kw.pop("status", "FINISHED"),
        "total_episodes": kw.pop("total_episodes", 12),
        "anilist_id": kw.pop("anilist_id", None),
        "genres": kw.pop("genres", ["Action"]), "studios": kw.pop("studios", ["Studio"]),
    }
    data.update(kw)
    return db.add_anime(data)


def watch(db, anime_id, upto, start_ts=None, per_day=1):
    """Mark episodes 1..upto watched, spaced a day apart from start_ts."""
    start_ts = start_ts or int(time.time()) - upto * DAY
    for ep in range(1, upto + 1):
        db.set_episode_watched(anime_id, ep, True)
        db._get_conn().execute(
            "UPDATE episodes SET watched_at=? WHERE anime_id=? AND episode_num=?",
            (start_ts + (ep - 1) * DAY // per_day, anime_id, ep))
    db._get_conn().commit()


# ── Qt ────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401  (must precede QApplication)
    except Exception:
        pass
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QFont
    app = QApplication.instance() or QApplication(["miroku-tests"])
    app.setFont(QFont("Segoe UI", 10))
    qss = ROOT / "resources" / "themes" / "dark.qss"
    if qss.exists():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))
    yield app


LATE_ERRORS = []


@pytest.fixture(scope="session", autouse=True)
def _qt_error_guard():
    """Errors escaping Qt callbacks would abort the whole test run (as they
    would the app without main.py's guard). Record them instead and fail
    the test they happened in."""
    import traceback

    def hook(t, v, tb):
        LATE_ERRORS.append("".join(traceback.format_exception(t, v, tb)))
        sys.__stderr__.write("\n[Qt callback error]\n" + LATE_ERRORS[-1])

    old = sys.excepthook
    sys.excepthook = hook
    yield
    sys.excepthook = old


@pytest.fixture(autouse=True)
def _no_callback_errors():
    start = len(LATE_ERRORS)
    yield
    new = LATE_ERRORS[start:]
    assert not new, "error in a Qt callback during this test:\n" + new[0]


@pytest.fixture(scope="session", autouse=True)
def _drain_workers_at_exit():
    """Let background workers finish before the interpreter shuts down;
    tearing Qt's thread pool down under a running worker hard-exits."""
    yield
    try:
        from PyQt6.QtCore import QThreadPool
        QThreadPool.globalInstance().waitForDone(10000)
    except Exception:
        pass


def pump(ms=50):
    """Let Qt process events (and finished background workers) for ms."""
    from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    QCoreApplication.processEvents()


def wait_until(pred, timeout=8.0, step=40):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        pump(step)
    return pred()
