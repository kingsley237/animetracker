"""Miroku - add an AniList media dict to the library."""
from typing import Dict, Optional

from core.api import format_air_date
from core.database import DatabaseManager


def add_media_to_library(db: DatabaseManager, media: Dict,
                         watch_status: Optional[str] = None) -> str:
    """Insert an AniList media dict into the library. Returns the watch
    status used ('planned' for not-yet-released, else 'watching' unless
    overridden)."""
    t    = media.get("title", {}) or {}
    cov  = media.get("coverImage") or {}
    nae  = media.get("nextAiringEpisode") or {}
    sd   = media.get("startDate") or {}
    trailer = media.get("trailer") or {}
    api_s = (media.get("status") or "").upper()
    ws   = watch_status or ("planned" if api_s == "NOT_YET_RELEASED" else "watching")

    db.add_anime({
        "anilist_id":       media.get("id"),
        "romaji_title":     t.get("romaji", "Unknown"),
        "english_title":    t.get("english") or "",
        "native_title":     t.get("native") or "",
        "watch_status":     ws,
        "status":           media.get("status", ""),
        "cover_url":        cov.get("large") or cov.get("medium") or "",
        "banner_url":       media.get("bannerImage") or "",
        "description":      media.get("description") or "",
        "genres":           media.get("genres") or [],
        "studios":          [s["name"] for s in
                             ((media.get("studios") or {}).get("nodes") or [])],
        "total_episodes":   media.get("episodes"),
        "season":           media.get("season") or "",
        "season_year":      media.get("seasonYear"),
        "average_score":    media.get("averageScore"),
        "popularity":       media.get("popularity"),
        "trailer_id":       trailer.get("id") or None,
        "trailer_site":     trailer.get("site") or None,
        "start_date":       format_air_date(sd),
        "next_episode_at":  nae.get("airingAt"),
        "next_episode_num": nae.get("episode"),
    })
    return ws


