"""
Raikō - local catalogue of popular titles, for search that understands
partial words ("vin" → Vinland Saga, "frie" → Frieren, "sev" → Severance).

AniList's search only matches nearly complete words, and TMDB's ranks
partial matches poorly. So we keep a small local catalogue of the most
popular anime (AniList), movies and TV shows (TMDB) - a few thousand titles,
saved under ~/.animetracker/catalog and refreshed weekly in the background -
and rank everything ourselves:

    title starts with what you typed  >  a word starts with it  >  contains it
    ties broken by popularity

Entries are stored in the same "hit" shape the Discover browser uses.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

DIR = Path.home() / ".animetracker" / "catalog"
MAX_AGE = 7 * 86400
_lock = threading.Lock()
_mem: Dict[str, List[Dict]] = {}


# ── matching ──────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_tier(names: List[str], query: str, normed: bool = False) -> int:
    """3 = a title starts with the query, 2 = every query word starts a word of
    a title, 1 = a title contains the query (4+ letters only, to avoid noise
    like "vin" in "Moving"), 0 = no match."""
    q = _norm(query)
    if not q:
        return 0
    qwords = q.split()
    best = 0
    for n in names:
        t = n if normed else _norm(n)
        if not t:
            continue
        if t.startswith(q):
            return 3
        words = t.split()
        if all(any(w.startswith(qw) for w in words) for qw in qwords):
            best = max(best, 2)
        elif len(q) >= 4 and (q in t or q.replace(" ", "") in t.replace(" ", "")):
            best = max(best, 1)
    return best


def names_of(hit: Dict) -> List[str]:
    """The title names (English / romaji / original)."""
    raw = hit.get("raw") or {}
    t = raw.get("title") if isinstance(raw.get("title"), dict) else {}
    out = [hit.get("title") or "", hit.get("original_title") or "",
           (t or {}).get("english") or "", (t or {}).get("romaji") or "",
           raw.get("name") or "", raw.get("original_name") or "", raw.get("original_title") or ""]
    return [n for n in out if n]


def synonyms_of(hit: Dict) -> List[str]:
    return [s for s in ((hit.get("raw") or {}).get("synonyms") or []) if s and len(s) < 80]


def tier_of(hit_names: List[str], syns: List[str], query: str, normed: bool = False) -> int:
    """Alternative titles count one step lower than real titles, so "jjk"
    still finds Jujutsu Kaisen but obscure synonyms don't crowd results."""
    return max(match_tier(hit_names, query, normed), max(0, match_tier(syns, query, normed) - 1))


def rank(hits: List[Dict], query: str, keep_unmatched: bool = True) -> List[Dict]:
    """Best matches first; ties by popularity. Online results that don't match
    the text at all (e.g. matched on a synonym we don't see) go last."""
    scored = []
    for i, h in enumerate(hits):
        tier = tier_of(names_of(h), synonyms_of(h), query)
        if tier == 0 and not keep_unmatched:
            continue
        pop = float(h.get("popularity") or 0)
        scored.append((-tier, -math.log10(pop + 1), i, h))
    scored.sort(key=lambda x: x[:3])
    return [h for *_k, h in scored]


def merge(*lists: List[Dict]) -> List[Dict]:
    seen, out = set(), []
    for lst in lists:
        for h in lst or []:
            k = (h.get("media_type"), h.get("provider_id"))
            if k in seen:
                continue
            seen.add(k)
            out.append(h)
    return out


# ── storage ───────────────────────────────────────────────────────────────────

def _path(kind: str) -> Path:
    return DIR / f"{kind}.json"


def load(kind: str) -> List[Dict]:
    with _lock:
        if kind in _mem:
            return _mem[kind]
    try:
        data = json.loads(_path(kind).read_text(encoding="utf-8"))
        hits = data.get("hits") or []
    except (OSError, ValueError):
        hits = []
    with _lock:
        _mem[kind] = hits
    return hits


def age(kind: str) -> Optional[float]:
    try:
        return time.time() - json.loads(_path(kind).read_text(encoding="utf-8")).get("at", 0)
    except (OSError, ValueError):
        return None


def _save(kind: str, hits: List[Dict]):
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(kind).with_suffix(".tmp")
    tmp.write_text(json.dumps({"at": time.time(), "hits": hits}), encoding="utf-8")
    tmp.replace(_path(kind))
    with _lock:
        _mem[kind] = hits


