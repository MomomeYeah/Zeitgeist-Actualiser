"""Source registry. A new platform is a new file plus one entry here."""

from collections.abc import Callable

from zeitgeist.config import Settings
from zeitgeist.sources.base import Source
from zeitgeist.sources.composite import CompositeSource
from zeitgeist.sources.lemmy import LemmySource
from zeitgeist.sources.reddit import RedditSource

BUILDERS: dict[str, Callable[[Settings], Source]] = {
    "lemmy": LemmySource.from_settings,
    "reddit": RedditSource.from_settings,
}


def build_source(settings: Settings) -> Source:
    """Build every enabled source and wrap them in one Source.

    Settings has already rejected unknown names, so a KeyError here would
    mean BUILDERS and KNOWN_SOURCES had drifted apart.
    """
    return CompositeSource([BUILDERS[name](settings) for name in settings.sources])
