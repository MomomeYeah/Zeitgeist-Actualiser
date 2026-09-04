"""A pydantic-settings source backed by the `settings` table.

Precedence, highest first: constructor arguments, environment variables,
this table, `.env`, field defaults. A shell `BLUESKY_TREND_LIMIT=10` in
front of a command beats the UI because it is the more explicit act; the UI
beats `.env` because it is the more recent one.
"""

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

# Exactly the fields the settings screen exposes. Everything else is refused
# here as well as at the endpoint: a UI that can rewrite where the database
# lives, or store an API key in a table, is a different and worse thing than
# a tuning screen.
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

DEFAULT_DB_PATH = Path("data") / "zeitgeist.db"

# The same file `Settings.model_config` names, resolved the same way: relative
# to the working directory.
DOTENV_PATH = Path(".env")


def _dotenv_value(key: str) -> str | None:
    """Read one `KEY=value` line out of `.env`.

    Hand-rolled rather than delegated to pydantic-settings' dotenv source or
    to python-dotenv, because this runs *during* `Settings` construction: the
    dotenv source has not produced a value yet, and asking `Settings` where
    its database lives is the circularity this whole module avoids. All that
    is needed is one unquoted scalar, so a full dotenv parser — interpolation,
    multi-line values, `export` prefixes — would be machinery to import for a
    partition on "=". Last assignment wins, as dotenv does.
    """
    try:
        text = DOTENV_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    found: str | None = None
    for line in text.splitlines():
        name, separator, value = line.strip().partition("=")
        if separator and name.strip() == key:
            found = value.strip().strip("\"'")
    return found


def _db_path() -> Path:
    """Where the settings table lives.

    The environment first, then `.env`, then the same default `Settings`
    declares — the precedence `Settings` itself gives `db_path`, minus the
    table, which is the one source that cannot be consulted to find the table.
    Reading only `os.environ` would send this at the default database whenever
    `DB_PATH` was set in `.env`, which is the documented place to set it, and
    every stored override would silently vanish.
    """
    env_path = os.environ.get("DB_PATH") or _dotenv_value("DB_PATH")
    return Path(env_path) if env_path else DEFAULT_DB_PATH


class SettingsTableSource(PydanticBaseSettingsSource):
    """Reads overrides the settings screen wrote.

    Deliberately does not read `Settings.db_path`: that is the object being
    constructed, so resolving the database's location from it is circular.
    The path comes from the environment and `.env` directly — see `_db_path`.
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        self._values = self._load()

    def _load(self) -> dict[str, str]:
        path = _db_path()
        if not path.is_file():
            # Settings has to load before anything has created the database —
            # the harness builds Settings in order to find out where it goes.
            return {}
        try:
            # closing as well as the context manager: `with sqlite3.connect`
            # commits, it does not close, so the handle would linger until the
            # refcount happened to drop.
            with closing(sqlite3.connect(path)) as conn:
                rows = conn.execute("SELECT key, value FROM settings").fetchall()
        except sqlite3.Error:
            # A database from another schema version, or mid-write. Settings
            # failing to load would be a worse outcome than ignoring overrides.
            return {}
        return {key: value for key, value in rows if key in WRITABLE_KEYS}

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        return self._values.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return {
            name: value
            for name, value in self._values.items()
            if name in self.settings_cls.model_fields
        }
