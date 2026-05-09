"""
AnimeTracker — Connectivity Monitor
Real-time internet connection monitoring.
Best practice: poll every 10s with a lightweight DNS check.
Emits online/offline signals. On reconnect, emits reconnected so
the app can refresh stale data without crashing.

Industry standard approach (used by Electron, Tauri, Qt apps):
- Do NOT rely on OS network state (unreliable on Windows/Mac)
- DO use a lightweight periodic check to a reliable host
- Emit typed signals so UI reacts declaratively
"""
import socket
import time
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


CHECK_INTERVAL_MS  = 10_000   # check every 10 seconds
CHECK_HOST         = "8.8.8.8"
CHECK_PORT         = 53
CHECK_TIMEOUT      = 3        # seconds


def _is_online() -> bool:
    """Lightweight connectivity check — DNS port on Google's resolver."""
    try:
        socket.setdefaulttimeout(CHECK_TIMEOUT)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
            (CHECK_HOST, CHECK_PORT)
        )
        return True
    except OSError:
        return False


class ConnectivityMonitor(QObject):
    """
    Polls connectivity every 10 seconds on the main thread via QTimer.
    Safe to use — the DNS check is fast (<100ms when online).

    Signals:
        went_offline()   — connection just dropped
        went_online()    — connection just restored (was offline)
        reconnected()    — same as went_online, used to trigger data refresh
        status_changed(is_online: bool, latency_ms: float)  — every poll
    """
    went_offline   = pyqtSignal()
    went_online    = pyqtSignal()
    reconnected    = pyqtSignal()
    status_changed = pyqtSignal(bool, float)   # is_online, latency_ms

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._is_online    = True   # optimistic initial state
        self._timer        = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self._check)

    def start(self):
        self._timer.start()
        # Run an immediate check
        QTimer.singleShot(500, self._check)

    def stop(self):
        self._timer.stop()

    def force_check(self):
        """Call this to trigger an immediate check (e.g. on app resume)."""
        self._check()

    def is_online(self) -> bool:
        return self._is_online

    def _check(self):
        t0       = time.monotonic()
        online   = _is_online()
        latency  = (time.monotonic() - t0) * 1000   # ms

        was_online = self._is_online
        self._is_online = online

        self.status_changed.emit(online, latency)

        if was_online and not online:
            self.went_offline.emit()
        elif not was_online and online:
            self.went_online.emit()
            self.reconnected.emit()