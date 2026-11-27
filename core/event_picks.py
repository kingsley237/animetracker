"""
Raikō - picks for the event spotlight.

  christmas   films & shows tagged christmas / christmas eve (TMDB)
  halloween   films & shows tagged halloween (TMDB) + popular horror anime (AniList)
  new_year    films tagged new year's eve (TMDB)
  season_*    this anime season's most anticipated (AniList)

Your own Watchlist / Plan to Watch titles that fit come first; titles you've
already finished are left out. Cached for the day.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List

CACHE = Path.home() / ".animetracker" / "cache" / "event_picks.json"
KEYWORDS = {"christmas": "207317|260365", "halloween": "3335|232795", "new_year": "613"}
GENRES = {"halloween": "27|14|9648|16", "new_year": "35|10749"}      # horror/fantasy/mystery/animation; comedy/romance


def _tmdb(kind: str, keywords: str, genres: str = "") -> List[Dict]:
    from core import tmdb
    from core.kinema_discover import _hits
    params = {"with_keywords": keywords, "sort_by": "popularity.desc",
              "vote_count.gte": 150 if kind == "movie" else 40, "include_adult": "false"}
    if genres and kind == "movie":
        params["with_genres"] = genres
    data = tmdb.get(f"/discover/{kind}", params, ttl=86400) or {}
    return _hits(data.get("results") or [], kind)


def _fetch(ev_id: str) -> List[Dict]:
    out: List[Dict] = []
    if ev_id in KEYWORDS:
        out += _tmdb("movie", KEYWORDS[ev_id], GENRES.get(ev_id, ""))
        if ev_id != "new_year":
            out += _tmdb("tv", KEYWORDS[ev_id])[:6]
    if ev_id == "halloween":
        from core.miroku_discover import _hits, _page
        out += _hits(_page('genre_in: ["Horror"], sort: [POPULARITY_DESC]', {}, pages=1))[:8]
    if ev_id.startswith("season"):
        from core.miroku_discover import load_source
        out += load_source("season")[:12]
    return out


def picks(ev_id: str, db=None, limit: int = 6) -> List[Dict]:
    """Network (cached a day): the event's picks, your saved titles first."""
    try:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    key = f"{ev_id}:{time.strftime('%Y-%m-%d')}"
    hits = cache.get(key)
    if hits is None:
        hits = _fetch(ev_id)
        cache = {key: hits}
        try:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(hits and cache, default=str), encoding="utf-8")
        except OSError:
            pass
    if db is None:
        return hits[:limit]
    from core.quick_add import in_library
    saved, fresh, seen = [], [], set()
    for h in hits:
        k = (h.get("media_type"), h.get("provider_id"))
        if k in seen:
            continue
        seen.add(k)
        row = in_library(db, h)
        if row is not None:
            if row.get("watch_status") == "planned":
                saved.append({**h, "reason": "On your Watchlist", "_lib_id": row["id"]})
            continue                                    # watching / finished: not a pick
        fresh.append(h)
    return (saved + fresh)[:limit]
