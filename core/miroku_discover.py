"""
Miroku - anime lists to browse, and recommendations (AniList).

Same shape as core.kinema_discover so one browser drives both:
  sources(kind)  the list chips
  genres(kind)   [{"id", "name"}]  (AniList genres are names, used as ids)
  load_source    hits for a list
  apply          genre filter + sort

Lists:
  for_you     AniList recommendations from what you finished (weighted by
              your rating), what you're watching and your Plan to Watch
  season      airing this season, most popular first
  next        next season, most anticipated first
  trending    trending now
  top_rated   best rated of all time
  popular     most popular of all time
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List

from core.api import MEDIA_FIELDS_SLIM, _post, get_current_season, get_next_season

SOURCES = [
    ("for_you", "For you"),
    ("season", "This season"),
    ("next", "Next season"),
    ("trending", "Trending"),
    ("top_rated", "Top rated"),
    ("popular", "Most popular"),
]

_FIELDS = MEDIA_FIELDS_SLIM + " description(asHtml: false) format"
_FORMATS = "[TV, TV_SHORT, ONA, MOVIE]"


def sources(kind: str = "anime"):
    return SOURCES


def genres(kind: str = "anime") -> List[Dict]:
    from core.api import get_genres_list
    return [{"id": g, "name": g} for g in get_genres_list()]


def _date(sd: Dict) -> str:
    sd = sd or {}
    if not sd.get("year"):
        return ""
    return f"{sd['year']:04d}-{(sd.get('month') or 1):02d}-{(sd.get('day') or 1):02d}"


def _hits(media: List[Dict]) -> List[Dict]:
    out, seen = [], set()
    for m in media or []:
        if not m or m.get("id") in seen or m.get("isAdult"):
            continue
        seen.add(m["id"])
        t = m.get("title") or {}
        out.append({
            "media_type": "anime", "provider_id": m["id"],
            "title": t.get("english") or t.get("romaji") or "",
            "original_title": t.get("romaji") or "",
            "year": m.get("seasonYear") or (m.get("startDate") or {}).get("year"),
            "status": m.get("status"),
            "poster_url": (m.get("coverImage") or {}).get("large") or "",
            "score": m.get("averageScore"),
            "popularity": m.get("popularity") or 0,
            "release_date": _date(m.get("startDate")),
            "genre_ids": m.get("genres") or [],
            "overview": _clean(m.get("description") or ""),
            "raw": m,
        })
    return out


def _clean(txt: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", txt).replace("\n\n", "\n").strip()


def _page(args: str, variables: Dict, pages: int = 2) -> List[Dict]:
    out = []
    for p in range(1, pages + 1):
        gql = f"""query ($page: Int{variables.get('_decl', '')}) {{
            Page(page: $page, perPage: 40) {{
                media(type: ANIME, isAdult: false, format_in: {_FORMATS}, {args}) {{ {_FIELDS} }}
            }} }}"""
        v = {k: val for k, val in variables.items() if not k.startswith("_")}
        data = _post(gql, {"page": p, **v})
        out += ((data or {}).get("Page") or {}).get("media") or []
    return out


def load_source(source: str, db=None, kind: str = "anime") -> List[Dict]:
    if source == "for_you":
        return recommend(db) if db is not None else []
    if source == "season":
        s, y = get_current_season()
        media = _page("season: $season, seasonYear: $year, sort: [POPULARITY_DESC]",
                      {"season": s, "year": y, "_decl": ", $season: MediaSeason, $year: Int"})
    elif source == "next":
        s, y = get_next_season()
        media = _page("season: $season, seasonYear: $year, sort: [POPULARITY_DESC]",
                      {"season": s, "year": y, "_decl": ", $season: MediaSeason, $year: Int"})
    elif source == "trending":
        media = _page("sort: [TRENDING_DESC]", {})
    elif source == "top_rated":
        media = _page("sort: [SCORE_DESC], popularity_greater: 20000", {})
    elif source == "popular":
        media = _page("sort: [POPULARITY_DESC]", {})
    else:
        media = []
    return _hits(media)


def _recommendations(ids: List[int]) -> Dict[int, List[Dict]]:
    """{anilist_id: [recommended media, best first]} in batched queries."""
    out: Dict[int, List[Dict]] = {}
    for i in range(0, len(ids), 5):
        chunk = ids[i:i + 5]
        parts, variables = [], {}
        for j, aid in enumerate(chunk):
            parts.append(f"""a{j}: Media(id: $id{j}, type: ANIME) {{
                recommendations(sort: [RATING_DESC], perPage: 15) {{
                    nodes {{ rating mediaRecommendation {{ {_FIELDS} isAdult }} }} }} }}""")
            variables[f"id{j}"] = aid
        decl = ", ".join(f"$id{j}: Int" for j in range(len(chunk)))
        data = _post(f"query ({decl}) {{ {' '.join(parts)} }}", variables, timeout=20)
        for j, aid in enumerate(chunk):
            nodes = (((data or {}).get(f"a{j}") or {}).get("recommendations") or {}).get("nodes") or []
            out[aid] = [n["mediaRecommendation"] for n in nodes
                        if n.get("mediaRecommendation") and (n.get("rating") or 0) > 0]
        if i + 5 < len(ids):
            time.sleep(0.6)
    return out


def recommend(db, limit: int = 36) -> List[Dict]:
    """Anime like the ones you loved, are watching, or want to watch.
    Finished anime count by your rating (1-2 ignored); anything already in
    your library (or dropped) is left out; picks are mixed across seeds."""
    rows = db.get_all_anime()
    known = {r["anilist_id"] for r in rows if r.get("anilist_id")}
    try:
        known |= {d.get("anilist_id") for d in db.get_dropped_anime() if d.get("anilist_id")}
    except Exception:
        pass
    seeds = []
    from core.hall import boosts
    hof = boosts(db)
    for r in rows:
        if not r.get("anilist_id"):
            continue
        if r["id"] in hof:
            seeds.append((hof[r["id"]], r))
            continue
        ws = r.get("watch_status")
        if ws == "completed":
            mine = db.get_overall_rating(r["id"])
            if mine is not None and mine <= 2:
                continue
            seeds.append(({6: 3.0, 5: 2.4, 4: 1.6, 3: 1.0}.get(int(mine), 1.0) if mine else 1.3, r))
        elif ws == "watching":
            seeds.append((1.5, r))
        elif ws == "planned":
            seeds.append((0.8, r))
    seeds.sort(key=lambda s: (-s[0], -(s[1].get("last_watched_at") or s[1].get("date_added") or 0)))
    seeds = seeds[:10]
    if not seeds:
        hits = load_source("trending")
        for h in hits:
            h["reason"] = "Popular right now. Add or rate a few anime for picks of your own."
        return [h for h in hits if h["provider_id"] not in known][:limit]

    recs = _recommendations([r["anilist_id"] for _w, r in seeds])
    score: Dict[int, float] = defaultdict(float)
    reason: Dict[int, str] = {}
    best: Dict[int, float] = {}
    raw: Dict[int, Dict] = {}
    for weight, seed in seeds:
        for rank, m in enumerate(recs.get(seed["anilist_id"]) or []):
            mid = m.get("id")
            if not mid or mid in known or m.get("isAdult"):
                continue
            score[mid] += weight * (1.0 - rank / 30.0)
            raw[mid] = m
            if weight > best.get(mid, 0):
                best[mid] = weight
                lead = {"completed": "Because you watched", "watching": "Because you're watching"}.get(
                    seed.get("watch_status"), "Because you want to see")
                reason[mid] = f"{lead} {seed.get('english_title') or seed.get('romaji_title')}"
    ranked = sorted(score, key=lambda k: (-score[k], -(raw[k].get("popularity") or 0)))
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
    out = _hits([raw[k] for k in mixed])
    for h in out:
        h["reason"] = reason.get(h["provider_id"], "")
    return out


def apply(hits, genre_id=None, sort="default", source=""):
    from core.kinema_discover import apply as _apply
    return _apply(hits, genre_id, sort, "upcoming" if source == "next" else source)
