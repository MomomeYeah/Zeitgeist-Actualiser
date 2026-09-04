"""Response models for endpoints whose shape is a composition.

Storage models are returned directly wherever they suffice — `TopicRow`,
`StageRecord` and `RenderRecord` are already the shape the UI reads. These
exist only where an endpoint joins several sources into one body.
"""

from typing import Literal

from pydantic import BaseModel

from zeitgeist.models import STRICT

# Four layers, though the settings screen draws three chips. A shell
# variable outranks the settings table, so `environment` is a real answer
# and the screen consuming this needs a fourth chip or a deliberate
# decision to fold it into one of the three.
SettingSource = Literal["settings", "environment", "dotenv", "default"]


class SettingField(BaseModel):
    """One tunable field, its effective value, and which layer supplied it."""

    model_config = STRICT

    key: str
    value: float | int
    source: SettingSource
