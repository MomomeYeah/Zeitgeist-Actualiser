"""Reddit ingestion via PRAW in read-only mode.

Pulls `hot` (what is currently large) and `rising` (Reddit's own early
signal), so the scorer sees things that have not already peaked.
"""

import logging
import math
from datetime import UTC, datetime
from typing import Any

from zeitgeist.config import Settings
from zeitgeist.models import Post
from zeitgeist.sources.base import SourceError

log = logging.getLogger(__name__)

BODY_EXCERPT_CHARS = 500


class RedditSource:
    name = "reddit"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        subreddits: list[str] | None = None,
        reddit: Any = None,
    ) -> None:
        if reddit is None:
            import praw

            reddit = praw.Reddit(
                client_id=client_id,
                client_secret=client_secret,
                user_agent=user_agent,
            )
            reddit.read_only = True
        self._reddit = reddit
        self._subreddits = list(subreddits or [])

    @classmethod
    def from_settings(cls, settings: Settings) -> RedditSource:
        return cls(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
            subreddits=settings.subreddits,
        )

    def fetch(self, limit: int) -> list[Post]:
        names = ["all", *self._subreddits]
        # Divide the budget across listings, not across listing *pairs*: hot
        # and rising overlap heavily, so halving again would undersample.
        per_listing = max(1, math.ceil(limit / len(names)))
        fetched_at = datetime.now(UTC)

        seen: dict[str, Post] = {}
        for name in names:
            # PRAW is lazy: subreddit() never raises, but iterating hot/rising
            # does — for a banned, private, or misspelled name, on the first
            # `next()`. One bad entry in SUBREDDITS must not abort the whole
            # run; only "nothing worked at all" (checked below) is fatal.
            try:
                listing = self._reddit.subreddit(name)
                fetched = [
                    submission
                    for stream in (listing.hot, listing.rising)
                    for submission in stream(limit=per_listing)
                ]
            except Exception as exc:
                log.warning("Skipping r/%s: %s", name, exc)
                continue

            # Mapping is pure: a bug here must crash, not look like an
            # unreachable subreddit.
            for submission in fetched:
                if submission.id in seen:
                    continue
                seen[submission.id] = _to_post(submission, fetched_at)
                if len(seen) >= limit:
                    return list(seen.values())

        if not seen:
            raise SourceError("Reddit returned no posts")
        return list(seen.values())


def _to_post(submission: Any, fetched_at: datetime) -> Post:
    body = (submission.selftext or "").strip()
    return Post(
        platform="reddit",
        source_id=submission.id,
        title=submission.title,
        body_excerpt=body[:BODY_EXCERPT_CHARS] or None,
        permalink=f"https://www.reddit.com{submission.permalink}",
        score=submission.score,
        comment_count=submission.num_comments,
        created_at=datetime.fromtimestamp(submission.created_utc, tz=UTC),
        fetched_at=fetched_at,
        channel=submission.subreddit.display_name,
    )
