"""
Raikō - Hall of Fame (data + ranking engine).

Three wings, each its own honest ranking: anime (Miroku), movies and TV
(Kinema). A cross-wing Pantheon of four pinned favourites. Tiers are an
independent label (S/A/B/C… renameable), shown as a tier list. Every rank
change is remembered. Honours (awards like best trilogy) live in
core.honours.

Ranking uses binary insertion ("which do you love more?"): the new title is
compared with the middle of the remaining range, so placing it among n
entries takes about log2(n) questions. Skip, "too close to call" (tie) and
undo are supported.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from typing import Dict, List, Optional

WINGS = ("anime", "movie", "tv")
WING_NAMES = {"anime": "Miroku", "movie": "Movies", "tv": "TV shows"}
DEFAULT_TIERS = [
    {"key": "S", "label": "S", "color": "#f472b6"},
    {"key": "A", "label": "A", "color": "#8b7bff"},
    {"key": "B", "label": "B", "color": "#38bdf8"},
    {"key": "C", "label": "C", "color": "#34d399"},
]


class Hall:
    def __init__(self, db):
        self.db = db
        self.conn = db._get_conn()
        self._ensure()

    # ── schema & migration ────────────────────────────────────────────────────

    def _ensure(self):
        c = self.conn
        c.executescript("""
            CREATE TABLE IF NOT EXISTS hof_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lib_id INTEGER NOT NULL UNIQUE,
                wing TEXT NOT NULL,
                rank INTEGER NOT NULL,
                tier TEXT,
                inducted_at INTEGER,
                note TEXT DEFAULT '',
                moment TEXT DEFAULT '',
                character TEXT DEFAULT '',
                pinned INTEGER
            );
            CREATE TABLE IF NOT EXISTS hof_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lib_id INTEGER NOT NULL,
                wing TEXT NOT NULL,
                from_rank INTEGER,
                to_rank INTEGER,
                at INTEGER
            );
            CREATE TABLE IF NOT EXISTS hof_meta (key TEXT PRIMARY KEY, value TEXT);
        """)
        c.commit()
        if self._meta("migrated_v1") is None:
            self._migrate_old()
            self._set_meta("migrated_v1", "1")

    def _migrate_old(self):
        """Bring back the rankings from the old (v2) Hall of Fame - kept in
        the library file when that screen was retired."""
        c = self.conn
        has_old = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hall_of_fame'").fetchone()
        if not has_old:
            return
        cols = {r[1] for r in c.execute("PRAGMA table_info(hall_of_fame)").fetchall()}
        rows = c.execute(
            "SELECT h.rank, h.anime_id, " + ("h.note" if "note" in cols else "''") + ", "
            + ("h.added_at" if "added_at" in cols else "NULL") + ", "
            + ("h.tier" if "tier" in cols else "NULL")
            + " FROM hall_of_fame h JOIN anime a ON a.id = h.anime_id ORDER BY h.rank").fetchall()
        rank_by_wing: Dict[str, int] = {}
        for _r, lib_id, note, added, tier in rows:
            if c.execute("SELECT 1 FROM hof_entries WHERE lib_id=?", (lib_id,)).fetchone():
                continue
            row = self.db.get_anime_by_id(lib_id) or {}
            wing = row.get("media_type") or "anime"
            rank_by_wing[wing] = rank_by_wing.get(wing, 0) + 1
            c.execute("INSERT INTO hof_entries (lib_id, wing, rank, tier, inducted_at, note) VALUES (?,?,?,?,?,?)",
                      (lib_id, wing, rank_by_wing[wing], tier or None, added or int(time.time()), note or ""))
        c.commit()

    def _meta(self, key: str) -> Optional[str]:
        r = self.conn.execute("SELECT value FROM hof_meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else None

    def _set_meta(self, key: str, value: str):
        self.conn.execute("INSERT INTO hof_meta (key, value) VALUES (?,?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()

    # ── reading ───────────────────────────────────────────────────────────────

    def _row(self, r) -> Dict:
        keys = ("id", "lib_id", "wing", "rank", "tier", "inducted_at", "note", "moment", "character", "pinned")
        e = dict(zip(keys, r))
        e["row"] = self.db.get_anime_by_id(e["lib_id"]) or {}
        e["title"] = e["row"].get("english_title") or e["row"].get("romaji_title") or "Untitled"
        return e

    _COLS = "id, lib_id, wing, rank, tier, inducted_at, note, moment, character, pinned"

    def entries(self, wing: str) -> List[Dict]:
        rows = self.conn.execute(f"SELECT {self._COLS} FROM hof_entries WHERE wing=? ORDER BY rank",
                                 (wing,)).fetchall()
        return [e for e in (self._row(r) for r in rows) if e["row"]]

    def entry(self, lib_id: int) -> Optional[Dict]:
        r = self.conn.execute(f"SELECT {self._COLS} FROM hof_entries WHERE lib_id=?", (lib_id,)).fetchone()
        return self._row(r) if r else None

    def count(self, wing: Optional[str] = None) -> int:
        if wing:
            return self.conn.execute("SELECT COUNT(*) FROM hof_entries WHERE wing=?", (wing,)).fetchone()[0]
        return self.conn.execute("SELECT COUNT(*) FROM hof_entries").fetchone()[0]

    @staticmethod
    def wing_of(row: Dict) -> str:
        return row.get("media_type") or "anime"

    def eligible(self, row: Dict) -> bool:
        """Finished titles only: anime/TV Completed (TV also with a fully
        watched season), movies Watched."""
        if not row or row.get("id", 0) <= 0:
            return False
        if row.get("watch_status") == "completed":
            return True
        if self.wing_of(row) == "tv" and row.get("watch_status") in ("watching", "dropped"):
            today = time.strftime("%Y-%m-%d")
            for s in self.db.get_tv_seasons(row["id"]):
                eps = [e for e in self.db.get_tv_episodes(row["id"], s["season_number"])
                       if e.get("air_date") and e["air_date"] <= today]
                if eps and all(e.get("watched") for e in eps):
                    return True
        return False

    def candidates(self, wing: str) -> List[Dict]:
        have = {r[0] for r in self.conn.execute("SELECT lib_id FROM hof_entries").fetchall()}
        rows = self.db.get_all_anime(media_type=wing, sort_by="title")
        return [r for r in rows if r["id"] not in have and self.eligible(r)]

    # ── changing ──────────────────────────────────────────────────────────────

    def _log(self, lib_id: int, wing: str, frm: Optional[int], to: Optional[int]):
        self.conn.execute("INSERT INTO hof_history (lib_id, wing, from_rank, to_rank, at) VALUES (?,?,?,?,?)",
                          (lib_id, wing, frm, to, int(time.time())))

    def insert_at(self, lib_id: int, position: int, tier: Optional[str] = None) -> int:
        """Put a title into its wing at `position` (1 = top); others shift down."""
        row = self.db.get_anime_by_id(lib_id) or {}
        wing = self.wing_of(row)
        n = self.count(wing)
        pos = max(1, min(int(position), n + 1))
        c = self.conn
        if c.execute("SELECT 1 FROM hof_entries WHERE lib_id=?", (lib_id,)).fetchone():
            return self.move(lib_id, pos)
        c.execute("UPDATE hof_entries SET rank=rank+1 WHERE wing=? AND rank>=?", (wing, pos))
        c.execute("INSERT INTO hof_entries (lib_id, wing, rank, tier, inducted_at) VALUES (?,?,?,?,?)",
                  (lib_id, wing, pos, tier, int(time.time())))
        self._log(lib_id, wing, None, pos)
        c.commit()
        return pos

    def move(self, lib_id: int, new_rank: int) -> int:
        e = self.entry(lib_id)
        if not e:
            return 0
        wing, old = e["wing"], e["rank"]
        n = self.count(wing)
        new = max(1, min(int(new_rank), n))
        if new == old:
            return old
        c = self.conn
        if new < old:
            c.execute("UPDATE hof_entries SET rank=rank+1 WHERE wing=? AND rank>=? AND rank<?", (wing, new, old))
        else:
            c.execute("UPDATE hof_entries SET rank=rank-1 WHERE wing=? AND rank>? AND rank<=?", (wing, old, new))
        c.execute("UPDATE hof_entries SET rank=? WHERE lib_id=?", (new, lib_id))
        self._log(lib_id, wing, old, new)
        c.commit()
        return new

    def offer_declined(self, lib_id: int) -> bool:
        try:
            return lib_id in json.loads(self._meta("declined") or "[]")
        except ValueError:
            return False

    def decline_offer(self, lib_id: int):
        try:
            d = json.loads(self._meta("declined") or "[]")
        except ValueError:
            d = []
        if lib_id not in d:
            d.append(lib_id)
        self._set_meta("declined", json.dumps(d))

    def remove(self, lib_id: int):
        e = self.entry(lib_id)
        if not e:
            return
        c = self.conn
        c.execute("DELETE FROM hof_entries WHERE lib_id=?", (lib_id,))
        c.execute("UPDATE hof_entries SET rank=rank-1 WHERE wing=? AND rank>?", (e["wing"], e["rank"]))
        self._log(lib_id, e["wing"], e["rank"], None)
        c.commit()

    def set_fields(self, lib_id: int, **fields):
        allowed = {k: v for k, v in fields.items() if k in ("tier", "note", "moment", "character")}
        if not allowed:
            return
        sets = ", ".join(f"{k}=?" for k in allowed)
        self.conn.execute(f"UPDATE hof_entries SET {sets} WHERE lib_id=?", (*allowed.values(), lib_id))
        self.conn.commit()

    # ── Pantheon (4 pins across wings) ────────────────────────────────────────

    def pantheon(self) -> List[Optional[Dict]]:
        slots: List[Optional[Dict]] = [None] * 4
        for r in self.conn.execute(f"SELECT {self._COLS} FROM hof_entries WHERE pinned BETWEEN 1 AND 4").fetchall():
            e = self._row(r)
            if e["row"]:
                slots[e["pinned"] - 1] = e
        return slots

    def pin(self, lib_id: int, slot: int):
        slot = max(1, min(4, int(slot)))
        c = self.conn
        c.execute("UPDATE hof_entries SET pinned=NULL WHERE pinned=?", (slot,))
        c.execute("UPDATE hof_entries SET pinned=? WHERE lib_id=?", (slot, lib_id))
        c.commit()

    def unpin(self, lib_id: int):
        self.conn.execute("UPDATE hof_entries SET pinned=NULL WHERE lib_id=?", (lib_id,))
        self.conn.commit()

    def auto_pantheon(self):
        """First time: fill empty Pantheon slots with the #1s of each wing."""
        if any(self.pantheon()):
            return
        slot = 1
        for wing in WINGS:
            top = self.entries(wing)[:1]
            if top and slot <= 4:
                self.pin(top[0]["lib_id"], slot)
                slot += 1

    # ── tiers ─────────────────────────────────────────────────────────────────

    def tiers(self) -> List[Dict]:
        try:
            t = json.loads(self._meta("tiers") or "null")
        except ValueError:
            t = None
        return t or [dict(x) for x in DEFAULT_TIERS]

    def set_tiers(self, tiers: List[Dict]):
        self._set_meta("tiers", json.dumps(tiers))

    # ── history, timeline, numbers ────────────────────────────────────────────

    def movement(self, lib_id: int, days: int = 120) -> int:
        """Net rank change in the last `days` (positive = moved up)."""
        cutoff = int(time.time()) - days * 86400
        rows = self.conn.execute("SELECT from_rank, to_rank FROM hof_history WHERE lib_id=? AND at>=? "
                                 "ORDER BY at", (lib_id, cutoff)).fetchall()
        rows = [r for r in rows if r[0] is not None and r[1] is not None]
        if not rows:
            return 0
        return rows[0][0] - rows[-1][1]

    def timeline(self) -> List[Dict]:
        out = []
        for wing in WINGS:
            out += self.entries(wing)
        out.sort(key=lambda e: e["inducted_at"] or 0, reverse=True)
        return out

    def numbers(self, wing: str) -> Dict:
        es = self.entries(wing)
        genres, studios, decades = Counter(), Counter(), Counter()
        minutes = 0
        for e in es:
            r = e["row"]
            for g in r.get("genres") or []:
                genres[g] += 1
            for s in (r.get("studios") or [])[:1]:
                studios[s] += 1
            y = r.get("season_year")
            if y:
                decades[f"{int(y) // 10 * 10}s"] += 1
            minutes += int(self.story(e["lib_id"]).get("minutes") or 0)
        return {"count": len(es), "genres": genres.most_common(5), "studios": studios.most_common(3),
                "decades": sorted(decades.items()), "hours": round(minutes / 60)}

    def story(self, lib_id: int) -> Dict:
        """What the plaque says from your real history."""
        row = self.db.get_anime_by_id(lib_id) or {}
        wing = self.wing_of(row)
        out: Dict = {"rating": self.db.get_overall_rating(lib_id),
                     "community": row.get("average_score"),
                     "rewatches": self.db.rewatch_count(lib_id) if hasattr(self.db, "rewatch_count") else 0,
                     "finished": row.get("completed_at"), "added": row.get("date_added")}
        if wing == "anime":
            eps = [e for e in self.db.get_episodes(lib_id) if e.get("watched")]
            stamps = [e["watched_at"] for e in eps if e.get("watched_at")]
            out["first"] = min(stamps) if stamps else None
            out["minutes"] = len(eps) * int(row.get("duration") or 24)
            rated = [r for r in self.db.get_ratings(lib_id) if r["episode_num"] > 0 and (r.get("score") or 0) > 0]
            if rated:
                best = max(rated, key=lambda r: (r["score"], -r["episode_num"]))
                out["best"] = f"Episode {best['episode_num']} · {int(best['score'])}/6"
        elif wing == "tv":
            eps = [e for e in self.db.get_tv_episodes(lib_id) if e.get("watched")]
            stamps = [e["watched_at"] for e in eps if e.get("watched_at")]
            out["first"] = min(stamps) if stamps else None
            out["minutes"] = sum(int(e.get("runtime") or row.get("duration") or 45) for e in eps)
            seasons = [s for s in self.db.get_tv_seasons(lib_id) if s.get("rating")]
            if seasons:
                b = max(seasons, key=lambda s: s["rating"])
                out["best"] = f"{b.get('name') or 'Season ' + str(b['season_number'])} · {int(b['rating'])}/6"
            rated = [e for e in self.db.get_tv_episodes(lib_id) if e.get("rating")]
            if rated and "best" not in out:
                b = max(rated, key=lambda e: e["rating"])
                out["best"] = f"S{b['season_number']:02d}E{b['episode_number']:02d} · {int(b['rating'])}/6"
        else:
            out["minutes"] = int(row.get("duration") or 120) * (1 + (out["rewatches"] or 0))
            out["first"] = row.get("completed_at")
        return out


