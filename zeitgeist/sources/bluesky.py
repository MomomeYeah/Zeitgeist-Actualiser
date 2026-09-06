"""Bluesky ingestion via the public AT Protocol AppView.

Needs no credentials: these endpoints accept unauthenticated requests.
Fetches in three steps, each fanning out from the last.

    getTrends       what is trending, with a description of each event
    getFeed         the posts behind one trend
    getPostThread   what people said underneath one post

`getTrends` carries a `link` which is a *web UI path*, and Bluesky maintains
a live feed generator behind it. Converting that path to an `at://` *record
address* is what lets `getFeed` return the trend's posts.

    link  /profile/{did}/feed/{rkey}
    uri   at://{did}/app.bsky.feed.generator/{rkey}

So the source never selects or ranks posts for a topic — Bluesky already has,
and this reads the result, including the trend description that names the
specific event.

The third step is why this module is async. Roughly 275 requests per run
serialised would take minutes; under a semaphore they take about one. The
async boundary stops at `fetch_evidence`, which is an ordinary synchronous
method, so no stage above this one becomes a coroutine.
"""

import asyncio
import hashlib
import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx

from zeitgeist.config import Settings
from zeitgeist.models import (
    BlueskyMetrics,
    Item,
    PostEvidence,
    Reply,
    TrendEvidence,
    TrendInfo,
    TrendStatus,
)
from zeitgeist.sources.base import SourceError

log = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.bsky.app"
TIMEOUT_SECONDS = 30.0
# getFeed's own maximum.
MAX_FEED_PAGE = 100
USER_AGENT = "zeitgeist-actualiser/0.1"

# Replies are fetched two levels deep: a reply-to-a-reply is still people
# talking about the trend, and it costs nothing extra — depth is a parameter
# of the same single request.
THREAD_DEPTH = 2

MAX_ATTEMPTS = 3
# Module-level so tests can zero it. Real runs rarely reach it: ~275 requests
# is well inside Bluesky's public limits.
RETRY_BASE_DELAY = 0.5

# `/profile/{did}/feed/{rkey}`. Not a documented contract — it is the path the
# web app renders — so a link that does not match costs one trend, not the run.
LINK_PATTERN = re.compile(r"^/profile/(?P<did>[^/]+)/feed/(?P<rkey>[^/]+)$")

LANGUAGE = "en"

# Union members of `getPostThread`'s reply list. Anything that is not a
# threadViewPost — a blocked or deleted post — carries no record to read.
THREAD_VIEW = "app.bsky.feed.defs#threadViewPost"

# trendView#status is typed `{"type": "string", "knownValues": ["hot"]}`.
# knownValues is explicitly non-exhaustive in AT Protocol, so every value
# observed live — "trending", "saturating", "cooling", "stale" — is
# legitimate alongside "hot", the one value actually documented.
# BlueskyMetrics.status stays a closed Literal on the model side, so the
# open set is collapsed onto it here, at the boundary. Anything not listed
# below degrades to the middle of the scale with a warning rather than
# raising: an enum that widens again is not a contract break.
STATUS_MAP: dict[str, TrendStatus] = {
    "hot": "trending",
    "trending": "trending",
    # Undocumented but real: 2 of 25 live trends carried it on 2026-08-23.
    "saturating": "saturating",
    "cooling": "cooling",
    "stale": "stale",
}


def _default_client() -> Any:
    return httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}
    )


