"""
Kinema - movie and TV lists to browse, and recommendations.

TV lists: for_you, airing (new episodes this week), upcoming (new shows),
trending, top_rated, popular.

Lists (US region by default, from Settings):
  for_you    recommendations from what you watched (weighted by your rating)
             and what's on your Watchlist, each with a reason
  upcoming   not released yet, most anticipated first
  trending   trending this week
  hd         out digitally in the last ~6 weeks ("Just out in HD")
  cinemas    playing in cinemas now
  top_rated  best rated of all time
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from core import tmdb

SOURCES = [
    ("for_you", "For you"),
    ("upcoming", "Coming soon"),
    ("trending", "Trending"),
    ("hd", "Just out in HD"),
    ("cinemas", "In cinemas"),
    ("top_rated", "Top rated"),
]

TV_SOURCES = [
    ("for_you", "For you"),
    ("airing", "Airing this week"),
    ("upcoming", "New shows coming"),
    ("trending", "Trending"),
    ("top_rated", "Top rated"),
    ("popular", "Popular"),
]


def sources(kind: str = "movie"):
    return TV_SOURCES if kind == "tv" else SOURCES


SORTS = [("popularity", "Popularity"), ("rating", "Rating"),
         ("release", "Release date"), ("title", "Title")]


def _hits(results: List[Dict], kind: str = "movie") -> List[Dict]:
    from core.providers import _hit
    out = []
    for r in results or []:
        if r.get("adult"):
            continue
        if kind == "tv" and 16 in (r.get("genre_ids") or []) and r.get("original_language") == "ja":
            continue                  # anime lives in Miroku
        h = _hit(r, kind)
        h["popularity"] = r.get("popularity") or 0
        h["release_date"] = r.get("release_date") or r.get("first_air_date") or ""
        h["genre_ids"] = r.get("genre_ids") or []
        out.append(h)
    return out


def _discover(params: Dict, pages: int = 2, kind: str = "movie") -> List[Dict]:
    base = {"region": tmdb.region(), "include_adult": "false", **params}
    if kind == "tv":
        base.pop("region")
        base["watch_region"] = tmdb.region()
    res = tmdb.get_many([(f"/discover/{kind}", {**base, "page": p}) for p in range(1, pages + 1)])
    rows = []
    for page in res:
        rows += (page or {}).get("results") or []
    return rows


def genres(kind: str = "movie") -> List[Dict]:
    data = tmdb.get(f"/genre/{'tv' if kind == 'tv' else 'movie'}/list", ttl=24 * 3600)
    return (data or {}).get("genres") or []


# talk shows, news, reality, soaps: not what people track
_TV_NOISE = "10767,10763,10764,10766"


def _load_tv(source: str) -> List[Dict]:
    today = datetime.now().date()
    if source == "airing":
        res = tmdb.get_many([("/tv/on_the_air", {"page": p}) for p in (1, 2)])
        rows = sum(((r or {}).get("results") or [] for r in res), [])
        rows = [r for r in rows if not set(r.get("genre_ids") or []) & {10767, 10763, 10764, 10766}]
    elif source == "upcoming":
        rows = _discover({"first_air_date.gte": today.isoformat(),
                          "sort_by": "popularity.desc", "without_genres": _TV_NOISE},
                         pages=3, kind="tv")
    elif source == "trending":
        rows = (tmdb.get("/trending/tv/week", ttl=1800) or {}).get("results") or []
    elif source == "top_rated":
        rows = _discover({"sort_by": "vote_average.desc", "vote_count.gte": 500,
                          "without_genres": _TV_NOISE + ",16"}, pages=2, kind="tv")
    elif source == "popular":
        rows = _discover({"sort_by": "popularity.desc", "without_genres": _TV_NOISE,
                          "vote_count.gte": 50}, pages=2, kind="tv")
    else:
        rows = []
    return rows


def load_source(source: str, db=None, kind: str = "movie") -> List[Dict]:
    today = datetime.now().date()
    if source == "for_you":
        return recommend(db, kind=kind) if db is not None else []
    if kind == "tv":
        rows = _load_tv(source)
    elif source == "upcoming":
        rows = _discover({"primary_release_date.gte": today.isoformat(),
                          "sort_by": "popularity.desc", "with_release_type": "2|3"}, pages=3)
    elif source == "trending":
        rows = (tmdb.get("/trending/movie/week", ttl=1800) or {}).get("results") or []
    elif source == "hd":
        rows = _discover({"with_release_type": "4",
                          "release_date.gte": (today - timedelta(days=45)).isoformat(),
                          "release_date.lte": today.isoformat(),
                          "sort_by": "popularity.desc"}, pages=3)
    elif source == "cinemas":
        res = tmdb.get_many([("/movie/now_playing", {"region": tmdb.region(), "page": p}) for p in (1, 2)])
        rows = sum(((r or {}).get("results") or [] for r in res), [])
    elif source == "top_rated":
        # Rated highly by MANY people, not a handful of early votes
        rows = _discover({"sort_by": "vote_average.desc", "vote_count.gte": 1000,
                          "without_genres": "99,10770"}, pages=2)
    else:
        rows = []
    seen, out = set(), []
    for h in _hits(rows, kind):
        if h["provider_id"] not in seen:
            seen.add(h["provider_id"])
            out.append(h)
    return out


def recommend(db, limit: int = 30, kind: str = "movie") -> List[Dict]:
    """Titles like the ones you loved and the ones you're waiting for.
    Watched / finished titles count by your rating (a 6/6 weighs most; 1-2
    are ignored), shows you're watching count well, Watchlist titles count a
    little. Titles already in your library are left out."""
    rows = db.get_all_anime(media_type=kind)
    in_library = {r["tmdb_id"] for r in rows if r.get("tmdb_id")}
    seeds = []
    from core.hall import boosts
    hof = boosts(db)
    for r in rows:
        if not r.get("tmdb_id"):
            continue
        if r["id"] in hof:
            seeds.append((hof[r["id"]], r))
            continue
        if r.get("watch_status") == "completed":
            mine = db.get_overall_rating(r["id"])
            if mine is not None and mine <= 2:
                continue
            weight = {6: 3.0, 5: 2.4, 4: 1.6, 3: 1.0}.get(int(mine), 1.0) if mine else 1.3
            seeds.append((weight, r))
        elif r.get("watch_status") == "watching":
            seeds.append((1.5, r))
        elif r.get("watch_status") == "planned":
            seeds.append((0.8, r))
    seeds.sort(key=lambda s: (-s[0], -(s[1].get("completed_at") or s[1].get("date_added") or 0)))
    seeds = seeds[:10]
    if not seeds:
        trend = load_source("trending", kind=kind)
        what = "shows" if kind == "tv" else "films"
        for h in trend:
            h["reason"] = f"Popular right now. Add or rate a few {what} for picks of your own."
        return [h for h in trend if h["provider_id"] not in in_library][:limit]

    pages = tmdb.get_many([(f"/{kind}/{r['tmdb_id']}/recommendations", {"page": 1}) for _w, r in seeds])
    score: Dict[int, float] = defaultdict(float)
    reason: Dict[int, str] = {}
    best_weight: Dict[int, float] = {}
    raw: Dict[int, Dict] = {}
    for (weight, seed), page in zip(seeds, pages):
        for rank, m in enumerate((page or {}).get("results") or []):
            mid = m.get("id")
            if not mid or mid in in_library or m.get("adult"):
                continue
            score[mid] += weight * (1.0 - rank / 40.0)
            raw[mid] = m
            if weight > best_weight.get(mid, 0):
                best_weight[mid] = weight
                lead = {"completed": "Because you watched", "watching": "Because you're watching"}.get(
                    seed.get("watch_status"), "Because you want to see")
                reason[mid] = f"{lead} {seed.get('romaji_title')}"
    ranked = sorted(score, key=lambda k: (-score[k], -(raw[k].get("popularity") or 0)))
    # Variety: don't let one favourite fill the list - take picks round-robin
    # across the films they came from, best first within each.
    buckets: Dict[str, List[int]] = defaultdict(list)
    for k in ranked:
        buckets[reason.get(k, "")].append(k)
    order = sorted(buckets, key=lambda r: -score[buckets[r][0]])
    mixed: List[int] = []
    while len(mixed) < limit and any(buckets.values()):
        for r in order:
            if buckets[r]:
                mixed.append(buckets[r].pop(0))
                if len(mixed) >= limit:
                    break
    ranked = mixed
    out = _hits([raw[k] for k in ranked], kind)
    for h in out:
        h["reason"] = reason.get(h["provider_id"], "")
    return out


def apply(hits: List[Dict], genre_id: Optional[int] = None, sort: str = "default",
          source: str = "") -> List[Dict]:
    """Filter by genre and sort. 'default' keeps each list's own order
    (e.g. For you = best match first, Coming soon = most anticipated)."""
    out = [h for h in hits if not genre_id or genre_id in (h.get("genre_ids") or [])]
    if sort == "popularity":
        out.sort(key=lambda h: -(h.get("popularity") or 0))
    elif sort == "rating":
        out.sort(key=lambda h: (-(h.get("score") or 0), -(h.get("popularity") or 0)))
    elif sort == "release":
        out.sort(key=lambda h: h.get("release_date") or "0000",
                 reverse=source not in ("upcoming",))
    elif sort == "title":
        out.sort(key=lambda h: (h.get("title") or "").lower())
    return out