def boosts(db) -> Dict[int, float]:
    """For-you weights: Hall of Fame titles count more than any rating
    (a 6/6 is 3.0; your #1 is 4.0, gently less down the ranking)."""
    try:
        rows = db._get_conn().execute("SELECT lib_id, rank FROM hof_entries").fetchall()
    except Exception:
        return {}
    return {lib: max(3.2, 4.0 - 0.08 * (rank - 1)) for lib, rank in rows}


def cleanup(db) -> int:
    """Drop entries whose title is gone and close the rank gaps."""
    h = Hall(db)
    c = h.conn
    gone = [r[0] for r in c.execute("SELECT lib_id FROM hof_entries WHERE lib_id NOT IN (SELECT id FROM anime)")]
    c.execute("DELETE FROM hof_entries WHERE lib_id NOT IN (SELECT id FROM anime)")
    for wing in WINGS:
        ids = [r[0] for r in c.execute("SELECT lib_id FROM hof_entries WHERE wing=? ORDER BY rank", (wing,))]
        for i, lib in enumerate(ids, start=1):
            c.execute("UPDATE hof_entries SET rank=? WHERE lib_id=?", (i, lib))
    c.commit()
    return len(gone)


def problems(db) -> Dict[str, int]:
    """For the Data Doctor: missing titles and rank gaps."""
    c = db._get_conn()
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='hof_entries'").fetchone():
        return {"missing": 0, "gaps": 0}
    missing = c.execute("SELECT COUNT(*) FROM hof_entries WHERE lib_id NOT IN (SELECT id FROM anime)").fetchone()[0]
    gaps = 0
    for wing in WINGS:
        ranks = [r[0] for r in c.execute("SELECT rank FROM hof_entries WHERE wing=? ORDER BY rank", (wing,))]
        if ranks != list(range(1, len(ranks) + 1)):
            gaps += 1
    return {"missing": missing, "gaps": gaps}


