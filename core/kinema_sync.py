"""
Kinema - keep TV shows & movies fresh from TMDB and raise alerts.

Movies on your Watchlist alert when:
  - they open in theaters (cinema release day, your country),
  - they become streamable (digital release + a streaming service has it),
  - their release date is set or moves,
  - a new trailer appears.
The first sync of a title is a silent baseline; fingerprints stop repeats.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List, Optional

from core.database import DatabaseManager

MOVIE_ALERT_KINDS = ["movie_theaters", "movie_streaming", "upcoming_date", "upcoming_trailer"]


def _norm(v):
    return v if v not in ("", None, [], {}) else None


def _day_ts(date_str: Optional[str]) -> Optional[int]:
    try:
        return int(datetime.strptime((date_str or "")[:10], "%Y-%m-%d").timestamp())
    except ValueError:
        return None


def _label(ts: int) -> str:
    d = datetime.fromtimestamp(ts)
    return d.strftime("%b ") + f"{d.day}, {d.year}"


class KinemaSync:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def sync_movies(self, only_ids: Optional[List[int]] = None) -> Dict:
        from core import tmdb
        from core.providers import movie_row

        movies = self.db.get_all_anime(media_type="movie")
        if only_ids is not None:
            movies = [m for m in movies if m["id"] in only_ids]
        movies = [m for m in movies if m.get("tmdb_id")]
        result = {"changed": [], "art_changed": [], "notifications": []}
        if not movies:
            return result

        with ThreadPoolExecutor(max_workers=6) as pool:
            details = list(pool.map(lambda m: tmdb.movie_details(m["tmdb_id"]), movies))

        now = int(datetime.now().timestamp())
        cols = self.db._anime_columns()
        for old, d in zip(movies, details):
            if not d:
                continue                      # offline / not found: keep what we have
            new = movie_row(d)
            stored = {k: v for k, v in new.items() if not k.startswith("_") and k in cols}
            updates = {k: v for k, v in stored.items()
                       if _norm(v) != _norm(old.get(k)) and _norm(v) is not None}
            first_sync = not old.get("meta_synced_at")
            if "cover_url" in updates:
                updates["cover_local"] = ""
                result["art_changed"].append(old["id"])
            elif "banner_url" in updates:
                result["art_changed"].append(old["id"])
            if updates:
                result["changed"].append(old["id"])
            self.db.update_anime(old["id"], {**updates, "meta_synced_at": now})
            if old.get("watch_status") == "planned":
                self._movie_alerts(old, new, d, updates, first_sync, now)

        result["notifications"] = self.db.get_due_notifications(limit=6, kinds=MOVIE_ALERT_KINDS)
        return result

    def _movie_alerts(self, old: Dict, new: Dict, details: Dict, updates: Dict,
                      first_sync: bool, now: int):
        from core import tmdb
        title = new.get("romaji_title") or old.get("romaji_title") or "Movie"
        tid = old.get("tmdb_id")
        base = {"anime_id": old["id"], "anilist_id": None}
        rel = new.get("_release_dates") or {}
        today = datetime.now().strftime("%Y-%m-%d")

        # In theaters: on (or within 3 days after) the cinema release day
        cinema = rel.get("theatrical") or rel.get("theatrical_limited")
        cinema_ts = _day_ts(cinema)
        if cinema_ts and 0 <= now - cinema_ts < 3 * 86400:
            self.db.upsert_notification({
                **base, "fingerprint": f"movie-theaters:{tid}:{cinema}",
                "kind": "movie_theaters", "title": "Out in theaters",
                "message": f"{title} is in theaters now.",
                "payload": {"tmdb_id": tid, "date": cinema}})

        # Now streaming: digital release has happened and a service carries it
        digital_ts = _day_ts(rel.get("digital"))
        services = tmdb.watch_providers(details).get("stream") or []
        if services and (not digital_ts or digital_ts <= now) and (
                not cinema_ts or cinema_ts <= now):
            names = ", ".join(services[:2])
            self.db.upsert_notification({
                **base, "fingerprint": f"movie-streaming:{tid}",
                "kind": "movie_streaming", "title": "Now streaming",
                "message": f"{title} is streaming on {names}.",
                "payload": {"tmdb_id": tid, "services": services[:4]}})

        if first_sync:
            return                              # quiet baseline for the rest

        # Release date set / moved (only future dates are news)
        if ("start_ts" in updates or "start_exact" in updates) and new.get("start_ts") \
                and new["start_ts"] > now and new.get("start_exact"):
            self.db.upsert_notification({
                **base, "fingerprint": f"movie-date:{tid}:{new['start_ts']}",
                "kind": "upcoming_date", "title": "Release date set",
                "message": f"{title} releases {_label(new['start_ts'])}.",
                "payload": {"start_ts": new["start_ts"]}})

        # New trailer
        if "trailer_id" in updates and new.get("trailer_id"):
            self.db.upsert_notification({
                **base, "fingerprint": f"upcoming-trailer:movie-{tid}:{new['trailer_id']}",
                "kind": "upcoming_trailer", "title": "New trailer is out",
                "message": f"{title} has a new trailer. Watch it right here.",
                "payload": {"trailer_id": new["trailer_id"], "trailer_site": "youtube",
                            "anime_title": title}})
