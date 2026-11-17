"""
Raikō - Honours: your own awards inside the Hall of Fame.

An award is a category ("Best trilogy", "Best villain", "Best of 2025"…)
with a winner and up to two runners-up. What a category holds depends on its
kind:

  group      several titles that belong together (trilogy, duology, saga):
             found from TMDB collections and AniList sequel chains in your
             library, or assembled by hand
  title      one title (best soundtrack, best animation, best of a year…)
  season     an anime title (each AniList entry is a season) or a TV season
  episode    one episode of a title (best finale, best fight…)
  character  a character / cast member from a title
  theme      a title plus a song name (best opening / ending)
  name       free text with suggestions (best studio / director)
"""
from __future__ import annotations

import json
import re
import time
from typing import Dict, List, Optional

TEMPLATES: List[Dict] = [
    # Groups
    {"key": "trilogy", "label": "Best trilogy", "kind": "group", "size": 3, "family": "Groups"},
    {"key": "duology", "label": "Best duology", "kind": "group", "size": 2, "family": "Groups"},
    {"key": "saga", "label": "Best saga", "kind": "group", "size": 0, "family": "Groups"},
    {"key": "anime_season", "label": "Best anime season", "kind": "season", "media": "anime", "family": "Groups"},
    {"key": "tv_season", "label": "Best TV season", "kind": "season", "media": "tv", "family": "Groups"},
    # Moments
    {"key": "finale", "label": "Best finale", "kind": "episode", "family": "Moments"},
    {"key": "episode", "label": "Best episode", "kind": "episode", "family": "Moments"},
    {"key": "twist", "label": "Best plot twist", "kind": "episode", "family": "Moments"},
    {"key": "fight", "label": "Best fight", "kind": "episode", "family": "Moments"},
    {"key": "opening", "label": "Best opening", "kind": "theme", "media": "anime", "family": "Moments"},
    {"key": "ending", "label": "Best ending", "kind": "theme", "media": "anime", "family": "Moments"},
    # People
    {"key": "villain", "label": "Best villain", "kind": "character", "family": "People"},
    {"key": "protagonist", "label": "Best protagonist", "kind": "character", "family": "People"},
    {"key": "character", "label": "Best character", "kind": "character", "family": "People"},
    {"key": "duo", "label": "Best duo", "kind": "character", "family": "People"},
    {"key": "studio", "label": "Best studio", "kind": "name", "family": "People"},
    # Craft
    {"key": "soundtrack", "label": "Best soundtrack", "kind": "title", "family": "Craft"},
    {"key": "animation", "label": "Best animation", "kind": "title", "media": "anime", "family": "Craft"},
    {"key": "cinematography", "label": "Best cinematography", "kind": "title", "family": "Craft"},
    # Time
    {"key": "year", "label": "Best of {year}", "kind": "title", "family": "Time"},
    {"key": "newcomer", "label": "Best newcomer", "kind": "title", "family": "Time"},
]
TEMPLATE_BY_KEY = {t["key"]: t for t in TEMPLATES}
PLACES = ("Winner", "Runner-up", "Runner-up")


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _base(title: str) -> str:
    """Franchise key from a title: 'Attack on Titan Season 3 Part 2' -> 'attack on titan'."""
    t = _norm(title)
    t = re.split(r"\b(season|part|cour|the movie|movie|film|final|2nd|3rd|\d+th|ii|iii|iv)\b", t)[0]
    t = re.sub(r"\b\d+\b.*$", "", t)
    return t.strip()


