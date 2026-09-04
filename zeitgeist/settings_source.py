"""A pydantic-settings source backed by the `settings` table.

Precedence, highest first: constructor arguments, environment variables,
this table, `.env`, field defaults. A shell `BLUESKY_TREND_LIMIT=10` in
front of a command beats the UI because it is the more explicit act; the UI
beats `.env` because it is the more recent one.
"""

import sqlite3
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


class SettingsTableSource(PydanticBaseSettingsSource):
    """Reads overrides the settings screen wrote.

    Deliberately does not read `Settings.db_path`: that is the object being
    constructed, so resolving the database's location from it is circular.
    The path comes from the environment, defaulting to the same value
    `Settings` declares.
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        self._values = self._load()

    def _load(self) -> dict[str, str]:
        import os

        path = Path(os.environ.get("DB_PATH", DEFAULT_DB_PATH))
        if not path.is_file():
            # Settings has to load before anything has created the database —
            # the harness builds Settings in order to find out where it goes.
            return {}
        try:
            with sqlite3.connect(path) as conn:
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
