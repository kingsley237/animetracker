"""
Raikō - anime-world events, from live data (AniList airing schedule + your library).

  premiere   a highly anticipated show (or new season) airs its first episode
             today - big on AniList (>= PREMIERE_POP members) or in your library
  farewell   a beloved series airs its final episode today - very popular
             (>= FAREWELL_POP) or in your library (watching / completed)

The event reflects the show: its key art, its top characters around the banner,
its colour as the accent. Yours come first: a show in your library beats a
more popular one you don't follow. Checked once a day (cached), never blocks
start-up; today's result is applied on the next start straight away.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Dict, List, Optional

PREMIERE_POP = 50_000
FAREWELL_POP = 100_000

_Q = """query ($a: Int, $b: Int, $p: Int) { Page(page: $p, perPage: 50) {
  pageInfo { hasNextPage }
  airingSchedules(airingAt_greater: $a, airingAt_lesser: $b, sort: TIME) {
    episode airingAt
    media { id title { english romaji } popularity episodes status format isAdult season seasonYear
            averageScore coverImage { extraLarge large color } bannerImage trailer { id site }
            characters(sort: [FAVOURITES_DESC], perPage: 6) { nodes { name { full } image { large } } } }
  } } }"""


def _day_bounds(day: Optional[datetime] = None):
    d = day or datetime.now()
    start = datetime(d.year, d.month, d.day).timestamp()
    return int(start), int(start + 86400)


def _schedule(a: int, b: int) -> List[Dict]:
    from core.api import _post
    out: List[Dict] = []
    for page in range(1, 6):
        data = _post(_Q, {"a": a, "b": b, "p": page}, timeout=20)
        if not data:
            break
        pg = data.get("Page") or {}
        out += pg.get("airingSchedules") or []
        if not (pg.get("pageInfo") or {}).get("hasNextPage"):
            break
    return out


def _title(m: Dict) -> str:
    t = m.get("title") or {}
    return t.get("english") or t.get("romaji") or ""


def library_index(db) -> Dict[int, Dict]:
    """Your anime by AniList id (read on the caller's thread)."""
    lib: Dict[int, Dict] = {}
    try:
        for r in db.get_all_anime(media_type="anime"):
            if r.get("anilist_id"):
                lib[int(r["anilist_id"])] = {"id": r["id"], "watch_status": r.get("watch_status")}
    except Exception:
        pass
    return lib


def detect(db, day: Optional[datetime] = None, lib: Optional[Dict[int, Dict]] = None) -> Optional[Dict]:
    """Network: today's anime event (or None). Pass `lib` (library_index) to
    avoid touching the database from a worker thread."""
    a, b = _day_bounds(day)
    if lib is None:
        lib = library_index(db)
    best, best_score = None, -1.0
    for s in _schedule(a, b):
        m = s.get("media") or {}
        if not m or m.get("isAdult") or (m.get("format") or "") not in ("TV", "TV_SHORT", "ONA", "MOVIE"):
            continue
        pop = int(m.get("popularity") or 0)
        mine = lib.get(int(m["id"]))
        ws = (mine or {}).get("watch_status")
        ep, total = int(s.get("episode") or 0), int(m.get("episodes") or 0)
        kind = None
        if ep == 1 and (pop >= PREMIERE_POP or ws in ("planned", "watching")):
            kind = "premiere"
        elif total >= 10 and ep == total and (pop >= FAREWELL_POP or ws in ("watching", "completed")):
            kind = "farewell"
        if not kind:
            continue
        score = pop + (1_000_000 if mine else 0) + (200_000 if kind == "farewell" and total >= 50 else 0)
        if score > best_score:
            best, best_score = (kind, s, m, mine), score
    if best is None:
        return None
    kind, s, m, mine = best
    title = _title(m)
    chars = (m.get("characters") or {}).get("nodes") or []
    color = (m.get("coverImage") or {}).get("color") or "#8b7bff"
    d = datetime.fromtimestamp(s["airingAt"])
    ev = {
        "id": f"{kind}-{m['id']}", "dynamic": True, "kind": kind, "category": "anime",
        "name": title, "anilist_id": m["id"], "lib_id": (mine or {}).get("id"),
        "start": (d.month, d.day), "end": (d.month, d.day), "variants": [],
        "color": color, "banner": m.get("bannerImage") or "",
        "cover": (m.get("coverImage") or {}).get("extraLarge") or (m.get("coverImage") or {}).get("large") or "",
        "portraits": [c["image"]["large"] for c in chars if (c.get("image") or {}).get("large")][:5],
        "characters": [c["name"]["full"] for c in chars if (c.get("name") or {}).get("full")][:5],
        "episode": s.get("episode"), "episodes": m.get("episodes"), "airing_at": s["airingAt"],
        "score": m.get("averageScore"), "trailer": m.get("trailer") or None,
        "date": d.strftime("%Y-%m-%d"),
        "emoji": "🎬" if kind == "premiere" else "🌸", "anim": "🎉" if kind == "premiere" else "✨",
        "romaji": (m.get("title") or {}).get("romaji") or "", "years": [m.get("seasonYear")],
        "lib_status": (mine or {}).get("watch_status"),
    }
    art = tmdb_art(title, (m.get("title") or {}).get("romaji") or "")
    ev["logo"] = art["logo"]
    ev["backdrops"] = art["backdrops"]
    if kind == "premiere":
        ev["greeting"] = "Premiere day"
        ev["line"] = f"{title} starts today" + (f" at {d.strftime('%H:%M')}." if d.hour or d.minute else ".")
        ev["tagline"] = "One of the most anticipated premieres — the wait is over." if not mine else \
            "It's on your list — the wait is over."
    else:
        ev["greeting"] = f"Thank you, {title}"
        ev["line"] = f"{title} airs its final episode today."
        ev["tagline"] = f"{ev['episodes']} episodes. Thank you for the ride."
    prefetch(ev)
    ev["extra"] = {"ambient": {"kind": "stars" if kind == "farewell" else "confetti", "density": 0.35,
                               "colors": [color, "#fff3c4", "#ffffff"]},
                   "ornaments": [{"anchor": "logo", "kind": "sparkles"}], "mascot": "party"}
    return ev


def prefetch(ev: Dict):
    """Warm the image cache (we're already off the UI thread) so the banner,
    logo, ticket and spotlight appear complete, not piece by piece."""
    try:
        from core.image_cache import download_image
        for u in [ev.get("logo"), *(ev.get("backdrops") or [])[:1], ev.get("banner"), ev.get("cover"),
                  *(ev.get("portraits") or [])]:
            if u:
                download_image(u)
    except Exception:
        pass


# ── daily cache (in settings) ─────────────────────────────────────────────────

def cached(today: str) -> Optional[Dict]:
    from core.app_settings import app_settings
    try:
        v = json.loads(str(app_settings().value("anime_event_today", "") or "{}"))
    except ValueError:
        return None
    if v.get("checked") == today:
        return v.get("event") or None
    return None


def store(today: str, ev: Optional[Dict]):
    from core.app_settings import app_settings
    app_settings().setValue("anime_event_today", json.dumps({"checked": today, "event": ev, "at": int(time.time())}))


# ── TMDB art: the show's transparent title logo + many backdrops ──────────────

def tmdb_art(title: str, alt: str = "") -> Dict:
    """{'logo': url, 'backdrops': [urls]} for a show (empty when not found)."""
    import random
    try:
        from core import tmdb
        for q in [t for t in (title, alt) if t]:
            res = (tmdb.get("/search/tv", {"query": q}, ttl=7 * 86400) or {}).get("results") or []
            res = [r for r in res if 16 in (r.get("genre_ids") or [])] or res
            if not res:
                continue
            tid = res[0]["id"]
            im = tmdb.get(f"/tv/{tid}/images", {"include_image_language": "en,null,ja"}, ttl=7 * 86400) or {}
            logos = sorted(im.get("logos") or [], key=lambda l: (l.get("iso_639_1") != "en",
                                                                 l.get("file_path", "").endswith(".svg"),
                                                                 -(l.get("vote_average") or 0)))
            backs = [b for b in (im.get("backdrops") or []) if (b.get("iso_639_1") in (None, "", "xx"))] or \
                (im.get("backdrops") or [])
            backs = sorted(backs, key=lambda b: -(b.get("vote_average") or 0))[:20]
            random.shuffle(backs)                    # a different look each time
            return {"logo": tmdb.image_url(logos[0]["file_path"], "w500") if logos else "",
                    "backdrops": [tmdb.image_url(b["file_path"], "w1280") for b in backs[:6]]}
    except Exception:
        pass
    return {"logo": "", "backdrops": []}


_SIM_Q = """query ($s: String) { Media(search: $s, type: ANIME, isAdult: false) {
    id title { english romaji } popularity episodes status format isAdult season seasonYear averageScore
    coverImage { extraLarge large color } bannerImage trailer { id site }
    characters(sort: [FAVOURITES_DESC], perPage: 6) { nodes { name { full } image { large } } } } }"""


def simulate(kind: str, query: str, db=None, day: Optional[datetime] = None) -> Optional[Dict]:
    """Network: a premiere / farewell event for any show, as if it aired today
    (for previews: main.py --simulate premiere:"One Piece")."""
    from core.api import _post
    data = _post(_SIM_Q, {"s": query}, timeout=20) or {}
    m = data.get("Media")
    if not m:
        return None
    d = day or datetime.now()
    at = int(datetime(d.year, d.month, d.day, 18, 0).timestamp())
    ep = 1 if kind == "premiere" else int(m.get("episodes") or 12)
    lib = library_index(db) if db is not None else {}
    fake = [{"episode": ep, "airingAt": at, "media": {**m, "popularity": max(int(m.get("popularity") or 0),
                                                                             PREMIERE_POP + FAREWELL_POP)}}]
    global _schedule
    real = _schedule
    try:
        _schedule = lambda a, b: fake          # noqa: E731
        ev = detect(None, d, lib)
    finally:
        _schedule = real
    if ev:
        ev["simulated"] = True
    return ev