# ── "Which do you love more?" ─────────────────────────────────────────────────

class InsertionSession:
    """Binary insertion with skip / tie / undo.

    ordered   lib ids of the wing, best first
    question  -> the lib id to compare the new title against (or None: done)
    answer('new' | 'existing' | 'tie' | 'skip')
    position  -> 1-based final rank once done
    """

    def __init__(self, ordered: List[int]):
        self.ordered = list(ordered)
        self.lo, self.hi = 0, len(self.ordered)
        self.skipped: set = set()
        self._stack: List[tuple] = []
        self._tie: Optional[int] = None
        self.asked = 0

    @property
    def done(self) -> bool:
        return self._tie is not None or self.lo >= self.hi

    @property
    def position(self) -> int:
        return (self._tie if self._tie is not None else self.lo) + 1

    def _pivot(self) -> Optional[int]:
        if self.done:
            return None
        mid = (self.lo + self.hi) // 2
        # nearest index to the middle that wasn't skipped
        for d in range(0, self.hi - self.lo):
            for i in (mid - d, mid + d):
                if self.lo <= i < self.hi and i not in self.skipped:
                    return i
        return None

    def question(self) -> Optional[int]:
        i = self._pivot()
        if i is None and not self.done:
            # everything left was skipped: settle in the middle
            self._tie = (self.lo + self.hi) // 2
            return None
        return None if i is None else self.ordered[i]

    def answer(self, choice: str):
        i = self._pivot()
        if i is None:
            return
        self._stack.append((self.lo, self.hi, set(self.skipped), self._tie, self.asked))
        self.asked += 1
        if choice == "new":            # the new title is loved more: it goes above
            self.hi = i
            self.skipped = {k for k in self.skipped if k < i}
        elif choice == "existing":     # the existing one wins: new goes below
            self.lo = i + 1
            self.skipped = {k for k in self.skipped if k > i}
        elif choice == "tie":          # too close to call: right next to it
            self._tie = i + 1
        elif choice == "skip":
            self.skipped.add(i)
            self.asked -= 1

    def undo(self) -> bool:
        if not self._stack:
            return False
        self.lo, self.hi, self.skipped, self._tie, self.asked = self._stack.pop()
        return True

    def estimate(self) -> int:
        """Roughly how many questions are left."""
        import math
        n = max(0, self.hi - self.lo)
        return 0 if self.done else max(1, math.ceil(math.log2(n + 1)))
