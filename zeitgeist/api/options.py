"""What the New run and settings screens offer as choices.

One endpoint, but it assembles from four unrelated sources — providers,
platforms, templates and `.env` — and belongs in none of the resource
routers.
"""

from fastapi import APIRouter, Depends

from zeitgeist.api.app import get_settings
from zeitgeist.api.schemas import ConfigOptions, PlatformOption, TemplateOption
from zeitgeist.config import KNOWN_SOURCES, TREND_SOURCES, Settings
from zeitgeist.llm.registry import available_models
from zeitgeist.media.templates import load_templates
from zeitgeist.runner import RUN_OVERRIDE_KEYS

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/options", response_model=ConfigOptions)
def read_options(settings: Settings = Depends(get_settings)) -> ConfigOptions:
    templates = load_templates(settings.templates_dir)
    return ConfigOptions(
        models=available_models(settings),
        platforms=[
            PlatformOption(name=name, enabled=name in TREND_SOURCES)
            for name in KNOWN_SOURCES
        ],
        templates=[
            TemplateOption(id=manifest.id, slots=[slot.name for slot in manifest.slots])
            for manifest in templates.values()
        ],
        # Only the fields a run may actually override. Reporting every
        # `Settings` field would put `anthropic_api_key` in the response,
        # which is the one thing this endpoint must never return.
        defaults={
            key: str(getattr(settings, key)) for key in sorted(RUN_OVERRIDE_KEYS)
        },
        anthropic_key_present=bool(settings.anthropic_api_key),
    )
