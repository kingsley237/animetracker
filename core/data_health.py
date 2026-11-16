"""
Data health - integrity checks for the whole library (anime, movies, TV),
with a proposed fix for each problem. Used by Data Doctor (which shows the
issues and applies the fixes you approve) and by the background health
check that raises a notification when something needs attention.

Nothing here changes data until a fix function is called.

Anime
  - watched more episodes than exist / than have aired
  - Completed with episodes unmarked
  - finished airing, every episode watched, still in Watching
  - duplicates (same AniList id)
  - in Dropped and in the library at the same time
  - ratings on episodes you haven't watched
  - stale airing countdowns
Movies
  - marked watched but not released yet
  - duplicates (same TMDB id)
TV shows
  - never synced (no seasons / episodes stored)       fix downloads them
  - episodes ticked that haven't aired yet
  - Completed with aired episodes unwatched
  - on the Watchlist with episodes already watched
All
  - SQLite integrity check
  - leftovers: episode rows / alerts pointing at deleted titles
  - malformed genres / studios
  - cached cover files that disappeared
  - duplicate activity rows
  - unexpected errors logged by the app (error.log)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import time
from typing import Callable, List, Optional

ERROR_LOG = Path.home() / ".animetracker" / "error.log"


@dataclass
class Issue:
    issue_id: str          # stable key, e.g. "overcount_42"
    severity: str          # "error" | "warning" | "info"
    title: str
    detail: str
    anime_id: Optional[int]
    anime_title: str
    fix_label: str
    fix_fn: Callable[[], None]
    checked: bool = True   # pre-selected in Data Doctor
    area: str = "Anime"    # Anime | Movies | TV shows | Library | App


def _name(row) -> str:
    try:
        return row["english_title"] or row["romaji_title"] or f"ID {row['id']}"
    except (IndexError, KeyError):
        return row["romaji_title"] or f"ID {row['id']}"


def recent_errors(since_ts: float = 0) -> List[str]:
    """Error blocks written by main.py's crash guard, newest last."""
    try:
        text = ERROR_LOG.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    out = []
    for block in text.split("\n["):
        block = block.strip().lstrip("[")
        if not block:
            continue
        try:
            ts = datetime.strptime(block[:19], "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            continue
        if ts >= since_ts:
            out.append(block)
    return out


class Scanner:
    def __init__(self, db):
        self.db = db

    # ── entry point ───────────────────────────────────────────────────────────

    def scan(self, quick: bool = False) -> List[Issue]:
        """quick=True skips the slower whole-file integrity check (used by
        the background health check)."""
        issues: List[Issue] = []
        conn = self.db._get_conn()
        if not quick:
            self._check_integrity(conn, issues)
        self._check_anime(conn, issues)
        self._check_movies(conn, issues)
        self._check_tv(conn, issues)
        self._check_library(conn, issues)
        self._check_errors(issues)
        return issues

    # ── database file ─────────────────────────────────────────────────────────

    def _check_integrity(self, conn, issues):
        try:
            res = [r[0] for r in conn.execute("PRAGMA quick_check").fetchall()]
        except Exception as e:
            res = [str(e)]
        if res != ["ok"]:
            issues.append(Issue(
                "integrity", "error", "The library file reports damage",
                "SQLite's own check found problems: " + "; ".join(res[:3])
                + ". Rebuilding the indexes repairs most of these. If it persists, restore "
                  "the newest copy from the backups folder (Settings → Backups).",
                None, "Library file", "Rebuild indexes", self._fix_reindex, area="Library"))

    # ── anime ─────────────────────────────────────────────────────────────────

    def _check_anime(self, conn, issues):
        rows = conn.execute(
            "SELECT * FROM anime WHERE hof_only=0 AND COALESCE(media_type,'anime')='anime'").fetchall()
        for row in rows:
            a = dict(row)
            aid, title = a["id"], _name(row)
            total = a.get("total_episodes") or 0
            next_ep = a.get("next_episode_num")
            api = (a.get("status") or "").upper()
            ws = (a.get("watch_status") or "").lower()
            watched = conn.execute(
                "SELECT COUNT(*) FROM episodes WHERE anime_id=? AND watched=1", (aid,)).fetchone()[0]
            aired = total if (total and api in ("FINISHED", "CANCELLED")) else (
                next_ep - 1 if next_ep and next_ep > 1 else 0)

            if total > 0 and watched > total:
                n = watched - total
                issues.append(Issue(
                    f"overcount_{aid}", "error", "More episodes watched than exist",
                    f"{title} has {watched} episodes marked watched but only {total} exist. "
                    f"Fix removes the {n} extra mark(s) above episode {total}.",
                    aid, title, f"Remove {n} extra mark(s)",
                    lambda a=aid, t=total: self._fix_overcount(a, t)))
            elif aired > 0 and watched > aired and api == "RELEASING":
                n = watched - aired
                issues.append(Issue(
                    f"ahead_{aid}", "warning", "Episodes marked that haven't aired",
                    f"{title} has {watched} episodes marked watched but only {aired} have aired. "
                    f"Fix un-marks the {n} episode(s) above episode {aired}.",
                    aid, title, f"Un-mark {n} future episode(s)",
                    lambda a=aid, ai=aired: self._fix_overcount(a, ai)))

            if ws == "completed" and total > 0 and watched < total:
                n = total - watched
                issues.append(Issue(
                    f"incomplete_{aid}", "warning", "Completed, but episodes are unmarked",
                    f"{title} is Completed but only {watched} of {total} episodes are marked. "
                    f"Fix marks all {total} watched.",
                    aid, title, f"Mark the {n} missing episode(s) watched",
                    lambda a=aid, t=total: self._fix_mark_all(a, t), checked=False))

            if ws == "watching" and api == "FINISHED" and total and watched >= total:
                issues.append(Issue(
                    f"status_mismatch_{aid}", "info", "Finished, but still in Watching",
                    f"You've watched every episode of {title} and it has finished airing, "
                    "but it's still in Watching. Fix moves it to Completed.",
                    aid, title, "Move to Completed",
                    lambda a=aid: self._fix_status(a, "completed")))

        for d in conn.execute(
                """SELECT anilist_id, COUNT(*) c FROM anime WHERE anilist_id IS NOT NULL
                   AND hof_only=0 AND COALESCE(media_type,'anime')='anime'
                   GROUP BY anilist_id HAVING c > 1""").fetchall():
            dupes = conn.execute("SELECT id, romaji_title FROM anime WHERE anilist_id=? "
                                 "ORDER BY date_added DESC", (d[0],)).fetchall()
            remove = [r[0] for r in dupes[1:]]
            issues.append(Issue(
                f"dup_{d[0]}", "error", "The same anime is in your library twice",
                f"'{dupes[0][1]}' appears {d[1]} times. Fix keeps the most recent entry "
                f"and deletes {len(remove)} older copy(ies).",
                dupes[0][0], dupes[0][1], f"Remove {len(remove)} duplicate(s)",
                lambda ids=remove: self._delete_titles(ids)))

        both = conn.execute(
            """SELECT d.id AS did, a.id, a.romaji_title, a.english_title, a.watch_status
               FROM dropped_anime d JOIN anime a ON a.anilist_id = d.anilist_id
               WHERE d.anilist_id IS NOT NULL AND a.hof_only=0""").fetchall()
        for r in both:
            issues.append(Issue(
                f"dropped_and_library_{r['did']}", "warning", "In Dropped and in your library",
                f"{_name(r)} is in your library ({r['watch_status']}) and also in Dropped. "
                "Fix removes the Dropped record and keeps the library entry.",
                r["id"], _name(r), "Remove from Dropped",
                lambda did=r["did"]: self._exec("DELETE FROM dropped_anime WHERE id=?", (did,))))

        stray = conn.execute(
            """SELECT COUNT(*) FROM ratings r
               JOIN anime a ON a.id = r.anime_id AND COALESCE(a.media_type,'anime')='anime'
               LEFT JOIN episodes e ON e.anime_id = r.anime_id AND e.episode_num = r.episode_num
               WHERE r.episode_num > 0 AND r.score > 0 AND COALESCE(e.watched,0) = 0""").fetchone()[0]
        if stray:
            issues.append(Issue(
                "stray_ratings", "info", "Ratings on episodes you haven't watched",
                f"{stray} episode rating(s) belong to episodes that aren't marked watched, "
                "so they don't show anywhere. Fix clears them.",
                None, "Episode ratings", f"Clear {stray} stray rating(s)", self._fix_stray_ratings,
                checked=False))

        cutoff = int(time()) - 7 * 86400
        for r in conn.execute(
                """SELECT id, romaji_title, english_title FROM anime WHERE status='RELEASING'
                   AND next_episode_at IS NOT NULL AND next_episode_at < ?
                   AND hof_only=0 AND COALESCE(media_type,'anime')='anime'""", (cutoff,)).fetchall():
            issues.append(Issue(
                f"stale_airing_{r['id']}", "info", "Airing countdown is out of date",
                f"{_name(r)} still counts down to an episode from over a week ago. "
                "Fix clears it so the next airing refresh fills it in again.",
                r["id"], _name(r), "Clear stale countdown",
                lambda a=r["id"]: self._exec(
                    "UPDATE anime SET next_episode_at=NULL, next_episode_num=NULL WHERE id=?", (a,))))

    # ── movies ────────────────────────────────────────────────────────────────

    def _check_movies(self, conn, issues):
        from core.kinema_sync import release_state
        for row in conn.execute("SELECT * FROM anime WHERE media_type='movie' AND hof_only=0"
                                " AND watch_status='completed'").fetchall():
            if release_state(dict(row))["state"] == "unreleased":
                issues.append(Issue(
                    f"movie_unreleased_{row['id']}", "warning", "Watched, but not released yet",
                    f"{_name(row)} is marked watched but hasn't come out. "
                    "Fix moves it back to your Watchlist so you're told when it's out in HD.",
                    row["id"], _name(row), "Move to Watchlist",
                    lambda a=row["id"]: self.db.update_anime(
                        a, {"watch_status": "planned", "completed_at": None}),
                    area="Movies"))
        self._dupes_tmdb(conn, issues, "movie", "Movies")

    def _dupes_tmdb(self, conn, issues, media, area):
        for d in conn.execute(
                "SELECT tmdb_id, COUNT(*) c FROM anime WHERE media_type=? AND tmdb_id IS NOT NULL "
                "GROUP BY tmdb_id HAVING c > 1", (media,)).fetchall():
            dupes = conn.execute("SELECT id, romaji_title FROM anime WHERE media_type=? AND tmdb_id=? "
                                 "ORDER BY date_added DESC", (media, d[0])).fetchall()
            remove = [r[0] for r in dupes[1:]]
            issues.append(Issue(
                f"dup_{media}_{d[0]}", "error", "The same title is in your library twice",
                f"'{dupes[0][1]}' appears {d[1]} times. Fix keeps the most recent entry.",
                dupes[0][0], dupes[0][1], f"Remove {len(remove)} duplicate(s)",
                lambda ids=remove: self._delete_titles(ids), area=area))

    # ── TV ────────────────────────────────────────────────────────────────────

    def _check_tv(self, conn, issues):
        today = datetime.now().strftime("%Y-%m-%d")
        for row in conn.execute("SELECT * FROM anime WHERE media_type='tv' AND hof_only=0").fetchall():
            aid, title, ws = row["id"], _name(row), row["watch_status"]
            n_eps = conn.execute("SELECT COUNT(*) FROM tv_episodes WHERE anime_id=?", (aid,)).fetchone()[0]
            if not n_eps and row["tmdb_id"]:
                issues.append(Issue(
                    f"tv_unsynced_{aid}", "warning", "Show has no episodes stored",
                    f"{title} has no seasons or episodes saved, so progress can't be tracked. "
                    "Fix downloads them from TMDB (needs internet).",
                    aid, title, "Download seasons & episodes",
                    lambda a=aid, t=row["tmdb_id"]: self._fix_tv_resync(a, t), area="TV shows"))
                continue
            future = conn.execute(
                "SELECT COUNT(*) FROM tv_episodes WHERE anime_id=? AND watched=1 "
                "AND air_date IS NOT NULL AND air_date > ?", (aid, today)).fetchone()[0]
            if future:
                issues.append(Issue(
                    f"tv_future_{aid}", "warning", "Episodes ticked that haven't aired",
                    f"{title} has {future} episode(s) marked watched that air in the future. "
                    "Fix un-marks them.", aid, title, f"Un-mark {future} episode(s)",
                    lambda a=aid: self._exec(
                        "UPDATE tv_episodes SET watched=0, watched_at=NULL WHERE anime_id=? "
                        "AND air_date > ?", (a, datetime.now().strftime("%Y-%m-%d"))),
                    area="TV shows"))
            left = conn.execute(
                "SELECT COUNT(*) FROM tv_episodes WHERE anime_id=? AND watched=0 AND season_number>0 "
                "AND air_date IS NOT NULL AND air_date <= ?", (aid, today)).fetchone()[0]
            seen = conn.execute("SELECT COUNT(*) FROM tv_episodes WHERE anime_id=? AND watched=1",
                                (aid,)).fetchone()[0]
            if ws == "completed" and left:
                issues.append(Issue(
                    f"tv_incomplete_{aid}", "warning", "Completed, but episodes are unwatched",
                    f"{title} is Completed but {left} aired episode(s) aren't marked. "
                    "Fix marks every aired episode watched.", aid, title,
                    f"Mark {left} episode(s) watched",
                    lambda a=aid: self._fix_tv_all_aired(a), checked=False, area="TV shows"))
            if ws == "planned" and seen:
                issues.append(Issue(
                    f"tv_planned_progress_{aid}", "info", "On your Watchlist, but you've started it",
                    f"{title} has {seen} episode(s) watched but sits on the Watchlist. "
                    "Fix moves it to Watching.", aid, title, "Move to Watching",
                    lambda a=aid: self._fix_status(a, "watching"), area="TV shows"))
        self._dupes_tmdb(conn, issues, "tv", "TV shows")

    # ── whole library ─────────────────────────────────────────────────────────

    def _check_library(self, conn, issues):
        orphans = conn.execute(
            "SELECT (SELECT COUNT(*) FROM episodes WHERE anime_id NOT IN (SELECT id FROM anime))"
            " + (SELECT COUNT(*) FROM tv_episodes WHERE anime_id NOT IN (SELECT id FROM anime))"
            " + (SELECT COUNT(*) FROM tv_seasons WHERE anime_id NOT IN (SELECT id FROM anime))"
        ).fetchone()[0]
        if orphans:
            issues.append(Issue(
                "orphan_eps", "info", "Leftover records from deleted titles",
                f"{orphans} episode/season record(s) belong to titles that no longer exist. "
                "Harmless, but they take space. Fix deletes them.",
                None, "Library", f"Delete {orphans} leftover record(s)", self._fix_orphans,
                area="Library"))

        dead = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE state='active' AND anime_id IS NOT NULL "
            "AND anime_id > 0 AND anime_id NOT IN (SELECT id FROM anime)").fetchone()[0]
        if dead:
            issues.append(Issue(
                "orphan_alerts", "info", "Alerts for titles you deleted",
                f"{dead} alert(s) point at titles no longer in your library. Fix withdraws them.",
                None, "Alerts", f"Withdraw {dead} alert(s)",
                lambda: self._exec(
                    "UPDATE notifications SET state='dismissed' WHERE state='active' AND "
                    "anime_id IS NOT NULL AND anime_id > 0 AND anime_id NOT IN (SELECT id FROM anime)"),
                area="Library"))

        for row in conn.execute("SELECT id, romaji_title, english_title, genres, studios FROM anime").fetchall():
            for column in ("genres", "studios"):
                raw = row[column]
                if raw in (None, ""):
                    continue
                try:
                    if not isinstance(json.loads(raw), list):
                        raise ValueError
                except Exception:
                    issues.append(Issue(
                        f"bad_json_{column}_{row['id']}", "warning", f"Damaged {column} data",
                        f"{_name(row)} has unreadable {column} data, which can upset filters. "
                        "Fix resets it (it refills on the next sync).",
                        row["id"], _name(row), f"Reset {column}",
                        lambda a=row["id"], c=column: self._exec(
                            f"UPDATE anime SET {c}='[]' WHERE id=?", (a,)), area="Library"))

        for row in conn.execute(
                "SELECT id, romaji_title, english_title, cover_local FROM anime "
                "WHERE cover_local IS NOT NULL AND TRIM(cover_local) != ''").fetchall():
            if not Path(row["cover_local"]).exists():
                issues.append(Issue(
                    f"missing_cover_{row['id']}", "info", "Cached cover image is missing",
                    f"{_name(row)} points to a cover file that's gone. Fix clears it so the "
                    "cover downloads again.", row["id"], _name(row), "Re-download cover",
                    lambda a=row["id"]: self._exec("UPDATE anime SET cover_local=NULL WHERE id=?", (a,)),
                    area="Library"))

        try:
            groups = conn.execute(
                """SELECT COUNT(*) FROM (SELECT 1 FROM watch_log
                   GROUP BY anime_id, episode_num, watched_at HAVING COUNT(*) > 1)""").fetchone()[0]
        except Exception:
            groups = 0
        if groups:
            issues.append(Issue(
                "duplicate_watch_log", "info", "Duplicate activity records",
                f"{groups} watch activity record(s) are duplicated. Fix keeps one of each.",
                None, "Watch history", "Remove duplicates",
                lambda: self._exec("DELETE FROM watch_log WHERE id NOT IN (SELECT MIN(id) FROM "
                                   "watch_log GROUP BY anime_id, episode_num, watched_at)"),
                area="Library"))

    def _check_errors(self, issues):
        from core.app_settings import app_settings
        try:
            seen = float(app_settings().value("errors_reviewed_at", 0) or 0)
        except Exception:
            seen = 0
        errs = recent_errors(seen)
        if not errs:
            return
        last = errs[-1]
        where = next((l.strip() for l in reversed(last.splitlines()) if l.strip().startswith("File ")), "")
        what = last.strip().splitlines()[-1][:160]
        issues.append(Issue(
            "app_errors", "warning",
            f"Raikō hit {len(errs)} unexpected error{'s' if len(errs) != 1 else ''}",
            f"The app caught and logged {len(errs)} error(s) instead of closing. Latest: {what}"
            + (f" ({where[:120]})" if where else "")
            + ". Your data is fine. Share ~/.animetracker/error.log if it keeps happening. "
              "Fix marks these as reviewed.",
            None, "App", "Mark as reviewed", self._fix_errors_reviewed, area="App"))

    # ── fixes ─────────────────────────────────────────────────────────────────

    def _exec(self, sql: str, args=()):
        conn = self.db._get_conn()
        conn.execute(sql, args)
        conn.commit()

    def _fix_reindex(self):
        conn = self.db._get_conn()
        conn.execute("REINDEX")
        conn.commit()

    def _fix_overcount(self, anime_id: int, max_ep: int):
        self._exec("UPDATE episodes SET watched=0, watched_at=NULL "
                   "WHERE anime_id=? AND episode_num > ? AND watched=1", (anime_id, max_ep))

    def _fix_mark_all(self, anime_id: int, total: int):
        for ep in range(1, total + 1):
            self.db.set_episode_watched(anime_id, ep, True)

    def _fix_status(self, anime_id: int, new_status: str):
        self.db.update_anime(anime_id, {"watch_status": new_status})

    def _delete_titles(self, ids: List[int]):
        conn = self.db._get_conn()
        for rid in ids:
            conn.execute("DELETE FROM anime WHERE id=?", (rid,))
        conn.commit()

    def _fix_stray_ratings(self):
        self._exec("""DELETE FROM ratings WHERE episode_num > 0 AND id IN (
            SELECT r.id FROM ratings r LEFT JOIN episodes e
            ON e.anime_id = r.anime_id AND e.episode_num = r.episode_num
            JOIN anime a ON a.id = r.anime_id AND COALESCE(a.media_type,'anime')='anime'
            WHERE r.episode_num > 0 AND COALESCE(e.watched,0) = 0)""")

    def _fix_orphans(self):
        for t in ("episodes", "tv_episodes", "tv_seasons"):
            self._exec(f"DELETE FROM {t} WHERE anime_id NOT IN (SELECT id FROM anime)")

    def _fix_tv_resync(self, anime_id: int, tmdb_id: int):
        from core.kinema_sync import fetch_tv_full
        row, eps = fetch_tv_full(tmdb_id)
        if not row:
            raise RuntimeError("Couldn't reach TMDB")
        self.db.save_tv_seasons(anime_id, row.get("_seasons") or [])
        self.db.save_tv_episodes(anime_id, eps)

    def _fix_tv_all_aired(self, anime_id: int):
        eps = self.db.get_tv_episodes(anime_id)
        today = datetime.now().strftime("%Y-%m-%d")
        last = max(((e["season_number"], e["episode_number"]) for e in eps
                    if e.get("air_date") and e["air_date"] <= today), default=None)
        if last:
            self.db.set_tv_watched_through(anime_id, *last)

    def _fix_errors_reviewed(self):
        from core.app_settings import app_settings
        app_settings().setValue("errors_reviewed_at", time())


def attention_needed(issues: List[Issue]) -> List[Issue]:
    """Issues worth an alert: errors and warnings, not housekeeping."""
    return [i for i in issues if i.severity in ("error", "warning")]
