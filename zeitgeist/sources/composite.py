"""Fans one fetch out across every enabled source.

Implements Source itself, so the pipeline stays single-source: adding a
platform never changes run_pipeline.
"""

import logging
import math

from zeitgeist.models import Post
from zeitgeist.sources.base import Source, SourceError

log = logging.getLogger(__name__)


class CompositeSource:
    def __init__(self, sources: list[Source]) -> None:
        if not sources:
            raise ValueError("CompositeSource needs at least one source")
        self._sources = sources
        # Names what actually ran, so a log line distinguishes a Lemmy-only
        # run from a Lemmy+Reddit one.
        self.name = ",".join(source.name for source in sources)

    def fetch(self, limit: int) -> list[Post]:
        per_source = max(1, math.ceil(limit / len(self._sources)))

        # Keyed by platform as well as id: source_id is only unique within a
        # platform, and a shortfall is not redistributed — a second pass to
        # top up would double the request count for a marginal gain.
        seen: dict[tuple[str, str], Post] = {}
        for source in self._sources:
            # A source can raise anything its client library defines, so the
            # guard is broad. One platform down must not lose the others.
            try:
                posts = source.fetch(limit=per_source)
            except Exception as exc:
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
