Verbatim reviewer output, Run 4 (cold, untuned, corrected prompt).

Dispatched: one general-purpose subagent, model opus, prompt lifted from
`.claude/skills/reviewing-plan-tests/reviewer-prompt.md` with every
placeholder filled. Working root: a detached `git worktree` at `5ed6747`.
Everything below the rule is the reviewer's output exactly as returned.

---

Rubric read: `C:\Users\gwynn\.claude\plugins\cache\claude-plugins-official\superpowers\6.2.0\skills\test-driven-development\writing-good-tests.md`

```
1. Every test names the break it catches
2. Every test exercises the real thing
```

**Tests audited:** 37 (Tasks 1-5) — **Findings:** 11

### Finding 1: `_bare_settings` (and every test built on it)

- **Location:** Task 1, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:63`)
- **Rule:** Project convention — hermetic by construction; a test whose outcome depends on the ambient environment is a defect.
- **Why it fails:** `_env_file=None` disables only the dotenv *file*. pydantic-settings' `EnvSettingsSource` still reads `os.environ`, and this repo's `tests/conftest.py` has no env-stripping fixture at all (`grep -rn "delenv\|autouse" tests/` returns nothing) — the convention describes a fixture that does not exist here. An exported `SOURCES=reddit` makes `test_sources_defaults_to_lemmy_only` fail; an exported `REDDIT_CLIENT_ID` makes `test_reddit_runs_without_credentials_when_disabled` and `test_enabling_reddit_without_credentials_is_rejected` fail; `LEMMY_INSTANCE`/`LEMMY_INCLUDE_NSFW` defeat `test_lemmy_settings_have_usable_defaults`; and Task 4's two `build_source` tests carry the same hole. The comment "No .env, no Reddit credentials — a fresh checkout's starting point" is a claim the helper does not deliver. (Task 5 Step 3's manual `Settings(anthropic_api_key='k')` check has the same problem in worse form: it reads the developer's real `.env`, so it cannot verify the documented defaults.) `test_sources_parse_from_env_strings` and `test_enabling_reddit_with_credentials_is_accepted` should also move onto the bare helper — after this fix it is the hermetic one.

- **Replacement:**

```python
# tests/conftest.py — add alongside the existing fixtures.

SETTINGS_ENV_VARS = (
    "SOURCES",
    "LEMMY_INSTANCE",
    "LEMMY_INCLUDE_NSFW",
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "REDDIT_USER_AGENT",
    "SUBREDDITS",
    "ANTHROPIC_API_KEY",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "OLLAMA_HOST",
    "POST_LIMIT",
    "TOPIC_COUNT",
    "SENTIMENT_WEIGHTS",
    "FONT_PATH",
    "TEMPLATES_DIR",
    "OUTPUT_DIR",
    "DB_PATH",
)