class BlueskySource:
    name = "bluesky"

    def __init__(
        self, api_base: str = DEFAULT_API_BASE, client_factory: Any = None
    ) -> None:
        self._api_base = api_base.rstrip("/")
        # A factory rather than a client: the client must be created inside
        # the event loop `fetch_evidence` starts, and a real AsyncClient
        # bound to a closed loop is unusable on the next call.
        self._client_factory: Any = client_factory or _default_client

    @classmethod
    def from_settings(cls, settings: Settings) -> BlueskySource:
        return cls(api_base=settings.bluesky_api_base)

    def fetch_evidence(self, settings: Settings) -> list[TrendEvidence]:
        """Gather every trend's posts and replies. Synchronous by design."""
        return asyncio.run(self._gather(settings))

    async def _gather(self, settings: Settings) -> list[TrendEvidence]:
        client = self._client_factory()
        semaphore = asyncio.Semaphore(settings.bluesky_fetch_concurrency)
        fetched_at = datetime.now(UTC)
        try:
            # Only transport failure is tolerated. A KeyError from a changed
            # payload propagates: that is a contract break, not an outage.
            try:
                payload = await self._get(
                    client,
                    semaphore,
                    "app.bsky.unspecced.getTrends",
                    {"limit": settings.bluesky_trend_limit},
                )
            except httpx.HTTPError as exc:
                raise SourceError(f"Bluesky trends unavailable: {exc}") from exc

            trends = payload["trends"]
            if not trends:
                raise SourceError("Bluesky returned no trends")

            gathered = await asyncio.gather(
                *(
                    self._trend_evidence(client, semaphore, trend, settings, fetched_at)
                    for trend in trends
                )
            )
        finally:
            await client.aclose()

        evidence = [entry for entry in gathered if entry is not None]
        if not evidence:
            raise SourceError("Bluesky returned no usable trends")
        return evidence

    async def _trend_evidence(
        self,
        client: Any,
        semaphore: asyncio.Semaphore,
        trend: dict[str, Any],
        settings: Settings,
        fetched_at: datetime,
    ) -> TrendEvidence | None:
        match = LINK_PATTERN.match(trend["link"])
        if match is None:
            log.warning("Skipping Bluesky trend with link %r", trend["link"])
            return None

        uri = f"at://{match['did']}/app.bsky.feed.generator/{match['rkey']}"
        try:
            payload = await self._get(
                client,
                semaphore,
                "app.bsky.feed.getFeed",
                {
                    "feed": uri,
                    "limit": min(MAX_FEED_PAGE, settings.bluesky_posts_per_trend),
                },
            )
        except httpx.HTTPError as exc:
            log.warning("Skipping Bluesky trend %s: %s", trend["displayName"], exc)
            return None

        # Mapping is pure: a bug here must crash, not look like an
        # unreachable trend.
        items: list[Item] = []
        for view in payload["feed"]:
            post = view["post"]
            if not _is_usable(post):
                continue
            item = _to_item(post, trend, fetched_at)
            if item is not None:
                items.append(item)

        if not items:
            log.warning("Skipping Bluesky trend %s: no usable posts", trend["topic"])
            return None

        replies = await asyncio.gather(
            *(self._replies(client, semaphore, item) for item in items)
        )
        log.debug(
            "Trend %s: %d posts, %d replies",
            trend["displayName"],
            len(items),
            sum(len(group) for group in replies),
        )
        return TrendEvidence(
            trend=_to_trend_info(trend),
            posts=[
                PostEvidence(item=item, replies=group)
                for item, group in zip(items, replies, strict=True)
            ],
        )

    async def _replies(
        self, client: Any, semaphore: asyncio.Semaphore, item: Item
    ) -> list[Reply]:
        try:
            payload = await self._get(
                client,
                semaphore,
                "app.bsky.feed.getPostThread",
                {"uri": item.source_id, "depth": THREAD_DEPTH},
            )
        except httpx.HTTPError as exc:
            # A post without its replies is still evidence of what was
            # posted, so it is kept rather than dropped.
            log.warning("No replies for %s: %s", item.permalink, exc)
            return []
        return list(_walk_replies((payload.get("thread") or {}).get("replies") or []))

    async def _get(
        self,
        client: Any,
        semaphore: asyncio.Semaphore,
        endpoint: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        url = f"{self._api_base}/xrpc/{endpoint}"
        delay = RETRY_BASE_DELAY
        for attempt in range(MAX_ATTEMPTS):
            async with semaphore:
                response = await client.get(url, params=params)
            if response.status_code == 429 and attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            # On the final attempt a 429 raises here, which the per-trend and
            # per-post guards treat as any other transport failure.
            response.raise_for_status()
            return response.json()
        raise AssertionError("unreachable: the loop always returns or raises")


def _to_trend_info(trend: dict[str, Any]) -> TrendInfo:
    return TrendInfo(
        # Stable while the trend lives, kept for cross-run identification
        topic_id=trend["topic"],
        display_name=trend["displayName"],
        # Optional in practice: bsky.unspecced endpoints promise nothing.
        description=trend.get("description") or "",
        category=trend.get("category") or "",
        post_count=trend.get("postCount", 0),
        started_at=_parse_timestamp(trend["startedAt"]),
        status=_normalise_status(trend.get("status")),
    )


def _is_usable(post: dict[str, Any]) -> bool:
    # `labels` is optional in postView; a post the labeler never touched
    # omits the key entirely rather than sending an empty list.
    if post.get("labels", []):
        return False
    if not post["record"]["text"].strip():
        return False
    # `langs` is optional and client-set, so absence means unknown rather than
    # non-English. Dropping those would discard a real share of every fetch.
    # Compared on the primary subtag: langs is BCP-47, so "en-US"/"en-GB" are
    # valid English tags that exact membership would otherwise drop.
    langs = post["record"].get("langs")
    return langs is None or any(lang.split("-")[0] == LANGUAGE for lang in langs)


def _to_item(
    post: dict[str, Any], trend: dict[str, Any], fetched_at: datetime
) -> Item | None:
    split = _split_uri(post["uri"])
    if split is None:
        # Same standard as a malformed trend link: a shape violation in an
        # identifier that isn't a documented contract costs one post, not
        # the run — and never a permalink that merely looks valid.
        log.warning("Skipping Bluesky post with malformed uri %r", post["uri"])
        return None
    did, rkey = split
    return Item(
        source_id=post["uri"],
        # Posts cap at 300 graphemes, so the text fits a title without
        # truncation and there is no separate body to excerpt.
        title=post["record"]["text"].strip(),
        body_excerpt=None,
        # Built, not copied: an at:// URI is an identifier, not an address.
        permalink=f"https://bsky.app/profile/{did}/post/{rkey}",
        fetched_at=fetched_at,
        metrics=BlueskyMetrics(
            # likeCount/replyCount/repostCount are all optional in postView:
            # a post with no engagement yet omits them rather than sending 0.
            like_count=post.get("likeCount", 0),
            reply_count=post.get("replyCount", 0),
            repost_count=post.get("repostCount", 0),
            trend=trend["displayName"],
            status=_normalise_status(trend.get("status")),
            # `indexedAt`, assigned by the relay, never `record.createdAt`,
            # which the posting client supplies and can back- or future-date.
            # The scorer divides engagement by age, so a future date would
            # yield a negative denominator.
            created_at=_parse_timestamp(post["indexedAt"]),
        ),
    )


def _normalise_status(raw: str | None) -> TrendStatus:
    """A missing or unrecognised status is the open enum working as
    documented, not a contract break, so this degrades to the neutral middle
    of STATUS_MOVEMENT's scale rather than crashing the run. The warning is
    what makes a future widening of the enum actually get noticed.
    """
    status = STATUS_MAP.get(raw) if raw is not None else None
    if status is None:
        log.warning("Unrecognised Bluesky trend status %r; treating as cooling", raw)
        return "cooling"
    return status


def _split_uri(uri: str) -> tuple[str, str] | None:
    """`at://{did}/{collection}/{rkey}` -> (did, rkey), or None if the URI
    does not have exactly that shape.

    A too-short URI would otherwise still produce a plausible-looking
    permalink: with fewer than three segments, `parts[0]` and `parts[-1]`
    collapse to the same value, so `did:plc:x` alone yields
    `.../profile/did:plc:x/post/did:plc:x` — a 404 stored as though valid.
    """
    parts = uri.removeprefix("at://").split("/")
    if len(parts) != 3:
        return None
    return parts[0], parts[-1]


def _parse_timestamp(raw: str) -> datetime:
    """The scorer subtracts this from an aware `now`, so a naive value would
    raise three stages later rather than here.
    """
    parsed = datetime.fromisoformat(raw)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _walk_replies(nodes: list[dict[str, Any]]) -> Iterator[Reply]:
    """Flatten the reply tree. Nesting is a fact about who answered whom,
    which no downstream stage reads — the distillation prompt wants the
    conversation, not its shape.
    """
    for node in nodes:
        if node.get("$type") != THREAD_VIEW:
            continue
        post = node.get("post")
        if not post:
            continue
        text = post["record"]["text"].strip()
        if text and not post.get("labels", []):
            yield Reply(
                text=text,
                like_count=post.get("likeCount", 0),
                created_at=_parse_timestamp(post["indexedAt"]),
                author_key=_author_key(post["author"]["did"]),
            )
        yield from _walk_replies(node.get("replies") or [])


def _author_key(did: str) -> str:
    """One-way and truncated. Distinct-account counting is the only thing
    downstream needs; the handle itself has no use and is never stored.
    """
    return hashlib.sha256(did.encode("utf-8")).hexdigest()[:16]
