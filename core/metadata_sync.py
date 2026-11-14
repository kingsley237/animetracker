"""
Miroku - metadata sync.

Keeps library entries in step with AniList: art, synopsis, trailer, dates,
episode count, format/source/studios and characters. Plan-to-Watch anime
also get "what's new" notifications when something the user is waiting for
appears (trailer, confirmed premiere date, episode count).

First sync of an entry is a silent baseline, so adding this feature (or
adding an anime) never dumps a pile of "new!" alerts that aren't new.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional

from core.database import DatabaseManager

SYNC_STATUSES = ("planned", "watching")


def _clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _date_parts(d: Optional[Dict]):
    d = d or {}
    return d.get("year"), d.get("month"), d.get("day")


def exact_start(d: Optional[Dict]) -> Optional[int]:
    y, m, day = _date_parts(d)
    if y and m and day:
        try:
            return int(datetime(y, m, day).timestamp())
        except ValueError:
            return None
    return None


def media_to_row(media: Dict) -> Dict:
    """AniList media -> anime-table columns (only keys we actually got)."""
    from core.api import format_air_date
    t = media.get("title") or {}
    cov = media.get("coverImage") or {}
    trailer = media.get("trailer") or {}
    nae = media.get("nextAiringEpisode") or {}
    sd = media.get("startDate") or {}
    chars = []
    for e in ((media.get("characters") or {}).get("edges") or [])[:8]:
        node = e.get("node") or {}
        name = (node.get("name") or {}).get("full")
        if name:
            chars.append({"name": name, "role": (e.get("role") or "").title(),
                          "image": (node.get("image") or {}).get("medium") or ""})
    row = {
        "romaji_title": t.get("romaji"),
        "english_title": t.get("english") or "",
        "native_title": t.get("native") or "",
        "status": media.get("status"),
        # Same size the rest of the app stores, so a sync never re-downloads
        # an unchanged poster just because of a different size variant.
        "cover_url": cov.get("large") or cov.get("extraLarge") or cov.get("medium") or "",
        "cover_color": cov.get("color") or "",
        "banner_url": media.get("bannerImage") or "",
        "description": _clean(media.get("description") or ""),
        "format": media.get("format") or "",
        "source": media.get("source") or "",
        "total_episodes": media.get("episodes"),
        "duration": media.get("duration"),
        "season": media.get("season") or "",
        "season_year": media.get("seasonYear") or sd.get("year"),
        "start_date": format_air_date(sd) if sd.get("year") else "",
        "start_ts": exact_start(sd),
        "start_exact": 1 if exact_start(sd) else 0,
        "next_episode_at": nae.get("airingAt"),
        "next_episode_num": nae.get("episode"),
        "trailer_id": trailer.get("id") or None,
        "trailer_site": (trailer.get("site") or "").lower() or None,
        "trailer_thumb": trailer.get("thumbnail") or None,
        "average_score": media.get("averageScore"),
        "popularity": media.get("popularity"),
        "genres": media.get("genres") or [],
        "studios": [n.get("name") for n in ((media.get("studios") or {}).get("nodes") or []) if n.get("name")],
        "characters": chars,
        "site_url": media.get("siteUrl") or "",
    }
    if not row["romaji_title"]:
        row.pop("romaji_title")
    return row


def _norm(v):
    return v if v not in ("", None, [], {}) else None


class MetadataSync:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def sync(self, statuses=SYNC_STATUSES, only_ids: Optional[List[int]] = None) -> Dict:
        """Returns {"changed": [anime_id...], "art_changed": [anime_id...],
        "notifications": [due planned-update notifications]}."""
        from core.api import get_metadata_batch

        anime = []
        for st in statuses:
            anime += self.db.get_all_anime(watch_status=st)
        if only_ids is not None:
            anime = [a for a in anime if a["id"] in only_ids]
        by_aid = {a["anilist_id"]: a for a in anime if a.get("anilist_id")}
        if not by_aid:
            return {"changed": [], "art_changed": [], "notifications": []}

        now = int(datetime.now().timestamp())
        changed, art_changed = [], []
        for aid, media in get_metadata_batch(list(by_aid)).items():
            old = by_aid[aid]
            new = media_to_row(media)
            updates = {k: v for k, v in new.items() if _norm(v) != _norm(old.get(k))}
            # Never wipe something we have just because AniList returned empty
            updates = {k: v for k, v in updates.items()
                       if _norm(v) is not None or k in ("next_episode_at", "next_episode_num")}
            first_sync = not old.get("meta_synced_at")
            if "cover_url" in updates:
                updates["cover_local"] = ""      # force the new poster to download
                art_changed.append(old["id"])
            elif "banner_url" in updates:
                art_changed.append(old["id"])
            if updates:
                changed.append(old["id"])
            self.db.update_anime(old["id"], {**updates, "meta_synced_at": now})
            if old.get("watch_status") == "planned":
                self._notify_planned(old, new, updates, first_sync)

        notes = self.db.get_due_notifications(
            limit=6, kinds=["upcoming_trailer", "upcoming_date", "upcoming_episodes"])
        return {"changed": changed, "art_changed": art_changed, "notifications": notes}

    def _notify_planned(self, old: Dict, new: Dict, updates: Dict, first_sync: bool):
        title = new.get("english_title") or new.get("romaji_title") or old.get("romaji_title") or "Anime"
        ident = old.get("anilist_id") or old["id"]
        base = {"anime_id": old["id"], "anilist_id": old.get("anilist_id")}

        # Trailer: notify when it's new to us (first sync included - a
        # trailer for something you're waiting on is always worth a look;
        # the fingerprint stops repeats).
        if new.get("trailer_id") and (first_sync or "trailer_id" in updates):
            self.db.upsert_notification({
                **base,
                "fingerprint": f"upcoming-trailer:{ident}:{new['trailer_id']}",
                "kind": "upcoming_trailer",
                "title": "New trailer is out" if not first_sync else "Trailer available",
                "message": f"{title} has a trailer. Watch it right here.",
                "payload": {"trailer_id": new["trailer_id"],
                            "trailer_site": new.get("trailer_site"),
                            "anime_title": title},
            })

        # Release date: only once AniList has an exact day.
        if new.get("start_exact") and new.get("start_ts") and not new.get("next_episode_at") and (
                first_sync or "start_ts" in updates or "start_exact" in updates):
            when = datetime.fromtimestamp(new["start_ts"])
            if when.timestamp() > datetime.now().timestamp() - 86400:
                label = when.strftime("%b ") + f"{when.day}, {when.year}"
                self.db.upsert_notification({
                    **base,
                    "fingerprint": f"upcoming-date-exact:{ident}:{new['start_ts']}",
                    "kind": "upcoming_date",
                    "title": "Release date confirmed",
                    "message": f"{title} premieres {label}.",
                    "payload": {"start_ts": new["start_ts"]},
                })

        # Episode count announced / changed (not on the silent baseline)
        if not first_sync and "total_episodes" in updates and new.get("total_episodes"):
            eps = new["total_episodes"]
            self.db.upsert_notification({
                **base,
                "fingerprint": f"upcoming-episodes:{ident}:{eps}",
                "kind": "upcoming_episodes",
                "title": "Episode count announced",
                "message": f"{title} will have {eps} episodes.",
                "payload": {"episodes": eps},
            })
