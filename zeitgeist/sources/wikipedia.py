"""Wikimedia pageviews ingestion via the public REST metrics API.

Needs no credentials. Unlike the forum sources this measures *attention*
rather than conversation: there are no comments and no communities, so it
cannot originate topics — it corroborates topics another platform found.
"""

import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from zeitgeist.config import Settings
from zeitgeist.models import Item, WikipediaMetrics
from zeitgeist.sources.base import SourceError

log = logging.getLogger(__name__)

BASE_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top"
TIMEOUT_SECONDS = 30.0
# Pageviews for a given day are not published immediately. Rather than pin a
# lag figure that could change, walk back until a day exists.
MAX_DAY_ATTEMPTS = 5

DEFAULT_CONTACT = "https://github.com/MomomeYeah/Zeitgeist-Actualiser"

# Namespace and maintenance pages. These occupy the very top of the listing —
# Main_Page alone draws sixteen times the first real article — so left in they
# would set the whole min-max range and flatten everything genuine to zero.
STRUCTURAL_PREFIXES = (
    "Special:",
    "Wikipedia:",
    "Portal:",
    "Help:",
    "Category:",
    "Template:",
    "File:",
    "Talk:",
)
STRUCTURAL_EXACT = frozenset({"Main_Page"})
DEATHS_PATTERN = re.compile(r"^Deaths_in_\d{4}$")


class WikipediaSource:
    name = "wikipedia"

    def __init__(
        self,
        project: str = "en.wikipedia",
        contact: str = DEFAULT_CONTACT,
        client: Any = None,
    ) -> None:
        self._project = project
        # Wikimedia's API policy requires contact information in the agent and
        # warns that generic agents may be rate-limited or blocked outright.
        self.user_agent = f"zeitgeist-actualiser/0.1 ({contact})"
        self._client = client or httpx.Client(
            timeout=TIMEOUT_SECONDS, headers={"User-Agent": self.user_agent}
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> WikipediaSource:
        return cls(
            project=settings.wikipedia_project,
            contact=settings.wikipedia_contact,
        )

    def fetch(self, limit: int) -> list[Item]:
        fetched_at = datetime.now(UTC)
        day = fetched_at.date()

        for _ in range(MAX_DAY_ATTEMPTS):
            # Only transport failure is tolerated. A KeyError from a changed
            # payload propagates: that is a contract break, not an outage.
            try:
                articles, measured = self._fetch_day(day)
            except httpx.HTTPError as exc:
                log.warning("Skipping Wikipedia pageviews for %s: %s", day, exc)
                day -= timedelta(days=1)
                continue

            # Mapping is pure: a bug here must crash, not look like a
            # missing day.
            items = [
                _to_item(entry, measured, self._project, fetched_at)
                for entry in articles
                if not _is_structural(entry["article"])
            ]
            if items:
                # Truncated after filtering, so the budget buys real articles
                # rather than being spent on namespace pages.
                return items[:limit]

            log.warning("Wikipedia pageviews for %s held no usable articles", day)
            day -= timedelta(days=1)

        raise SourceError(
            f"Wikipedia returned no usable articles in {MAX_DAY_ATTEMPTS} days"
        )

    def _fetch_day(self, day: date) -> tuple[list[dict[str, Any]], date]:
        url = (
            f"{BASE_URL}/{self._project}/all-access/"
            f"{day.year:04d}/{day.month:02d}/{day.day:02d}"
        )
        response = self._client.get(url)
        response.raise_for_status()
        payload = response.json()
        entry = payload["items"][0]
        measured = date(int(entry["year"]), int(entry["month"]), int(entry["day"]))
        return entry["articles"], measured


def _is_structural(article: str) -> bool:
    return (
        article in STRUCTURAL_EXACT
        or article.startswith(STRUCTURAL_PREFIXES)
        or DEATHS_PATTERN.match(article) is not None
    )


def _to_item(
    entry: dict[str, Any], measured: date, project: str, fetched_at: datetime
) -> Item:
    article = entry["article"]
    return Item(
        # The day is part of the identity: the same article on two days is
        # two measurements, not a duplicate.
        source_id=f"{project}:{article}:{measured.isoformat()}",
        title=article.replace("_", " "),
        body_excerpt=None,
        # Built from `project`, not hardcoded: a de.wikipedia run measures
        # German pageviews, so linking to the English article would send
        # every reader somewhere the numbers did not come from.
        permalink=f"https://{project}.org/wiki/{article}",
        fetched_at=fetched_at,
        metrics=WikipediaMetrics(
            views=entry["views"],
            rank=entry["rank"],
            measured_on=measured,
        ),
    )
