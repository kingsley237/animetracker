"""
Miroku - notification detection.

Creates persistent notification records from local library state. Network-backed
metadata and sequel checks can build on this same table later.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional

from core.database import DatabaseManager

NEW_SEASON_KIND = "new_season"

# A sequel that has already finished airing is only "news" if it ended
# recently, or if the user only just finished (or dropped) the prequel -
# otherwise the first scan would dump years of backlog on them at once.
_COMPLETE_SEQUEL_RECENT_DAYS = 60
_PREQUEL_RECENT_DAYS = 45


def _date_ts(d: Optional[Dict]) -> int:
    """AniList fuzzy date -> unix ts (0 when unknown)."""
    if not d or not d.get("year"):
        return 0
    try:
        return int(datetime(d["year"], d.get("month") or 1, d.get("day") or 1).timestamp())
    except Exception:
        return 0


def fuzzy_date_label(d: Optional[Dict]) -> str:
    """'Jan 9, 2027' / 'Jan 2027' / '2027' depending on what AniList knows."""
    if not d or not d.get("year"):
        return ""
    y, m, day = d.get("year"), d.get("month"), d.get("day")
    if m and day:
        return datetime(y, m, day).strftime("%b ") + f"{day}, {y}"
    if m:
        return datetime(y, m, 1).strftime("%b %Y")
    return str(y)


def sequel_phase(status: str) -> Optional[str]:
    return {
        "NOT_YET_RELEASED": "announced",
        "RELEASING": "airing",
        "FINISHED": "complete",
    }.get((status or "").upper())


def _clean_synopsis(text: str, limit: int = 420) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"\(Source:[^)]*\)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def build_new_season_payload(sequel: Dict, prequel: Dict) -> Dict:
    """Snapshot everything the spotlight needs so it renders with no fetch."""
    title = sequel.get("title") or {}
    cover = sequel.get("coverImage") or {}
    trailer = sequel.get("trailer") or {}
    nae = sequel.get("nextAiringEpisode") or {}
    studios = (sequel.get("studios") or {}).get("nodes") or []
    return {
        "phase": sequel_phase(sequel.get("status")),
        "sequel": {
            "id": sequel.get("id"),
            "title": title.get("english") or title.get("romaji") or "New season",
            "romaji": title.get("romaji") or "",
            "format": sequel.get("format") or "",
            "status": sequel.get("status") or "",
            "episodes": sequel.get("episodes"),
            "season": sequel.get("season") or "",
            "season_year": sequel.get("seasonYear"),
            "start_ts": _date_ts(sequel.get("startDate")),
            "start_exact": bool((sequel.get("startDate") or {}).get("day")),
            "start_label": fuzzy_date_label(sequel.get("startDate")),
            "next_airing_at": nae.get("airingAt"),
            "next_episode": nae.get("episode"),
            "cover_url": cover.get("large") or cover.get("medium") or "",
            "cover_color": cover.get("color") or "",
            "banner_url": sequel.get("bannerImage") or "",
            "trailer_id": trailer.get("id") or "",
            "trailer_site": (trailer.get("site") or "").lower(),
            "score": sequel.get("averageScore"),
            "genres": (sequel.get("genres") or [])[:3],
            "studios": [n.get("name") for n in studios if n.get("name")][:2],
            "synopsis": _clean_synopsis(sequel.get("description") or ""),
        },
        "prequel": prequel,
    }


def new_season_copy(payload: Dict) -> tuple:
    """(title, message) for plain-text surfaces and the DB record."""
    phase = payload.get("phase")
    seq = payload.get("sequel") or {}
    pre = payload.get("prequel") or {}
    name, pname = seq.get("title", "A new season"), pre.get("title", "an anime")
    if phase == "announced":
        when = ""
        if seq.get("start_label"):
            when = " - premieres " + seq["start_label"]
        elif seq.get("season") and seq.get("season_year"):
            when = f" - {seq['season'].title()} {seq['season_year']}"
        title, msg = "New season announced", f"{name} was announced{when}."
    elif phase == "airing":
        title, msg = "New season is airing", f"{name} is airing now."
    else:
        eps = seq.get("episodes")
        title = "New season available"
        if seq.get("format") == "MOVIE":
            msg = f"{name} is out now."
        else:
            msg = f"{name} is fully out" + (f" - all {eps} episodes." if eps else ".")
    if pre.get("source") == "dropped":
        at = pre.get("last_episode")
        msg += f" You dropped {pname}" + (f" at ep {at}" if at else "") + " - maybe give it another shot?"
    else:
        msg += f" Sequel to {pname}, which you completed."
    return title, msg


class NotificationService:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def scan(self) -> List[Dict]:
        self._scan_finished_watching()
        self._scan_aired_episodes()
        self._scan_planned_status_changes()
        self._scan_upcoming_metadata()
        self._scan_incomplete_completions()
        return self.db.get_due_notifications(limit=4, exclude_kinds=[NEW_SEASON_KIND])

    # ── Sequels (network) ─────────────────────────────────────────────────────

    def scan_sequels(self, include_dropped: bool = True) -> List[Dict]:
        """Check AniList relations of completed (and optionally dropped) anime
        for sequels the user doesn't have yet. One alert per sequel per phase
        (announced -> airing -> complete), so the moment an announced season
        starts airing the user hears about it again. Returns the due
        new-season notifications for the spotlight."""
        from core.api import get_sequels

        now = int(datetime.now().timestamp())
        prequels: Dict[int, Dict] = {}
        for anime in self.db.get_all_anime(watch_status="completed"):
            aid = anime.get("anilist_id")
            if not aid:
                continue
            prequels[int(aid)] = {
                "source": "completed",
                "anime_id": anime["id"],
                "anilist_id": int(aid),
                "title": anime.get("english_title") or anime.get("romaji_title") or "Anime",
                "rating": self.db.get_overall_rating(anime["id"]),
                "recent_ts": int(anime.get("last_watched_at") or anime.get("last_updated") or 0),
            }
        dropped_ids = set()
        for d in self.db.get_dropped_anime():
            aid = d.get("anilist_id")
            if not aid:
                continue
            dropped_ids.add(int(aid))
            if include_dropped and int(aid) not in prequels:
                prequels[int(aid)] = {
                    "source": "dropped",
                    "anime_id": None,
                    "anilist_id": int(aid),
                    "title": d.get("english_title") or d.get("romaji_title") or "Anime",
                    "rating": None,
                    "last_episode": d.get("last_episode"),
                    "recent_ts": int(d.get("dropped_at") or 0),
                }
        if not prequels:
            return []

        for pre_id, sequels in get_sequels(list(prequels.keys())).items():
            prequel = prequels[pre_id]
            for sequel in sequels:
                sid = sequel.get("id")
                phase = sequel_phase(sequel.get("status"))
                if not sid or not phase:
                    continue
                if sid in dropped_ids or sid in prequels:
                    continue   # already dropped / already completed it
                if self.db.get_anime_by_anilist_id(sid):
                    self._retire_new_season(sid)   # they already added it
                    continue
                if phase == "complete":
                    ended = _date_ts(sequel.get("endDate"))
                    recent_end = bool(ended) and now - ended < _COMPLETE_SEQUEL_RECENT_DAYS * 86400
                    pre_ts = prequel.get("recent_ts") or 0
                    recent_pre = bool(pre_ts) and now - pre_ts < _PREQUEL_RECENT_DAYS * 86400
                    if not (recent_end or recent_pre):
                        continue
                payload = build_new_season_payload(sequel, prequel)
                title, message = new_season_copy(payload)
                self.db.upsert_notification({
                    "fingerprint": f"new-season:{sid}:{phase}",
                    "kind": NEW_SEASON_KIND,
                    "anime_id": prequel.get("anime_id"),
                    "anilist_id": sid,
                    "title": title,
                    "message": message,
                    "payload": payload,
                })
                # An earlier phase's alert for the same sequel is now stale.
                self._retire_new_season(sid, keep_phase=phase)
        return self.db.get_due_notifications(limit=10, kinds=[NEW_SEASON_KIND])

    def _retire_new_season(self, sequel_id: int, keep_phase: Optional[str] = None):
        for n in self.db.get_active_notifications(NEW_SEASON_KIND):
            if n.get("anilist_id") != sequel_id:
                continue
            if keep_phase and (n.get("payload") or {}).get("phase") == keep_phase:
                continue
            self.db.dismiss_notification(n["id"])

    def _scan_finished_watching(self):
        """A show the user is Watching has stopped airing.

        - If they never started it (0 episodes watched), "Completed" would be
          a lie — move it back to Plan to Watch instead.
        - Otherwise move it to Completed. If they're behind on episodes it'll
          show up flagged in the Completed list (see _scan_incomplete_completions)
          rather than lingering in Watching forever.
        """
        for anime in self.db.get_all_anime(watch_status="watching"):
            api_status = (anime.get("status") or "").upper()
            if api_status not in ("FINISHED", "CANCELLED"):
                continue
            title = anime.get("english_title") or anime.get("romaji_title") or "Anime"
            ident = anime.get("anilist_id") or anime["id"]
            watched = self.db.get_watched_count(anime["id"])

            if watched == 0:
                self.db.update_anime(anime["id"], {"watch_status": "planned"})
                self.db.upsert_notification({
                    "fingerprint": f"auto-planned:{ident}:{api_status}",
                    "kind": "auto_planned",
                    "anime_id": anime["id"],
                    "anilist_id": anime.get("anilist_id"),
                    "title": "Anime finished airing",
                    "message": (
                        f"{title} finished airing before you started it. "
                        "Moved to Plan to Watch."
                    ),
                    "payload": {"status": api_status},
                })
            else:
                self.db.update_anime(anime["id"], {"watch_status": "completed"})
                self.db.upsert_notification({
                    "fingerprint": f"auto-completed:{ident}:{api_status}",
                    "kind": "auto_completed",
                    "anime_id": anime["id"],
                    "anilist_id": anime.get("anilist_id"),
                    "title": "Anime finished airing",
                    "message": f"{title} has finished airing and was moved to Completed.",
                    "payload": {"status": api_status},
                })

    def _scan_incomplete_completions(self):
        """Nag periodically about shows marked Completed with unwatched
        episodes still sitting there — "Completed" should mean actually
        finished. Fingerprint is day-bucketed so the reminder resurfaces
        daily even if the user dismisses today's, but stops entirely once
        they catch up (or drop/move the show)."""
        today = datetime.now().strftime("%Y-%m-%d")
        for anime in self.db.get_all_anime(watch_status="completed"):
            total = anime.get("total_episodes") or 0
            if not total:
                continue
            watched = self.db.get_watched_count(anime["id"])
            if watched >= total:
                continue
            title = anime.get("english_title") or anime.get("romaji_title") or "Anime"
            ident = anime.get("anilist_id") or anime["id"]
            remaining = total - watched
            self.db.upsert_notification({
                "fingerprint": f"incomplete-completion:{ident}:{today}",
                "kind": "incomplete_completion",
                "anime_id": anime["id"],
                "anilist_id": anime.get("anilist_id"),
                "title": "Unfinished in Completed",
                "message": (
                    f"{title} is marked Completed but has {remaining} "
                    f"episode(s) left unwatched ({watched}/{total})."
                ),
                "payload": {"remaining": remaining, "watched": watched, "total": total},
            })

    def _scan_aired_episodes(self):
        now = int(datetime.now().timestamp())
        for anime in self.db.get_all_anime(watch_status="watching"):
            next_at = int(anime.get("next_episode_at") or 0)
            next_ep = int(anime.get("next_episode_num") or 0)
            if not next_at or next_at > now or next_ep <= 1:
                continue
            episode_to_mark = next_ep - 1
            watched = self.db.get_watched_count(anime["id"])
            if watched >= episode_to_mark:
                continue
            title = anime.get("english_title") or anime.get("romaji_title") or "Anime"
            self.db.upsert_notification({
                "fingerprint": f"episode-aired:{anime.get('anilist_id') or anime['id']}:{episode_to_mark}",
                "kind": "episode_aired",
                "anime_id": anime["id"],
                "anilist_id": anime.get("anilist_id"),
                "title": f"Episode {episode_to_mark} aired",
                "message": f"{title} has a newly aired episode ready to mark watched.",
                "payload": {"episode": episode_to_mark},
            })

    def _scan_planned_status_changes(self):
        now = int(datetime.now().timestamp())
        for anime in self.db.get_all_anime(watch_status="planned"):
            title = anime.get("english_title") or anime.get("romaji_title") or "Anime"
            api_status = (anime.get("status") or "").upper()
            next_at = int(anime.get("next_episode_at") or 0)
            ident = anime.get("anilist_id") or anime["id"]

            if api_status == "RELEASING" or (next_at and next_at <= now):
                self.db.upsert_notification({
                    "fingerprint": f"planned-started:{ident}",
                    "kind": "planned_started",
                    "anime_id": anime["id"],
                    "anilist_id": anime.get("anilist_id"),
                    "title": "Planned anime has started",
                    "message": f"{title} is now airing. Move it to Watching when you are ready.",
                    "payload": {},
                })
            elif api_status in ("FINISHED", "CANCELLED"):
                watched = self.db.get_watched_count(anime["id"])
                if watched > 0:
                    # They'd already started it before parking it in Planned -
                    # mirror _scan_finished_watching and move it to Completed
                    # instead of leaving it stuck showing stale airing info.
                    self.db.update_anime(anime["id"], {"watch_status": "completed"})
                    self.db.upsert_notification({
                        "fingerprint": f"auto-completed:{ident}:{api_status}",
                        "kind": "auto_completed",
                        "anime_id": anime["id"],
                        "anilist_id": anime.get("anilist_id"),
                        "title": "Anime finished airing",
                        "message": f"{title} has finished airing and was moved to Completed.",
                        "payload": {"status": api_status},
                    })
                else:
                    self.db.upsert_notification({
                        "fingerprint": f"planned-ended:{ident}:{api_status}",
                        "kind": "planned_ended",
                        "anime_id": anime["id"],
                        "anilist_id": anime.get("anilist_id"),
                        "title": "Planned anime has ended",
                        "message": f"{title} is marked {api_status.title()}. Review whether it still belongs in Planned.",
                        "payload": {"status": api_status},
                    })

    def _scan_upcoming_metadata(self):
        for anime in self.db.get_all_anime(watch_status="planned"):
            api_status = (anime.get("status") or "").upper()
            if api_status != "NOT_YET_RELEASED":
                continue
            title = anime.get("english_title") or anime.get("romaji_title") or "Anime"
            ident = anime.get("anilist_id") or anime["id"]
            next_at = int(anime.get("next_episode_at") or 0)
            trailer_id = anime.get("trailer_id") or ""

            if next_at:
                air_date = datetime.fromtimestamp(next_at).strftime("%b %d, %Y")
                self.db.upsert_notification({
                    "fingerprint": f"upcoming-date:{ident}:{next_at}",
                    "kind": "upcoming_date",
                    "anime_id": anime["id"],
                    "anilist_id": anime.get("anilist_id"),
                    "title": "Release date available",
                    "message": f"{title} now has a scheduled premiere date: {air_date}.",
                    "payload": {"airing_at": next_at},
                })

            if trailer_id:
                self.db.upsert_notification({
                    "fingerprint": f"upcoming-trailer:{ident}:{trailer_id}",
                    "kind": "upcoming_trailer",
                    "anime_id": anime["id"],
                    "anilist_id": anime.get("anilist_id"),
                    "title": "New trailer available",
                    "message": f"{title} has trailer information available.",
                    "payload": {"trailer_id": trailer_id},
                })
