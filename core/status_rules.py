"""
Raikō - which library status moves make sense, and what they do.

One set of rules for the status switcher in every detail panel:

  movie   Watchlist · Watched
          Watched only once it's out (in cinemas or digitally).
  tv      Watchlist · Watching · Finished · Dropped
          Watching / Finished / Dropped only once it has premiered.
          Finished works for running shows too (= caught up): it marks the
          remaining aired episodes watched, and new episodes bring the show
          back to Watching by themselves.
  anime   Plan to watch · Watching · Completed · Dropped
          Watching / Dropped only once it has aired; Completed only when the
          anime has finished airing (each AniList entry is one season).
          Completing marks every episode watched.

options(db, row) -> [{key, label, allowed, reason, current}]
plan(db, row, key) -> {"allowed", "reason", "confirm"}     (confirm: text or None)
apply(db, row, key) -> message for a toast  (anime 'dropped' is handled by the
                       panel, which moves the title to the Dropped list)
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List

LABELS = {
    "movie": {"planned": "Watchlist", "completed": "Watched"},
    "tv": {"planned": "Watchlist", "watching": "Watching", "completed": "Finished", "dropped": "Dropped"},
    "anime": {"planned": "Plan to watch", "watching": "Watching", "completed": "Completed", "dropped": "Dropped"},
}


def _media(row: Dict) -> str:
    return row.get("media_type") or "anime"


def _date(s) -> str:
    try:
        d = datetime.strptime(str(s)[:10], "%Y-%m-%d")
        return d.strftime("%b ") + str(d.day) + d.strftime(", %Y")
    except (TypeError, ValueError):
        return ""


def _name(row: Dict) -> str:
    return row.get("english_title") or row.get("romaji_title") or "This title"


def _anime_facts(db, row: Dict) -> Dict:
    api = (row.get("status") or "").upper()
    total = int(row.get("total_episodes") or 0)
    nxt = row.get("next_episode_num")
    if api in ("FINISHED", "CANCELLED"):
        aired = total or len(db.get_episodes(row["id"]))
    elif api == "NOT_YET_RELEASED":
        aired = 0
    else:
        aired = max(0, int(nxt) - 1) if nxt else (total if api == "" and total else 0)
        if api in ("RELEASING", "HIATUS") and not nxt and not aired:
            aired = len(db.get_episodes(row["id"]))
    watched = db.get_watched_count(row["id"]) if row.get("id", 0) > 0 else 0
    return {"api": api, "total": total, "aired": aired, "watched": watched}


def _premiere(row: Dict) -> str:
    d = _date(row.get("start_date") or row.get("first_air_date") or row.get("cinema_date"))
    return f" (premieres {d})" if d else ""


def plan(db, row: Dict, key: str) -> Dict:
    media = _media(row)
    cur = row.get("watch_status")
    no = lambda why: {"allowed": False, "reason": why, "confirm": None}  # noqa: E731
    ok = lambda confirm=None, why="": {"allowed": True, "reason": why, "confirm": confirm}  # noqa: E731
    if key not in LABELS[media]:
        return no("Not available for this kind of title.")
    if key == cur:
        return ok(why="Current status")

    if media == "movie":
        if key == "completed":
            from core.kinema_sync import release_state
            if release_state(row)["state"] == "unreleased":
                d = _date(row.get("cinema_date") or row.get("digital_date"))
                return no(f"Not out yet{' — releases ' + d if d else ''}. You can mark it watched once it's out.")
        return ok()

    if media == "tv":
        p = db.tv_progress(row["id"])
        if key == "planned":
            return ok(f"You've watched {p['watched']} episode(s) — they'll be kept." if p["watched"] else None)
        if not p["aired"]:
            return no("Hasn't premiered yet" + _premiere(row) + ".")
        if key == "completed":
            left = p["unwatched_aired"]
            running = (row.get("status") or "") in ("RELEASING", "HIATUS", "NOT_YET_RELEASED")
            note = " New episodes will bring it back to Watching." if running else ""
            if left:
                return ok(f"This marks the {left} remaining aired episode{'s' if left != 1 else ''} as watched.{note}")
            return ok(why=("You're caught up." + note) if running else "")
        return ok()

    # anime
    f = _anime_facts(db, row)
    if key == "planned":
        return ok(f"You've watched {f['watched']} episode(s) — they'll be kept." if f["watched"] else None)
    if f["api"] == "NOT_YET_RELEASED":
        if key == "dropped":
            return no("Hasn't aired yet — nothing to drop. Use Delete to remove it.")
        return no("Hasn't aired yet" + _premiere(row) + ".")
    if key == "completed":
        if f["api"] not in ("FINISHED", "CANCELLED"):
            of = f" of {f['total']}" if f["total"] else ""
            return no(f"Still airing (episode {f['aired']}{of} is out) — it can be completed once the last "
                      "episode has aired.")
        left = max(0, (f["total"] or f["aired"]) - f["watched"])
        return ok(f"This marks all {f['total'] or f['aired']} episodes as watched." if left else None)
    if key == "dropped":
        return ok(f"'{_name(row)}' moves to your Dropped list (you can restore it later).")
    return ok()


def options(db, row: Dict) -> List[Dict]:
    media = _media(row)
    out = []
    for key, label in LABELS[media].items():
        p = plan(db, row, key)
        out.append({"key": key, "label": label, "allowed": p["allowed"], "reason": p["reason"],
                    "current": row.get("watch_status") == key})
    return out


def apply(db, row: Dict, key: str) -> str:
    """Do the move (after any confirmation). Returns the toast message."""
    media = _media(row)
    lid = row["id"]
    name = _name(row)
    label = LABELS[media][key]
    upd: Dict = {"watch_status": key}
    if key != "completed":
        upd["completed_at"] = None
    else:
        upd["completed_at"] = int(time.time())
    if media == "tv" and key == "completed":
        today = time.strftime("%Y-%m-%d")
        aired = [(e["season_number"], e["episode_number"]) for e in db.get_tv_episodes(lid)
                 if e["season_number"] > 0 and e.get("air_date") and e["air_date"] <= today]
        unwatched = [e for e in db.get_tv_episodes(lid) if e["season_number"] > 0 and e.get("air_date")
                     and e["air_date"] <= today and not e.get("watched")]
        if aired and unwatched:
            db.set_tv_watched_through(lid, *max(aired))
    if media == "anime" and key == "completed":
        total = int(row.get("total_episodes") or 0) or len(db.get_episodes(lid))
        for n in range(1, total + 1):
            db.set_episode_watched(lid, n, True)
    db.update_anime(lid, upd)
    if key == "completed":
        return f"'{name}' marked {label.lower()}. How was it?"
    return f"'{name}' moved to {label}."


def reopen_if_new_episodes(db, lib_id: int) -> bool:
    """A TV show marked Finished while still running goes back to Watching
    when new episodes air. Returns True when it moved."""
    row = db.get_anime_by_id(lib_id) or {}
    if _media(row) != "tv" or row.get("watch_status") != "completed":
        return False
    if (row.get("status") or "") not in ("RELEASING", "HIATUS"):
        return False
    if db.tv_progress(lib_id)["unwatched_aired"] > 0:
        db.update_anime(lib_id, {"watch_status": "watching", "completed_at": None})
        return True
    return False
