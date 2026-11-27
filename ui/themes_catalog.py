"""
Raikō - the permanent themes.

Each theme sets roles (see ui.theme.BASE_ROLES), fonts and shape; anything it
doesn't set comes from Raikō Night. Every theme must pass the contrast checks
in tests/test_theme.py (text and muted text readable on the background,
accents usable on surfaces).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ui.theme import BASE_ROLES, Theme

# id -> (name, tagline, dark, roles, fonts, extra)
_DEFS: Dict[str, Dict] = {
    "raiko_night": {
        "name": "Raikō Night", "tagline": "The original — deep night, soft light.",
        "dark": True, "roles": {}, "fonts": {}, "extra": {},
    },
    "midnight_ink": {
        "name": "Midnight Ink", "tagline": "True black with neon hairlines. Easy on OLED.",
        "dark": True,
        "roles": {"bg": "#000000", "text": "#f2f3f8", "violet": "#a594ff", "sky": "#22d3ee",
                  "green": "#2ee6a6", "pink": "#ff6ec7"},
        "fonts": {}, "extra": {},
    },
    "sakura_dawn": {
        "name": "Sakura Dawn", "tagline": "Warm paper, blush pink, ink. A light theme.",
        "dark": False,
        "roles": {"bg": "#fbf6f1", "text": "#2a2230", "violet": "#c2417a", "amber": "#965800",
                  "gold": "#8c5600", "sky": "#0b6fa4", "green": "#0f7a55", "red": "#c0322b",
                  "pink": "#be185d", "orange": "#c2410c"},
        "fonts": {"display": "Quicksand"},
        "extra": {"radius": 1.25, "ambient": {"kind": "petals", "density": 0.3}},
    },
    "neo_tokyo": {
        "name": "Neo-Tokyo", "tagline": "Night city neon, hard edges, signal glow.",
        "dark": True,
        "roles": {"bg": "#06060f", "text": "#eaf2ff", "violet": "#ff2bd6", "sky": "#00e5ff",
                  "amber": "#ffe600", "gold": "#ffd400", "green": "#39ff88", "red": "#ff3860",
                  "pink": "#ff4fd8", "orange": "#ff8a00"},
        "fonts": {"display": "Orbitron"}, "extra": {"radius": 0.6},
    },
    "studio_watercolor": {
        "name": "Studio Watercolor", "tagline": "Soft washes on warm paper, storybook serif.",
        "dark": False,
        "roles": {"bg": "#f3ede2", "text": "#1f1b18", "violet": "#4f5fb0", "amber": "#8a5214",
                  "gold": "#7d5812", "sky": "#2f6f96", "green": "#3f7a4c", "red": "#a8432f",
                  "pink": "#a34a72", "orange": "#b45a1f"},
        "fonts": {"display": "Fraunces"}, "extra": {"radius": 1.15},
    },
    "retro_vhs": {
        "name": "Retro VHS", "tagline": "CRT glow, chunky edges, pixel titles.",
        "dark": True,
        "roles": {"bg": "#0e0b16", "text": "#f1e9ff", "violet": "#c77dff", "sky": "#4cc9f0",
                  "amber": "#ffbe0b", "gold": "#ffd166", "green": "#06d6a0", "red": "#ef476f",
                  "pink": "#ff70a6", "orange": "#fb8500"},
        "fonts": {"display": "VT323"}, "extra": {"radius": 0.35},
    },
    "zen_mono": {
        "name": "Zen Mono", "tagline": "Greyscale calm with a single accent.",
        "dark": True,
        "roles": {"bg": "#101010", "text": "#ececec", "violet": "#e2b714", "amber": "#cfcfcf",
                  "gold": "#e2b714", "sky": "#bdbdbd", "green": "#d6d6d6", "red": "#f08a8a",
                  "pink": "#cfcfcf", "orange": "#cfcfcf"},
        "fonts": {}, "extra": {"radius": 0.8},
    },
    "high_contrast": {
        "name": "High Contrast", "tagline": "Maximum readability. Clear edges, no fuss.",
        "dark": True,
        "roles": {"bg": "#000000", "text": "#ffffff", "violet": "#b9a8ff", "amber": "#ffd400",
                  "gold": "#ffd400", "sky": "#7dd3fc", "green": "#4ade80", "red": "#ff7070",
                  "pink": "#ff9ad5", "orange": "#ffa94d"},
        "fonts": {}, "extra": {},
    },
}

ORDER = list(_DEFS)

# ── Event & seasonal looks (variants per event; see core/events.py) ──────────
_EVENT_DEFS: Dict[str, Dict] = {
    # Christmas
    "xmas_cozy": {
        "name": "Cozy Cabin", "tagline": "Firelight, wood and wool socks.", "dark": True,
        "roles": {"bg": "#140d0a", "text": "#fbf1e6", "violet": "#e2553f", "gold": "#f2b54a", "amber": "#f2b54a",
                  "green": "#4caf6e", "pink": "#ef7b6b", "sky": "#7fb7d6"},
        "fonts": {"display": "Fraunces"},
        "extra": {"ambient": {"kind": "embers", "density": 0.45},
                  "ornaments": [{"anchor": "logo", "kind": "sparkles"}, {"anchor": "add_button", "kind": "holly"},
                                {"anchor": "hall_nav", "kind": "sparkles"}], "mascot": "santa"}},
    "xmas_snow": {
        "name": "Snowfall Night", "tagline": "Deep blue night, quiet snow.", "dark": True,
        "roles": {"bg": "#071022", "text": "#f2f7ff", "violet": "#7cc4ff", "gold": "#f2d27a", "amber": "#f2d27a",
                  "green": "#4fd1a1", "red": "#ff7a85", "pink": "#ff9fc6", "sky": "#9fdcff"},
        "fonts": {},
        "extra": {"ambient": {"kind": "snow", "density": 0.9},
                  "ornaments": [{"anchor": "logo", "kind": "sparkles"}, {"anchor": "settings_button", "kind": "snowcap"},
                                {"anchor": "add_button", "kind": "holly"}], "mascot": "santa"}},
    "xmas_candy": {
        "name": "Candy Cane", "tagline": "Playful red, peppermint white.", "dark": True,
        "roles": {"bg": "#1a0b10", "text": "#fff5f6", "violet": "#ff4d6d", "gold": "#ffd166", "amber": "#ffd166",
                  "green": "#3ccf8e", "pink": "#ff8fab", "sky": "#9bd7ff"},
        "fonts": {"display": "Quicksand"},
        "extra": {"radius": 1.2, "ambient": {"kind": "confetti", "density": 0.35,
                                             "colors": ["#ff4d6d", "#ffffff", "#3ccf8e"]},
                  "ornaments": [{"anchor": "logo", "kind": "sparkles"}, {"anchor": "add_button", "kind": "holly"}],
                  "mascot": "santa"}},
    "xmas_golden": {
        "name": "Golden Eve", "tagline": "Black tie, warm gold, candlelight.", "dark": True,
        "roles": {"bg": "#0b0a08", "text": "#fbf6ea", "violet": "#e0b552", "gold": "#f3cf6f", "amber": "#f3cf6f",
                  "green": "#8fc79a", "red": "#e07b6b", "pink": "#e8a6a0", "sky": "#a9c4d8"},
        "fonts": {"display": "Fraunces"},
        "extra": {"ambient": {"kind": "stars", "density": 0.5, "colors": ["#f3cf6f", "#fff3c4"]},
                  "ornaments": [{"anchor": "logo", "kind": "sparkles"}, {"anchor": "hall_nav", "kind": "sparkles"}],
                  "mascot": "santa"}},
    # New Year
    "ny_midnight": {
        "name": "Midnight Countdown", "tagline": "Fireworks, champagne gold, a fresh start.", "dark": True,
        "roles": {"bg": "#070712", "text": "#f6f4ff", "violet": "#b18cff", "gold": "#ffd36e", "amber": "#ffd36e",
                  "pink": "#ff7ac6", "sky": "#7fd8ff"},
        "fonts": {"display": "Fraunces"},
        "extra": {"ambient": {"kind": "confetti", "density": 0.4,
                              "colors": ["#ffd36e", "#b18cff", "#ff7ac6", "#7fd8ff"]},
                  "ornaments": [{"anchor": "logo", "kind": "sparkles"}, {"anchor": "settings_button", "kind": "sparkles"}],
                  "mascot": "party"}},
    "ny_sunrise": {
        "name": "Hatsuhinode", "tagline": "The first sunrise of the year, warm and hopeful.", "dark": True,
        "roles": {"bg": "#160d12", "text": "#fff4ec", "violet": "#ff8a5b", "gold": "#ffc46b", "amber": "#ffc46b",
                  "pink": "#ff9aa2", "sky": "#9ecbff", "red": "#ff6b6b"},
        "fonts": {"display": "Quicksand"},
        "extra": {"ambient": {"kind": "stars", "density": 0.35, "colors": ["#ffd9a8", "#ffffff"]},
                  "ornaments": [{"anchor": "logo", "kind": "sparkles"}], "mascot": "party"}},
    # Halloween
    "hw_haunted": {
        "name": "Haunted Night", "tagline": "Bats, fog and a glowing moon.", "dark": True,
        "roles": {"bg": "#0b0912", "text": "#f3ecff", "violet": "#ff8a1f", "pink": "#b06cff", "gold": "#ffb347",
                  "amber": "#ffb347", "green": "#7ee081", "sky": "#9b8cff"},
        "fonts": {},
        "extra": {"ambient": {"kind": "embers", "density": 0.45},
                  "ornaments": [{"anchor": "settings_button", "kind": "bats"}, {"anchor": "hall_nav", "kind": "pumpkin"}],
                  "mascot": "witch"}},
    "hw_pumpkin": {
        "name": "Pumpkin Patch", "tagline": "Cute, cosy and very orange.", "dark": True,
        "roles": {"bg": "#160c06", "text": "#fff1e4", "violet": "#ff7b1c", "gold": "#ffc15e", "amber": "#ffc15e",
                  "green": "#7bc96f", "pink": "#ff9e7a", "sky": "#ffb38a"},
        "fonts": {"display": "Quicksand"},
        "extra": {"radius": 1.2, "ambient": {"kind": "leaves", "density": 0.45},
                  "ornaments": [{"anchor": "hall_nav", "kind": "pumpkin"}, {"anchor": "add_button", "kind": "pumpkin"}],
                  "mascot": "witch"}},
    "hw_yokai": {
        "name": "Yokai Night", "tagline": "Lanterns and spirits from Japanese folklore.", "dark": True,
        "roles": {"bg": "#08070f", "text": "#eef0ff", "violet": "#5ee6c8", "pink": "#ff6fa5", "gold": "#ffcf6b",
                  "amber": "#ffcf6b", "red": "#ff5a5a", "sky": "#8fb6ff"},
        "fonts": {},
        "extra": {"ambient": {"kind": "fireflies", "density": 0.55, "colors": ["#a6fff0", "#e0fffa"]},
                  "ornaments": [{"anchor": "settings_button", "kind": "lantern"}],
                  "mascot": "witch"}},
}

# Curated accents (the picker shows these; any colour can be typed too)
ACCENTS = ["#8b7bff", "#38bdf8", "#34d399", "#f5c451", "#fb923c", "#f472b6", "#f87171", "#e2e8f0"]


def _def(tid: str):
    return _DEFS.get(tid) or _EVENT_DEFS.get(tid)


def info(tid: str) -> Dict:
    d = _def(tid) or _DEFS["raiko_night"]
    return {"id": tid if _def(tid) else "raiko_night", "name": d["name"], "tagline": d["tagline"],
            "dark": d["dark"], "event": tid in _EVENT_DEFS}


def build(tid: str, accent: str = "") -> Theme:
    """The Theme for an id (+ optional accent replacing the main accent)."""
    if not _def(tid):
        tid = "raiko_night"
    d = _def(tid)
    roles = dict(d["roles"])
    if accent:
        roles["violet"] = accent
    return Theme(tid, d["name"], roles, dark=d["dark"], fonts=dict(d["fonts"]), extra=dict(d["extra"]))


def event_extra(tid: str) -> Dict:
    """Only the living details of an event look (for Decorations on your own theme)."""
    d = _EVENT_DEFS.get(tid) or {}
    ex = d.get("extra") or {}
    return {k: v for k, v in ex.items() if k in ("ambient", "ornaments", "mascot")}


def all_themes() -> List[Dict]:
    return [info(t) for t in ORDER]


def roles_of(tid: str, accent: str = "") -> Dict[str, str]:
    return {**BASE_ROLES, **build(tid, accent).roles}


def accent_of(tid: str) -> Optional[str]:
    return roles_of(tid)["violet"]
