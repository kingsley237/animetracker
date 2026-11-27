"""
Raikō - event & seasonal themes: which event is on, and how strongly.

Intensity (docs/THEMES_SCOPE.md §6.0):
  full         the whole event look
  decorations  your own theme stays; the event adds ambient effects,
               ornaments and Rai
  off          nothing

Default ("auto"): full for people on the default theme (Raikō Night),
decorations for anyone who chose a theme themselves - an explicit choice
is never replaced. Every event can be set individually (auto / full /
decorations / off); "Ask me first" waits for a yes on the banner.

Your choice is remembered per event and per year. `today()` can be
overridden for previews: RAIKO_DATE=YYYY-MM-DD (or `main.py --date`).
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

EVENTS: List[Dict] = [
    {"id": "christmas", "name": "Christmas", "category": "holidays", "emoji": "🎄", "anim": "❄️",
     "start": (12, 20), "end": (12, 26), "variants": ["xmas_snow", "xmas_cozy", "xmas_candy", "xmas_golden"],
     "greeting": "Merry Christmas", "line": "Raikō dressed up for Christmas."},
    {"id": "new_year", "name": "New Year", "category": "holidays", "emoji": "🎆", "anim": "🎉",
     "start": (12, 31), "end": (1, 2), "variants": ["ny_midnight", "ny_sunrise"],
     "greeting": "Happy New Year", "line": "Raikō is ready to ring in the new year."},
    {"id": "halloween", "name": "Halloween", "category": "holidays", "emoji": "🎃", "anim": "🎃",
     "start": (10, 25), "end": (10, 31), "variants": ["hw_haunted", "hw_pumpkin", "hw_yokai"],
     "greeting": "Happy Halloween", "line": "Raikō dressed up for Halloween."},
]
BY_ID = {e["id"]: e for e in EVENTS}
CATEGORIES = {"holidays": "Holidays", "seasons": "Seasons", "anime": "Anime events", "milestones": "Milestones"}
INTENSITIES = {"auto": "Automatic (recommended)", "full": "Full theme", "decorations": "Decorations only",
               "off": "Off"}


def today() -> date:
    v = os.environ.get("RAIKO_DATE", "").strip()
    if v:
        try:
            return datetime.strptime(v, "%Y-%m-%d").date()
        except ValueError:
            pass
    return date.today()


def _in_window(ev: Dict, d: date) -> bool:
    s, e = ev["start"], ev["end"]
    md = (d.month, d.day)
    if s <= e:
        return s <= md <= e
    return md >= s or md <= e                      # spans the new year


def window_dates(ev: Dict, d: Optional[date] = None) -> Tuple[date, date]:
    """The event's next (or current) start and end dates."""
    d = d or today()
    s, e = ev["start"], ev["end"]
    y = d.year
    if s > e and (d.month, d.day) <= e:            # in the January part of a wrapping window
        start, end = date(y - 1, *s), date(y, *e)
    else:
        start = date(y, *s)
        end = date(y + (1 if s > e else 0), *e)
        if end < d:                                # already over this year -> next one
            start, end = date(y + 1, *s), date(y + 1 + (1 if s > e else 0), *e)
    return start, end


def season_key(ev: Dict, d: Optional[date] = None) -> str:
    """'christmas-2026' (wrapping events use the year they started in)."""
    return f"{ev['id']}-{window_dates(ev, d)[0].year}"


def active(d: Optional[date] = None) -> Optional[Dict]:
    d = d or today()
    for ev in EVENTS:
        if _in_window(ev, d):
            return ev
    return None


def upcoming(d: Optional[date] = None, limit: int = 6) -> List[Tuple[Dict, date, date]]:
    d = d or today()
    out = [(ev, *window_dates(ev, d)) for ev in EVENTS]
    out.sort(key=lambda x: x[1])
    return out[:limit]


# ── settings ──────────────────────────────────────────────────────────────────

def _st():
    from core.app_settings import app_settings
    return app_settings()


def setting(ev_id: str) -> str:
    """Per-event intensity: auto | full | decorations | off."""
    v = str(_st().value(f"event_intensity/{ev_id}", "auto") or "auto")
    return v if v in INTENSITIES else "auto"


def set_setting(ev_id: str, v: str):
    _st().setValue(f"event_intensity/{ev_id}", v)


def ask_first() -> bool:
    return str(_st().value("event_ask_first", "false")).lower() == "true"


def set_ask_first(on: bool):
    _st().setValue("event_ask_first", "true" if on else "false")


def variant(ev: Dict) -> str:
    v = str(_st().value(f"event_variant/{ev['id']}", "") or "")
    return v if v in ev["variants"] else ev["variants"][0]


def set_variant(ev: Dict, tid: str):
    _st().setValue(f"event_variant/{ev['id']}", tid)


def choice(ev: Dict, d: Optional[date] = None) -> str:
    """What you chose on this year's banner: '' (nothing yet) | full | decorations | off | kept."""
    return str(_st().value(f"event_choice/{season_key(ev, d)}", "") or "")


def set_choice(ev: Dict, v: str, d: Optional[date] = None):
    _st().setValue(f"event_choice/{season_key(ev, d)}", v)


def intensity(ev: Dict, user_theme_id: str, d: Optional[date] = None) -> str:
    """The intensity actually used right now for `ev`."""
    c = choice(ev, d)
    if c in ("full", "decorations", "off"):
        return c
    s = setting(ev["id"])
    if s != "auto":
        return s
    if ask_first() and c != "kept":
        return "off"
    return "full" if user_theme_id in ("", "raiko_night") else "decorations"


def resolve(user_theme, user_theme_id: str, d: Optional[date] = None):
    """(theme to apply, event or None, intensity)."""
    ev = active(d)
    if ev is None:
        return user_theme, None, "off"
    level = intensity(ev, user_theme_id, d)
    if level == "off":
        return user_theme, ev, "off"
    from ui.theme import Theme
    from ui.themes_catalog import build, event_extra
    vid = variant(ev)
    if level == "full":
        t = build(vid)
        return Theme(t.id, t.name, t.roles, dark=t.dark, fonts=t.fonts,
                     extra={**t.extra, "event": ev["id"], "event_level": "full"}), ev, "full"
    deco = event_extra(vid)
    return Theme(user_theme.id, user_theme.name, user_theme.roles, dark=user_theme.dark, fonts=user_theme.fonts,
                 extra={**user_theme.extra, **deco, "event": ev["id"], "event_level": "decorations"}), ev, \
        "decorations"
