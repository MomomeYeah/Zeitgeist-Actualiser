import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from zeitgeist.config import Settings
from zeitgeist.models import WikipediaMetrics
from zeitgeist.sources.base import SourceError
from zeitgeist.sources.wikipedia import MAX_DAY_ATTEMPTS, WikipediaSource

FIXTURES = Path(__file__).parent / "fixtures"


def _payload() -> dict:
    return json.loads((FIXTURES / "wikipedia_top.json").read_text(encoding="utf-8"))


class _FakeClient:
    """Returns a queued response per call, recording the URLs requested."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.urls: list[str] = []

    def get(self, url: str, **kwargs) -> object:
        self.urls.append(url)
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_structural_pages_are_filtered_out():
    """Main_Page alone draws sixteen times the first real article, so left in
    it would set the entire min-max range and flatten everything genuine."""
    source = WikipediaSource(client=_FakeClient([_Response(_payload())]))

    items = source.fetch(limit=50)

    titles = {item.title for item in items}
    assert "Main Page" not in titles
    assert "Special:Search" not in titles
    assert "Wikipedia:Featured pictures" not in titles
    assert "Deaths in 2026" not in titles


def test_real_articles_survive_filtering():
    source = WikipediaSource(client=_FakeClient([_Response(_payload())]))

    items = source.fetch(limit=50)

    assert "Hayden Panettiere" in {item.title for item in items}


def test_perennial_pages_are_not_filtered():
    """Google is merely popular, not structural. Neutralising it is the
    scorer's job via rank-delta; filtering here would be a guessing game."""
    source = WikipediaSource(client=_FakeClient([_Response(_payload())]))

    items = source.fetch(limit=50)

    assert "Google" in {item.title for item in items}


def test_metrics_carry_rank_views_and_the_measurement_day():
    source = WikipediaSource(client=_FakeClient([_Response(_payload())]))

    items = source.fetch(limit=50)

    hayden = next(i for i in items if i.title == "Hayden Panettiere")
    assert isinstance(hayden.metrics, WikipediaMetrics)
    assert hayden.metrics.rank == 4
    assert hayden.metrics.views == 411486
    assert hayden.metrics.measured_on == date(2026, 8, 20)


def test_source_id_includes_the_day_so_runs_do_not_collide():
    """The same article on two days is two measurements, not one."""
    source = WikipediaSource(client=_FakeClient([_Response(_payload())]))

    items = source.fetch(limit=50)

    hayden = next(i for i in items if i.title == "Hayden Panettiere")
    assert hayden.source_id == "en.wikipedia:Hayden_Panettiere:2026-08-20"


def test_permalink_points_at_the_article():
    source = WikipediaSource(client=_FakeClient([_Response(_payload())]))

    items = source.fetch(limit=50)

    hayden = next(i for i in items if i.title == "Hayden Panettiere")
    assert hayden.permalink == "https://en.wikipedia.org/wiki/Hayden_Panettiere"


def _day_from_url(url: str) -> date:
    """The trailing /YYYY/MM/DD of a pageviews URL."""
    year, month, day = url.rsplit("/", 3)[-3:]
    return date(int(year), int(month), int(day))


def test_a_missing_day_falls_back_to_exactly_one_day_earlier():
    """Pageviews data is not published immediately for the current day, and
    how far it lags is not something this source should need to know. The
    step must be one day backwards: forwards finds a day that will never
    have data, and two days silently skips a day that does.

    The URLs are compared to each other rather than to a literal because
    fetch() derives the first day from datetime.now(UTC), and the suite must
    not depend on the wall clock.
    """
    client = _FakeClient([httpx.HTTPError("not ready"), _Response(_payload())])
    source = WikipediaSource(client=client)

    items = source.fetch(limit=50)

    assert items
    assert len(client.urls) == 2
    first, second = (_day_from_url(url) for url in client.urls)
    assert second == first - timedelta(days=1)