class Honours:
    def __init__(self, db):
        self.db = db
        self.conn = db._get_conn()
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS hof_awards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT, label TEXT NOT NULL, kind TEXT NOT NULL,
                size INTEGER DEFAULT 0, media TEXT, position INTEGER, created_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS hof_award_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                award_id INTEGER NOT NULL REFERENCES hof_awards(id) ON DELETE CASCADE,
                place INTEGER NOT NULL,
                kind TEXT, lib_ids TEXT, label TEXT, sub TEXT, image TEXT,
                reason TEXT DEFAULT '', extra TEXT, awarded_at INTEGER,
                UNIQUE(award_id, place)
            );
            CREATE TABLE IF NOT EXISTS hof_meta (key TEXT PRIMARY KEY, value TEXT);
        """)
        self.conn.commit()

    # ── categories ────────────────────────────────────────────────────────────

    def categories(self) -> List[Dict]:
        rows = self.conn.execute("SELECT id, key, label, kind, size, media, position FROM hof_awards "
                                 "ORDER BY position, id").fetchall()
        out = []
        for r in rows:
            a = dict(zip(("id", "key", "label", "kind", "size", "media", "position"), r))
            a["entries"] = self.entries(a["id"])
            out.append(a)
        return out

    def category(self, award_id: int) -> Optional[Dict]:
        return next((a for a in self.categories() if a["id"] == award_id), None)

    def add_category(self, key: Optional[str] = None, label: Optional[str] = None, kind: str = "title",
                     size: int = 0, media: Optional[str] = None) -> int:
        t = TEMPLATE_BY_KEY.get(key or "")
        if t:
            label = label or t["label"].replace("{year}", str(time.localtime().tm_year))
            kind, size, media = t["kind"], t.get("size", 0), t.get("media")
        pos = (self.conn.execute("SELECT COALESCE(MAX(position), 0) FROM hof_awards").fetchone()[0] or 0) + 1
        cur = self.conn.execute("INSERT INTO hof_awards (key, label, kind, size, media, position, created_at) "
                                "VALUES (?,?,?,?,?,?,?)", (key, (label or "My award").strip()[:60], kind, size,
                                                           media, pos, int(time.time())))
        self.conn.commit()
        return cur.lastrowid

    def rename(self, award_id: int, label: str):
        self.conn.execute("UPDATE hof_awards SET label=? WHERE id=?", (label.strip()[:60], award_id))
        self.conn.commit()

    def remove_category(self, award_id: int):
        self.conn.execute("DELETE FROM hof_award_entries WHERE award_id=?", (award_id,))
        self.conn.execute("DELETE FROM hof_awards WHERE id=?", (award_id,))
        self.conn.commit()

    def move_category(self, award_id: int, delta: int):
        ids = [a["id"] for a in self.categories()]
        if award_id not in ids:
            return
        i = ids.index(award_id)
        j = max(0, min(len(ids) - 1, i + delta))
        ids.insert(j, ids.pop(i))
        for pos, aid in enumerate(ids, start=1):
            self.conn.execute("UPDATE hof_awards SET position=? WHERE id=?", (pos, aid))
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(DISTINCT award_id) FROM hof_award_entries WHERE place=0").fetchone()[0]

    # ── entries ───────────────────────────────────────────────────────────────

    def entries(self, award_id: int) -> List[Optional[Dict]]:
        out: List[Optional[Dict]] = [None, None, None]
        for r in self.conn.execute("SELECT place, kind, lib_ids, label, sub, image, reason, extra, awarded_at "
                                   "FROM hof_award_entries WHERE award_id=? ORDER BY place", (award_id,)).fetchall():
            e = dict(zip(("place", "kind", "lib_ids", "label", "sub", "image", "reason", "extra", "awarded_at"), r))
            e["lib_ids"] = json.loads(e["lib_ids"] or "[]")
            e["extra"] = json.loads(e["extra"] or "{}")
            if 0 <= e["place"] < 3:
                out[e["place"]] = e
        return out

    def set_entry(self, award_id: int, place: int, entry: Dict):
        old = self.entries(award_id)[place] if 0 <= place < 3 else None
        self.conn.execute(
            "INSERT INTO hof_award_entries (award_id, place, kind, lib_ids, label, sub, image, reason, extra, awarded_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(award_id, place) DO UPDATE SET kind=excluded.kind, "
            "lib_ids=excluded.lib_ids, label=excluded.label, sub=excluded.sub, image=excluded.image, "
            "reason=excluded.reason, extra=excluded.extra, awarded_at=excluded.awarded_at",
            (award_id, place, entry.get("kind"), json.dumps(entry.get("lib_ids") or []), entry.get("label") or "",
             entry.get("sub") or "", entry.get("image") or "",
             entry.get("reason", (old or {}).get("reason", "")) or "",
             json.dumps(entry.get("extra") or {}), int(time.time())))
        self.conn.commit()

    def set_reason(self, award_id: int, place: int, reason: str):
        self.conn.execute("UPDATE hof_award_entries SET reason=? WHERE award_id=? AND place=?",
                          (reason.strip(), award_id, place))
        self.conn.commit()

    def clear_entry(self, award_id: int, place: int):
        self.conn.execute("DELETE FROM hof_award_entries WHERE award_id=? AND place=?", (award_id, place))
        # keep places contiguous: a lone runner-up moves up
        rest = [e for e in self.entries(award_id) if e]
        self.conn.execute("DELETE FROM hof_award_entries WHERE award_id=?", (award_id,))
        self.conn.commit()
        for i, e in enumerate(rest):
            self.set_entry(award_id, i, e)

    def swap(self, award_id: int, a: int, b: int):
        es = self.entries(award_id)
        ea, eb = es[a], es[b]
        self.conn.execute("DELETE FROM hof_award_entries WHERE award_id=? AND place IN (?,?)", (award_id, a, b))
        self.conn.commit()
        if eb:
            self.set_entry(award_id, a, eb)
        if ea:
            self.set_entry(award_id, b, ea)

    # ── building entries from the library ─────────────────────────────────────

    def _title(self, row: Dict) -> str:
        return row.get("english_title") or row.get("romaji_title") or "Untitled"

    def title_entry(self, lib_id: int) -> Dict:
        row = self.db.get_anime_by_id(lib_id) or {}
        y = row.get("season_year") or (row.get("start_date") or "")[:4]
        media = row.get("media_type") or "anime"
        return {"kind": "title", "lib_ids": [lib_id], "label": self._title(row),
                "sub": " · ".join(b for b in ({"anime": "Anime", "movie": "Movie", "tv": "TV"}[media],
                                               str(y) if y else "") if b),
                "image": row.get("cover_url") or ""}

    def season_entry(self, lib_id: int, season: Optional[int] = None) -> Dict:
        row = self.db.get_anime_by_id(lib_id) or {}
        if season is None:
            e = self.title_entry(lib_id)
            e["kind"] = "season"
            return e
        s = next((x for x in self.db.get_tv_seasons(lib_id) if x["season_number"] == season), {})
        return {"kind": "season", "lib_ids": [lib_id], "label": f"{self._title(row)} — "
                + (s.get("name") or f"Season {season}"), "sub": (s.get("air_date") or "")[:4],
                "image": s.get("poster_url") or row.get("cover_url") or "", "extra": {"season": season}}

    def episode_entry(self, lib_id: int, episode: int, season: Optional[int] = None) -> Dict:
        row = self.db.get_anime_by_id(lib_id) or {}
        name, image = "", row.get("banner_url") or row.get("cover_url") or ""
        if season is not None:
            ep = next((e for e in self.db.get_tv_episodes(lib_id, season) if e["episode_number"] == episode), {})
            name = ep.get("name") or ""
            image = ep.get("still_url") or image
            code = f"S{season:02d}E{episode:02d}"
        else:
            code = f"Episode {episode}"
        label = f"{code} · “{name}”" if name and not name.lower().startswith("episode ") else code
        return {"kind": "episode", "lib_ids": [lib_id], "label": label, "sub": self._title(row), "image": image,
                "extra": {"episode": episode, "season": season}}

    def character_entry(self, lib_id: int, ch: Dict) -> Dict:
        row = self.db.get_anime_by_id(lib_id) or {}
        media = row.get("media_type") or "anime"
        if media == "anime":
            label, sub = ch.get("name") or "", self._title(row)
        else:   # TMDB cast: the character is the role, played by the actor
            label = ch.get("role") or ch.get("name") or ""
            sub = f"{ch.get('name')} · {self._title(row)}" if ch.get("role") else self._title(row)
        return {"kind": "character", "lib_ids": [lib_id], "label": label, "sub": sub,
                "image": ch.get("image") or row.get("cover_url") or "", "extra": {"character": ch}}

    def theme_entry(self, lib_id: int, song: str) -> Dict:
        row = self.db.get_anime_by_id(lib_id) or {}
        return {"kind": "theme", "lib_ids": [lib_id], "label": song.strip() or self._title(row),
                "sub": self._title(row), "image": row.get("cover_url") or ""}

    def name_entry(self, name: str) -> Dict:
        return {"kind": "name", "lib_ids": [], "label": name.strip(), "sub": "", "image": ""}

    def group_entry(self, group: Dict) -> Dict:
        parts = group["parts"]
        ids = [p["lib_id"] for p in parts if p.get("lib_id")]
        seen = sum(1 for p in parts if p.get("watched"))
        return {"kind": "group", "lib_ids": ids, "label": group["name"],
                "sub": f"{len(parts)} parts" + (f" · {seen} watched" if seen < len(parts) else ""),
                "image": next((p.get("poster") for p in parts if p.get("poster")), ""),
                "extra": {"media": group.get("media"),
                          "parts": [{k: p.get(k) for k in ("lib_id", "title", "year", "poster", "watched",
                                                           "tmdb_id", "anilist_id")} for p in parts]}}

    def studios(self) -> List[str]:
        names = {}
        for media in ("anime", "movie", "tv"):
            for r in self.db.get_all_anime(media_type=media):
                for s in (r.get("studios") or [])[:2]:
                    names[s] = names.get(s, 0) + 1
        return [k for k, _v in sorted(names.items(), key=lambda kv: -kv[1])]

    # ── groups: trilogies, duologies, sagas ───────────────────────────────────

    def _meta(self, key):
        r = self.conn.execute("SELECT value FROM hof_meta WHERE key=?", (key,)).fetchone()
        try:
            return json.loads(r[0]) if r else None
        except ValueError:
            return None

    def _set_meta(self, key, value):
        self.conn.execute("INSERT INTO hof_meta (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET "
                          "value=excluded.value", (key, json.dumps(value)))
        self.conn.commit()

    def _part(self, row: Dict) -> Dict:
        y = row.get("season_year") or (row.get("start_date") or row.get("cinema_date") or "")[:4]
        return {"lib_id": row["id"], "title": self._title(row), "year": str(y or ""),
                "poster": row.get("cover_url") or "", "watched": row.get("watch_status") == "completed",
                "sort": (row.get("start_ts") or 0, str(y or "")),
                "tmdb_id": row.get("tmdb_id"), "anilist_id": row.get("anilist_id")}

    def groups(self, size: int = 0) -> List[Dict]:
        """Groups found from what's already known (no network). size 0 = any (2+)."""
        out: List[Dict] = []
        out += self._anime_groups()
        out += self._movie_groups()
        if size:
            out = [g for g in out if len(g["parts"]) == size]
        out.sort(key=lambda g: (-sum(1 for p in g["parts"] if p.get("watched")), g["name"].lower()))
        return out

    def _anime_groups(self) -> List[Dict]:
        rows = [r for r in self.db.get_all_anime(media_type="anime") if r.get("watch_status") != "planned"]
        by_al = {r["anilist_id"]: r for r in rows if r.get("anilist_id")}
        rel = self._meta("anime_sequels") or {}
        # union-find over SEQUEL links inside your library
        parent = {r["id"]: r["id"] for r in rows}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            parent[find(a)] = find(b)

        linked = False
        for al, seqs in rel.items():
            a = by_al.get(int(al))
            for s in seqs:
                b = by_al.get(int(s))
                if a and b:
                    union(a["id"], b["id"])
                    linked = True
        # offline fallback (and for titles AniList didn't link): same franchise name
        base: Dict[str, int] = {}
        for r in rows:
            k = _base(r.get("romaji_title") or "") or _base(self._title(r))
            if len(k) >= 4:
                if k in base:
                    union(r["id"], base[k])
                else:
                    base[k] = r["id"]
        comps: Dict[int, List[Dict]] = {}
        for r in rows:
            comps.setdefault(find(r["id"]), []).append(r)
        out = []
        for members in comps.values():
            if len(members) < 2:
                continue
            parts = sorted((self._part(m) for m in members), key=lambda p: p["sort"])
            first = min(members, key=lambda m: (m.get("start_ts") or 0, len(self._title(m))))
            name = self._title(first)
            name = re.split(r":| Season| Part| 2nd| \d", name)[0].strip() or name
            out.append({"key": f"anime:{min(m['id'] for m in members)}", "name": name, "media": "anime",
                        "parts": parts, "source": "AniList" if linked else "titles"})
        return out

    def _movie_groups(self) -> List[Dict]:
        cols = self._meta("movie_collections") or {}
        by_tmdb = {r.get("tmdb_id"): r for r in self.db.get_all_anime(media_type="movie") if r.get("tmdb_id")}
        out = []
        for cid, c in cols.items():
            parts = []
            for p in c.get("parts") or []:
                row = by_tmdb.get(p.get("id"))
                if row:
                    part = self._part(row)
                else:
                    part = {"lib_id": None, "title": p.get("title") or "", "year": (p.get("release_date") or "")[:4],
                            "poster": p.get("poster") or "", "watched": False}
                part["tmdb_id"] = p.get("id")
                part["sort"] = (p.get("release_date") or "9999",)
                parts.append(part)
            parts = [p for p in parts if p["year"] or p["lib_id"]]      # drop unannounced placeholders
            if len(parts) < 2 or sum(1 for p in parts if p["lib_id"]) < 1:
                continue
            parts.sort(key=lambda p: p["sort"])
            out.append({"key": f"movie:{cid}", "name": c.get("name") or "Collection", "media": "movie",
                        "parts": parts, "source": "TMDB"})
        return out

    def search_groups(self, query: str) -> List[Dict]:
        """Network: series and collections matching `query`, whether or not
        they're in your library - TMDB collections (films) and AniList
        sequel chains (anime)."""
        q = (query or "").strip()
        out: List[Dict] = []
        if not q:
            return out
        try:
            from core import tmdb
            res = (tmdb.get("/search/collection", {"query": q}, ttl=3600) or {}).get("results") or []
            by_tmdb = {r.get("tmdb_id"): r for r in self.db.get_all_anime(media_type="movie") if r.get("tmdb_id")}
            for c in res[:6]:
                full = tmdb.collection(c["id"]) or {}
                parts = []
                for p in sorted(full.get("parts") or [], key=lambda p: p.get("release_date") or "9999"):
                    if not p.get("release_date"):
                        continue                      # not even dated yet
                    row = by_tmdb.get(p.get("id"))
                    part = self._part(row) if row else {
                        "lib_id": None, "title": p.get("title") or "", "year": (p.get("release_date") or "")[:4],
                        "poster": tmdb.image_url(p.get("poster_path"), "w342") if p.get("poster_path") else "",
                        "watched": False}
                    part["tmdb_id"] = p.get("id")
                    parts.append(part)
                if len(parts) >= 2:
                    out.append({"key": f"movie:{c['id']}", "name": full.get("name") or c.get("name") or "",
                                "media": "movie", "parts": parts, "source": "TMDB"})
        except Exception:
            pass
        try:
            from core.api import get_sequels, search_anime
            seen = set()
            for m in (search_anime(q, per_page=6) or [])[:3]:
                if m.get("id") in seen or (m.get("format") or "TV") not in ("TV", "TV_SHORT", "ONA", "MOVIE"):
                    continue
                chain = [m]
                seen.add(m["id"])
                for _ in range(8):
                    nxt = (get_sequels([chain[-1]["id"]]).get(chain[-1]["id"]) or [])
                    nxt = [n for n in nxt if n.get("id") not in seen]
                    if not nxt:
                        break
                    chain.append(nxt[0])
                    seen.add(nxt[0]["id"])
                if len(chain) < 2:
                    continue
                parts = []
                for n in chain:
                    row = self.db.get_anime_by_anilist_id(n["id"])
                    if row:
                        part = self._part(row)
                    else:
                        t = n.get("title") or {}
                        part = {"lib_id": None, "title": t.get("english") or t.get("romaji") or "",
                                "year": str(n.get("seasonYear") or (n.get("startDate") or {}).get("year") or ""),
                                "poster": (n.get("coverImage") or {}).get("large") or "", "watched": False}
                    part["anilist_id"] = n["id"]
                    parts.append(part)
                name = parts[0]["title"]
                name = re.split(r":| Season| Part| 2nd| \d", name)[0].strip() or name
                out.append({"key": f"anime:al{chain[0]['id']}", "name": name, "media": "anime", "parts": parts,
                            "source": "AniList"})
        except Exception:
            pass
        return out

    def refresh_groups(self, max_age_days: int = 7) -> bool:
        """Network: learn sequel links (AniList) and collections (TMDB) for the
        library. Cached; returns True when something was fetched."""
        stamp = self._meta("groups_fetched_at") or 0
        if time.time() - stamp < max_age_days * 86400:
            return False
        fetched = False
        try:
            from core import api
            ids = [r["anilist_id"] for r in self.db.get_all_anime(media_type="anime") if r.get("anilist_id")]
            if ids:
                res = api.get_sequels(ids)
                if res:
                    self._set_meta("anime_sequels", {str(k): [s.get("id") for s in v] for k, v in res.items()})
                    fetched = True
        except Exception:
            pass
        try:
            from core import tmdb
            cols: Dict[str, Dict] = self._meta("movie_collections") or {}
            for r in self.db.get_all_anime(media_type="movie"):
                if not r.get("tmdb_id"):
                    continue
                d = tmdb.movie_details(r["tmdb_id"]) or {}
                c = d.get("belongs_to_collection") or {}
                if not c.get("id") or str(c["id"]) in cols:
                    continue
                full = tmdb.collection(c["id"]) or {}
                parts = [{"id": p.get("id"), "title": p.get("title"), "release_date": p.get("release_date"),
                          "poster": tmdb.image_url(p.get("poster_path"), "w342") if p.get("poster_path") else ""}
                         for p in (full.get("parts") or [])]
                cols[str(c["id"])] = {"name": c.get("name"), "parts": parts}
                fetched = True
            self._set_meta("movie_collections", cols)
        except Exception:
            pass
        if fetched:
            self._set_meta("groups_fetched_at", int(time.time()))
        return fetched
