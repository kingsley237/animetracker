"""
Miroku — Smart external link opener.

Opens platform links in native apps when possible (Telegram, etc.) with an
optional user preference to always use the browser.
"""
from __future__ import annotations

import re
import subprocess
import sys
import webbrowser
from typing import Optional, Tuple
from urllib.parse import urlparse

from core.app_settings import app_settings

_PLATFORM_PATTERNS = {
    "telegram": re.compile(r"(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/", re.I),
    "crunchyroll": re.compile(r"(?:https?://)?(?:www\.)?crunchyroll\.com/", re.I),
    "netflix": re.compile(r"(?:https?://)?(?:www\.)?netflix\.com/", re.I),
    "disney": re.compile(r"(?:https?://)?(?:www\.)?disneyplus\.com/", re.I),
    "hulu": re.compile(r"(?:https?://)?(?:www\.)?hulu\.com/", re.I),
    "prime": re.compile(r"(?:https?://)?(?:www\.)?amazon\.(?:com|co\.uk)/.*/gp/video/", re.I),
    "youtube": re.compile(r"(?:https?://)?(?:www\.)?(?:youtube\.com|youtu\.be)/", re.I),
}

_PLATFORM_LABELS = {
    "telegram": "Telegram",
    "crunchyroll": "Crunchyroll",
    "netflix": "Netflix",
    "disney": "Disney+",
    "hulu": "Hulu",
    "prime": "Prime Video",
    "youtube": "YouTube",
    "other": "Link",
}


def detect_platform(url: str) -> str:
    url = (url or "").strip()
    for name, pattern in _PLATFORM_PATTERNS.items():
        if pattern.search(url):
            return name
    return "other"


def platform_label(platform: str) -> str:
    return _PLATFORM_LABELS.get(platform, "Link")


def links_always_open_browser() -> bool:
    return app_settings().value("links_always_open_browser", False, type=bool)


def set_links_always_open_browser(value: bool) -> None:
    app_settings().setValue("links_always_open_browser", bool(value))


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://", "tg://")):
        return url
    return f"https://{url}"


def _telegram_app_url(url: str) -> Optional[str]:
    """Convert t.me / telegram.me URL to tg:// deep link."""
    url = normalize_url(url)
    if url.startswith("tg://"):
        return url
    m = re.match(
        r"https?://(?:t\.me|telegram\.me|telegram\.dog)/([^/?#]+)(?:/(\d+))?",
        url,
        re.I,
    )
    if not m:
        return None
    handle, post_id = m.group(1), m.group(2)
    if post_id:
        return f"tg://resolve?domain={handle}&post={post_id}"
    return f"tg://resolve?domain={handle}"


def app_url_for(url: str, platform: Optional[str] = None) -> Tuple[str, str]:
    """
    Return (primary_url, fallback_url) for opening a link.

    primary_url prefers the native app scheme; fallback_url is the web URL.
    """
    url = normalize_url(url)
    platform = platform or detect_platform(url)
    if platform == "telegram":
        app_link = _telegram_app_url(url)
        if app_link:
            return app_link, url
    return url, url


def _open_with_os(url: str) -> bool:
    try:
        if sys.platform == "win32":
            os_result = subprocess.run(
                ["cmd", "/c", "start", "", url],
                check=False,
                capture_output=True,
            )
            return os_result.returncode == 0
        if sys.platform == "darwin":
            subprocess.run(["open", url], check=False)
            return True
        subprocess.run(["xdg-open", url], check=False)
        return True
    except Exception:
        return False


def open_link(url: str, *, force_browser: bool = False, platform: Optional[str] = None) -> bool:
    """Open a link in the best available handler."""
    url = normalize_url(url)
    if not url:
        return False

    use_browser = force_browser or links_always_open_browser()
    primary, fallback = app_url_for(url, platform)

    if use_browser:
        webbrowser.open(fallback)
        return True

    if primary != fallback:
        if _open_with_os(primary):
            return True
        webbrowser.open(fallback)
        return True

    if _open_with_os(primary):
        return True
    webbrowser.open(fallback)
    return True
