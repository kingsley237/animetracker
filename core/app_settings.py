"""
Miroku — application settings (QSettings) with one-time legacy migration.
"""
from PyQt6.QtCore import QSettings

_LEGACY_ORG = "AnimeTracker"
_LEGACY_APP = "AnimeTracker"
_ORG = "Miroku"
_APP = "Miroku"
_MIGRATED_KEY = "settings_migrated_from_animetracker"


def app_settings() -> QSettings:
    """Return the canonical Miroku settings store."""
    return QSettings(_ORG, _APP)


def preferred_theme() -> str:
    """Return the saved appearance preference."""
    value = str(app_settings().value("theme", "dark") or "dark").lower()
    return value if value in {"dark", "light", "system"} else "dark"


def resolved_theme() -> str:
    """
    Return the concrete theme file stem to load.

    Miroku currently ships a complete dark theme. The setting still accepts
    "system" and "light" so the UI is future-proof, but both fall back to dark
    until a dedicated light stylesheet is present.
    """
    theme = preferred_theme()
    return "light" if theme == "light" else "dark"


def set_preferred_theme(theme: str) -> None:
    value = (theme or "dark").lower()
    if value not in {"dark", "light", "system"}:
        value = "dark"
    app_settings().setValue("theme", value)


def migrate_legacy_settings() -> None:
    """Copy keys from the old AnimeTracker namespace on first run after rebrand."""
    current = app_settings()
    if current.value(_MIGRATED_KEY, False, type=bool):
        return

    legacy = QSettings(_LEGACY_ORG, _LEGACY_APP)
    for key in legacy.allKeys():
        if not current.contains(key):
            current.setValue(key, legacy.value(key))

    current.setValue(_MIGRATED_KEY, True)
