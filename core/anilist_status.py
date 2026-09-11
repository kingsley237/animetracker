"""
Miroku — AniList API Status Monitor

AniList's GraphQL API occasionally gets disabled outright on their end
(distinct from the user's own internet being down — ConnectivityMonitor
already covers that). When it happens every request returns HTTP 403
with a body like {"errors":[{"message":"The AniList API has been
temporarily disabled due to severe stability issues.", "status":403}]}.

This polls a minimal query on its own schedule so the app can surface
a clear "AniList is down, not you" warning instead of Discover/library
refreshes just silently coming back empty.
"""
import time
from typing import Optional

import requests
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

ANILIST_URL       = "https://graphql.anilist.co"
CHECK_INTERVAL_MS = 120_000   # re-check every 2 minutes while down/unknown
CHECK_TIMEOUT     = 8
_PING_QUERY       = "query{Page(page:1,perPage:1){media(sort:TRENDING_DESC){id}}}"


def check_anilist_status() -> tuple[bool, str]:
    """One-shot check. Returns (is_up, message)."""
    try:
        resp = requests.post(
            ANILIST_URL,
            json={"query": _PING_QUERY, "variables": {}},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=CHECK_TIMEOUT,
        )
    except requests.RequestException as e:
        return False, f"Couldn't reach AniList ({e.__class__.__name__})."

    if resp.status_code == 200:
        return True, "AniList API is operating normally."

    message = None
    try:
        body = resp.json()
        errors = body.get("errors") or []
        if errors:
            message = errors[0].get("message")
    except ValueError:
        pass

    if resp.status_code == 403 and message and "disabled" in message.lower():
        return False, message
    return False, message or f"AniList API returned HTTP {resp.status_code}."


class AniListStatusMonitor(QObject):
    """
    Polls AniList's own status (not general internet connectivity) on a
    QTimer. Only polls while status is down or unknown — once confirmed
    up, it goes quiet until something asks it to check again (a failed
    fetch elsewhere in the app calls report_failure() to resume polling
    immediately instead of waiting out the interval).

    Signals:
        api_down(message: str)     — just went from up/unknown to down
        api_up()                   — just went from down to up
        checked(is_up: bool, message: str)  — every poll, regardless of change
    """
    api_down = pyqtSignal(str)
    api_up   = pyqtSignal()
    checked  = pyqtSignal(bool, str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._is_up: Optional[bool] = None   # None = unknown yet
        self._last_message = ""
        self._last_checked_at: Optional[float] = None
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self._check)

    def start(self):
        self._timer.start()
        QTimer.singleShot(400, self._check)

    def stop(self):
        self._timer.stop()

    def is_up(self) -> Optional[bool]:
        return self._is_up

    def last_message(self) -> str:
        return self._last_message

    def last_checked_at(self) -> Optional[float]:
        return self._last_checked_at

    def force_check(self):
        """Trigger an immediate check (manual retry button, etc.)."""
        self._check()

    def report_failure(self, message: str = ""):
        """
        Called by any code path that just got a real request failure from
        AniList (not this monitor's own ping), so the banner can appear
        right away instead of waiting up to CHECK_INTERVAL_MS. Runs a
        real check rather than trusting the caller's message blindly.
        """
        self._check()

    def _check(self):
        from workers.workers import Worker, run_worker

        def fetch():
            return check_anilist_status()

        def on_done(result):
            is_up, message = result
            self._last_checked_at = time.time()
            was_up = self._is_up
            self._is_up = is_up
            self._last_message = message
            self.checked.emit(is_up, message)

            if was_up is not False and not is_up:
                self.api_down.emit(message)
            elif was_up is False and is_up:
                self.api_up.emit()

        w = Worker(fetch)
        w.signals.result.connect(on_done)
        run_worker(w)
