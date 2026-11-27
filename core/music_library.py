"""
Raikō - your music: liked openings / endings / intros / soundtracks, three
rankings (Openings, Endings, Soundtracks) and the downloads you've made.

A song is a YouTube video found by core.music: {id, site, kind, title, thumb}
plus where it's from (source title, media type, library id when the title is
in your library).
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

KINDS = ("opening", "ending", "intro", "soundtrack")
KIND_LABEL = {"opening": "Opening", "ending": "Ending", "intro": "Intro", "soundtrack": "Soundtrack"}
LISTS = {"op": "Openings & intros", "ed": "Endings", "ost": "Soundtracks"}


def list_for(kind: str) -> str:
    return {"opening": "op", "intro": "op", "ending": "ed"}.get(kind, "ost")


def song_title(item: Dict) -> str:
    """The video title without the trailing '· channel' we add for display."""
    return (item.get("title") or "").split("  ·  ")[0].strip()


class MusicLibrary:
    def __init__(self, db):
        self.db = db
        self.conn = db._get_conn()
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS music_likes (
                vid TEXT PRIMARY KEY, site TEXT, kind TEXT, title TEXT, channel TEXT, thumb TEXT,
                source TEXT, media TEXT, lib_id INTEGER, liked_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS music_ranks (
                vid TEXT NOT NULL, list TEXT NOT NULL, rank INTEGER NOT NULL,
                site TEXT, kind TEXT, title TEXT, thumb TEXT, source TEXT, media TEXT, lib_id INTEGER,
                ranked_at INTEGER, PRIMARY KEY (vid, list)
            );
            CREATE TABLE IF NOT EXISTS music_downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT, vid TEXT, mode TEXT, path TEXT, title TEXT,
                source TEXT, kind TEXT, at INTEGER
            );
        """)
        self.conn.commit()

    # ── likes ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _fields(item: Dict) -> Dict:
        full = item.get("title") or ""
        channel = full.split("  ·  ")[1] if "  ·  " in full else item.get("channel") or ""
        return {"vid": item["id"], "site": item.get("site") or "youtube", "kind": item.get("kind") or "soundtrack",
                "title": song_title(item), "channel": channel, "thumb": item.get("thumb") or "",
                "source": item.get("source") or "", "media": item.get("media") or "",
                "lib_id": item.get("lib_id")}

    def like(self, item: Dict):
        f = self._fields(item)
        self.conn.execute(
            "INSERT INTO music_likes (vid, site, kind, title, channel, thumb, source, media, lib_id, liked_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(vid) DO UPDATE SET liked_at=liked_at",
            (f["vid"], f["site"], f["kind"], f["title"], f["channel"], f["thumb"], f["source"], f["media"],
             f["lib_id"], int(time.time())))
        self.conn.commit()

    def unlike(self, vid: str):
        self.conn.execute("DELETE FROM music_likes WHERE vid=?", (vid,))
        self.conn.commit()

    def toggle_like(self, item: Dict) -> bool:
        if self.is_liked(item["id"]):
            self.unlike(item["id"])
            return False
        self.like(item)
        return True

    def is_liked(self, vid: str) -> bool:
        return bool(self.conn.execute("SELECT 1 FROM music_likes WHERE vid=?", (vid,)).fetchone())

    def liked(self, kind: Optional[str] = None) -> List[Dict]:
        q = "SELECT vid, site, kind, title, channel, thumb, source, media, lib_id, liked_at FROM music_likes"
        args: tuple = ()
        if kind:
            kinds = ("opening", "intro") if kind == "op" else (kind,)
            q += f" WHERE kind IN ({','.join('?' * len(kinds))})"
            args = kinds
        rows = self.conn.execute(q + " ORDER BY liked_at DESC", args).fetchall()
        return [self._item(dict(zip(("vid", "site", "kind", "title", "channel", "thumb", "source", "media",
                                     "lib_id", "liked_at"), r))) for r in rows]

    @staticmethod
    def _item(r: Dict) -> Dict:
        """Row -> playable item (same shape as the gallery's)."""
        return {"id": r["vid"], "site": r.get("site") or "youtube", "kind": r.get("kind"),
                "title": r.get("title") or "", "song": r.get("title") or "", "channel": r.get("channel") or "",
                "thumb": r.get("thumb") or f"https://i.ytimg.com/vi/{r['vid']}/hqdefault.jpg",
                "source": r.get("source") or "", "media": r.get("media") or "", "lib_id": r.get("lib_id"),
                **({"rank": r["rank"]} if "rank" in r else {}),
                **({"liked_at": r["liked_at"]} if r.get("liked_at") else {})}

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM music_likes").fetchone()[0]

    # ── rankings ──────────────────────────────────────────────────────────────

    def ranked(self, lst: str) -> List[Dict]:
        rows = self.conn.execute("SELECT vid, site, kind, title, thumb, source, media, lib_id, rank FROM music_ranks "
                                 "WHERE list=? ORDER BY rank", (lst,)).fetchall()
        return [self._item(dict(zip(("vid", "site", "kind", "title", "thumb", "source", "media", "lib_id", "rank"),
                                    r))) for r in rows]

    def rank_of(self, vid: str, lst: str) -> int:
        r = self.conn.execute("SELECT rank FROM music_ranks WHERE vid=? AND list=?", (vid, lst)).fetchone()
        return r[0] if r else 0

    def insert_at(self, item: Dict, lst: str, pos: int) -> int:
        f = self._fields(item)
        if self.rank_of(f["vid"], lst):
            return self.move(f["vid"], lst, pos)
        n = len(self.ranked(lst))
        pos = max(1, min(int(pos), n + 1))
        c = self.conn
        c.execute("UPDATE music_ranks SET rank=rank+1 WHERE list=? AND rank>=?", (lst, pos))
        c.execute("INSERT INTO music_ranks (vid, list, rank, site, kind, title, thumb, source, media, lib_id, "
                  "ranked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (f["vid"], lst, pos, f["site"], f["kind"], f["title"], f["thumb"], f["source"], f["media"],
                   f["lib_id"], int(time.time())))
        c.commit()
        return pos

    def move(self, vid: str, lst: str, new: int) -> int:
        old = self.rank_of(vid, lst)
        if not old:
            return 0
        n = len(self.ranked(lst))
        new = max(1, min(int(new), n))
        if new == old:
            return old
        c = self.conn
        if new < old:
            c.execute("UPDATE music_ranks SET rank=rank+1 WHERE list=? AND rank>=? AND rank<?", (lst, new, old))
        else:
            c.execute("UPDATE music_ranks SET rank=rank-1 WHERE list=? AND rank>? AND rank<=?", (lst, old, new))
        c.execute("UPDATE music_ranks SET rank=? WHERE vid=? AND list=?", (new, vid, lst))
        c.commit()
        return new

    def unrank(self, vid: str, lst: str):
        old = self.rank_of(vid, lst)
        if not old:
            return
        self.conn.execute("DELETE FROM music_ranks WHERE vid=? AND list=?", (vid, lst))
        self.conn.execute("UPDATE music_ranks SET rank=rank-1 WHERE list=? AND rank>?", (lst, old))
        self.conn.commit()

    # ── downloads ─────────────────────────────────────────────────────────────

    def record_download(self, item: Dict, mode: str, path: str):
        self.conn.execute("INSERT INTO music_downloads (vid, mode, path, title, source, kind, at) VALUES (?,?,?,?,?,?,?)",
                          (item["id"], mode, path, song_title(item), item.get("source") or "",
                           item.get("kind") or "", int(time.time())))
        self.conn.commit()

    def downloads(self) -> List[Dict]:
        rows = self.conn.execute("SELECT id, vid, mode, path, title, source, kind, at FROM music_downloads "
                                 "ORDER BY at DESC").fetchall()
        return [dict(zip(("id", "vid", "mode", "path", "title", "source", "kind", "at"), r)) for r in rows]

    def forget_download(self, did: int):
        self.conn.execute("DELETE FROM music_downloads WHERE id=?", (did,))
        self.conn.commit()
