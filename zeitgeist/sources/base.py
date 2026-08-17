"""The extension point. A new platform is a new file implementing this."""

from typing import Protocol

from zeitgeist.models import Post


class SourceError(Exception):
    """Raised when a platform cannot be reached or returns nothing usable."""


class Source(Protocol):
    name: str

    def fetch(self, limit: int) -> list[Post]: ...
