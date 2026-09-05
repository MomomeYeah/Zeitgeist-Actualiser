"""The settings read.

Reports which layer supplied each value, because a settings screen that
hides which layer won is worse than no settings screen. Only the seven
tunable fields appear: a UI that could rewrite where the database lives, or
read an API key back out, is a different and worse thing than a tuning
screen.
"""

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from zeitgeist.api.app import get_settings, get_store
from zeitgeist.api.schemas import SettingField, SettingSource, SettingsUpdate
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
def read_settings(store: Store = Depends(get_store)) -> list[SettingField]:
    """Built from a fresh `Settings()`, not `app.state.settings`.

    `app.state.settings` is frozen at startup (`create_app`'s parameter),
    and `init_settings` outranks the table in `Settings.settings_customise_
    sources` — so `getattr` on that frozen object would never see a value a
    `PUT` had since written, no matter how recently. The chip beside it
    would say "settings" while the value shown was the old one: the worst
    possible presentation, because it names the very layer that just won as
    the source of a value that layer did not produce. A fresh `Settings()`
    re-resolves every field through the normal precedence chain — including
    `SettingsTableSource`, which reads the table at construction — so a
    `PUT` is visible to the very next `GET`. `write_settings` already built
    one of these to answer its own response before this existed as its own
    read path; this makes that the only place that ever needs to.
    """
    stored = store.get_settings()
    settings = Settings()
    return [
        SettingField(
            key=key,
            value=getattr(settings, key),
            source=_source(key, stored),
        )
        for key in sorted(WRITABLE_KEYS)
    ]


@router.put("", response_model=list[SettingField])
def write_settings(
    body: SettingsUpdate,
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> list[SettingField]:
    """Write the seven tunables, then report every field's new state.

    Same response shape as the `GET`, so the screen re-renders its source
    chips from this reply rather than issuing a second request.
    """
    unknown = sorted(set(body.values) - WRITABLE_KEYS)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Not writable through settings: {', '.join(unknown)}",
        )

    # Validate before writing anything. Stored unvalidated, a
    # meme_potential_weight of 2.0 would be accepted here and fail when the
    # *next run* built its Settings — a broken run rather than a rejected
    # save. Validating a candidate object is also how the endpoint stays
    # ignorant of each field's type.
    proposed = {key: value for key, value in body.values.items() if value != ""}
    if proposed:
        try:
            Settings(**(settings.model_dump() | proposed))
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=exc.errors()) from exc

    # Only after every field has been accepted: a request naming one good
    # field and one bad one must write neither, or the screen shows a
    # partial save with a 400 beside it.
    for key, value in body.values.items():
        if value == "":
            # "Reset to .env" deletes the row so the fallback applies again.
            # Writing the default back would pin the value and make a later
            # .env edit invisible.
            store.clear_setting(key)
        else:
            store.set_setting(key, value)

    return read_settings(store=store)
