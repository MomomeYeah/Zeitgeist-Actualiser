"""Source registry. A new platform is a new file plus one entry here."""

from collections.abc import Callable

from zeitgeist.config import Settings
from zeitgeist.sources.base import Source, TrendSource
from zeitgeist.sources.bluesky import BlueskySource
from zeitgeist.sources.composite import CompositeSource
from zeitgeist.sources.lemmy import LemmySource
from zeitgeist.sources.wikipedia import WikipediaSource

# Dormant. Kept wired so the platforms stay buildable and their tests keep
# running; no live pipeline stage calls build_source.
BUILDERS: dict[str, Callable[[Settings], Source]] = {
    "lemmy": LemmySource.from_settings,
    "wikipedia": WikipediaSource.from_settings,
}

TREND_BUILDERS: dict[str, Callable[[Settings], TrendSource]] = {
    "bluesky": BlueskySource.from_settings,
}


def build_source(settings: Settings) -> Source:
    """Build every enabled item source and wrap them in one Source."""
    return CompositeSource([BUILDERS[name](settings) for name in settings.sources])


def build_trend_source(settings: Settings) -> TrendSource:
    """Build the single enabled trend source.

    Settings has already rejected anything else, so a KeyError here would
    mean TREND_BUILDERS and TREND_SOURCES had drifted apart.
    """
    return TREND_BUILDERS[settings.sources[0]](settings)
