"""
Raikō - find any title online and add it to the library in one step.

Used where you want to pick something you've watched that isn't in Kinema /
Miroku yet (the Hall of Fame pickers): search AniList / TMDB, then add the
chosen title as watched so it lands in its library with full details.
"""
from __future__ import annotations

from typing import Dict, List, Optional


def in_library(db, hit: Dict) -> Optional[Dict]:
    kind = hit.get("media_type") or "movie"
    if kind == "anime":
        return db.get_anime_by_anilist_id(hit["provider_id"])
    return db.get_title_by_tmdb(kind, hit["provider_id"])


def search(kind: str, query: str, page: int = 1) -> List[Dict]:
    """Online search for one library kind ('anime' | 'movie' | 'tv'),
    ranked so titles starting with what you typed come first."""
    from core import catalog
    q = (query or "").strip()
    if not q:
        return []
    local = catalog.search(kind, q) if page == 1 else []
    try:
        if kind == "anime":
            from core.api import search_anime
            from core.miroku_discover import _hits
            online = _hits(search_anime(q, page=page, per_page=30) or [])
        else:
            from core import tmdb
            from core.kinema_discover import _hits
            online = _hits(tmdb.search(q, kind, page=page), kind)
    except Exception:
        online = []
    return catalog.rank(catalog.merge(local, online), q) if page == 1 else online


def add_watched(db, hit: Dict) -> Optional[int]:
    """Network + database: add `hit` as finished/watched. Returns the library
    id (the existing one if it's already there), or None when offline."""
    have = in_library(db, hit)
    if have:
        return have["id"]
    kind = hit.get("media_type") or "movie"
    pid = hit["provider_id"]
    if kind == "anime":
        from core.api import get_metadata_batch
        from ui.kinema_add_dialog import _save_anime
        m = get_metadata_batch([pid]).get(int(pid))
        if not m:
            return None
        finished = (m.get("status") or "") in ("FINISHED", "CANCELLED")
        lib_id = _save_anime(db, m, "completed" if finished else "watching")
        if not finished:
            nxt = (m.get("nextAiringEpisode") or {}).get("episode")
            for n in range(1, int(nxt or 1)):
                db.set_episode_watched(lib_id, n, True)
        return lib_id
    if kind == "tv":
        from core.kinema_sync import fetch_tv_full, save_tv_full
        import time
        row, eps = fetch_tv_full(pid)
        if not row:
            return None
        ended = row.get("status") in ("FINISHED", "CANCELLED")
        lib_id = save_tv_full(db, row, eps or [], "completed" if ended else "watching")
        today = time.strftime("%Y-%m-%d")
        aired = [(e["season_number"], e["episode_number"]) for e in eps or []
                 if e["season_number"] > 0 and e.get("air_date") and e["air_date"] <= today]
        if aired:
            db.set_tv_watched_through(lib_id, *max(aired))
        return lib_id
    from core.providers import get_provider
    row = get_provider("movie").details(pid)
    if not row:
        return None
    return db.save_tmdb_title(row, "completed")


def add_movie_by_tmdb(db, tmdb_id: int) -> Optional[int]:
    return add_watched(db, {"media_type": "movie", "provider_id": int(tmdb_id)})
