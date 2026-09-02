"""
Miroku — Database Manager
SQLite-backed persistence layer with schema migrations.
"""
import sqlite3
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple


DB_VERSION = 4
# Legacy data directory name (kept so existing installs keep their library).
APP_DIR = Path.home() / ".animetracker"
DB_PATH = APP_DIR / "anime.db"
BACKUP_DIR = APP_DIR / "backups"
IMAGE_CACHE_DIR = APP_DIR / "covers"


def get_db_path() -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return DB_PATH


class DatabaseManager:
    """Thread-safe SQLite database manager with schema migrations."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_db_path()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # ─── Connection ───────────────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ─── Schema Init & Migration ──────────────────────────────────────────────

    def _init_db(self):
        conn = self._get_conn()
        # Schema version tracking
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        current = row["version"] if row else 0

        if current < 1:
            self._migrate_v1(conn)
        if current < 2:
            self._migrate_v2(conn)
        if current < 3:
            self._migrate_v3(conn)
        if current < 4:
            self._migrate_v4(conn)

        if current == 0:
            conn.execute("INSERT INTO schema_version VALUES (?)", (DB_VERSION,))
        else:
            conn.execute("UPDATE schema_version SET version=?", (DB_VERSION,))

        # Safe column additions — run every startup, ignored if column already exists
        for col_sql in [
            "ALTER TABLE anime ADD COLUMN hof_only INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(col_sql)
            except Exception:
                pass   # column already exists

        conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint     TEXT UNIQUE NOT NULL,
                kind            TEXT NOT NULL,
                anime_id        INTEGER,
                anilist_id      INTEGER,
                title           TEXT NOT NULL,
                message         TEXT NOT NULL,
                payload         TEXT DEFAULT '{}',
                state           TEXT DEFAULT 'active',
                first_seen      INTEGER,
                last_seen       INTEGER,
                remind_at       INTEGER,
                dismissed_at    INTEGER
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notifications_state "
            "ON notifications(state, remind_at)"
        )

        conn.commit()

    def _migrate_v1(self, conn: sqlite3.Connection):
        """Core schema: anime, episodes, ratings."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS anime (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                anilist_id      INTEGER UNIQUE,
                romaji_title    TEXT NOT NULL,
                english_title   TEXT,
                native_title    TEXT,
                status          TEXT DEFAULT 'WATCHING',
                watch_status    TEXT DEFAULT 'watching',
                cover_url       TEXT,
                banner_url      TEXT,
                cover_local     TEXT,
                description     TEXT,
                genres          TEXT DEFAULT '[]',
                studios         TEXT DEFAULT '[]',
                total_episodes  INTEGER,
                episode_offset  INTEGER DEFAULT 0,
                season          TEXT,
                season_year     INTEGER,
                average_score   INTEGER,
                popularity      INTEGER,
                trailer_id      TEXT,
                trailer_site    TEXT,
                start_date      TEXT,
                end_date        TEXT,
                next_episode_at INTEGER,
                next_episode_num INTEGER,
                is_frozen       INTEGER DEFAULT 0,
                sort_order      INTEGER DEFAULT 0,
                date_added      INTEGER,
                last_updated    INTEGER,
                last_watched_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS episodes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                anime_id    INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE,
                episode_num INTEGER NOT NULL,
                watched     INTEGER DEFAULT 0,
                downloaded  INTEGER DEFAULT 0,
                watched_at  INTEGER,
                note        TEXT,
                UNIQUE(anime_id, episode_num)
            );

            CREATE TABLE IF NOT EXISTS ratings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                anime_id    INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE,
                episode_num INTEGER NOT NULL,
                score       REAL NOT NULL,
                label       TEXT,
                created_at  INTEGER,
                UNIQUE(anime_id, episode_num)
            );

            CREATE TABLE IF NOT EXISTS dropped_anime (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                romaji_title    TEXT NOT NULL,
                english_title   TEXT,
                anilist_id      INTEGER,
                cover_url       TEXT,
                cover_local     TEXT,
                genres          TEXT DEFAULT '[]',
                dropped_at      INTEGER,
                drop_reason     TEXT,
                last_episode    INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_anime_status ON anime(watch_status);
            CREATE INDEX IF NOT EXISTS idx_episodes_anime ON episodes(anime_id);
            CREATE INDEX IF NOT EXISTS idx_ratings_anime ON ratings(anime_id);
        """)
        # Add hof_only column if not present (safe to run multiple times)
        try:
            conn.execute("ALTER TABLE anime ADD COLUMN hof_only INTEGER DEFAULT 0")
            conn.commit()
        except Exception:
            pass  # column already exists

    def _migrate_v2(self, conn: sqlite3.Connection): 
        """Add statistics table and search FTS."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS watch_sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                anime_id    INTEGER REFERENCES anime(id) ON DELETE CASCADE,
                episode_num INTEGER,
                started_at  INTEGER,
                ended_at    INTEGER,
                duration_s  INTEGER
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS anime_fts USING fts5(
                romaji_title, english_title, genres, content='anime', content_rowid='id'
            );

            CREATE TRIGGER IF NOT EXISTS anime_fts_insert
            AFTER INSERT ON anime BEGIN
                INSERT INTO anime_fts(rowid, romaji_title, english_title, genres)
                VALUES (new.id, new.romaji_title, new.english_title, new.genres);
            END;

            CREATE TRIGGER IF NOT EXISTS anime_fts_delete
            AFTER DELETE ON anime BEGIN
                INSERT INTO anime_fts(anime_fts, rowid, romaji_title, english_title, genres)
                VALUES ('delete', old.id, old.romaji_title, old.english_title, old.genres);
            END;

            CREATE TRIGGER IF NOT EXISTS anime_fts_update
            AFTER UPDATE ON anime BEGIN
                INSERT INTO anime_fts(anime_fts, rowid, romaji_title, english_title, genres)
                VALUES ('delete', old.id, old.romaji_title, old.english_title, old.genres);
                INSERT INTO anime_fts(rowid, romaji_title, english_title, genres)
                VALUES (new.id, new.romaji_title, new.english_title, new.genres);
            END;
        """)
    
    def _migrate_v3(self, conn: sqlite3.Connection):
        """Add watch_log table (heatmap / activity history)."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS watch_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                anime_id    INTEGER REFERENCES anime(id) ON DELETE CASCADE,
                episode_num INTEGER NOT NULL,
                watched_at  INTEGER NOT NULL,
                anime_title TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_watch_log_date
                ON watch_log(watched_at);
            CREATE INDEX IF NOT EXISTS idx_watch_log_anime
                ON watch_log(anime_id);

        """)

    def _migrate_v4(self, conn: sqlite3.Connection):
        """Per-anime quick links (streaming, Telegram, etc.)."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS anime_links (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                anime_id    INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE,
                label       TEXT NOT NULL,
                url         TEXT NOT NULL,
                platform    TEXT DEFAULT 'other',
                sort_order  INTEGER DEFAULT 0,
                created_at  INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_anime_links_anime
                ON anime_links(anime_id, sort_order);
        """)

    # ─── Anime CRUD ───────────────────────────────────────────────────────────

    def add_anime(self, data: Dict[str, Any]) -> int:
        conn = self._get_conn()
        now = int(datetime.now().timestamp())
        data.setdefault("date_added", now)
        data.setdefault("last_updated", now)
        if "genres" in data and isinstance(data["genres"], list):
            data["genres"] = json.dumps(data["genres"])
        if "studios" in data and isinstance(data["studios"], list):
            data["studios"] = json.dumps(data["studios"])

        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" * len(data))
        cur = conn.execute(
            f"INSERT OR REPLACE INTO anime ({cols}) VALUES ({placeholders})",
            list(data.values()),
        )
        conn.commit()
        return cur.lastrowid

    def get_all_anime(
        self,
        watch_status: Optional[str] = None,
        sort_by: str = "release_date",
    ) -> List[Dict]:
        ORDER = {
            "release_date": "COALESCE(next_episode_at, 99999999999) ASC, season_year ASC, romaji_title ASC",
            "title":        "romaji_title ASC",
            "score":        "average_score DESC, romaji_title ASC",
            "date_added":   "date_added DESC",
            "rating":       "romaji_title ASC",
        }.get(sort_by, "COALESCE(next_episode_at, 99999999999) ASC, romaji_title ASC")
        conn = self._get_conn()
        if watch_status:
            where = "WHERE watch_status=? AND hof_only=0"
            params = (watch_status,)
        else:
            where = "WHERE hof_only=0"
            params = ()
        rows = conn.execute(
            f"SELECT * FROM anime {where} ORDER BY {ORDER}", params
        ).fetchall()
        result = [self._hydrate_anime(dict(r)) for r in rows]
        if sort_by == "rating":
            def _avg(a):
                r = conn.execute(
                    "SELECT AVG(score) FROM ratings WHERE anime_id=?", (a["id"],)
                ).fetchone()
                return r[0] if r and r[0] else -1
            result.sort(key=_avg, reverse=True)
        return result

    def delete_dropped_anime(self, dropped_id: int):
        conn = self._get_conn()
        conn.execute("DELETE FROM dropped_anime WHERE id=?", (dropped_id,))
        conn.commit()

    def get_anime_by_id(self, anime_id: int) -> Optional[Dict]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM anime WHERE id=?", (anime_id,)).fetchone()
        return self._hydrate_anime(dict(row)) if row else None

    def get_anime_by_anilist_id(self, anilist_id: int) -> Optional[Dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM anime WHERE anilist_id=?", (anilist_id,)
        ).fetchone()
        return self._hydrate_anime(dict(row)) if row else None

    def update_anime(self, anime_id: int, data: Dict[str, Any]):
        conn = self._get_conn()
        data["last_updated"] = int(datetime.now().timestamp())
        if "genres" in data and isinstance(data["genres"], list):
            data["genres"] = json.dumps(data["genres"])
        if "studios" in data and isinstance(data["studios"], list):
            data["studios"] = json.dumps(data["studios"])
        sets = ", ".join(f"{k}=?" for k in data)
        conn.execute(
            f"UPDATE anime SET {sets} WHERE id=?", list(data.values()) + [anime_id]
        )
        conn.commit()

    def delete_anime(self, anime_id: int, drop: bool = False, reason: str = ""):
        conn = self._get_conn()
        if drop:
            row = conn.execute("SELECT * FROM anime WHERE id=?", (anime_id,)).fetchone()
            if row:
                row = dict(row)
                last_ep = conn.execute(
                    "SELECT MAX(episode_num) FROM episodes WHERE anime_id=? AND watched=1",
                    (anime_id,),
                ).fetchone()
                conn.execute(
                    """INSERT INTO dropped_anime
                    (romaji_title, english_title, anilist_id, cover_url, cover_local,
                     genres, dropped_at, drop_reason, last_episode)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        row["romaji_title"], row["english_title"], row["anilist_id"],
                        row["cover_url"], row["cover_local"], row["genres"],
                        int(datetime.now().timestamp()), reason,
                        last_ep[0] if last_ep and last_ep[0] else 0,
                    ),
                )
        conn.execute("DELETE FROM anime WHERE id=?", (anime_id,))
        conn.commit()

    def search_anime(self, query: str) -> List[Dict]:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT anime.* FROM anime
               JOIN anime_fts ON anime.id = anime_fts.rowid
               WHERE anime_fts MATCH ? AND anime.hof_only=0
               ORDER BY rank""",
            (query + "*",),
        ).fetchall()
        return [self._hydrate_anime(dict(r)) for r in rows]

    def _hydrate_anime(self, data: Dict) -> Dict:
        for key in ("genres", "studios"):
            if isinstance(data.get(key), str):
                try:
                    data[key] = json.loads(data[key])
                except (json.JSONDecodeError, TypeError):
                    data[key] = []
        return data

    # ─── Episode CRUD ─────────────────────────────────────────────────────────

    def get_episodes(self, anime_id: int) -> List[Dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM episodes WHERE anime_id=? ORDER BY episode_num",
            (anime_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_episode_watched(self, anime_id: int, ep_num: int, watched: bool):
        conn = self._get_conn()
        now = int(datetime.now().timestamp()) if watched else None
        conn.execute(
            """INSERT INTO episodes (anime_id, episode_num, watched, watched_at)
               VALUES (?,?,?,?)
               ON CONFLICT(anime_id, episode_num)
               DO UPDATE SET watched=excluded.watched, watched_at=excluded.watched_at""",
            (anime_id, ep_num, int(watched), now),
        )
        if watched:
            conn.execute(
                "UPDATE anime SET last_watched_at=? WHERE id=?",
                (now, anime_id),
            )
            # Log to watch_log for heatmap and history
            title_row = conn.execute(
                "SELECT romaji_title FROM anime WHERE id=?", (anime_id,)
            ).fetchone()
            title = title_row[0] if title_row else ""
            conn.execute(
                """INSERT OR IGNORE INTO watch_log
                   (anime_id, episode_num, watched_at, anime_title)
                   VALUES (?,?,?,?)""",
                (anime_id, ep_num, now, title),
            )
        conn.commit()

    def set_episode_downloaded(self, anime_id: int, ep_num: int, downloaded: bool):
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO episodes (anime_id, episode_num, downloaded)
               VALUES (?,?,?)
               ON CONFLICT(anime_id, episode_num)
               DO UPDATE SET downloaded=excluded.downloaded""",
            (anime_id, ep_num, int(downloaded)),
        )
        conn.commit()

    def set_episode_note(self, anime_id: int, ep_num: int, note: str):
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO episodes (anime_id, episode_num, note)
               VALUES (?,?,?)
               ON CONFLICT(anime_id, episode_num)
               DO UPDATE SET note=excluded.note""",
            (anime_id, ep_num, note),
        )
        conn.commit()

    def get_watched_count(self, anime_id: int) -> int:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE anime_id=? AND watched=1", (anime_id,)
        ).fetchone()
        return row[0]

    def get_downloaded_count(self, anime_id: int) -> int:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE anime_id=? AND downloaded=1", (anime_id,)
        ).fetchone()
        return row[0]

    # ─── Ratings ─────────────────────────────────────────────────────────────

    def set_rating(self, anime_id: int, ep_num: int, score: float, label: str = ""):
        conn = self._get_conn()
        now = int(datetime.now().timestamp())
        conn.execute(
            """INSERT INTO ratings (anime_id, episode_num, score, label, created_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(anime_id, episode_num)
               DO UPDATE SET score=excluded.score, label=excluded.label""",
            (anime_id, ep_num, score, label, now),
        )
        conn.commit()

    def get_ratings(self, anime_id: int) -> List[Dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM ratings WHERE anime_id=? ORDER BY episode_num",
            (anime_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_average_rating(self, anime_id: int) -> Optional[float]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT AVG(score) FROM ratings WHERE anime_id=?", (anime_id,)
        ).fetchone()
        val = row[0]
        return round(val, 1) if val is not None else None

    def get_overall_rating(self, anime_id: int) -> Optional[float]:
        """The user's explicit overall rating (episode_num=0), as opposed to
        get_average_rating() which blends it together with every per-episode
        rating. Use this whenever you need "what did the user actually rate
        this show overall" rather than a derived average."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT score FROM ratings WHERE anime_id=? AND episode_num=0",
            (anime_id,),
        ).fetchone()
        return row[0] if row is not None else None

    def get_remarkable_anime(self) -> Dict[str, Any]:
        """Return per-anime highlights for the stats page."""
        conn = self._get_conn()
        result = {}

        # Most watched episodes
        row = conn.execute("""
            SELECT a.id, a.romaji_title, a.english_title, COUNT(e.id) as cnt
            FROM anime a JOIN episodes e ON a.id=e.anime_id
            WHERE e.watched=1 AND a.hof_only=0
            GROUP BY a.id ORDER BY cnt DESC LIMIT 1
        """).fetchone()
        if row: result["most_watched"] = dict(row)

        # Highest rated by user
        row = conn.execute("""
            SELECT a.id, a.romaji_title, a.english_title, AVG(r.score) as avg_sc
            FROM anime a JOIN ratings r ON a.id=r.anime_id
            WHERE a.hof_only=0
            GROUP BY a.id HAVING COUNT(r.id) >= 1
            ORDER BY avg_sc DESC LIMIT 1
        """).fetchone()
        if row: result["highest_rated"] = dict(row)

        # Lowest rated
        row = conn.execute("""
            SELECT a.id, a.romaji_title, a.english_title, AVG(r.score) as avg_sc
            FROM anime a JOIN ratings r ON a.id=r.anime_id
            WHERE a.hof_only=0
            GROUP BY a.id HAVING COUNT(r.id) >= 1
            ORDER BY avg_sc ASC LIMIT 1
        """).fetchone()
        if row: result["lowest_rated"] = dict(row)

        # Most recently added
        row = conn.execute("""
            SELECT id, romaji_title, english_title, date_added
            FROM anime WHERE hof_only=0
            ORDER BY date_added DESC LIMIT 1
        """).fetchone()
        if row: result["most_recent"] = dict(row)

        # Longest wait (planned with furthest next_episode_at)
        row = conn.execute("""
            SELECT id, romaji_title, english_title, next_episode_at
            FROM anime WHERE watch_status='planned' AND next_episode_at IS NOT NULL
            AND hof_only=0
            ORDER BY next_episode_at DESC LIMIT 1
        """).fetchone()
        if row: result["longest_wait"] = dict(row)

        return result

    # ─── Statistics ───────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        conn = self._get_conn()
        # All counts exclude hof_only entries
        total = conn.execute(
            "SELECT COUNT(*) FROM anime WHERE hof_only=0"
        ).fetchone()[0]
        watching = conn.execute(
            "SELECT COUNT(*) FROM anime WHERE watch_status='watching' AND hof_only=0"
        ).fetchone()[0]
        completed = conn.execute(
            "SELECT COUNT(*) FROM anime WHERE watch_status='completed' AND hof_only=0"
        ).fetchone()[0]
        planned = conn.execute(
            "SELECT COUNT(*) FROM anime WHERE watch_status='planned' AND hof_only=0"
        ).fetchone()[0]
        dropped = conn.execute("SELECT COUNT(*) FROM dropped_anime").fetchone()[0]
        total_watched = conn.execute(
            """SELECT COUNT(*) FROM episodes e
               JOIN anime a ON e.anime_id = a.id
               WHERE e.watched=1 AND a.hof_only=0"""
        ).fetchone()[0]
        avg_score = conn.execute(
            """SELECT AVG(r.score) FROM ratings r
               JOIN anime a ON r.anime_id = a.id
               WHERE a.hof_only=0"""
        ).fetchone()[0]
        genre_counts = conn.execute(
            "SELECT genres FROM anime WHERE genres != '[]' AND hof_only=0"
        ).fetchall()

        genre_map: Dict[str, int] = {}
        for row in genre_counts:
            try:
                genres = json.loads(row[0])
                for g in genres:
                    genre_map[g] = genre_map.get(g, 0) + 1
            except Exception:
                pass

        top_genres = sorted(genre_map.items(), key=lambda x: x[1], reverse=True)[:8]

        studio_counts = conn.execute(
            "SELECT studios FROM anime WHERE studios != '[]' AND hof_only=0"
        ).fetchall()

        studio_map: Dict[str, int] = {}
        for row in studio_counts:
            try:
                studios = json.loads(row[0])
                for s in studios:
                    studio_map[s] = studio_map.get(s, 0) + 1
            except Exception:
                pass

        top_studios = sorted(studio_map.items(), key=lambda x: x[1], reverse=True)[:8]

        return {
            "total": total,
            "watching": watching,
            "completed": completed,
            "planned": planned,
            "dropped": dropped,
            "total_episodes_watched": total_watched,
            "average_score": round(avg_score, 1) if avg_score else None,
            "top_genres": top_genres,
            "top_studios": top_studios,
        }

    def get_decade_breakdown(self) -> List[Tuple[int, int]]:
        """Count of anime per decade (by season_year), chronological order."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT season_year FROM anime "
            "WHERE hof_only=0 AND season_year IS NOT NULL"
        ).fetchall()
        counts: Dict[int, int] = {}
        for r in rows:
            year = r[0]
            if not year:
                continue
            decade = (int(year) // 10) * 10
            counts[decade] = counts.get(decade, 0) + 1
        return sorted(counts.items(), key=lambda x: x[0])

    # ─── Watch Log ────────────────────────────────────────────────────────────

    def get_watch_log_year(self, year: int) -> List[Dict]:
        start = int(datetime(year, 1, 1).timestamp())
        end   = int(datetime(year, 12, 31, 23, 59, 59).timestamp())
        conn  = self._get_conn()
        rows  = conn.execute(
            """SELECT watched_at, anime_id, episode_num, anime_title
               FROM watch_log WHERE watched_at BETWEEN ? AND ?
               ORDER BY watched_at ASC""",
            (start, end),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_available_log_years(self) -> List[int]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT strftime('%Y', watched_at, 'unixepoch') AS y "
            "FROM watch_log ORDER BY y DESC"
        ).fetchall()
        years = [int(r[0]) for r in rows if r[0]]
        return years if years else [datetime.now().year]

    def get_longest_streak(self) -> int:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT DISTINCT date(watched_at, 'unixepoch') AS d
               FROM watch_log ORDER BY d ASC"""
        ).fetchall()
        if not rows:
            return 0
        from datetime import date, timedelta
        longest  = 1
        current  = 1
        prev: Optional[date] = None
        for row in rows:
            d = date.fromisoformat(row[0])
            if prev is not None and d == prev + timedelta(days=1):
                current += 1
            elif prev is not None and d != prev:
                current = 1
            longest = max(longest, current)
            prev = d
        return longest

    def get_current_streak(self) -> int:
        conn  = self._get_conn()
        rows  = conn.execute(
            """SELECT DISTINCT date(watched_at, 'unixepoch') AS d
               FROM watch_log ORDER BY d DESC"""
        ).fetchall()
        if not rows:
            return 0
        from datetime import date, timedelta
        today    = date.today()
        streak   = 0
        expected = today
        for row in rows:
            d = date.fromisoformat(row[0])
            if d == expected:
                streak  += 1
                expected = expected - timedelta(days=1)
            elif d == today - timedelta(days=1) and streak == 0:
                streak  += 1
                expected = d - timedelta(days=1)
            else:
                break
        return streak

    # ─── Dropped ──────────────────────────────────────────────────────────────

    def get_dropped_anime(self) -> List[Dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM dropped_anime ORDER BY dropped_at DESC"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("genres"), str):
                try:
                    d["genres"] = json.loads(d["genres"])
                except Exception:
                    d["genres"] = []
            result.append(d)
        return result

    def restore_dropped(self, dropped_id: int) -> Optional[int]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM dropped_anime WHERE id=?", (dropped_id,)
        ).fetchone()
        if not row:
            return None
        r = dict(row)
        new_id = self.add_anime({
            "romaji_title": r["romaji_title"],
            "english_title": r["english_title"],
            "anilist_id": r["anilist_id"],
            "cover_url": r["cover_url"],
            "cover_local": r["cover_local"],
            "genres": r["genres"],
            "watch_status": "watching",
        })
        conn.execute("DELETE FROM dropped_anime WHERE id=?", (dropped_id,))
        conn.commit()
        return new_id

    # ─── Backup ───────────────────────────────────────────────────────────────

    def backup(self) -> Path:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = BACKUP_DIR / f"anime_backup_{ts}.db"
        shutil.copy2(str(self.db_path), str(dest))
        # Keep only last 5 backups
        backups = sorted(BACKUP_DIR.glob("anime_backup_*.db"))
        for old in backups[:-5]:
            old.unlink(missing_ok=True)
        return dest

    # ─── Legacy JSON migration ────────────────────────────────────────────────

    def import_legacy_json(self, json_path: str) -> int:
        """Migrate from the old anime_info.json flat file format."""
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        count = 0
        for item in data:
            try:
                anime_data = {
                    "romaji_title": item.get("name", "Unknown"),
                    "english_title": item.get("english_title", ""),
                    "watch_status": "watching",
                    "genres": item.get("genres", []),
                    "is_frozen": int(item.get("frozen", False)),
                    "next_episode_at": int(item.get("next_episode_date") or 0) or None,
                    "next_episode_num": item.get("episode_number"),
                    "last_watched_at": int(item.get("last_watched_date") or 0) or None,
                }
                if item.get("status") == "Finished":
                    anime_data["watch_status"] = "completed"
                elif item.get("status") == "Upcoming":
                    anime_data["watch_status"] = "planned"

                aid = self.add_anime(anime_data)

                for ep in item.get("watched_episodes", []):
                    self.set_episode_watched(aid, ep, True)
                for ep in item.get("downloaded_episodes", []):
                    self.set_episode_downloaded(aid, ep, True)
                for ep_str, score in item.get("ratings", {}).items():
                    try:
                        real_score = 5.5 if score == 6 else float(score)
                        self.set_rating(aid, int(ep_str), real_score)
                    except (ValueError, TypeError):
                        pass

                count += 1
            except Exception:
                continue
        return count

    # Notifications

    def upsert_notification(self, data: Dict[str, Any]) -> Optional[int]:
        conn = self._get_conn()
        now = int(datetime.now().timestamp())
        payload = data.get("payload", {})
        if not isinstance(payload, str):
            payload = json.dumps(payload)
        row = conn.execute(
            "SELECT id, state, remind_at FROM notifications WHERE fingerprint=?",
            (data["fingerprint"],),
        ).fetchone()
        if row:
            if row["state"] == "dismissed":
                return None
            conn.execute(
                """UPDATE notifications
                   SET last_seen=?, title=?, message=?, payload=?
                   WHERE id=?""",
                (now, data["title"], data["message"], payload, row["id"]),
            )
            conn.commit()
            return row["id"]
        cur = conn.execute(
            """INSERT INTO notifications
               (fingerprint, kind, anime_id, anilist_id, title, message, payload,
                state, first_seen, last_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                data["fingerprint"],
                data["kind"],
                data.get("anime_id"),
                data.get("anilist_id"),
                data["title"],
                data["message"],
                payload,
                "active",
                now,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid

    def get_due_notifications(self, limit: int = 3) -> List[Dict]:
        conn = self._get_conn()
        now = int(datetime.now().timestamp())
        rows = conn.execute(
            """SELECT * FROM notifications
               WHERE state='active'
                 AND (remind_at IS NULL OR remind_at <= ?)
               ORDER BY last_seen DESC
               LIMIT ?""",
            (now, limit),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["payload"] = json.loads(item.get("payload") or "{}")
            except Exception:
                item["payload"] = {}
            result.append(item)
        return result

    def dismiss_notification(self, notification_id: int):
        conn = self._get_conn()
        now = int(datetime.now().timestamp())
        conn.execute(
            "UPDATE notifications SET state='dismissed', dismissed_at=? WHERE id=?",
            (now, notification_id),
        )
        conn.commit()

    def remind_notification_later(self, notification_id: int, hours: int = 24):
        conn = self._get_conn()
        remind_at = int(datetime.now().timestamp()) + max(1, hours) * 3600
        conn.execute(
            "UPDATE notifications SET state='active', remind_at=? WHERE id=?",
            (remind_at, notification_id),
        )
        conn.commit()

    # ─── Anime links ──────────────────────────────────────────────────────────

    def get_anime_links(self, anime_id: int) -> List[Dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM anime_links WHERE anime_id=? ORDER BY sort_order, id",
            (anime_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_anime_link(
        self,
        anime_id: int,
        label: str,
        url: str,
        platform: str = "other",
    ) -> int:
        conn = self._get_conn()
        now = int(datetime.now().timestamp())
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM anime_links WHERE anime_id=?",
            (anime_id,),
        ).fetchone()[0]
        cur = conn.execute(
            """INSERT INTO anime_links
               (anime_id, label, url, platform, sort_order, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (anime_id, label, url, platform, max_order + 1, now),
        )
        conn.commit()
        return cur.lastrowid

    def update_anime_link(
        self,
        link_id: int,
        *,
        label: Optional[str] = None,
        url: Optional[str] = None,
        platform: Optional[str] = None,
    ):
        conn = self._get_conn()
        updates = {}
        if label is not None:
            updates["label"] = label
        if url is not None:
            updates["url"] = url
        if platform is not None:
            updates["platform"] = platform
        if not updates:
            return
        sets = ", ".join(f"{k}=?" for k in updates)
        conn.execute(
            f"UPDATE anime_links SET {sets} WHERE id=?",
            list(updates.values()) + [link_id],
        )
        conn.commit()

    def delete_anime_link(self, link_id: int):
        conn = self._get_conn()
        conn.execute("DELETE FROM anime_links WHERE id=?", (link_id,))
        conn.commit()

    def has_anime_links(self, anime_id: int) -> bool:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT 1 FROM anime_links WHERE anime_id=? LIMIT 1",
            (anime_id,),
        ).fetchone()
        return row is not None

