"""
AnimeTracker — Image Cache
Downloads and caches anime cover art and banners locally.
Serves cached images on subsequent requests.
"""
import os
import hashlib
import threading
import requests
from pathlib import Path
from typing import Optional, Callable


IMAGE_CACHE_DIR = Path.home() / ".animetracker" / "covers"
IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_active_downloads: set = set()
_lock = threading.Lock()


def _url_to_path(url: str, suffix: str = ".jpg") -> Path:
    key = hashlib.md5(url.encode()).hexdigest()
    return IMAGE_CACHE_DIR / f"{key}{suffix}"


def get_cached_path(url: str) -> Optional[Path]:
    """Return local path if image is already cached, else None."""
    if not url:
        return None
    for ext in (".jpg", ".png", ".webp"):
        p = _url_to_path(url, ext)
        if p.exists() and p.stat().st_size > 1000:
            return p
    return None


def download_image(
    url: str,
    on_done: Optional[Callable[[Optional[str]], None]] = None,
    force: bool = False,
) -> Optional[str]:
    """
    Download an image. Blocking version — call from a worker thread.
    Returns local path string on success, None on failure.
    Calls on_done(path_or_None) when complete.
    """
    if not url:
        if on_done:
            on_done(None)
        return None

    cached = get_cached_path(url)
    if cached and not force:
        result = str(cached)
        if on_done:
            on_done(result)
        return result

    with _lock:
        if url in _active_downloads:
            if on_done:
                on_done(None)
            return None
        _active_downloads.add(url)

    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "AnimeTracker/2.0"})
        resp.raise_for_status()

        # Detect extension from content-type
        ct = resp.headers.get("content-type", "")
        if "png" in ct:
            ext = ".png"
        elif "webp" in ct:
            ext = ".webp"
        else:
            ext = ".jpg"

        dest = _url_to_path(url, ext)
        dest.write_bytes(resp.content)
        result = str(dest)
    except Exception:
        result = None
    finally:
        with _lock:
            _active_downloads.discard(url)

    if on_done:
        on_done(result)
    return result


def purge_cache(max_size_mb: int = 500):
    """Remove oldest cached images if cache exceeds max_size_mb."""
    files = sorted(
        IMAGE_CACHE_DIR.iterdir(),
        key=lambda p: p.stat().st_mtime,
    )
    total = sum(p.stat().st_size for p in files)
    max_bytes = max_size_mb * 1024 * 1024
    for p in files:
        if total <= max_bytes:
            break
        total -= p.stat().st_size
        p.unlink(missing_ok=True)


def cache_size_mb() -> float:
    total = sum(p.stat().st_size for p in IMAGE_CACHE_DIR.iterdir())
    return round(total / (1024 * 1024), 1)