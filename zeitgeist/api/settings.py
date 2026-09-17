"""The settings read and write, over every scoped field.

Reports whether each value was set here or is still the field's default,
because a settings screen that cannot tell the two apart is worse than no
settings screen. Every field in `GLOBAL_KEYS | RUN_KEYS` appears — including
`anthropic_api_key`, which is written through this endpoint like any other
field, but whose value is never read back out of it.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from zeitgeist.api.app import get_store
from zeitgeist.api.schemas import SettingField, SettingScope, SettingsUpdate
from zeitgeist.config import (
    GLOBAL_KEYS,
    RUN_KEYS,
    SECRET_KEYS,
    Settings,
    format_validation_errors,
    load_settings,
)
from zeitgeist.store import Store

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Every field this screen can read or write: the union of both scopes.
# `templates_dir` and `output_dir` are real `Settings` fields but declare
# neither scope, so they stay off this list — a UI able to point every run
# at another directory is a different and worse thing than a tuning screen.
SETTABLE_KEYS = GLOBAL_KEYS | RUN_KEYS


def _validation_detail(exc: ValidationError) -> str:
    """`exc.errors()` as one readable string naming every offending field,
    rather than the list of objects pydantic hands back.

    Every other 400 among the project's fifteen endpoints uses a plain
    string for `detail` — `"Not writable through settings: ..."` two lines
    below `write_settings`'s own use of this, for one. A generated
    TypeScript client sees `detail` as `string` everywhere else and
    `ValidationError[]` only here, without this. Delegates to
    `zeitgeist.config.format_validation_errors`, which `load_settings` also
    raises through, rather than re-deriving the same expression here.
    """
    return format_validation_errors(exc)


def _scope(key: str) -> SettingScope:
    return "global" if key in GLOBAL_KEYS else "run"


def _display(
    value: str | float | int | bool | Path | list[str] | None,
) -> str | float | int | bool | None:
    """The field's value as JSON the client can round-trip back as a string.

    `Path` and `list` are the two declared types that have no JSON form the
    `PUT` would accept back: a bare `Path` is not serialisable at all, and a
    list would come back as a list where `SettingsUpdate` wants the CSV
    string `_split_csv` reads.

    Typed as the union every `Settings` field actually is, not `object`: an
    untyped parameter lets `isinstance(value, Path)` and `isinstance(value,
    list)` narrow it, but only down to "not a Path and not a list" — still
    unprovably a subtype of the return union to a checker that has no reason
    to believe `object` holds nothing else. The real domain is exactly this
    union, so stating it is what lets the final `return value` type-check
    rather than needing a suppression for a call that is not actually wrong.
    """
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return ",".join(str(part) for part in value)
    return value


@router.get("", response_model=list[SettingField])
def read_settings(store: Store = Depends(get_store)) -> list[SettingField]:
    """Built from `load_settings`, not from `app.state.settings`, which is
    frozen when the app is built — so a `PUT` is visible to the very next
    `GET`.
    """
    stored = store.get_settings()
    settings = load_settings(store)
    return [
        SettingField(
            key=key,
            value=None if key in SECRET_KEYS else _display(getattr(settings, key)),
            scope=_scope(key),
            source="settings" if key in stored else "default",
            secret=key in SECRET_KEYS,
        )
        for key in sorted(SETTABLE_KEYS)
    ]


@router.put("", response_model=list[SettingField])
def write_settings(
    body: SettingsUpdate,
    store: Store = Depends(get_store),
) -> list[SettingField]:
    """Write every accepted field, then report every field's new state.

    Same response shape as the `GET`, so the screen re-renders its source
    chips from this reply rather than issuing a second request.
    """
    unknown = sorted(set(body.values) - SETTABLE_KEYS)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Not writable through settings: {', '.join(unknown)}",
        )

    # Validate before writing anything, against what the table currently
    # holds rather than the app's frozen `Settings` — the same reason
    # `read_settings` reads through `load_settings` rather than
    # `app.state.settings`. Stored unvalidated, a meme_potential_weight of
    # 2.0 would be accepted here and fail when the *next run* built its
    # Settings — a broken run rather than a rejected save. Validating a
    # candidate object is also how the endpoint stays ignorant of each
    # field's type.
    proposed = {key: value for key, value in body.values.items() if value != ""}
    if proposed:
        try:
            Settings(**(load_settings(store).model_dump() | proposed))
        except ValidationError as exc:
            raise HTTPException(
                status_code=400, detail=_validation_detail(exc)
            ) from exc

    # Only after every field has been accepted: a request naming one good
    # field and one bad one must write neither, or the screen shows a
    # partial save with a 400 beside it.
    for key, value in body.values.items():
        if value == "":
            # Reset deletes the row so the field's declared default applies
            # again. Writing that default back as a value would pin it, and
            # the screen could no longer tell a deliberate choice from a
            # field nobody has ever touched.
            store.clear_setting(key)
        else:
            store.set_setting(key, value)

    return read_settings(store=store)
