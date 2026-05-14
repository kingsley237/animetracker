"""
AnimeTracker — Update Checker
Checks GitHub Releases API on startup in a background thread.
No auth required — uses the public API endpoint.

Usage:
    checker = UpdateChecker("your-username", "animetracker")
    checker.signals.update_available.connect(on_update)
    checker.signals.up_to_date.connect(on_up_to_date)
    QThreadPool.globalInstance().start(checker)
"""
import re
import requests
from typing import Optional, Tuple

from PyQt6.QtCore import QRunnable, QObject, pyqtSignal

# ── Change this to your GitHub username once you've pushed the repo ──────────
GITHUB_OWNER = "kingsley237"
GITHUB_REPO  = "animetracker"

# Current app version — bump this every release
APP_VERSION  = "2.2.0"

def _parse_version(v: str) -> Tuple[int, int, int]:
    """Parse 'v2.1.3' or '2.1.3' into (2, 1, 3)."""
    v = v.lstrip("v").strip()
    parts = re.findall(r"\d+", v)
    parts = (parts + ["0", "0", "0"])[:3]
    return tuple(int(p) for p in parts)


def _is_newer(latest: str, current: str) -> bool:
    return _parse_version(latest) > _parse_version(current)


class _UpdateSignals(QObject):
    update_available = pyqtSignal(str, str, str)  # latest_version, release_notes, download_url
    up_to_date       = pyqtSignal(str)             # current_version
    error            = pyqtSignal(str)


class UpdateChecker(QRunnable):
    """
    Background worker that checks GitHub Releases for a newer version.
    Emits update_available if a newer release exists, up_to_date otherwise.
    """

    def __init__(self, owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO):
        super().__init__()
        self.owner   = owner
        self.repo    = repo
        self.signals = _UpdateSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            url  = f"https://api.github.com/repos/{self.owner}/{self.repo}/releases/latest"
            resp = requests.get(
                url,
                timeout=8,
                headers={"Accept": "application/vnd.github+json"},
            )
            if resp.status_code == 404:
                # Repo has no releases yet — silently ignore
                return
            resp.raise_for_status()
            data = resp.json()

            latest_version = data.get("tag_name", "")
            release_notes  = data.get("body", "")[:800]   # cap at 800 chars
            html_url       = data.get("html_url", "")

            # Find the Windows .exe asset download URL if available
            assets       = data.get("assets", [])
            download_url = html_url   # fallback to release page
            for asset in assets:
                name = asset.get("name", "").lower()
                if name.endswith(".exe") or name.endswith(".zip"):
                    download_url = asset.get("browser_download_url", html_url)
                    break

            if latest_version and _is_newer(latest_version, APP_VERSION):
                self.signals.update_available.emit(
                    latest_version, release_notes, download_url
                )
            else:
                self.signals.up_to_date.emit(APP_VERSION)

        except requests.ConnectionError:
            pass   # Offline — silently ignore
        except requests.Timeout:
            pass   # Slow connection — silently ignore
        except Exception as e:
            self.signals.error.emit(str(e))