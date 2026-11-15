"""
Raikō - data providers.

Every screen asks the same questions about a title, whatever kind it is:
search, full details (as a library row), refresh, videos, where to watch.
A provider answers them for one kind of media:

    anime  -> AniList   (the Miroku library)
    tv     -> TMDB      (the Kinema library)
    movie  -> TMDB      (the Kinema library)

Library rows share one shape (the `anime` table, now holding all media),
so cards, panels, alerts and the timeline work unchanged across kinds.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from core import tmdb

MEDIA_TYPES = ("anime", "tv", "movie")


def _year(date_str: Optional[str]) -> Optional[int]:
    try:
        return int((date_str or "")[:4]) or None
    except ValueError:
        return None


def _ts(date_str: Optional[str]) -> Optional[int]:
    try:
        return int(datetime.strptime((date_str or "")[:10], "%Y-%m-%d").timestamp())
    except ValueError:
        return None


def _label(date_str: Optional[str]) -> str:
    ts = _ts(date_str)
    if not ts:
        return ""
    d = datetime.fromtimestamp(ts)
    return d.strftime("%b ") + f"{d.day}, {d.year}"


def _season_of(date_str: Optional[str]) -> str:
    try:
        m = int((date_str or "")[5:7])
    except ValueError:
        return ""
    return {12: "WINTER", 1: "WINTER", 2: "WINTER", 3: "SPRING", 4: "SPRING", 5: "SPRING",
            6: "SUMMER", 7: "SUMMER", 8: "SUMMER"}.get(m, "FALL")


# AniList status vocabulary is the app's lingua franca (cards, alerts, panels).
_TV_STATUS = {"Returning Series": "RELEASING", "Ended": "FINISHED", "Canceled": "CANCELLED",
              "In Production": "NOT_YET_RELEASED", "Planned": "NOT_YET_RELEASED",
              "Pilot": "NOT_YET_RELEASED"}


class Provider:
    media_type = ""

    def search(self, query: str) -> List[Dict]:
        raise NotImplementedError

    def details(self, provider_id: int) -> Optional[Dict]:
        """Full library row (column -> value) or None when unavailable."""
        raise NotImplementedError

    def refresh(self, provider_ids: List[int]) -> Dict[int, Dict]:
        rows = {}
        for pid in provider_ids:
            r = self.details(pid)
            if r:
                rows[pid] = r
        return rows

    def videos(self, provider_id: int) -> List[Dict]:
        return []

    def where_to_watch(self, provider_id: int) -> Dict[str, List[str]]:
        return {"stream": [], "rent": [], "buy": [], "link": ""}


# ── Anime (Miroku) ────────────────────────────────────────────────────────────

class AniListProvider(Provider):
    """Wraps the existing AniList client and mapping. Behaviour is exactly
    what Miroku already does; this only gives it the shared interface."""
    media_type = "anime"

    def search(self, query: str) -> List[Dict]:
        from core.api import search_anime
        out = []
        for m in search_anime(query) or []:
            t = m.get("title") or {}
            out.append({
                "media_type": "anime", "provider_id": m.get("id"),
                "title": t.get("english") or t.get("romaji") or "",
                "original_title": t.get("romaji") or "",
                "year": m.get("seasonYear"), "status": m.get("status"),
                "poster_url": (m.get("coverImage") or {}).get("large") or "",
                "score": m.get("averageScore"), "raw": m,
            })
        return out

    def details(self, provider_id: int) -> Optional[Dict]:
        from core.api import get_metadata_batch
        from core.metadata_sync import media_to_row
        m = get_metadata_batch([provider_id]).get(int(provider_id))
        if not m:
            return None
        row = media_to_row(m)
        row.update({"media_type": "anime", "anilist_id": int(provider_id)})
        return row

    def refresh(self, provider_ids: List[int]) -> Dict[int, Dict]:
        from core.api import get_metadata_batch
        from core.metadata_sync import media_to_row
        out = {}
        for pid, m in get_metadata_batch(list(provider_ids)).items():
            row = media_to_row(m)
            row.update({"media_type": "anime", "anilist_id": int(pid)})
            out[pid] = row
        return out

    def videos(self, provider_id: int) -> List[Dict]:
        from core.videos import build_playlist
        row = self.details(provider_id) or {}
        return build_playlist(row)


# ── TV shows (Kinema) ─────────────────────────────────────────────────────────

def tv_row(d: Dict) -> Dict:
    """TMDB TV details -> library row."""
    nxt = d.get("next_episode_to_air") or {}
    last = d.get("last_episode_to_air") or {}
    first = d.get("first_air_date")
    vids = tmdb.videos(d)
    cast = []
    for c in ((d.get("credits") or {}).get("cast") or [])[:8]:
        cast.append({"name": c.get("name"), "role": c.get("character") or "",
                     "image": tmdb.image_url(c.get("profile_path"), "w185")})
    runtimes = d.get("episode_run_time") or []
    seasons = [s for s in d.get("seasons") or [] if (s.get("season_number") or 0) > 0]
    return {
        "media_type": "tv", "tmdb_id": d.get("id"),
        "imdb_id": (d.get("external_ids") or {}).get("imdb_id"),
        "romaji_title": d.get("name") or d.get("original_name") or "Untitled",
        "english_title": d.get("name") or "",
        "native_title": d.get("original_name") or "",
        "status": _TV_STATUS.get(d.get("status") or "", "RELEASING" if nxt else "FINISHED"),
        "format": "TV",
        "cover_url": tmdb.image_url(d.get("poster_path"), "w500"),
        "banner_url": tmdb.image_url(d.get("backdrop_path"), "w1280"),
        "description": d.get("overview") or "",
        "genres": [g.get("name") for g in d.get("genres") or [] if g.get("name")],
        "studios": [n.get("name") for n in (d.get("networks") or [])[:2] if n.get("name")],
        "total_episodes": d.get("number_of_episodes"),
        "duration": (runtimes[0] if runtimes else (last.get("runtime") or None)),
        "season": _season_of(first), "season_year": _year(first),
        "start_date": _label(first), "start_ts": _ts(first), "start_exact": 1 if _ts(first) else 0,
        "next_episode_at": _ts(nxt.get("air_date")),
        "next_episode_num": nxt.get("episode_number"),
        "trailer_id": vids[0]["id"] if vids else None,
        "trailer_site": "youtube" if vids else None,
        "trailer_thumb": vids[0]["thumb"] if vids else None,
        "videos": vids[1:],
        "average_score": int(round((d.get("vote_average") or 0) * 10)) or None,
        "popularity": int(d.get("popularity") or 0) or None,
        "characters": cast,
        "site_url": f"https://www.themoviedb.org/tv/{d.get('id')}",
        "_seasons": [{"season_number": s.get("season_number"), "name": s.get("name"),
                      "episode_count": s.get("episode_count"), "air_date": s.get("air_date"),
                      "poster_url": tmdb.image_url(s.get("poster_path"), "w342"),
                      "overview": s.get("overview") or ""} for s in seasons],
        "_next_season": nxt.get("season_number"),
    }


class TMDBTVProvider(Provider):
    media_type = "tv"

    def search(self, query: str) -> List[Dict]:
        return [_hit(r, "tv") for r in tmdb.search(query, "tv")]

    def details(self, provider_id: int) -> Optional[Dict]:
        d = tmdb.tv_details(provider_id)
        return tv_row(d) if d else None

    def season(self, provider_id: int, season_number: int) -> List[Dict]:
        s = tmdb.tv_season(provider_id, season_number) or {}
        return [{"season_number": season_number, "episode_number": e.get("episode_number"),
                 "name": e.get("name") or "", "air_date": e.get("air_date"),
                 "runtime": e.get("runtime"),
                 "still_url": tmdb.image_url(e.get("still_path"), "w300")}
                for e in s.get("episodes") or []]

    def videos(self, provider_id: int) -> List[Dict]:
        return tmdb.videos(tmdb.tv_details(provider_id) or {})

    def where_to_watch(self, provider_id: int) -> Dict[str, List[str]]:
        return tmdb.watch_providers(tmdb.tv_details(provider_id) or {})


# ── Movies (Kinema) ───────────────────────────────────────────────────────────

def movie_row(d: Dict) -> Dict:
    """TMDB movie details -> library row."""
    rel = tmdb.us_release_dates(d)
    released = (d.get("status") == "Released")
    when = rel.get("theatrical") or rel.get("theatrical_limited") or d.get("release_date")
    vids = tmdb.videos(d)
    cast = []
    for c in ((d.get("credits") or {}).get("cast") or [])[:8]:
        cast.append({"name": c.get("name"), "role": c.get("character") or "",
                     "image": tmdb.image_url(c.get("profile_path"), "w185")})
    coll = d.get("belongs_to_collection") or {}
    return {
        "media_type": "movie", "tmdb_id": d.get("id"),
        "imdb_id": d.get("imdb_id") or (d.get("external_ids") or {}).get("imdb_id"),
        "romaji_title": d.get("title") or d.get("original_title") or "Untitled",
        "english_title": d.get("title") or "",
        "native_title": d.get("original_title") or "",
        "status": "FINISHED" if released else "NOT_YET_RELEASED",
        "format": "MOVIE",
        "cover_url": tmdb.image_url(d.get("poster_path"), "w500"),
        "banner_url": tmdb.image_url(d.get("backdrop_path"), "w1280"),
        "description": d.get("overview") or "",
        "genres": [g.get("name") for g in d.get("genres") or [] if g.get("name")],
        "studios": [c.get("name") for c in (d.get("production_companies") or [])[:2] if c.get("name")],
        "total_episodes": 1,
        "duration": d.get("runtime"),
        "season": _season_of(when), "season_year": _year(when),
        "start_date": _label(when), "start_ts": _ts(when), "start_exact": 1 if _ts(when) else 0,
        "trailer_id": vids[0]["id"] if vids else None,
        "trailer_site": "youtube" if vids else None,
        "trailer_thumb": vids[0]["thumb"] if vids else None,
        "videos": vids[1:],
        "average_score": int(round((d.get("vote_average") or 0) * 10)) or None,
        "popularity": int(d.get("popularity") or 0) or None,
        "characters": cast,
        "site_url": f"https://www.themoviedb.org/movie/{d.get('id')}",
        "_release_dates": rel,
        "_collection": {"id": coll.get("id"), "name": coll.get("name")} if coll else None,
    }


class TMDBMovieProvider(Provider):
    media_type = "movie"

    def search(self, query: str) -> List[Dict]:
        return [_hit(r, "movie") for r in tmdb.search(query, "movie")]

    def details(self, provider_id: int) -> Optional[Dict]:
        d = tmdb.movie_details(provider_id)
        return movie_row(d) if d else None

    def videos(self, provider_id: int) -> List[Dict]:
        return tmdb.videos(tmdb.movie_details(provider_id) or {})

    def where_to_watch(self, provider_id: int) -> Dict[str, List[str]]:
        return tmdb.watch_providers(tmdb.movie_details(provider_id) or {})

    def collection_parts(self, collection_id: int) -> List[Dict]:
        c = tmdb.collection(collection_id) or {}
        parts = sorted(c.get("parts") or [], key=lambda p: p.get("release_date") or "9999")
        return [_hit(p, "movie") for p in parts]


def _hit(r: Dict, kind: str) -> Dict:
    date = r.get("first_air_date") if kind == "tv" else r.get("release_date")
    return {
        "media_type": kind, "provider_id": r.get("id"),
        "title": r.get("name") or r.get("title") or "",
        "original_title": r.get("original_name") or r.get("original_title") or "",
        "year": _year(date), "status": None,
        "poster_url": tmdb.image_url(r.get("poster_path"), "w342"),
        "score": int(round((r.get("vote_average") or 0) * 10)) or None,
        "overview": r.get("overview") or "", "raw": r,
    }


_PROVIDERS = {"anime": AniListProvider(), "tv": TMDBTVProvider(), "movie": TMDBMovieProvider()}


def get_provider(media_type: str) -> Provider:
    return _PROVIDERS[media_type or "anime"]
