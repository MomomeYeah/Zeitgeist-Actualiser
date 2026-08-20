"""Fans one fetch out across every enabled source.

Implements Source itself, so the pipeline stays single-source: adding a
platform never changes run_pipeline.
"""

import logging
import math
from collections.abc import Sequence

from zeitgeist.models import Post
from zeitgeist.sources.base import Source, SourceError

log = logging.getLogger(__name__)


class CompositeSource:
    # Sequence, not list: list is invariant, so a list of any concrete
    # Source implementation was rejected at the call site.
    def __init__(self, sources: Sequence[Source]) -> None:
        if not sources:
            raise ValueError("CompositeSource needs at least one source")
        self._sources = sources
        # Names what actually ran, so a log line distinguishes a Lemmy-only
        # run from a Lemmy+Reddit one.
        self.name = ",".join(source.name for source in sources)

    def fetch(self, limit: int) -> list[Post]:
        log.info("Fetching from sources: %s", self.name)
        per_source = max(1, math.ceil(limit / len(self._sources)))

        # Keyed by platform as well as id: source_id is only unique within a
        # platform, and a shortfall is not redistributed — a second pass to
        # top up would double the request count for a marginal gain.
        seen: dict[tuple[str, str], Post] = {}
        for source in self._sources:
            # Each source converts its own recoverable failures (transport
            # errors, an empty listing) into SourceError and lets everything
            # else escape — that is the contract in base.py. So SourceError
            # is the only exception a source can raise that means "this
            # platform is down"; anything else is a bug in that source (e.g.
            # a mapping error from a changed payload) and must crash here
            # rather than be logged as an unreachable platform.
            try:
                posts = source.fetch(limit=per_source)
            except SourceError as exc:
                log.warning("Skipping source %s: %s", source.name, exc)
                continue

            for post in posts:
                key = (post.platform, post.source_id)
                if key in seen:
                    continue
                seen[key] = post
                if len(seen) >= limit:
                    return list(seen.values())

        if not seen:
            raise SourceError("No source returned any posts")
        return list(seen.values())
