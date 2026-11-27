"""
Raikō - personal milestones: celebrated once, briefly (a toast + a short
confetti burst), never a theme.

  episodes  100 · 250 · 500 · 1,000 · 2,500 · 5,000 · 10,000   (anime + TV)
  movies    10 · 25 · 50 · 100 · 250 · 500
  series    10 · 25 · 50 · 100 · 250                          (anime + TV finished)

Existing totals are recorded quietly the first time (no flood of old
milestones); only new ones are celebrated.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

STEPS = {
    "episodes": [100, 250, 500, 1000, 2500, 5000, 10000],
    "movies": [10, 25, 50, 100, 250, 500],
    "series": [10, 25, 50, 100, 250],
}
WORDS = {"episodes": "episodes watched", "movies": "movies watched", "series": "series finished"}


def counts(db) -> Dict[str, int]:
    c = db._get_conn()

    def one(sql: str) -> int:
        try:
            return int(c.execute(sql).fetchone()[0] or 0)
        except Exception:
            return 0
    return {
        "episodes": one("SELECT COUNT(*) FROM episodes e JOIN anime a ON a.id=e.anime_id WHERE e.watched=1")
        + one("SELECT COUNT(*) FROM tv_episodes WHERE watched=1"),
        "movies": one("SELECT COUNT(*) FROM anime WHERE media_type='movie' AND watch_status='completed'"),
        "series": one("SELECT COUNT(*) FROM anime WHERE COALESCE(media_type,'anime') IN ('anime','tv') "
                      "AND watch_status='completed'"),
    }


def _reached(kind: str, n: int) -> int:
    hit = [s for s in STEPS[kind] if n >= s]
    return hit[-1] if hit else 0


def check(db) -> Optional[Tuple[str, int]]:
    """The newest milestone just reached (kind, value), or None. Records it."""
    from core.app_settings import app_settings
    st = app_settings()
    try:
        seen = json.loads(str(st.value("milestones_seen", "") or "{}"))
    except ValueError:
        seen = {}
    now = counts(db)
    first = not seen.get("_baseline")
    seen["_baseline"] = 1
    new: List[Tuple[str, int]] = []
    for kind, n in now.items():
        r = _reached(kind, n)
        if r > int(seen.get(kind, 0) or 0):
            if not first:
                new.append((kind, r))
            seen[kind] = r
    st.setValue("milestones_seen", json.dumps(seen))
    if not new:
        return None
    return max(new, key=lambda x: STEPS[x[0]].index(x[1]) / len(STEPS[x[0]]))


def message(kind: str, value: int) -> str:
    return f"🎉  {value:,} {WORDS[kind]}! What a run — here's to the next {STEPS[kind][min(len(STEPS[kind]) - 1, STEPS[kind].index(value) + 1)]:,}."
