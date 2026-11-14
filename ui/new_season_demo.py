"""
Miroku - sample data for `python main.py --demo-new-season`.

Builds three in-memory new-season notifications (one per phase) from real
AniList data so the artwork, trailers and Details dialog are genuine. Ids are
negative so every action is a no-op against the database. If AniList is
unreachable a static fallback is used (artwork then falls back to the
tinted placeholder).
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List, Optional

from core.notification_service import build_new_season_payload, new_season_copy


def _fake_sequel(title: str, status: str, color: str) -> Dict:
    return {
        "id": None, "title": {"english": title, "romaji": title}, "format": "TV",
        "status": status, "episodes": 12, "season": "WINTER", "seasonYear": 2027,
        "coverImage": {"color": color}, "description": "Sample synopsis - AniList was unreachable, "
        "so this demo card is using placeholder data. Artwork, trailer and details need a connection.",
    }


def _item(nid: int, sequel: Dict, prequel: Dict, phase_override: Optional[str] = None, **seq_overrides) -> Dict:
    payload = build_new_season_payload(sequel, prequel)
    if phase_override:
        payload["phase"] = phase_override
    payload["sequel"].update(seq_overrides)
    title, message = new_season_copy(payload)
    return {
        "id": nid, "kind": "new_season", "anime_id": prequel.get("anime_id"),
        "anilist_id": payload["sequel"].get("id"), "title": title,
        "message": message, "payload": payload,
    }


def _first_sequel(name: str):
    from core.api import get_anime_by_name, get_sequels
    media = get_anime_by_name(name)
    if not media:
        return None, None
    seqs = get_sequels([media["id"]]).get(media["id"]) or []
    return media, (seqs[0] if seqs else None)


def build_demo_items(completed: List[Dict]) -> List[Dict]:
    now = int(time.time())
    items: List[Dict] = []

    # A - announced, with an exact premiere date -> live countdown
    try:
        pre, seq = _first_sequel("Dr. STONE")
    except Exception:
        pre, seq = None, None
    if not seq:
        seq = _fake_sequel("Dr. STONE: STONE WARS", "NOT_YET_RELEASED", "#5ba14a")
    premiere = now + 3 * 86400 + 4 * 3600 + 17 * 60
    local = next((c for c in completed if pre and c.get("anilist_id") == pre.get("id")), None)
    items.append(_item(
        -1, {**seq, "status": "NOT_YET_RELEASED"},
        {"source": "completed", "anime_id": (local or {}).get("anime_id"),
         "title": (local or {}).get("title") or "Dr. STONE",
         "rating": (local or {}).get("rating") or 5},
        phase_override="announced",
        start_ts=premiere, start_exact=True,
        start_label=datetime.fromtimestamp(premiere).strftime("%b ") +
        f"{datetime.fromtimestamp(premiere).day}, {datetime.fromtimestamp(premiere).year}",
    ))

    # B - airing, sequel of something actually in the user's Completed list
    #     (so the "Sequel to ..." link and the card ribbon are testable)
    airing = None
    try:
        from core.api import get_sequels
        ids = [c["anilist_id"] for c in completed][:8]
        found = get_sequels(ids) if ids else {}
        for c in completed:
            seqs = found.get(c["anilist_id"]) or []
            if seqs:
                airing = (c, seqs[0])
                break
        if not airing:
            pre_b, seq_b = _first_sequel("Frieren: Beyond Journey's End")
            if seq_b:
                airing = ({"anime_id": None, "title": "Frieren: Beyond Journey's End", "rating": 6}, seq_b)
    except Exception:
        pass
    if not airing:
        airing = ({"anime_id": None, "title": "Your favourite show", "rating": 6},
                  _fake_sequel("Your Favourite Show Season 2", "RELEASING", "#e4a15d"))
    c, seq_b = airing
    items.append(_item(
        -2, {**seq_b, "status": "RELEASING"},
        {"source": "completed", "anime_id": c.get("anime_id"), "title": c.get("title"),
         "rating": c.get("rating")},
        phase_override="airing",
        next_airing_at=now + 5 * 3600 + 12 * 60, next_episode=2,
    ))

    # C - fully released sequel of a DROPPED show
    try:
        pre_c, seq_c = _first_sequel("Chainsaw Man")
    except Exception:
        pre_c, seq_c = None, None
    if not seq_c:
        seq_c = _fake_sequel("Chainsaw Man - The Movie: Reze Arc", "FINISHED", "#e45d5d")
    items.append(_item(
        -3, {**seq_c, "status": "FINISHED"},
        {"source": "dropped", "anime_id": None, "title": "Chainsaw Man", "last_episode": 5},
        phase_override="complete",
    ))
    return items
