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
     "greeting": "Merry Christmas", "line": "Raikō dressed up for Christmas.",
     "tagline": "Cosy classics and festive favourites for the holidays."},
    {"id": "new_year", "name": "New Year", "category": "holidays", "emoji": "🎆", "anim": "🎉",
     "start": (12, 31), "end": (1, 2), "variants": ["ny_midnight", "ny_sunrise"],
     "greeting": "Happy New Year", "line": "Raikō is ready to ring in the new year.",
     "tagline": "Feel-good films to welcome the new year."},
    {"id": "halloween", "name": "Halloween", "category": "holidays", "emoji": "🎃", "anim": "🎃",
     "start": (10, 25), "end": (10, 31), "variants": ["hw_haunted", "hw_pumpkin", "hw_yokai"],
     "greeting": "Happy Halloween", "line": "Raikō dressed up for Halloween.",
     "tagline": "Spooky picks, from cosy chills to proper scares."},
]
# Anime-world: the first week of each anime season (decorations + this season's most anticipated)
_SEASON_EXTRA = {"ambient": {"kind": "stars", "density": 0.35, "colors": ["#fff3c4", "#c7bfff"]},
                 "ornaments": [{"anchor": "logo", "kind": "sparkles"}]}
for _sid, _name, _m, _d in (("season_winter", "Winter", 1, 3), ("season_spring", "Spring", 4, 1),
                            ("season_summer", "Summer", 7, 1), ("season_fall", "Fall", 10, 1)):
    EVENTS.append({"id": _sid, "name": f"{_name} Season Premiere Week", "category": "anime", "emoji": "✨",
                   "anim": "🎉", "start": (_m, _d), "end": (_m, _d + 6), "variants": [], "extra": _SEASON_EXTRA,
                   "greeting": f"A new {_name.lower()} season", "line": "Premiere week — the most anticipated anime are "
                                                                         "arriving.",
                   "tagline": "The new anime everyone is waiting for."})
BY_ID = {e["id"]: e for e in EVENTS}
# settings-only rows for the live anime events (no fixed dates)
LIVE = [{"id": "anime_premiere", "name": "Big premiere days", "emoji": "🎬", "variants": [],
         "about": "When a highly anticipated show (or one on your list) airs its first episode"},
        {"id": "anime_farewell", "name": "Farewells", "emoji": "🌸", "variants": [],
         "about": "When a beloved series (or one you watch) airs its final episode"}]
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
    if ev.get("dynamic"):
        return f"{ev['id']}-{ev.get('date', '')}"
    return f"{ev['id']}-{window_dates(ev, d)[0].year}"


_SIM: Dict = {}


def _simulated(d: date) -> Optional[Dict]:
    """RAIKO_SIMULATE='premiere:One Piece' (main.py --simulate ...) previews any show's event."""
    spec = os.environ.get("RAIKO_SIMULATE", "").strip()
    if not spec or ":" not in spec:
        return None
    key = f"{spec}|{d}"
    if key not in _SIM:
        kind, query = spec.split(":", 1)
        try:
            from core.anime_events import simulate
            from datetime import datetime as _dt
            ev = simulate(kind.strip(), query.strip(), None, _dt(d.year, d.month, d.day))
        except Exception:
            ev = None
        if ev:
            ev["date"] = d.strftime("%Y-%m-%d")
        _SIM[key] = ev
    return _SIM[key]


def dynamic(d: Optional[date] = None) -> Optional[Dict]:
    """Today's anime-world event (premiere / farewell), from the daily check."""
    d = d or today()
    sim = _simulated(d)
    if sim is not None:
        return sim
    try:
        from core.anime_events import cached
        ev = cached(d.strftime("%Y-%m-%d"))
    except Exception:
        ev = None
    if ev and ev.get("date") == d.strftime("%Y-%m-%d"):
        return ev
    return None


def calendar_event(d: Optional[date] = None) -> Optional[Dict]:
    d = d or today()
    for ev in EVENTS:
        if _in_window(ev, d):
            return ev
    return None


def active_all(d: Optional[date] = None) -> List[Dict]:
    """Everything on today. When a holiday and an anime event share a day, the
    holiday keeps the look (people expect it all week) and the anime event leads
    the spotlight with its own banner and moment."""
    d = d or today()
    cal = calendar_event(d)
    dyn = dynamic(d)
    if cal is not None and dyn is not None and cal.get("category") == "anime":
        return [dyn]                              # a premiere day outranks premiere *week*
    return [e for e in (cal, dyn) if e is not None]


def active(d: Optional[date] = None) -> Optional[Dict]:
    """The event that sets today's look (the primary one)."""
    evs = active_all(d)
    return evs[0] if evs else None


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
    """Per-event intensity: auto | full | decorations | off.
    Premieres and farewells share one setting each ('anime_premiere', 'anime_farewell')."""
    if ev_id.startswith("premiere-"):
        ev_id = "anime_premiere"
    elif ev_id.startswith("farewell-"):
        ev_id = "anime_farewell"
    v = str(_st().value(f"event_intensity/{ev_id}", "auto") or "auto")
    return v if v in INTENSITIES else "auto"


def set_setting(ev_id: str, v: str):
    _st().setValue(f"event_intensity/{ev_id}", v)


def ask_first() -> bool:
    return str(_st().value("event_ask_first", "false")).lower() == "true"


def set_ask_first(on: bool):
    _st().setValue("event_ask_first", "true" if on else "false")


def variant(ev: Dict) -> str:
    if not ev.get("variants"):
        return ""
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
    if not ev.get("variants") or ev.get("category") == "anime":
        return "decorations"                  # anime events decorate by default; "full" is offered
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
    if not ev.get("variants") and not (ev.get("dynamic") and level == "full"):
        level = "decorations"
    if ev.get("dynamic") and level == "full":
        return show_theme(ev, user_theme), ev, "full"
    vid = variant(ev) if ev.get("variants") else ""
    if level == "full":
        t = build(vid)
        return Theme(t.id, t.name, t.roles, dark=t.dark, fonts=t.fonts,
                     extra={**t.extra, "event": ev["id"], "event_level": "full"}), ev, "full"
    deco = dict(ev.get("extra") or {}) if not vid else event_extra(vid)
    return Theme(user_theme.id, user_theme.name, user_theme.roles, dark=user_theme.dark, fonts=user_theme.fonts,
                 extra={**user_theme.extra, **deco, "event": ev["id"], "event_level": "decorations"}), ev, \
        "decorations"


def readable_accent(color: str) -> str:
    """The show's colour, nudged until it works as an accent on Raikō's dark
    surfaces (>= 3:1) and dark text on it stays readable (>= 4.5:1)."""
    from ui.theme import contrast, hex_rgb, oklab_to_rgb, rgb_hex, rgb_to_oklab
    try:
        L, a, b = rgb_to_oklab(*hex_rgb(color))
    except Exception:
        return "#8b7bff"
    for _ in range(40):
        c = rgb_hex(*oklab_to_rgb(L, a, b))
        if contrast(c, "#12141d") >= 3 and contrast("#0b0d12", c) >= 4.5:
            return c
        L = min(0.97, L + 0.02)
    return "#8b7bff"


def show_theme(ev: Dict, user_theme):
    """A full look coloured from the show's own key colour."""
    from ui.theme import Theme
    acc = readable_accent(ev.get("color") or "#8b7bff")
    return Theme(f"show-{ev['id']}", ev["name"], {"violet": acc, "gold": acc}, dark=True,
                 extra={**(ev.get("extra") or {}), "event": ev["id"], "event_level": "full"})
