"""
Raikō - themes & music for the detail panel's video card.

Tabs per kind of title (Trailers come from the title's own videos):
  anime   Openings · Endings · Soundtrack
  tv      Intro · Soundtrack
  movie   Soundtrack

Found with a YouTube search (no account or key needed), filtered to what
fits (an opening is a short clip of the right show, not a reaction or a
piano cover), official channels first, cached for a week. Same item shape as
the trailer playlists: {id, site, kind, title, thumb}, so they play in the
in-app player with Up Next.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

TABS = {
    "anime": [("trailers", "Trailers"), ("op", "Openings"), ("ed", "Endings"), ("ost", "Soundtrack")],
    "tv": [("trailers", "Trailers"), ("intro", "Intro"), ("ost", "Soundtrack")],
    "movie": [("trailers", "Trailers"), ("ost", "Soundtrack")],
}
CACHE = Path.home() / ".animetracker" / "cache" / "music.json"
TTL = 7 * 86400
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0 Safari/537.36")
_NOISE = re.compile(r"\b(reacts?|reaction|cover|piano|guitar|violin|drum|tutorial|nightcore|8d audio|"
                    r"amv|edit|fan ?made|parody|tier list|ranking|top \d+|explained|review|breakdown|"
                    r"karaoke|instrumental cover|lofi|lo-fi|slowed|sped up|remix|meme|shorts?)\b", re.I)
_OFFICIAL = re.compile(r"official|viz|crunchyroll|aniplex|toho|netflix|prime video|hbo|max|disney|"
                       r"warner|sony|universal|paramount|hulu|apple tv|funimation|muse asia|ani-one|"
                       r"tv tokyo|mbs|fuji|kadokawa|bandai|records|music|soundtrack|ost", re.I)


def _short(t: str) -> str:
    """Title without season/part suffixes, for searching."""
    t = re.split(r"\s*[:(]\s*|\s+season\s+\d|\s+part\s+\d|\s+\d+(st|nd|rd|th)\s+season", t or "", flags=re.I)[0]
    return t.strip() or (t or "")


def _query(row: Dict, tab: str) -> str:
    media = row.get("media_type") or "anime"
    title = row.get("english_title") or row.get("romaji_title") or ""
    if media == "anime":
        base = row.get("english_title") or row.get("romaji_title") or ""
        return {"op": f"{base} opening", "ed": f"{base} ending",
                "ost": f"{_short(base)} original soundtrack OST"}[tab]
    year = (row.get("cinema_date") or row.get("start_date") or "")[:4] if media == "movie" else ""
    if tab == "intro":
        return f"{title} intro opening credits"
    return f"{title} {year} soundtrack".replace("  ", " ").strip()


def _secs(length: Optional[str]) -> int:
    if not length:
        return 0
    n = 0
    for part in length.split(":"):
        n = n * 60 + int(part or 0)
    return n


def youtube_search(query: str, limit: int = 25) -> List[Dict]:
    """Network: YouTube search results -> [{id, title, channel, secs}]."""
    import requests
    r = requests.get("https://www.youtube.com/results", params={"search_query": query},
                     headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}, timeout=15)
    r.raise_for_status()
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", r.text, re.S)
    if not m:
        return []
    data = json.loads(m.group(1))
    out: List[Dict] = []

    def walk(o):
        if len(out) >= limit:
            return
        if isinstance(o, dict):
            v = o.get("videoRenderer")
            if v and v.get("videoId"):
                out.append({
                    "id": v["videoId"],
                    "title": "".join(x.get("text", "") for x in (v.get("title") or {}).get("runs", [])),
                    "channel": "".join(x.get("text", "") for x in (v.get("ownerText") or {}).get("runs", [])),
                    "secs": _secs((v.get("lengthText") or {}).get("simpleText")),
                })
                return
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(data)
    return out


def _words(t: str) -> List[str]:
    stop = {"the", "a", "an", "of", "no", "to", "and", "season", "part", "movie", "film"}
    return [w for w in re.findall(r"[a-z0-9]+", (t or "").lower()) if len(w) > 2 and w not in stop]


def pick(row: Dict, tab: str, results: List[Dict]) -> List[Dict]:
    """Keep what fits the tab, official channels first."""
    names = [row.get("english_title") or "", row.get("romaji_title") or ""]
    keys = set()
    for n in names:
        keys |= set(_words(_short(n))[:3])
    want = {"op": re.compile(r"\bop(ening)?\b|オープニング|\bop\d", re.I),
            "ed": re.compile(r"\bed(ing)?\b|ending|エンディング|\bed\d", re.I),
            "intro": re.compile(r"intro|opening|title sequence|main title|credits|theme", re.I),
            "ost": re.compile(r"soundtrack|\bost\b|score|original music|music from|theme|suite|bgm", re.I)}[tab]
    other = {"op": re.compile(r"\bending\b|\bed\s?\d", re.I), "ed": re.compile(r"\bopening\b|\bop\s?\d", re.I)}
    out, seen = [], set()
    for v in results:
        t = v["title"]
        low = t.lower()
        if v["id"] in seen or _NOISE.search(low):
            continue
        if keys and not any(k in low for k in keys):
            continue                                   # not this show
        if not want.search(t) or (tab in other and other[tab].search(t) and not want.search(low)):
            continue
        if tab in ("op", "ed", "intro") and not (20 <= v["secs"] <= 7 * 60):
            continue                                   # a theme is a short clip
        if tab == "ost" and v["secs"] and v["secs"] < 60:
            continue
        seen.add(v["id"])
        out.append(v)
    out.sort(key=lambda v: 0 if _OFFICIAL.search(v["channel"] + " " + v["title"]) else 1)
    kind = {"op": "opening", "ed": "ending", "intro": "intro", "ost": "soundtrack"}[tab]
    return [{"id": v["id"], "site": "youtube", "kind": kind,
             "title": v["title"] + (f"  ·  {v['channel']}" if v.get("channel") else ""),
             "thumb": f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg"} for v in out[:16]]


def _load_cache() -> Dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def find(row: Dict, tab: str, refresh: bool = False) -> List[Dict]:
    """Network (cached a week): the videos for one music tab of a title."""
    key = f"{row.get('media_type') or 'anime'}:{row.get('anilist_id') or row.get('tmdb_id') or row.get('id')}:{tab}"
    cache = _load_cache()
    hit = cache.get(key)
    if hit and not refresh and time.time() - hit.get("at", 0) < TTL:
        return hit.get("items") or []
    items = pick(row, tab, youtube_search(_query(row, tab)))
    if len(items) < 5:                                 # thin: try a looser second search
        title = _short(row.get("english_title") or row.get("romaji_title") or "")
        extra = {"op": f"{title} op", "ed": f"{title} ed", "intro": f"{title} theme song",
                 "ost": f"{title} music theme"}[tab]
        have = {i["id"] for i in items}
        items += [i for i in pick(row, tab, youtube_search(extra)) if i["id"] not in have]
    cache[key] = {"at": int(time.time()), "items": items}
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass
    return items