@pytest.fixture(autouse=True)
def _strip_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings reads os.environ as well as .env, and `_env_file=None`
    disables only the file. Without this, whether the config tests pass is
    decided by whoever exported SOURCES in their shell.
    """
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# tests/test_config.py — the helpers, now actually bare.

def _bare_settings(**overrides) -> Settings:
    """No .env, no environment, no Reddit credentials — a fresh checkout."""
    return Settings(_env_file=None, anthropic_api_key="key", **overrides)


def _settings(**overrides) -> Settings:
    defaults = dict(
        reddit_client_id="id",
        reddit_client_secret="secret",
        anthropic_api_key="key",
    )
    return Settings(_env_file=None, **{**defaults, **overrides})
```

### Finding 2: `test_unknown_source_is_rejected_with_the_valid_names`

- **Location:** Task 1, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:112`)
- **Rule:** Principle 1 — name the break; the expectation must be satisfiable only by the code under test.
- **Why it fails:** `pytest.raises(ValueError, match="mastodon")` searches the whole rendered `ValidationError`, and pydantic appends `input_value={'sources': ['mastodon'], ...}` to it. The substring "mastodon" is therefore present no matter what the validator's message says — a validator raising a bare `ValueError("bad source")`, or one that lists no valid names at all, passes this test. The one thing the test's own name promises (that the message tells the user which names *would* work) is never asserted, so dropping `. Valid: {valid}` from the message is invisible.

- **Replacement:**

```python
def test_unknown_source_is_rejected_with_the_valid_names():
    """`match="mastodon"` alone proves nothing: pydantic echoes the input
    dict into every validation error, so the rejected name is in the string
    whatever the validator says. What has to be there is the list of names
    that would have worked.
    """
    with pytest.raises(ValueError) as err:
        _bare_settings(sources="mastodon")
    message = str(err.value)
    assert "Unknown source(s): mastodon" in message
    assert "lemmy" in message
    assert "reddit" in message
```

### Finding 3: Half-configured Reddit credentials (missing test, Task 1)

- **Location:** Task 1, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:96`)
- **Rule:** Mutation check — missing validation for empty input.
- **Why it fails:** `test_enabling_reddit_without_credentials_is_rejected` only exercises the both-blank case. Mutate `_check_sources` to `if not (self.reddit_client_id or self.reddit_client_secret): raise ValueError("REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET must be set...")` and every test in the plan still passes — yet the likeliest real mistake, filling in one of the two `.env` lines, now starts a run that dies inside PRAW's auth handshake several stages later, which is exactly the failure mode Task 1 exists to prevent. The same gap hides the inverse mutation: a message that always names both variables, sending a user who set `REDDIT_CLIENT_ID` correctly to the wrong line.

- **Replacement:**

```python
@pytest.mark.parametrize(
    "credentials,named,not_named",
    [
        ({"reddit_client_id": "id"}, "REDDIT_CLIENT_SECRET", "REDDIT_CLIENT_ID"),
        (
            {"reddit_client_secret": "secret"},
            "REDDIT_CLIENT_ID",
            "REDDIT_CLIENT_SECRET",
        ),
    ],
)
def test_half_configured_reddit_is_rejected_naming_only_what_is_missing(
    credentials, named, not_named
):
    """Filling in one of the two .env lines is the likeliest way to get this
    wrong. A check that fires only when both are blank lets the run start and
    die inside PRAW instead, and a message naming the variable the user
    already set points them at the wrong line.
    """
    with pytest.raises(ValueError) as err:
        _bare_settings(sources="reddit", **credentials)
    message = str(err.value)
    assert named in message
    assert not_named not in message
```

### Finding 4: `_view` — the Lemmy fixture does not mirror the real payload

- **Location:** Task 2, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:265`)
- **Rule:** Principle 2 — "Mirror real data completely… all documented fields"; project convention on fixtures reproducing the real structure in full.
- **Why it fails:** `_view` carries exactly the eight keys `_to_post` reads today, and `StubResponse` wraps them in a `{"posts": [...]}` envelope with no `next_page`. A real `PostView` from `/api/v3/post/list` carries `post.nsfw`, `post.url`, `post.thumbnail_url`, `post.removed`/`deleted`/`locked`, `counts.upvotes`/`downvotes`, and a whole `creator` object. The first change that reads any of them — client-side NSFW filtering, using `url` for link posts, skipping removed posts — will be written against a fixture where the key does not exist, so the test either `KeyError`s at authoring time and gets "fixed" by adding just that key, or silently exercises the `.get()` default while the real payload takes the other branch. The plan's own Task 2 header notes NSFW is an API-side concern; a fixture with no `nsfw` field cannot demonstrate that.

- **Replacement:**

```python
def _view(ap_id, title, score=10, comments=2, community="cats", body="", nsfw=False):
    """Mirrors a Lemmy v3 PostView as lemmy.world returns it, including the
    fields the mapper ignores today: the next change to read `nsfw` or `url`
    must find them here rather than inventing them.
    """
    return {
        "post": {
            "id": 12345,
            "name": title,
            "url": None,
            "body": body,
            "creator_id": 999,
            "community_id": 42,
            "removed": False,
            "locked": False,
            "published": "2026-08-18T09:00:00.123456Z",
            "updated": None,
            "deleted": False,
            "nsfw": nsfw,
            "embed_title": None,
            "embed_description": None,
            "embed_video_url": None,
            "thumbnail_url": None,
            "ap_id": f"https://lemmy.world/post/{ap_id}",
            "local": True,
            "language_id": 37,
            "featured_community": False,
            "featured_local": False,
        },
        "creator": {
            "id": 999,
            "name": "someone",
            "display_name": None,
            "banned": False,
            "published": "2024-01-01T00:00:00.000000Z",
            "actor_id": "https://lemmy.world/u/someone",
            "local": True,
            "deleted": False,
            "bot_account": False,
            "instance_id": 1,
        },
        "community": {
            "id": 42,
            "name": community,
            "title": community.title(),
            "removed": False,
            "published": "2023-06-01T00:00:00.000000Z",
            "updated": None,
            "deleted": False,
            "nsfw": False,
            "actor_id": f"https://lemmy.world/c/{community}",
            "local": True,
            "hidden": False,
            "posting_restricted_to_mods": False,
            "instance_id": 1,
        },
        "creator_banned_from_community": False,
        "banned_from_community": False,
        "creator_is_moderator": False,
        "creator_is_admin": False,
        "counts": {
            "post_id": 12345,
            "comments": comments,
            "score": score,
            "upvotes": score + 3,
            "downvotes": 3,
            "published": "2026-08-18T09:00:00.123456Z",
            "newest_comment_time": "2026-08-18T10:00:00.000000Z",
            "featured_community": False,
            "featured_local": False,
            "hot_rank": 1500,
            "hot_rank_active": 1400,
            "controversy_rank": 0.0,
            "scaled_rank": 1600,
            "community_id": 42,
            "instance_id": 1,
        },
        "subscribed": "NotSubscribed",
        "saved": False,
        "read": False,
        "hidden": False,
        "creator_blocked": False,
        "unread_comments": 0,
    }


class StubResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class StubClient:
    """Returns one canned page per (sort, page); anything unlisted is empty."""

    def __init__(self, pages):
        self._pages = pages
        self.calls = []
        self.urls = []

    def get(self, url, params):
        self.urls.append(url)
        self.calls.append(params)
        key = (params["sort"], params["page"])
        # The real envelope carries next_page alongside posts.
        return StubResponse({"posts": self._pages.get(key, []), "next_page": None})
```

### Finding 5: `test_respects_the_limit` (Lemmy)

- **Location:** Task 2, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:393`)
- **Rule:** Principle 1 — the expectation must be hand-derived against the real behaviour.
- **Why it fails:** This one does not pass. `fetch(limit=5)` computes `per_sort = max(1, ceil(5 / 2)) = 3`; `_fetch_sort("Hot", 3)` returns `collected[:3]`, and `("Scaled", 1)` is absent from the fixture so Scaled contributes nothing. The call returns **3** posts, not 5, and Task 2 Step 4's "Expected: PASS, all tests" is wrong. The expectation was transcribed from `tests/test_sources_reddit.py:101`, where a single listing owns the entire budget; Lemmy splits it across `SORTS`. Populating both listings makes the test assert what its name says, and the shortfall behaviour deserves its own pin — it is a real design choice (matching `CompositeSource`'s "a shortfall is not redistributed") that currently nothing records.

- **Replacement:**

```python
def test_respects_the_limit():
    """Both listings are populated on purpose: the budget is split across
    SORTS, so a single-listing fixture would make this assert the divider
    rather than the limit.
    """
    pages = {
        ("Hot", 1): [_view(f"h{n}", f"T{n}") for n in range(50)],
        ("Scaled", 1): [_view(f"s{n}", f"U{n}") for n in range(50)],
    }
    assert len(_source(pages).fetch(limit=5)) == 5


def test_a_single_populated_listing_returns_only_its_share():
    """Hot alone can spend only ceil(limit / 2) and the shortfall is not
    redistributed, matching CompositeSource. Pinning it means a future
    top-up pass has to change a test rather than slip in unnoticed.
    """
    pages = {("Hot", 1): [_view(f"h{n}", f"T{n}") for n in range(50)]}
    assert len(_source(pages).fetch(limit=5)) == 3
```

### Finding 6: `test_stops_paging_on_an_empty_page`

- **Location:** Task 2, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:384`)
- **Rule:** Warning sign — "The test can fail only through a panic, crash, or missing selector"; mutation check.
- **Why it fails:** The mutation this test targets is deleting `if not views: break`. With that gone, `collected` never grows, `while len(collected) < budget` never terminates, and `page` increments forever against a stub that answers instantly — the run hangs and `assert len(source._client.calls) <= 4` is never reached. A hung suite reports nothing; CI kills it on a timeout with no failing test named. The guard has to live in the stub, where it can raise. The `<= 4` bound is also loose enough to hide a listing that is paged once too often; the exact page sequence is knowable and worth asserting.

- **Replacement:**

```python
class ExhaustibleClient(StubClient):
    """Fails loudly instead of hanging. Without the empty-page break the
    paging loop never terminates, and a hung test reports nothing at all.
    """

    def __init__(self, pages, max_calls=8):
        super().__init__(pages)
        self._max_calls = max_calls

    def get(self, url, params):
        if len(self.calls) >= self._max_calls:
            raise AssertionError(
                f"paging did not stop: {self._max_calls} requests issued"
            )
        return super().get(url, params)


def test_stops_paging_on_an_empty_page():
    """A listing shorter than the budget must end the loop: one page of
    content, one empty page that ends it, then the same for the next sort.
    """
    source = LemmySource(
        instance="https://lemmy.world",
        client=ExhaustibleClient({("Hot", 1): [_view("a1", "Only one")]}),
    )
    source.fetch(limit=500)
    assert [params["page"] for params in source._client.calls] == [1, 2, 1]
```

### Finding 7: `test_created_at_is_timezone_aware_when_the_instance_omits_the_zone`

- **Location:** Task 2, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:345`)
- **Rule:** Principle 1 — derive expectations as literals; the assertion must distinguish right from wrong, not present from absent.
- **Why it fails:** `assert post.created_at.tzinfo is not None` passes for *any* zone the mapper attaches. `parsed.replace(tzinfo=timezone(timedelta(hours=5)))`, or a fallback of `datetime.now(UTC)` when the parse yields a naive value, both satisfy it while shifting every velocity in the scorer by hours. The exact value is available as a literal, and the sibling test at line 332 already uses that shape.

- **Replacement:**

```python
def test_naive_published_is_read_as_utc():
    """Instances that omit the zone send UTC. Asserting only that tzinfo is
    set would pass for any zone attached — a +05:00 reading shifts every
    score-per-hour in the scorer and still satisfies it.
    """
    view = _view("a1", "T")
    view["post"]["published"] = "2026-08-18T09:00:00"
    post = _source({("Hot", 1): [view]}).fetch(limit=10)[0]
    assert post.created_at == datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
```

### Finding 8: The request the source actually issues (missing test, Task 2)

- **Location:** Task 2, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:398`)
- **Rule:** Mutation check — wrong constant or argument; "test the contract your code makes at its boundaries".
- **Why it fails:** `StubClient.get` discards `url` entirely and the tests assert only `limit` and `show_nsfw`. Mutate the endpoint to `/api/v4/post/list` (404 per the plan's own verified API notes) or `type_` to `"Local"` and every Lemmy test still passes, because the stub keys off `(sort, page)` alone. `type_=All` is precisely the setting the README paragraph in Task 5 relies on — "because instances federate, one already returns posts from across the network" — so flipping it silently shrinks the corpus to one server's own posts with no error anywhere. This finding assumes the `StubClient` from Finding 4, which records URLs.

- **Replacement:**

```python
def test_requests_the_federated_v3_listing_endpoint():
    """`/api/v4` is a 404 and `type_=Local` quietly drops every federated
    post — the exact claim the README makes about querying one instance.
    Neither mutation changes a single mapped field, so only the request
    itself can catch them.
    """
    source = _source({("Hot", 1): [_view("a1", "T")]})
    source.fetch(limit=1)

    assert source._client.urls[0] == "https://lemmy.world/api/v3/post/list"
    params = source._client.calls[0]
    assert params["type_"] == "All"
    assert params["sort"] == "Hot"
    assert params["page"] == 1
```

### Finding 9: An HTTP error status from the instance (missing test, Task 2)

- **Location:** Task 2, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:435`)
- **Rule:** Mutation check — missing side effect; Principle 2 — give each branch its own fixture.
- **Why it fails:** `StubResponse.raise_for_status` returns `None` in every fixture, and the only failure path exercised is `FailingClient` raising `ConnectError` from `get()` itself. Delete `response.raise_for_status()` from `_fetch_sort` and no test changes colour — but a real 503 from lemmy.world then reaches `response.json()["posts"]`, raises `KeyError` on the error body, and the run crashes with a contract-break traceback for what is an ordinary outage. That inverts the Global Constraint the whole task is built around. A 5xx is also the most likely failure a public instance actually produces, and it is the one branch of the transport/contract split that has no fixture.

- **Replacement:**

```python
def test_an_error_status_is_skipped_like_an_outage_not_raised_as_a_bug(caplog):
    """A 503 is an outage, not a changed payload: it must be warned and
    skipped. Without raise_for_status() it becomes a KeyError on the error
    body and takes the whole run down on a bad afternoon at lemmy.world.
    """

    class ErrorStatusResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "503 Service Unavailable",
                request=httpx.Request("GET", "https://lemmy.world"),
                response=httpx.Response(503),
            )

        def json(self):
            return {"error": "service_unavailable"}

    class ErrorStatusClient:
        def get(self, url, params):
            return ErrorStatusResponse()

    source = LemmySource(instance="https://lemmy.world", client=ErrorStatusClient())
    with caplog.at_level(logging.WARNING):
        with pytest.raises(SourceError, match="no posts"):
            source.fetch(limit=10)

    assert "Hot" in caplog.text
    assert "Scaled" in caplog.text
```

### Finding 10: `CompositeSource` swallowing a mapping bug (missing test, Task 3)

- **Location:** Task 3, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:758`)
- **Rule:** Mutation check — wrong branch handler; Global Constraint at plan line 18.
- **Why it fails:** Every failing double in this file (`FailingSource`) raises `SourceError`, so `except SourceError` and `except Exception` are indistinguishable to the suite. The plan ships `except Exception`, which means a `ValueError` or `KeyError` out of `LemmySource._to_post` — the exact bug `test_mapping_bug_in_to_post_propagates_not_swallowed` (line 477) exists to force into the open — is caught one layer up, logged as "Skipping source lemmy", and the run continues with a platform silently missing. The invariant is pinned inside the source and then undone by its wrapper, and no test notices. The two tests below pin both halves of the intended split; applying them requires narrowing the composite's guard to `except (SourceError, httpx.HTTPError)`, which is the planner's call to make — the point is that the current suite cannot tell the two designs apart.

- **Replacement:**

```python
# Add `import httpx` to the imports of tests/test_sources_composite.py.


class BuggySource:
    """A pure-mapping bug inside a child source, not an outage."""

    name = "lemmy"

    def fetch(self, limit):
        raise ValueError("simulated mapping bug")


class OfflineSource:
    """A client library's own transport error — a genuine outage."""

    name = "lemmy"

    def fetch(self, limit):
        raise httpx.ConnectError("connection refused")


