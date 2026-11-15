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

MOVIE_ALERT_KINDS = ["movie_digital", "movie_theaters", "movie_digital_date",
                     "upcoming_date", "upcoming_trailer"]


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


def release_state(row: Dict, now: Optional[int] = None) -> Dict:
    """Where a movie is in its release, from the user's point of view
    (they watch in HD at home, so 'digital' is what matters):

      unreleased  not out anywhere yet           -> can't be marked watched
      cinema      in cinemas, not yet in HD      -> "Waiting for HD"
      digital     out digitally / rentable / streaming -> "Ready to watch"
    """
    now = now or int(datetime.now().timestamp())
    cinema = _day_ts(row.get("cinema_date"))
    digital = _day_ts(row.get("digital_date"))
    physical = _day_ts(row.get("physical_date"))
    out_digitally = bool(row.get("digital_available")) or bool(digital and digital <= now)
    released = (row.get("status") != "NOT_YET_RELEASED") or bool(cinema and cinema <= now) \
        or out_digitally
    state = "digital" if out_digitally else ("cinema" if released else "unreleased")
    return {"state": state, "cinema_ts": cinema, "digital_ts": digital, "physical_ts": physical}


def alert_mode() -> str:
    """'digital' (default) | 'cinema' | 'both' | 'off'"""
    try:
        from core.app_settings import app_settings
        v = str(app_settings().value("movie_alert_mode", "digital") or "digital")
    except Exception:
        v = "digital"
    return v if v in ("digital", "cinema", "both", "off") else "digital"


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
        """One alert per moment that matters, never repeated. The first
        sync of a title is a silent baseline: you just added it, you can see
        where it stands."""
        from core import tmdb
        if first_sync:
            return
        mode = alert_mode()
        if mode == "off":
            return
        title = new.get("romaji_title") or old.get("romaji_title") or "Movie"
        tid = old.get("tmdb_id")
        base = {"anime_id": old["id"], "anilist_id": None}
        before = release_state(old, now)["state"]
        after_row = {**old, **updates}
        st = release_state(after_row, now)

        # Out in HD (digital release reached, or it showed up to rent/buy/stream)
        if mode in ("digital", "both") and st["state"] == "digital" and before != "digital":
            w = tmdb.watch_providers(details)
            where = w.get("stream") or w.get("rent") or w.get("buy") or []
            how = ("streaming on " if w.get("stream") else "to rent or buy on ") + ", ".join(where[:2]) \
                if where else "digitally"
            self.db.upsert_notification({
                **base, "fingerprint": f"movie-digital:{tid}",
                "kind": "movie_digital", "title": "Out in HD",
                "message": f"{title} is out {how}.",
                "payload": {"tmdb_id": tid, "where": where[:4]}})

        # Heads-up: a digital release date was announced (future)
        if mode in ("digital", "both") and "digital_date" in updates and st["digital_ts"] \
                and st["digital_ts"] > now:
            self.db.upsert_notification({
                **base, "fingerprint": f"movie-digital-date:{tid}:{new.get('digital_date')}",
                "kind": "movie_digital_date", "title": "HD release date announced",
                "message": f"{title} comes out digitally {_label(st['digital_ts'])}.",
                "payload": {"tmdb_id": tid, "date": new.get("digital_date")}})

        # Cinema (only if wanted)
        if mode in ("cinema", "both"):
            c = st["cinema_ts"]
            if c and 0 <= now - c < 3 * 86400:
                self.db.upsert_notification({
                    **base, "fingerprint": f"movie-theaters:{tid}:{new.get('cinema_date')}",
                    "kind": "movie_theaters", "title": "Out in cinemas",
                    "message": f"{title} is in cinemas now.",
                    "payload": {"tmdb_id": tid}})
            if ("start_ts" in updates or "start_exact" in updates) and new.get("start_ts") \
                    and new["start_ts"] > now and new.get("start_exact"):
                self.db.upsert_notification({
                    **base, "fingerprint": f"movie-date:{tid}:{new['start_ts']}",
                    "kind": "upcoming_date", "title": "Cinema date set",
                    "message": f"{title} hits cinemas {_label(new['start_ts'])}.",
                    "payload": {"start_ts": new["start_ts"]}})

        # New trailer
        if "trailer_id" in updates and new.get("trailer_id"):
            self.db.upsert_notification({
                **base, "fingerprint": f"upcoming-trailer:movie-{tid}:{new['trailer_id']}",
                "kind": "upcoming_trailer", "title": "New trailer is out",
                "message": f"{title} has a new trailer. Watch it right here.",
                "payload": {"trailer_id": new["trailer_id"], "trailer_site": "youtube",
                            "anime_title": title}})
