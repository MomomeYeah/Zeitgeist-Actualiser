"""Lemmy ingestion via the public v3 API.

Needs no credentials: Lemmy's API is open and unauthenticated. Pulls `Hot`
(what is currently large) and `Scaled` (Hot normalised by community size, so
posts climbing in smaller communities surface), mirroring the hot/rising pair
the Reddit source uses.
"""

import logging
import math
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from zeitgeist.config import Settings
from zeitgeist.models import Post
from zeitgeist.sources.base import SourceError

log = logging.getLogger(__name__)

BODY_EXCERPT_CHARS = 500
# Instances reject anything larger: limit=100 returns couldnt_get_posts.
PAGE_SIZE = 50
SORTS = ("Hot", "Scaled")
TIMEOUT_SECONDS = 30.0
# Some instances sit behind a CDN that filters the default httpx UA. Static
# rather than configurable: unlike Reddit's, this API needs no per-app
# identity, just something that is not the bare library default.
USER_AGENT = "zeitgeist-actualiser/0.1"


class LemmySource:
    name = "lemmy"

    def __init__(
        self,
        instance: str = "https://lemmy.world",
        include_nsfw: bool = False,
        client: Any = None,
    ) -> None:
        self._instance = instance.rstrip("/")
        self._include_nsfw = include_nsfw
        self._client = client or httpx.Client(
            timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> LemmySource:
        return cls(
            instance=settings.lemmy_instance,
            include_nsfw=settings.lemmy_include_nsfw,
        )

    def fetch(self, limit: int) -> list[Post]:
        # Split the budget evenly between the two listings. Hot and Scaled
        # overlap heavily, so dedup typically removes a meaningful share of
        # what each contributes — a run yields fewer than `limit` unique
        # posts more often than not. `limit` is an upper bound, not a target.
        per_sort = max(1, math.ceil(limit / len(SORTS)))
        fetched_at = datetime.now(UTC)

        seen: dict[str, Post] = {}
        for sort in SORTS:
            # Only transport failure is tolerated. A KeyError from a changed
            # payload propagates: that is a contract break, not an outage.
            try:
                views = self._fetch_sort(sort, per_sort)
            except httpx.HTTPError as exc:
                log.warning("Skipping Lemmy %s listing: %s", sort, exc)
                continue

            # Mapping is pure: a bug here must crash, not look like an
            # unreachable instance.
            for view in views:
                post = _to_post(view, fetched_at)
                if post.source_id in seen:
                    continue
                seen[post.source_id] = post
                if len(seen) >= limit:
                    return list(seen.values())

        if not seen:
            raise SourceError("Lemmy returned no posts")
        return list(seen.values())

    def _fetch_sort(self, sort: str, budget: int) -> list[dict[str, Any]]:
        """Page through one listing until the budget is met or it runs dry."""
        collected: list[dict[str, Any]] = []
        page = 1
        while len(collected) < budget:
            response = self._client.get(
                f"{self._instance}/api/v3/post/list",
                params={
                    "type_": "All",
                    "sort": sort,
                    "limit": PAGE_SIZE,
                    "page": page,
                    "show_nsfw": "true" if self._include_nsfw else "false",
                },
            )
            response.raise_for_status()
            views = response.json()["posts"]
            # A short page means the listing is exhausted; without this the
            # loop would keep requesting until the budget was met.
            if not views:
                break
            collected.extend(views)
            page += 1
        # Trimmed to `budget`, a real per-listing share, not just a paging
        # target: pages are 50 at a time, so an unaligned budget can overshoot
        # by up to 49. Left untrimmed, a well-stocked Hot would swallow that
        # overshoot into the global limit before Scaled is ever asked —
        # crowding out the rising signal Scaled exists to surface.
        return collected[:budget]


def _to_post(view: dict[str, Any], fetched_at: datetime) -> Post:
    post = view["post"]
    counts = view["counts"]
    body = (post.get("body") or "").strip()
    return Post(
        platform="lemmy",
        source_id=post["ap_id"],
        title=post["name"],
        body_excerpt=body[:BODY_EXCERPT_CHARS] or None,
        # ap_id is the canonical URL of the post on its home instance.
        permalink=post["ap_id"],
        score=counts["score"],
        comment_count=counts["comments"],
        created_at=_parse_published(post["published"]),
        fetched_at=fetched_at,
        channel=_channel(view["community"]),
    )


def _channel(community: dict[str, Any]) -> str:
    """`name@host`. Community names collide across federated instances, and
    channel_spread counts distinct channels, so bare names would undercount.
    """
    host = urlsplit(community["actor_id"]).netloc
    return f"{community['name']}@{host}"


def _parse_published(raw: str) -> datetime:
    """Instances send `2026-08-18T09:00:00.123456Z`; some omit the zone.
    The scorer subtracts this from an aware `now`, so a naive value would
    raise three stages later rather than here.
    """
    parsed = datetime.fromisoformat(raw)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
