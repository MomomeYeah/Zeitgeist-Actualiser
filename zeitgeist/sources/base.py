"""The extension point. A new platform is a new file implementing this."""

from typing import Protocol

from zeitgeist.config import Settings
from zeitgeist.models import Item, TrendEvidence


class SourceError(Exception):
    """Raised when a platform cannot be reached or returns nothing usable."""


class Source(Protocol):
    name: str

    def fetch(self, limit: int) -> list[Item]: ...


class TrendSource(Protocol):
    """A platform that clusters posts into trends itself.

    Returns evidence rather than a flat item list, so `Source` cannot
    describe it. There is no `limit`: the fan-out is bounded by
    `bluesky_trend_limit` and `bluesky_posts_per_trend`, a two-dimensional
    budget a single integer cannot express.
    """

    name: str

    def fetch_evidence(self, settings: Settings) -> list[TrendEvidence]: ...
