"""Bluesky ingestion via the public AT Protocol AppView.

Needs no credentials: these endpoints accept unauthenticated requests. Fetches
in two steps. `getTrends` returns what is trending; each trend carries a `link`
which is a *web UI path*, and Bluesky maintains a live feed generator behind
it. Converting that path to an `at://` *record address* is what lets `getFeed`
return the trend's posts.

    link  /profile/{did}/feed/{rkey}
    uri   at://{did}/app.bsky.feed.generator/{rkey}

So the source never selects or ranks posts for a topic — Bluesky already has,
and this reads the result.
"""

import logging
import math
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from zeitgeist.config import Settings
from zeitgeist.models import BlueskyMetrics, Item, TrendStatus
from zeitgeist.sources.base import SourceError

log = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.bsky.app"
TIMEOUT_SECONDS = 30.0
# getTrends returns 400 above 25, so this is a ceiling rather than a tuning
# parameter: the source can never see more than 25 topics per run.
TREND_LIMIT = 25
# getFeed's own maximum.
MAX_FEED_PAGE = 100
USER_AGENT = "zeitgeist-actualiser/0.1"

# `/profile/{did}/feed/{rkey}`. Not a documented contract — it is the path the
# web app renders — so a link that does not match costs one trend, not the run.
LINK_PATTERN = re.compile(r"^/profile/(?P<did>[^/]+)/feed/(?P<rkey>[^/]+)$")

LANGUAGE = "en"

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


class BlueskySource:
    name = "bluesky"

    def __init__(self, api_base: str = DEFAULT_API_BASE, client: Any = None) -> None:
        self._api_base = api_base.rstrip("/")
        # Explicitly annotated: without it, ty infers `Any | Client` for the
        # `or` fallback rather than collapsing to `Any`, and callers that
        # read `_client` back (the tests do, extensively) then see spurious
        # unresolved-attribute errors on the `Client` arm.
        self._client: Any = client or httpx.Client(
            timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> BlueskySource:
        return cls(api_base=settings.bluesky_api_base)

    def fetch(self, limit: int) -> list[Item]:
        fetched_at = datetime.now(UTC)

        # Only transport failure is tolerated. A KeyError from a changed
        # payload propagates: that is a contract break, not an outage.
        try:
            trends = self._fetch_trends()
        except httpx.HTTPError as exc:
            raise SourceError(f"Bluesky trends unavailable: {exc}") from exc

        if not trends:
            raise SourceError("Bluesky returned no trends")

        per_trend = min(MAX_FEED_PAGE, max(1, math.ceil(limit / len(trends))))

        seen: dict[str, Item] = {}
        for trend in trends:
            match = LINK_PATTERN.match(trend["link"])
            if match is None:
                log.warning("Skipping Bluesky trend with link %r", trend["link"])
                continue

            uri = f"at://{match['did']}/app.bsky.feed.generator/{match['rkey']}"
            try:
                views = self._fetch_feed(uri, per_trend)
            except httpx.HTTPError as exc:
                log.warning("Skipping Bluesky trend %s: %s", trend["topic"], exc)
                continue

            # Mapping is pure: a bug here must crash, not look like an
            # unreachable trend.
            for view in views:
                post = view["post"]
                if not _is_usable(post):
                    continue
                # First trend wins, mirroring LemmySource's dedup.
                if post["uri"] in seen:
                    continue
                item = _to_item(post, trend, fetched_at)
                if item is None:
                    continue
                seen[post["uri"]] = item
                if len(seen) >= limit:
                    return list(seen.values())

        if not seen:
            raise SourceError("Bluesky returned no usable posts")
        return list(seen.values())

    def _fetch_trends(self) -> list[dict[str, Any]]:
        response = self._client.get(
            f"{self._api_base}/xrpc/app.bsky.unspecced.getTrends",
            params={"limit": TREND_LIMIT},
        )
        response.raise_for_status()
        return response.json()["trends"]

    def _fetch_feed(self, uri: str, limit: int) -> list[dict[str, Any]]:
        response = self._client.get(
            f"{self._api_base}/xrpc/app.bsky.feed.getFeed",
            params={"feed": uri, "limit": limit},
        )
        response.raise_for_status()
        return response.json()["feed"]


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
