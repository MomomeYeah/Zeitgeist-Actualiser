"""The settings read.

Reports which layer supplied each value, because a settings screen that
hides which layer won is worse than no settings screen. Only the seven
tunable fields appear: a UI that could rewrite where the database lives, or
read an API key back out, is a different and worse thing than a tuning
screen.
"""

import os

from fastapi import APIRouter, Depends

from zeitgeist.api.app import get_settings, get_store
from zeitgeist.api.schemas import SettingField, SettingSource
from zeitgeist.config import Settings
from zeitgeist.settings_source import WRITABLE_KEYS, _dotenv_value
from zeitgeist.store import Store

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _source(key: str, stored: dict[str, str]) -> SettingSource:
    """Which layer supplied this field, in `Settings`' own precedence.

    Environment first, then the settings table, then `.env`, then the field
    default — the order `settings_customise_sources` establishes.
    """
    if key.upper() in os.environ:
        return "environment"
    if key in stored:
        return "settings"
    if _dotenv_value(key.upper()) is not None:
        return "dotenv"
    return "default"


@router.get("", response_model=list[SettingField])
def read_settings(
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> list[SettingField]:
    stored = store.get_settings()
    return [
        SettingField(
            key=key,
            value=getattr(settings, key),
            source=_source(key, stored),
        )
        for key in sorted(WRITABLE_KEYS)
    ]
