"""The settings read.

Reports whether each value was set here or is still the field's default,
because a settings screen that cannot tell the two apart is worse than no
settings screen. Only the seven tunable fields appear: a UI that could read
an API key back out is a different and worse thing than a tuning screen.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from zeitgeist.api.app import get_settings, get_store
from zeitgeist.api.schemas import SettingField, SettingSource, SettingsUpdate
from zeitgeist.config import Settings, load_settings
from zeitgeist.store import Store

router = APIRouter(prefix="/api/settings", tags=["settings"])

# The fields this screen offers. A subset of `GLOBAL_KEYS | RUN_KEYS`, which
# is everything the table can hold: `anthropic_api_key` is stored but must
# never be read back out here, and the run-scoped choices (`sources`,
# `llm_model` and the rest) belong to the New run screen, which sets them
# per run rather than globally.
WRITABLE_KEYS = frozenset(
    {
        "bluesky_trend_limit",
        "bluesky_posts_per_trend",
        "bluesky_fetch_concurrency",
        "meme_potential_weight",
        "phrase_min_authors",
        "distil_char_budget",
        "distil_concurrency",
    }
)


def _validation_detail(exc: ValidationError) -> str:
    """`exc.errors()` as one readable string naming every offending field,
    rather than the list of objects pydantic hands back.

    Every other 400 among the project's fifteen endpoints uses a plain
    string for `detail` — `"Not writable through settings: ..."` two lines
    below `write_settings`'s own use of this, for one. A generated
    TypeScript client sees `detail` as `string` everywhere else and
    `ValidationError[]` only here, without this.
    """
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    )


def _source(key: str, stored: dict[str, str]) -> SettingSource:
    """Whether this field was set here or is still its declared default.

    The only two answers there are: a value is a row in the `settings` table
    or it is nothing at all.
    """
    return "settings" if key in stored else "default"


@router.get("", response_model=list[SettingField])
def read_settings(store: Store = Depends(get_store)) -> list[SettingField]:
    """Read from the store, not from `app.state.settings`.

    `app.state.settings` is frozen at startup (`create_app`'s parameter), so
    `getattr` on it would never see a value a `PUT` had since written, no
    matter how recently. The chip beside it would say "settings" while the
    value shown was the old one: the worst possible presentation, because it
    names the very layer that just won as the source of a value that layer
    did not produce. `load_settings` reads the table on each request, so a
    `PUT` is visible to the very next `GET`.
    """
    stored = store.get_settings()
    settings = load_settings(store)
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
