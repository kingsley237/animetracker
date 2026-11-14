"""
Miroku - trailers & promo videos.

AniList only carries one trailer per anime. MyAnimeList (through the free,
key-less Jikan API) lists every promo video - PV 1, PV 2, teasers, CMs -
plus the opening/ending music videos. We merge both into one ordered
playlist: AniList's trailer first, then promos, then music videos.

Jikan is optional: if it is down or unreachable, the playlist is simply the
AniList trailer. Failures are cached briefly so we don't hammer it.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

import requests

JIKAN = "https://api.jikan.moe/v4/anime/{mal_id}/videos"
_HEADERS = {"User-Agent": "Miroku-anime-tracker", "Accept": "application/json"}
_last_call = 0.0
_FAIL_BACKOFF = 6 * 3600
_failed_at: Dict[int, float] = {}


def _yt_thumb(vid: str) -> str:
    return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"


def parse_jikan_videos(data: Dict) -> List[Dict]:
    """Jikan /anime/{id}/videos payload -> [{id, site, title, kind, thumb}]."""
    out: List[Dict] = []
    for p in (data or {}).get("promo") or []:
        tr = p.get("trailer") or {}
        vid = tr.get("youtube_id")
        if not vid:
            continue
        imgs = tr.get("images") or {}
        out.append({
            "id": vid, "site": "youtube", "kind": "promo",
            "title": (p.get("title") or "Promo").strip(),
            "thumb": imgs.get("maximum_image_url") or imgs.get("large_image_url") or _yt_thumb(vid),
        })
    for m in (data or {}).get("music_videos") or []:
        v = m.get("video") or {}
        vid = v.get("youtube_id")
        if not vid:
            continue
        meta = m.get("meta") or {}
        title = (m.get("title") or "Theme").strip()
        song = meta.get("title")
        if song and song.lower() not in title.lower():
            title = f"{title} · {song}"
        imgs = v.get("images") or {}
        out.append({
            "id": vid, "site": "youtube", "kind": "music",
            "title": title, "artist": meta.get("author") or "",
            "thumb": imgs.get("maximum_image_url") or imgs.get("large_image_url") or _yt_thumb(vid),
        })
    return out


def fetch_mal_videos(mal_id: Optional[int], timeout: int = 8) -> Optional[List[Dict]]:
    """None = couldn't ask (offline / Jikan down); [] = asked, nothing there."""
    global _last_call
    if not mal_id:
        return []
    if time.time() - _failed_at.get(int(mal_id), 0) < _FAIL_BACKOFF:
        return None
    wait = 0.45 - (time.time() - _last_call)      # Jikan: ~3 requests/second
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()
    try:
        r = requests.get(JIKAN.format(mal_id=int(mal_id)), headers=_HEADERS, timeout=timeout)
        if r.status_code == 404:
            return []
        if r.status_code == 429:
            time.sleep(1.5)
            r = requests.get(JIKAN.format(mal_id=int(mal_id)), headers=_HEADERS, timeout=timeout)
        r.raise_for_status()
        return parse_jikan_videos(r.json().get("data") or {})
    except Exception:
        _failed_at[int(mal_id)] = time.time()
        return None


def build_playlist(anime: Dict, mal_videos: Optional[List[Dict]] = None) -> List[Dict]:
    """AniList trailer first, then MAL promos and themes, de-duplicated."""
    items: List[Dict] = []
    seen = set()
    tid = anime.get("trailer_id")
    site = (anime.get("trailer_site") or "youtube").lower()
    if tid and site in ("youtube", "dailymotion"):
        items.append({"id": tid, "site": site, "kind": "promo", "title": "Official trailer",
                      "thumb": anime.get("trailer_thumb") or (_yt_thumb(tid) if site == "youtube" else "")})
        seen.add(tid)
    for v in (mal_videos if mal_videos is not None else (anime.get("videos") or [])):
        if v.get("id") and v["id"] not in seen:
            items.append(v)
            seen.add(v["id"])
    return items