def test_exhausting_every_attempt_raises_source_error():
    client = _FakeClient([httpx.HTTPError("down")] * MAX_DAY_ATTEMPTS)
    source = WikipediaSource(client=client)

    with pytest.raises(SourceError):
        source.fetch(limit=50)

    assert len(client.urls) == MAX_DAY_ATTEMPTS


def test_a_payload_with_only_structural_pages_raises_source_error():
    """An empty result after filtering is an outage-shaped condition, so it
    becomes SourceError and CompositeSource degrades to a Lemmy-only run."""
    payload = _payload()
    payload["items"][0]["articles"] = [{"article": "Main_Page", "views": 1, "rank": 1}]
    client = _FakeClient([_Response(payload)] * MAX_DAY_ATTEMPTS)
    source = WikipediaSource(client=client)

    with pytest.raises(SourceError):
        source.fetch(limit=50)


def test_a_changed_payload_shape_crashes_rather_than_looking_like_an_outage():
    """A missing 'articles' key is a contract break, not an unreachable host,
    so it must not be swallowed into SourceError and reported as a down
    platform. The day fields are present and valid on purpose: the KeyError
    has to come from the articles lookup itself, or softening that lookup to
    .get("articles", []) would leave this test green — _fetch_day reads the
    date fields first, so an incomplete payload raises on "month" instead.
    """
    payload = {
        "items": [
            {"project": "en.wikipedia", "year": "2026", "month": "08", "day": "20"}
        ]
    }
    client = _FakeClient([_Response(payload)])
    source = WikipediaSource(client=client)

    with pytest.raises(KeyError, match="articles"):
        source.fetch(limit=50)


def test_limit_is_applied_after_filtering():
    """The budget buys real articles, not Main_Page and friends."""
    source = WikipediaSource(client=_FakeClient([_Response(_payload())]))

    items = source.fetch(limit=2)

    assert len(items) == 2
    assert {i.title for i in items} == {"Hayden Panettiere", "Natalie Harp"}


def test_the_configured_contact_reaches_the_request_headers():
    """Wikimedia's API policy warns that generic agents may be rate-limited
    or blocked outright, so what matters is the header the client will send,
    not the string the source happens to store. Asserting the attribute
    would stay green if the headers= argument were dropped from the client.
    """
    source = WikipediaSource(contact="https://example.org/bot")

    # Substring, not equality: the version prefix is free to change, and
    # pinning it would fail on a release bump that broke nothing. What must
    # hold is that the header exists at all and carries the contact — the
    # KeyError if headers= were dropped is the break worth catching.
    assert "https://example.org/bot" in source._client.headers["User-Agent"]


def test_a_non_default_project_reaches_the_url_the_id_and_the_permalink():
    """`project` decides which wiki is measured and is threaded through three
    places. Only the URL is obvious when it is dropped: a hardcoded
    en.wikipedia.org permalink sends every reader of a de.wikipedia run to
    the wrong article, and a project-less source_id makes the same article
    on two wikis look like one item to CompositeSource.
    """
    client = _FakeClient([_Response(_payload())])
    source = WikipediaSource(project="de.wikipedia", client=client)

    items = source.fetch(limit=50)

    hayden = next(i for i in items if i.title == "Hayden Panettiere")
    assert "/de.wikipedia/all-access/" in client.urls[0]
    assert hayden.source_id == "de.wikipedia:Hayden_Panettiere:2026-08-20"
    assert hayden.permalink == "https://de.wikipedia.org/wiki/Hayden_Panettiere"


def test_from_settings_wires_the_project_and_contact_through():
    """from_settings is plumbing, so it fails silently: a dropped project or
    contact only shows up in the request that goes out.
    """
    settings = Settings(
        _env_file=None,
        wikipedia_project="fr.wikipedia",
        wikipedia_contact="https://example.org/bot",
    )

    source = WikipediaSource.from_settings(settings)
    source._client = _FakeClient([_Response(_payload())])
    source.fetch(limit=1)

    assert "/fr.wikipedia/all-access/" in source._client.urls[0]
    assert "https://example.org/bot" in source.user_agent
