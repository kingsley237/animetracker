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
        "fonts": {"display": "Quicksand"}, "extra": {"radius": 1.25},
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

# Curated accents (the picker shows these; any colour can be typed too)
ACCENTS = ["#8b7bff", "#38bdf8", "#34d399", "#f5c451", "#fb923c", "#f472b6", "#f87171", "#e2e8f0"]


def info(tid: str) -> Dict:
    d = _DEFS.get(tid) or _DEFS["raiko_night"]
    return {"id": tid if tid in _DEFS else "raiko_night", "name": d["name"], "tagline": d["tagline"],
            "dark": d["dark"]}


def build(tid: str, accent: str = "") -> Theme:
    """The Theme for an id (+ optional accent replacing the main accent)."""
    if tid not in _DEFS:
        tid = "raiko_night"
    d = _DEFS[tid]
    roles = dict(d["roles"])
    if accent:
        roles["violet"] = accent
    return Theme(tid, d["name"], roles, dark=d["dark"], fonts=dict(d["fonts"]), extra=dict(d["extra"]))


def all_themes() -> List[Dict]:
    return [info(t) for t in ORDER]


def roles_of(tid: str, accent: str = "") -> Dict[str, str]:
    return {**BASE_ROLES, **build(tid, accent).roles}


def accent_of(tid: str) -> Optional[str]:
    return roles_of(tid)["violet"]
