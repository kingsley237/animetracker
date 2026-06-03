"""
Miroku — Background Workers
QThread-based workers for non-blocking API calls and image downloads.
"""
from PyQt6.QtCore import QThread, pyqtSignal, QObject, QRunnable, QThreadPool
from typing import Optional, List, Dict, Any, Callable
import threading


# ─── Generic Worker Runnable ──────────────────────────────────────────────────

class WorkerSignals(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    finished = pyqtSignal()
    progress = pyqtSignal(int, int)   # current, total


class Worker(QRunnable):
    """Generic threadpool worker. Pass any callable."""

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.result.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


# ─── Image Download Worker ────────────────────────────────────────────────────

class ImageWorker(QRunnable):
    """Downloads a single image and emits the local path."""

    def __init__(self, url: str, target_id: Any, size: str = "cover"):
        super().__init__()
        self.url = url
        self.target_id = target_id
        self.size = size
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            from core.image_cache import download_image
            path = download_image(self.url)
            self.signals.result.emit((self.target_id, self.size, path))
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


# ─── Search Worker ────────────────────────────────────────────────────────────

class SearchWorker(QRunnable):
    def __init__(self, query: str):
        super().__init__()
        self.query = query
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            from core.api import search_anime
            results = search_anime(self.query, per_page=20)
            self.signals.result.emit(results)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


# ─── Seasonal Worker ──────────────────────────────────────────────────────────

class SeasonalWorker(QRunnable):
    def __init__(self, season: str, year: int, sort: str = "SCORE_DESC", genre: Optional[str] = None):
        super().__init__()
        self.season = season
        self.year = year
        self.sort = sort
        self.genre = genre
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            from core.api import get_seasonal_anime
            results = get_seasonal_anime(self.season, self.year, self.sort, self.genre)
            self.signals.result.emit(results)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


# ─── Airing Refresh Worker ────────────────────────────────────────────────────

class AiringRefreshWorker(QRunnable):
    def __init__(self, anilist_ids: List[int]):
        super().__init__()
        self.anilist_ids = anilist_ids
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            from core.api import refresh_airing_data
            results = refresh_airing_data(self.anilist_ids)
            self.signals.result.emit(results)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


# ─── Legacy JSON Import Worker ────────────────────────────────────────────────

class ImportWorker(QRunnable):
    def __init__(self, json_path: str, db_manager):
        super().__init__()
        self.json_path = json_path
        self.db = db_manager
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            count = self.db.import_legacy_json(self.json_path)
            self.signals.result.emit(count)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


# ─── Thread pool singleton ────────────────────────────────────────────────────

_pool: Optional[QThreadPool] = None


def get_pool() -> QThreadPool:
    global _pool
    if _pool is None:
        _pool = QThreadPool.globalInstance()
        _pool.setMaxThreadCount(6)
    return _pool


def run_worker(worker: QRunnable):
    get_pool().start(worker)