def test_a_bug_inside_a_source_propagates_rather_than_looking_like_an_outage():
    """test_sources_lemmy.py pins that a mapping bug crashes instead of
    being logged as an unreachable platform. A blanket `except Exception`
    here undoes that one layer up: the platform vanishes from the run and
    the only symptom is thinner output.
    """
    composite = CompositeSource(
        [BuggySource(), StubSource("reddit", [_post("reddit", "r1")])]
    )
    with pytest.raises(ValueError, match="simulated mapping bug"):
        composite.fetch(limit=10)


def test_a_transport_failure_from_a_source_is_still_skipped(caplog):
    """The other half of the same rule: a network error is an outage and
    must not cost the run the platforms that are up.
    """
    composite = CompositeSource(
        [OfflineSource(), StubSource("reddit", [_post("reddit", "r1")])]
    )
    with caplog.at_level(logging.WARNING):
        posts = composite.fetch(limit=10)

    assert [post.source_id for post in posts] == ["r1"]
    assert "lemmy" in caplog.text
```

### Finding 11: The CLI passing the configured source into the pipeline (missing test, Task 4)

- **Location:** Task 4, Step 5 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:971`)
- **Rule:** Mutation check — missing side effect; the task's stated purpose has no test.
- **Why it fails:** Task 4 opens with "This is the task that actually switches Reddit off", and Step 4 changes `source=RedditSource.from_settings(settings)` to `source=build_source(settings)` in `zeitgeist/cli.py:92`. Nothing asserts it. Both CLI tests stub `run_pipeline` and only inspect printed output, so skipping Step 4 entirely leaves the suite green while every run still scrapes Reddit; Step 7's `python -c` check exercises `build_source` directly and never touches the CLI. The revised `_set_minimal_settings_env` already sets `SOURCES=lemmy`, so capturing the kwargs `run_pipeline` receives closes the gap in four lines.

- **Replacement:**

```python
def test_run_passes_the_configured_sources_into_the_pipeline(monkeypatch, tmp_path):
    """Task 4's whole point is that the CLI stops hard-coding Reddit. With
    run_pipeline stubbed, nothing else notices if `source=` still reads
    RedditSource.from_settings — the run would just scrape the platform the
    config disabled.
    """
    _set_minimal_settings_env(monkeypatch, tmp_path)
    run_dir = tmp_path / "output" / "run-1"
    run_dir.mkdir(parents=True)
    captured: dict[str, object] = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return run_dir

    monkeypatch.setattr(cli_module, "run_pipeline", _capture)

    assert main(["run"]) == 0
    assert captured["source"].name == "lemmy"
```

Note, not a test finding: `_to_post` at plan line 607 never passes `fetched_at` to `Post(...)`, and `Post.fetched_at` is required with no default (`zeitgeist/models.py:47`) — compare `RedditSource._to_post` at `zeitgeist/sources/reddit.py:102`. Every Lemmy test will fail with a `ValidationError`, so Task 2 Step 4's "Expected: PASS" cannot hold until that line is added. The tests do catch it, so it is an implementation defect rather than a test one.
