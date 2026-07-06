"""
Miroku - notification detection.

Creates persistent notification records from local library state. Network-backed
metadata and sequel checks can build on this same table later.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from core.database import DatabaseManager


class NotificationService:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def scan(self) -> List[Dict]:
        self._scan_finished_watching()
        self._scan_aired_episodes()
        self._scan_planned_status_changes()
        self._scan_upcoming_metadata()
        self._scan_incomplete_completions()
        return self.db.get_due_notifications(limit=4)

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
