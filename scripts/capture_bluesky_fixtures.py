"""Captures real Bluesky payloads into tests/fixtures/bluesky/.

Run when the API's shapes are in question. The fixtures in
tests/test_sources_bluesky.py are hand-built and deliberately minimal; these
are the full article, for checking that a hand-built fixture has not drifted
from what the endpoint actually returns.

    uv run python scripts/capture_bluesky_fixtures.py

Hits the network, so it is a script rather than a test.
"""

import json
from pathlib import Path

import httpx

API_BASE = "https://api.bsky.app"
OUT = Path("tests/fixtures/bluesky")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        timeout=30.0, headers={"User-Agent": "zeitgeist-actualiser/0.1"}
    ) as client:
        trends = _get(client, "app.bsky.unspecced.getTrends", {"limit": 25})
        _dump("trends.json", trends)

        trend = trends["trends"][0]
        did, rkey = trend["link"].split("/")[2], trend["link"].split("/")[4]
        uri = f"at://{did}/app.bsky.feed.generator/{rkey}"

        # httpx already URL-encodes dict values passed as `params`, so the
        # AT-URI must be passed raw here — pre-quoting it double-encodes the
        # `:` and `/` characters and the API rejects the result with a 400.
        feed = _get(client, "app.bsky.feed.getFeed", {"feed": uri, "limit": 10})
        _dump("feed.json", feed)

        post = max(feed["feed"], key=lambda v: v["post"].get("replyCount", 0))["post"]
        thread = _get(
            client,
            "app.bsky.feed.getPostThread",
            {"uri": post["uri"], "depth": 2},
        )
        _dump("thread.json", thread)

    print(f"Captured trends, feed and thread into {OUT}")


def _get(client: httpx.Client, endpoint: str, params: dict) -> dict:
    response = client.get(f"{API_BASE}/xrpc/{endpoint}", params=params)
    response.raise_for_status()
    return response.json()


def _dump(name: str, payload: dict) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