_index: Dict[str, List] = {}


def _indexed(kind: str) -> List:
    """(hit, normalised names, log popularity) - prepared once per catalogue."""
    hits = load(kind)
    cached = _index.get(kind)
    if cached is not None and cached[0] is hits:
        return cached[1]
    rows = [(h, [n for n in (_norm(x) for x in names_of(h)) if n],
             [n for n in (_norm(x) for x in synonyms_of(h)) if n],
             math.log10(float(h.get("popularity") or 0) + 1)) for h in hits]
    _index[kind] = (hits, rows)
    return rows


def search(kind: str, query: str, limit: int = 30) -> List[Dict]:
    """Instant, offline matches from the catalogue."""
    if len(_norm(query)) < 2:
        return []
    direct, via_alias = [], []
    for i, (h, names, syns, pop) in enumerate(_indexed(kind)):
        tier = match_tier(names, query, normed=True)
        if tier:
            direct.append((-tier, -pop, i, h))
        else:
            t2 = match_tier(syns, query, normed=True)
            if t2:
                via_alias.append((-t2, -pop, i, h))
    # alternative titles (abbreviations, other languages) only when nothing
    # matches a real title: "jjk" -> Jujutsu Kaisen, but "vin" stays Vinland Saga
    scored = sorted(direct or via_alias, key=lambda x: x[:3])
    return [h for *_k, h in scored[:limit]]


# ── refresh (background, weekly) ──────────────────────────────────────────────

_ANIME_Q = """query ($page: Int) { Page(page: $page, perPage: 50) {
  media(type: ANIME, isAdult: false, sort: [POPULARITY_DESC], format_in: [TV, TV_SHORT, ONA, MOVIE, OVA]) {
    id title { romaji english } synonyms coverImage { large } bannerImage status format
    seasonYear startDate { year month day } averageScore popularity genres description(asHtml: false)
  } } }"""


def refresh_anime(pages: int = 40, delay: float = 3.0) -> int:
    from core.api import _post
    from core.miroku_discover import _hits
    media: List[Dict] = []
    for p in range(1, pages + 1):
        page = []
        for attempt in range(3):               # AniList throttles bursts: wait and retry
            data = _post(_ANIME_Q, {"page": p}, timeout=20)
            page = ((data or {}).get("Page") or {}).get("media") or []
            if page:
                break
            time.sleep(20)
        if not page:
            if p == 1:
                return 0                       # AniList unreachable: keep the old catalogue
            break
        media += page
        time.sleep(delay)                      # gentle on AniList's rate limit
    hits = _hits(media)
    for h, m in zip(hits, media):
        h["raw"] = {"title": m.get("title"), "synonyms": m.get("synonyms") or [],
                    "bannerImage": m.get("bannerImage"), "coverImage": m.get("coverImage"),
                    "id": m.get("id"), "status": m.get("status")}
    _save("anime", hits)
    return len(hits)


def refresh_tmdb(kind: str, pages: int = 40) -> int:
    from core import tmdb
    from core.kinema_discover import _hits, _TV_NOISE
    if not tmdb.has_credentials():
        return 0
    params = {"sort_by": "popularity.desc", "include_adult": "false", "vote_count.gte": 40}
    if kind == "tv":
        params["without_genres"] = _TV_NOISE
    res = tmdb.get_many([(f"/discover/{kind}", {**params, "page": p}) for p in range(1, pages + 1)])
    rows = []
    for page in res:
        rows += (page or {}).get("results") or []
    if not rows:
        return 0
    hits = _hits(rows, kind)
    for h in hits:
        r = h.get("raw") or {}
        h["raw"] = {k: r.get(k) for k in ("id", "title", "name", "original_title", "original_name",
                                          "backdrop_path", "poster_path", "release_date", "first_air_date")}
    _save(kind, hits)
    return len(hits)


def refresh_stale():
    """Refresh any catalogue older than a week (or missing). Run in a worker."""
    done = {}
    for kind, fn in (("movie", lambda: refresh_tmdb("movie")), ("tv", lambda: refresh_tmdb("tv")),
                     ("anime", refresh_anime)):
        a = age(kind)
        if a is None or a > MAX_AGE:
            try:
                done[kind] = fn()
            except Exception:
                done[kind] = 0
    return done
