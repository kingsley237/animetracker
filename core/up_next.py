"""
Raikō - Up Next: what to watch now and what's coming, across anime (Miroku),
TV shows and movies (Kinema). Pure data; the Home page draws it.

continue_watching   titles in Watching with an aired, unwatched episode:
                    anime + TV, most recently active first; "new" when the
                    episode aired in the last 7 days
coming_up           next 14 days: anime / TV episodes and premieres of shows
                    you watch or plan to, Watchlist movies reaching cinemas
                    or HD (next 30 days)
ready_to_watch      Watchlist movies you can watch at home now
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

DAY = 86400


def _name(r: Dict) -> str:
    return r.get("english_title") or r.get("romaji_title") or "Untitled"


def _anime_counts(db, r: Dict):
    total = r.get("total_episodes") or 0
    nxt = r.get("next_episode_num")
    ended = (r.get("status") or "").upper() in ("FINISHED", "CANCELLED")
    aired = total if (total and (ended or not nxt)) else (nxt - 1 if nxt and nxt > 1 else 0)
    watched = {e["episode_num"] for e in db.get_episodes(r["id"]) if e.get("watched")}
    return total, aired, watched, ended


def continue_watching(db, now: Optional[float] = None) -> List[Dict]:
    now = now or datetime.now().timestamp()
    out: List[Dict] = []
    for r in db.get_all_anime(watch_status="watching"):
        total, aired, watched, ended = _anime_counts(db, r)
        n = next((k for k in range(1, aired + 1) if k not in watched), None)
        if not n:
            continue
        left = sum(1 for k in range(1, aired + 1) if k not in watched)
        offset = r.get("episode_offset") or 0
        # the newest aired episode came out about a week before the next one
        last_air = (r.get("next_episode_at") or 0) - 7 * DAY if not ended else 0
        out.append({
            "id": r["id"], "media": "anime", "title": _name(r), "row": r,
            "episode": n, "label": f"Episode {n + offset}",
            "sub": f"{left} to watch" + (f" · {len(watched)}/{total or aired}" if (total or aired) else ""),
            "new": bool(last_air and now - last_air < 7 * DAY and left <= 2),
            "active": r.get("last_watched_at") or r.get("date_added") or 0,
            "progress": len(watched) / (total or aired) if (total or aired) else 0,
        })
    for r in db.get_all_anime(watch_status="watching", media_type="tv"):
        p = db.tv_progress(r["id"])
        e = p["next"]
        if not e:
            continue
        today = datetime.now().strftime("%Y-%m-%d")
        week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        code = f"S{e['season_number']:02d}E{e['episode_number']:02d}"
        out.append({
            "id": r["id"], "media": "tv", "title": _name(r), "row": r,
            "season": e["season_number"], "episode": e["episode_number"],
            "label": code + (f" · {e['name']}" if e.get("name") and not e["name"].startswith("Episode ") else ""),
            "sub": f"{p['unwatched_aired']} to watch · {p['watched']}/{p['aired']}",
            "new": bool(e.get("air_date") and week <= e["air_date"] <= today),
            "active": r.get("last_watched_at") or r.get("date_added") or 0,
            "progress": p["watched"] / p["aired"] if p["aired"] else 0,
        })
    out.sort(key=lambda x: (not x["new"], -(x["active"] or 0)))
    return out


def coming_up(db, days: int = 14, now: Optional[float] = None) -> List[Dict]:
    now = now or datetime.now().timestamp()
    end = now + days * DAY
    out: List[Dict] = []
    for ws in ("watching", "planned"):
        for r in db.get_all_anime(watch_status=ws):
            at = r.get("next_episode_at")
            if at and now < at <= end and (r.get("status") or "").upper() not in ("FINISHED", "CANCELLED"):
                n = (r.get("next_episode_num") or 1) + (r.get("episode_offset") or 0)
                out.append({"id": r["id"], "media": "anime", "title": _name(r), "row": r, "when": at,
                            "label": "Premiere" if n == 1 else f"Episode {n}", "exact": True})
            elif ws == "planned" and r.get("start_exact") and r.get("start_ts") and now < r["start_ts"] <= end \
                    and not at:
                out.append({"id": r["id"], "media": "anime", "title": _name(r), "row": r,
                            "when": r["start_ts"], "label": "Premiere", "exact": False})
        for r in db.get_all_anime(watch_status=ws, media_type="tv"):
            up = db.tv_progress(r["id"])["upcoming"]
            if not up or not up.get("air_date"):
                continue
            ts = datetime.strptime(up["air_date"], "%Y-%m-%d").timestamp()
            if now - DAY < ts <= end:
                label = (f"Season {up['season_number']} premiere" if up["episode_number"] == 1
                         else f"S{up['season_number']:02d}E{up['episode_number']:02d}")
                out.append({"id": r["id"], "media": "tv", "title": _name(r), "row": r, "when": ts,
                            "label": label, "exact": False})
    from core.kinema_sync import release_state
    for r in db.get_all_anime(watch_status="planned", media_type="movie"):
        rs = release_state(r, int(now))
        if rs["digital_ts"] and now - DAY < rs["digital_ts"] <= now + 30 * DAY:
            out.append({"id": r["id"], "media": "movie", "title": _name(r), "row": r,
                        "when": rs["digital_ts"], "label": "Out in HD", "exact": False})
        elif rs["state"] == "unreleased" and rs["cinema_ts"] and now - DAY < rs["cinema_ts"] <= end:
            out.append({"id": r["id"], "media": "movie", "title": _name(r), "row": r,
                        "when": rs["cinema_ts"], "label": "In cinemas", "exact": False})
    out.sort(key=lambda x: x["when"])
    return out


def ready_to_watch(db) -> List[Dict]:
    from core.kinema_sync import release_state
    out = []
    for r in db.get_all_anime(watch_status="planned", media_type="movie", sort_by="top_rated"):
        if release_state(r)["state"] == "digital":
            out.append({"id": r["id"], "media": "movie", "title": _name(r), "row": r,
                        "label": f"★ {r['average_score'] / 10:.1f}" if r.get("average_score") else "Movie"})
    return out


def mark_next(db, item: Dict):
    """One-click 'watched' for a Continue watching item."""
    if item["media"] == "anime":
        db.set_episode_watched(item["id"], item["episode"], True)
    elif item["media"] == "tv":
        db.set_tv_episode_watched(item["id"], item["season"], item["episode"], True)


def summary(db) -> Dict[str, int]:
    cw = continue_watching(db)
    return {"to_watch": len(cw), "new": sum(1 for c in cw if c["new"]),
            "this_week": sum(1 for c in coming_up(db, days=7)),
            "ready": len(ready_to_watch(db))}
