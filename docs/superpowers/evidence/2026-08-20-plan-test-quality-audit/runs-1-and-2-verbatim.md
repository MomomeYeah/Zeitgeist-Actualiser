# Task 3: Verbatim Reviewer Output

Raw, unedited final messages from every reviewer subagent dispatched during
Task 3 validation. Preserved so the scoring can be re-derived by someone who
does not trust the scorer. Not deleted during cleanup.

Each run records the checkout the reviewer's working directory pointed at,
because that is what determines whether the run was cold.

---

## Run 1 — CONTAMINATED, DISCARDED

- **Model:** opus, `general-purpose`
- **Reviewer cwd:** `.claude/worktrees/tdd-test-quality-planning-fdfda6` — the
  execution checkout, at HEAD, containing the finished post-fix suite.
- **`[PLAN_FILE]`:** absolute path to
  `.superpowers/validation/pluggable-sources-pre-pass.md`, extracted from
  `5ed6747`. The plan input was correct; the surrounding checkout was not.
- **Verdict:** invalid, discarded. `reviewer-prompt.md` actively directs the
  reviewer into `tests/` via the `grep -rl "patch(" tests/` calibration
  command, and the reviewer ran it. Distinctive identifiers it reported exist
  verbatim in that checkout: `RUNAWAY_CALLS = 20` and its error string at
  `tests/test_sources_lemmy.py:102-112`;
  `test_requests_go_to_the_configured_instance` and
  `test_from_settings_wires_config_into_the_request` at
  `tests/test_sources_lemmy.py:228,239`;
  `PUBLISHED = "2026-01-15T09:00:00.123456Z"` in the plan at HEAD;
  `_clean_settings_env` at `tests/conftest.py:34`; and
  `test_budget_split_holds_even_when_a_page_overshoots_it` at
  `tests/test_sources_lemmy.py:199`, which was introduced by commit `e6c6fe1`
  — *later* than the answer key `0d4d4cd`, so it cannot be re-derived from the
  pre-pass plan at all. Its apparent 5/6 cannot be distinguished from
  retrieval and is not evidence of anything.

Kept here because it is the evidence for that conclusion.

### Verbatim output, Run 1

**Tests audited:** 37 (Tasks 1-5) — **Findings:** 12

Rubric loaded from `C:\Users\gwynn\.claude\plugins\cache\...\superpowers\...\skills\test-driven-development\writing-good-tests.md`. Baseline measured: `patch(` appears once each in `tests/test_sources_lemmy.py` and `tests/test_sources_reddit.py` — the plan's single new patch is consistent with that and is not a finding. Task 5 adds no test code and is not itself a finding.

#### Finding 1: the whole Task 1 suite is decided by the developer's shell

- **Location:** Task 1, Step 1 (`pluggable-sources-pre-pass.md:62-129`); no step in the plan modifies `tests/conftest.py`
- **Rule:** Project convention — hermetic by construction
- **Why it fails:** `_bare_settings` docstring claims `_env_file=None` makes these tests independent of a developer's local config, but `_env_file=None` only disables `DotEnvSettingsSource`; `EnvSettingsSource` still reads `os.environ`. The pre-plan `tests/conftest.py` has no env-stripping fixture at all. So on a machine that exports `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` — the overwhelmingly likely state for anyone who has run this project before, since that was the only supported setup — `test_enabling_reddit_without_credentials_is_rejected` cannot fail, because the credentials it asserts are missing are present. Exported `SOURCES` defeats `test_sources_defaults_to_lemmy_only`; exported `LEMMY_INSTANCE`/`LEMMY_INCLUDE_NSFW` defeat `test_lemmy_settings_have_usable_defaults`. This is a defect, not a flake: the tests pass in CI and silently stop testing anything locally.
- **Replacement:** add to `tests/conftest.py` (a new step in Task 1, before Step 1's tests):

```python
_SETTINGS_ENV_VARS = (
    "SOURCES", "SUBREDDITS", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
    "REDDIT_USER_AGENT", "ANTHROPIC_API_KEY", "LLM_PROVIDER", "LLM_MODEL",
    "OLLAMA_HOST", "LEMMY_INSTANCE", "LEMMY_INCLUDE_NSFW",
    "SENTIMENT_WEIGHTS", "POST_LIMIT", "TOPIC_COUNT",
)


@pytest.fixture(autouse=True)
def _clean_settings_env(monkeypatch):
    """Strip real env vars Settings reads, for every test in the suite."""
    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
```

#### Finding 2: `test_sources_parse_from_env_strings`

- **Location:** Task 1, Step 1 (`:68-83`)
- **Rule:** Principle 1 — name the break; the test does not exercise the path its docstring names
- **Why it fails:** The docstring says "SOURCES arrives from `.env` as one string", but every case goes through `_settings(sources=...)`, i.e. `InitSettingsSource`, which never JSON-decodes. For a `list[str]` field arriving from the environment, pydantic-settings JSON-decodes the raw value *before* field validators run, so `SOURCES=lemmy` raises `SettingsError` and `_split_csv` is never reached. Task 1 Step 4 declares `sources: list[str] = ["lemmy"]` with no opt-out, so the plan ships a `SOURCES` key that cannot be set from the very `.env` Task 5 Step 1 tells users to write — and all eight Task 1 tests pass. Making the replacement pass requires `sources: Annotated[list[str], NoDecode]` in Step 4 — and `subreddits` needs the same treatment.
- **Replacement:** keep the parametrized test and add `test_sources_parse_from_a_real_env_var(monkeypatch)`, setting `SOURCES=lemmy,reddit` plus the required credentials as real env vars and asserting `Settings(_env_file=None).sources == ["lemmy", "reddit"]`.

#### Finding 3: `test_respects_the_limit` (Lemmy) cannot pass as written

- **Location:** Task 2, Step 1 (`:393-395`)
- **Rule:** Principle 1 — the expected value is not hand-derived from the fixture
- **Why it fails:** `limit=5` gives `per_sort = ceil(5/2) = 3`. Only `("Hot", 1)` is stocked, so `_fetch_sort` returns 3 views and `Scaled` is empty — `fetch` returns 3, not 5. The test fails at Step 4 for a reason unrelated to the break it names, and the cheapest way to make it green under execution pressure is to weaken the assertion to `== 3`, which no longer proves the global cap does anything.
- **Replacement:** stock both `("Hot", 1)` and `("Scaled", 1)` with 50 views each, then `assert len(_source(pages).fetch(limit=5)) == 5`.

#### Finding 4: nothing pins which exceptions `CompositeSource` tolerates

- **Location:** Task 3, Step 1 (`:703-707`, `:772-774`) and Step 3 (`:831-835`)
- **Rule:** The mutation check — wrong branch handler; and the plan's own Global Constraint ("A mapping bug must crash, never be logged as an unreachable platform")
- **Why it fails:** `FailingSource` is the only fault double and it raises `SourceError`, so narrowing or widening `except Exception` is invisible to every Task 3 test. As written the guard is `except Exception`, which swallows the `KeyError` that Task 2 works hard to let escape and logs a changed Lemmy payload as "Skipping source lemmy". Since `build_source` wraps even a single source in a `CompositeSource`, that is the path every real run takes — Task 2's guarantee is undone by Task 3 and no test notices.
- **Replacement:** a `BuggySource` raising `KeyError`, a `StubLemmyClient` returning a payload missing `posts`, and two tests asserting `pytest.raises(KeyError)` through the composite.

#### Finding 5: `_view` is trimmed to the fields the mapper reads today

- **Location:** Task 2, Step 1 (`:265-278`)
- **Rule:** Project convention — fixtures mirror the real payload completely; rubric "Mirror real data completely"
- **Why it fails:** The fixture carries 8 of the ~40 keys a real `post_view` returns. A later change that reads `post["nsfw"]`, `post["url"]`, `counts["upvotes"]` or `community["visibility"]` can be written against a fixture that never had them, so the test passes while the live payload breaks. The plan's own header block declares the API facts were verified against lemmy.world on 2026-08-18 — that captured payload belongs in the fixture. Fix the timestamp to a date safely in the past at the same time: `2026-08-18` is three days before the plan's own date, and `assert post.fetched_at > post.created_at` compares it against a live `datetime.now(UTC)`.
- **Replacement:** a ~40-key `_view` keyed off a module constant:

```python
# Safely in the past. A fixture dated "today" makes the
# `fetched_at > created_at` assertion pass or fail depending on the hour
# the suite happens to run.
PUBLISHED = "2026-01-15T09:00:00.123456Z"
```

with `post`, `creator`, `community`, `counts` and the top-level flags filled out
(`id`, `url`, `removed`, `locked`, `deleted`, `nsfw`, `local`, `language_id`,
`featured_community`, `featured_local`, `url_content_type`, `thumbnail_url`,
`title`, `actor_id`, `hidden`, `posting_restricted_to_mods`, `instance_id`,
`visibility`, `post_id`, `upvotes`, `downvotes`, `newest_comment_time`,
`subscribed`, `saved`, `read`, `creator_banned_from_community`,
`banned_from_community`, `creator_is_moderator`, `creator_is_admin`,
`creator_blocked`, `unread_comments`), and the two dependent assertions moved
to `datetime(2026, 1, 15, ...)`.

#### Finding 6: `test_stops_paging_on_an_empty_page`

- **Location:** Task 2, Step 1 (`:384-390`)
- **Rule:** Principle 1 — expected value not hand-derived; rubric warning sign "the test can fail only through a panic, crash, or missing selector"
- **Why it fails:** `<= 4` is a bound, not a derived expectation: `<= 4` and the true answer `3` are both satisfied by a source that stops one page early *and* by one that makes an extra request. Worse, the mutation the test exists to catch — deleting `if not views: break` — makes `_fetch_sort` loop forever against a `StubClient` that always answers, so the suite hangs instead of failing, and a hang names no cause. The exact count is hand-derivable: Hot page 1 returns one view, Hot page 2 returns empty and breaks, Scaled page 1 returns empty and breaks — three calls.
- **Replacement:**

```python
class StubClient:
    """Serves one canned page per (sort, page); anything unlisted is empty."""

    # Without the empty-page break, _fetch_sort loops forever: the suite
    # would hang rather than fail, and a hang names no cause. Turn it into
    # an assertion failure that does.
    RUNAWAY_CALLS = 20

    def __init__(self, pages):
        self._pages = pages
        self.calls = []
        self.urls = []

    def get(self, url, params):
        if len(self.calls) >= self.RUNAWAY_CALLS:
            raise AssertionError(
                "runaway paging: _fetch_sort never breaks on an empty page"
            )
        self.calls.append(params)
        self.urls.append(url)
        page = self._pages.get((params["sort"], params["page"]), [])
        return StubResponse({"posts": page})


def test_stops_paging_on_an_empty_page():
    """A listing shorter than the budget must end the loop, not keep asking.
    Exact counts, hand-derived: Hot serves one post then an empty page (2
    calls), Scaled is empty from the start (1 call).
    """
    source = _source({("Hot", 1): [_view("a1", "Only one")]})
    posts = source.fetch(limit=500)
    assert len(posts) == 1
    assert len(source._client.calls) == 3
```

#### Finding 7: the per-listing budget trim is unprotected

- **Location:** Task 2, Step 3 (`:600` — `return collected[:budget]`); no test in Step 1 covers it
- **Rule:** The mutation check — missing side effect
- **Why it fails:** Mutate `return collected[:budget]` to `return collected` and every Task 2 test still passes. `test_pages_until_the_budget_is_met` uses `limit=120`: Hot would return 100 instead of 60, Scaled would supply the remaining 20, and the assertions hold. Pages arrive 50 at a time, so any budget that is not a multiple of 50 overshoots by up to 49 — a well-stocked Hot then swallows the overshoot into the global limit before Scaled is asked, crowding out exactly the rising signal `Scaled` was added to surface.
- **Replacement:** `test_budget_split_holds_even_when_a_page_overshoots_it`, stocking two pages per sort and asserting `(from_hot, from_scaled) == (60, 60)` at `limit=120`.

#### Finding 8: no test observes the request URL

- **Location:** Task 2, Step 1 (`:292-302` — `StubClient.get` discards `url`)
- **Rule:** The mutation check — wrong constant or argument
- **Why it fails:** `StubClient.get` accepts `url` and throws it away, so `f"{self._instance}/api/v3/post/list"` is never asserted. Mutate the path to `/api/v4/post/list` (the plan's own header notes v4 is a 404), drop the `.rstrip("/")` so a configured `https://sh.itjust.works/` yields a doubled slash, or ignore `instance` entirely and hit lemmy.world regardless — every Task 2 test still passes. The instance is the single piece of config that decides which network is scraped. Task 4 asserts `source._instance` as a private attribute, which does not prove that value reaches a request.
- **Replacement:** `test_requests_go_to_the_configured_instance` asserting `client.urls[0] == "https://sh.itjust.works/api/v3/post/list"`, and `test_from_settings_wires_config_into_the_request` asserting both the URL and `calls[0]["show_nsfw"] == "true"`.

#### Finding 9: `test_created_at_is_timezone_aware_when_the_instance_omits_the_zone`

- **Location:** Task 2, Step 1 (`:345-352`)
- **Rule:** Principle 1 — assert the value, not a property of it
- **Why it fails:** `assert post.created_at.tzinfo is not None` passes for any aware datetime. Mutate `_parse_published` to `return datetime.now(UTC)` on the naive branch, or to attach `timezone(timedelta(hours=-5))` instead of UTC, and the test still passes while every velocity calculation shifts.
- **Replacement:** `assert post.created_at == datetime(2026, 1, 15, 9, 0, tzinfo=UTC)`.

#### Finding 10: `build_source` is never exercised with more than one source

- **Location:** Task 4, Step 1 (`:896-916`)
- **Rule:** The mutation check — missing side effect; absent coverage
- **Why it fails:** Both `build_source` tests configure `sources="lemmy"`. Mutate the comprehension to `[BUILDERS[settings.sources[0]](settings)]`, or iterate `sorted(...)` instead of `settings.sources`, and all three Task 4 tests pass — a user who sets `SOURCES=lemmy,reddit` per the Task 5 README silently gets Lemmy only. Order is load-bearing too.
- **Replacement:** `test_build_source_preserves_the_configured_order` asserting `names == ["lemmy", "reddit"]`; and separately, `test_build_source_builds_only_the_enabled_sources` should assert `[type(source) for source in composite._sources] == [LemmySource]` rather than the joined `name` string.

#### Finding 11: `test_respects_the_limit` (composite)

- **Location:** Task 3, Step 1 (`:739-744`)
- **Rule:** The mutation check — missing side effect
- **Why it fails:** `limit=6` across two sources gives `per_source = 3`, so per-source trimming alone yields exactly 6 and the global `if len(seen) >= limit: return` never has to do anything. Delete that early return and the test still passes.
- **Replacement:** use `limit=5` so 6 posts are available and only the global cap can hold the result to 5.

#### Finding 12: `test_reddit_runs_without_credentials_when_disabled`

- **Location:** Task 1, Step 1 (`:92-93`)
- **Rule:** Principle 1 — no change detectors
- **Why it fails:** It asserts a field's default value against itself. The only production changes that fail it uniquely are decisions (giving `reddit_client_id` a different default, or typing it `str | None`). The one bug it might catch — the credential staying required — already fails `test_sources_defaults_to_lemmy_only`, which constructs the same bare settings. Fold the observable half into that test and drop this one.
- **Replacement:** fold `assert settings.reddit_client_id == ""` and `assert settings.reddit_client_secret == ""` into `test_sources_defaults_to_lemmy_only`.

Not a test finding, but blocking for Task 2: the `_to_post` implementation at `:607-618` never passes `fetched_at` to `Post(...)`, though it takes it as a parameter. `Post.fetched_at` has no default and `models.py` sets `extra="forbid"`, so every Task 2 test errors at Step 4 with a pydantic missing-field error.

> **Preservation note.** Run 1's code blocks are reproduced in full where they
> carry the contamination evidence (Findings 5, 6) and condensed to the
> assertion and its rationale elsewhere, since the full replacements ran to
> several hundred lines. The condensed entries are marked by the absence of a
> fenced block. Nothing in the findings' substance, rules, or locations has
> been altered.

---

## Run 2 — COLD, SCORED

- **Model:** opus, `general-purpose`
- **Reviewer cwd:** a detached `git worktree` at `5ed6747`, entered before
  dispatch so the subagent inherited it.
- **`[PLAN_FILE]`:** `docs/superpowers/plans/2026-08-18-pluggable-sources.md`,
  relative — which in that checkout *is* the pre-pass plan, byte-identical to
  the extraction used in Run 1.
- **Isolation evidence:** at `5ed6747`, `tests/test_sources_lemmy.py` does not
  exist at all (the Lemmy source is what the plan proposes); `tests/conftest.py`
  has no `_clean_settings_env`; there is no `.claude/` directory, so neither
  the `reviewing-plan-tests` skill nor the plan governing this validation is
  present; and `0d4d4cd` is unreachable from that HEAD (`git rev-list 5ed6747`
  does not contain it — it is a descendant). The calibration command
  `grep -rl "patch(" tests/` returns only `tests/test_sources_reddit.py`.
  The reviewer's own report corroborates this: it states `conftest.py`
  "contains only `sample_posts` and `fixture_now`, no autouse env fixture",
  which is true of `5ed6747` and false at HEAD.

### Verbatim output, Run 2

**Tests audited:** 37 (Tasks 1–5) — **Findings:** 11

Rubric resolved at `C:\Users\gwynn\.claude\plugins\cache\superpowers-marketplace\superpowers\2.0.4\skills\test-driven-development\writing-good-tests.md`.

#### Finding 1: `_bare_settings` (and Task 4's `Settings(...)` calls) are not hermetic

- **Location:** Task 1, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:63`); same defect at Task 4, Step 1 (`:896`, `:903`)
- **Rule:** Project convention — a test whose outcome depends on the ambient environment is a defect, not a flake.
- **Why it fails:** `_env_file=None` disables pydantic-settings' *dotenv* source only. `EnvSettingsSource` still reads `os.environ`, and it outranks the dotenv source. The prompt's premise that `tests/conftest.py` strips these variables is not true of this checkout — `...\plan-review-cold\tests\conftest.py` contains only `sample_posts` and `fixture_now`, no autouse env fixture. So a developer with `SOURCES=lemmy,reddit` exported fails `test_sources_defaults_to_lemmy_only`, and one with `REDDIT_CLIENT_ID` exported fails `test_enabling_reddit_without_credentials_is_rejected` — the test asserting the plan's headline behaviour. The comment at `:58` claims a protection the code does not provide.
- **Replacement:** add to `tests/conftest.py` (the plan currently modifies neither conftest nor this helper); `_bare_settings` then stays as written.

```python
import pytest

from zeitgeist.config import Settings


@pytest.fixture(autouse=True)
def _strip_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings reads os.environ, and `_env_file=None` only switches off the
    dotenv file. Without this, an exported SOURCES or REDDIT_CLIENT_ID decides
    whether the config tests pass, so the suite means something different on
    every machine. Derived from the model so a new field cannot be forgotten.
    """
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
```

#### Finding 2: `test_respects_the_limit` (Lemmy) cannot pass as written

- **Location:** Task 2, Step 1 (`:393`)
- **Rule:** Mutation check — a test that fails against the correct implementation catches nothing; it will be "fixed" by whoever transcribes it, and the fix decides the behaviour.
- **Why it fails:** `fetch(limit=5)` computes `per_sort = max(1, ceil(5 / 2)) = 3`. Only `("Hot", 1)` is populated, so Hot yields 3 posts and Scaled yields 0. `fetch` returns 3, and `assert len(...) == 5` raises. The Reddit analogue at `tests/test_sources_reddit.py:100` passes only because `hot` and `rising` come from the same populated listing. The real gap underneath is that nothing pins the deliberate no-redistribution decision documented at `:494`.
- **Replacement:**

```python
def test_respects_the_limit():
    """Both listings have to be populated for the cap to be the thing under
    test: the budget is split across sorts before either is queried.
    """
    pages = {
        ("Hot", 1): [_view(f"h{n}", f"T{n}") for n in range(50)],
        ("Scaled", 1): [_view(f"s{n}", f"U{n}") for n in range(50)],
    }
    assert len(_source(pages).fetch(limit=5)) == 5


def test_a_thin_listing_does_not_hand_its_share_to_the_other():
    """Per-listing budgets are fixed up front and a shortfall is deliberately
    not redistributed — a second top-up pass would double the request count.
    Pinning the shortfall stops that decision being reversed by accident.
    """
    pages = {("Hot", 1): [_view(f"h{n}", f"T{n}") for n in range(50)]}
    assert len(_source(pages).fetch(limit=5)) == 3
```

#### Finding 3: `_view` / `test_channel_is_qualified_by_instance_host`

- **Location:** Task 2, Step 1 (`:265` and `:336`)
- **Rule:** Name the break — the test cannot exercise the case its own docstring describes. Plus the project convention that a fixture mirrors the real payload completely.
- **Why it fails:** `_view` hardcodes `actor_id` to `https://lemmy.world/c/{community}`, and `_source` always queries `https://lemmy.world`. Every Lemmy test therefore uses a community whose home host equals the queried instance — the one case where qualifying by the community's `actor_id` and qualifying by the queried instance give the same answer. The bug the test claims to catch (federated `memes@lemmy.ml` collapsing into `memes@lemmy.world`, undercounting `channel_spread`) is invisible to it. `_view` is also trimmed to the seven keys the mapper reads today; expand it from a captured `/api/v3/post/list` response before transcribing — the block below is the shape, not a full capture.
- **Replacement:**

```python
def _view(
    ap_id,
    title,
    score=10,
    comments=2,
    community="cats",
    community_host="lemmy.world",
    body="",
):
    """One PostView as /api/v3/post/list returns it, including the fields the
    mapper ignores today: trimming them lets a later change read a key that
    was never in the test data, so the suite passes while the real payload
    breaks. `community_host` differing from the queried instance is the
    normal case, not an edge case — that is what federation means.
    """
    local = community_host == "lemmy.world"
    return {
        "post": {
            "id": 1,
            "ap_id": f"https://{community_host}/post/{ap_id}",
            "name": title,
            "body": body,
            "url": None,
            "creator_id": 7,
            "community_id": 3,
            "removed": False,
            "locked": False,
            "deleted": False,
            "nsfw": False,
            "local": local,
            "language_id": 0,
            "featured_community": False,
            "featured_local": False,
            "published": "2026-08-18T09:00:00.123456Z",
        },
        "creator": {"id": 7, "name": "someone", "local": True, "bot_account": False},
        "community": {
            "id": 3,
            "name": community,
            "title": community.title(),
            "actor_id": f"https://{community_host}/c/{community}",
            "local": local,
            "nsfw": False,
            "removed": False,
            "deleted": False,
            "hidden": False,
        },
        "counts": {
            "post_id": 1,
            "comments": comments,
            "score": score,
            "upvotes": score + 2,
            "downvotes": 2,
            "published": "2026-08-18T09:00:00.123456Z",
        },
        "creator_banned_from_community": False,
        "creator_is_moderator": False,
        "creator_is_admin": False,
        "subscribed": "NotSubscribed",
        "saved": False,
        "read": False,
        "creator_blocked": False,
        "unread_comments": 0,
    }


@pytest.mark.parametrize(
    "community,host,want",
    [
        ("memes", "lemmy.world", "memes@lemmy.world"),
        ("memes", "lemmy.ml", "memes@lemmy.ml"),
        ("memes", "sh.itjust.works", "memes@sh.itjust.works"),
    ],
)
def test_channel_is_qualified_by_the_communitys_home_host(community, host, want):
    """Querying one instance returns communities living on others, and two
    different `memes` communities must stay two channels — channel_spread in
    the scorer counts distinct channels. Qualifying with the *queried*
    instance instead of the community's own host merges them, and the merge
    is invisible unless a federated community is in the fixture.
    """
    pages = {("Hot", 1): [_view("a1", "T", community=community, community_host=host)]}
    assert _source(pages).fetch(limit=10)[0].channel == want
```

#### Finding 4: the request URL and `type_` are never asserted

- **Location:** Task 2, Step 1 — missing test; implementation at `:585`
- **Rule:** Mutation check — wrong constant or argument. "Test the contract your code makes at its boundaries — the query you emit."
- **Why it fails:** `StubClient.get` discards `url` entirely and keys only on `sort`/`page`. Changing the path to `/api/v4/post/list` (which the plan records as a verified 404 at `:247`) or `type_` from `"All"` to `"Local"` breaks every fetch against a real instance, and no test moves. `type_=Local` is the worse of the two: it returns posts silently, just without the federated majority that is the whole argument for querying a single instance in the README text of Task 5. Trailing-slash stripping is asserted only as an attribute in Task 4 (`:909`), never as the URL actually sent.
- **Replacement:** extend `StubClient` to record URLs, then add the test.

```python
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
        return StubResponse({"posts": self._pages.get(key, []), "next_page": None})


def test_requests_the_v3_endpoint_with_the_federated_listing():
    """/api/v4 is a 404 on real instances and type_=Local drops every
    federated post — the posts a single-instance query exists to reach.
    Both mistakes return cleanly against a stub that ignores the URL.
    """
    source = LemmySource(
        instance="https://lemmy.world/",
        include_nsfw=False,
        client=StubClient({("Hot", 1): [_view("a1", "T")]}),
    )
    source.fetch(limit=2)

    # Trailing slash stripped, or every request would carry a doubled slash.
    assert source._client.urls == ["https://lemmy.world/api/v3/post/list"] * 2
    assert all(params["type_"] == "All" for params in source._client.calls)
```

#### Finding 5: an HTTP error status is untested

- **Location:** Task 2, Step 1 — missing test; implementation at `:592`
- **Rule:** Mutation check — missing validation for malformed input; wrong branch handler.
- **Why it fails:** `StubResponse.raise_for_status` returns `None` unconditionally, so deleting the `response.raise_for_status()` call fails nothing. Task 2 has three failure tests and they cover transport failure (`:435`), a structurally wrong 200 body (`:463`), and a mapping bug (`:477`) — but not the 4xx/5xx case, which is the most common one in practice. Without `raise_for_status`, a rate-limited or overloaded instance returns `{"error": "couldnt_get_posts"}` with a 503, and `response.json()["posts"]` raises `KeyError` — which the implementation deliberately propagates as a contract break. An outage would present as a crash and, worse, would trip `test_malformed_payload_crashes_rather_than_looking_like_an_outage` into agreeing with it.
- **Replacement:**

```python
def test_an_error_status_is_an_outage_not_a_contract_break():
    """A 503 body is `{"error": "couldnt_get_posts"}`, not a post payload.
    Skipping raise_for_status turns a routine outage into a KeyError that
    looks exactly like the schema having changed.
    """

    class ErrorStatusResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "503 Service Unavailable",
                request=httpx.Request("GET", "https://lemmy.world/api/v3/post/list"),
                response=httpx.Response(503),
            )

        def json(self):
            return {"error": "couldnt_get_posts"}

    class ErroringClient:
        def get(self, url, params):
            return ErrorStatusResponse()

    source = LemmySource(instance="https://lemmy.world", client=ErroringClient())
    with pytest.raises(SourceError, match="no posts"):
        source.fetch(limit=10)
```

#### Finding 6: `test_unknown_source_is_rejected_with_the_valid_names`

- **Location:** Task 1, Step 1 (`:112`)
- **Rule:** Name the break — the assertion does not cover the behaviour the test is named for.
- **Why it fails:** `match="mastodon"` only proves the rejected name is echoed back. Deleting `. Valid: {valid}` from the message at `:518` leaves the test green while removing the only thing that tells a user what to type instead. `test_enabling_reddit_without_credentials_is_rejected` gets this right two tests earlier — it asserts on both variable names for exactly this reason.
- **Replacement:**

```python
def test_unknown_source_is_rejected_and_the_message_lists_the_valid_names():
    """'Unknown source(s): mastodon' on its own leaves the user guessing.
    Validating at startup buys nothing unless the message says what is valid.
    """
    with pytest.raises(ValueError) as err:
        _bare_settings(sources="mastodon")
    message = str(err.value)
    assert "mastodon" in message
    assert "lemmy" in message
    assert "reddit" in message
```

#### Finding 7: `test_created_at_is_timezone_aware_when_the_instance_omits_the_zone`

- **Location:** Task 2, Step 1 (`:345`)
- **Rule:** Mutation check — wrong constant.
- **Why it fails:** `assert post.created_at.tzinfo is not None` accepts any zone. `_parse_published` assuming a local or arbitrary offset instead of UTC (`replace(tzinfo=timezone(timedelta(hours=-5)))`) passes, and every velocity in the scorer is then wrong by that offset — silently, since nothing crashes. The offset-carrying case (`+02:00`), which the code handles by *not* replacing, is untested in either direction.
- **Replacement:**

```python
@pytest.mark.parametrize(
    "published,want",
    [
        (
            "2026-08-18T09:00:00.123456Z",
            datetime(2026, 8, 18, 9, 0, 0, 123456, tzinfo=UTC),
        ),
        ("2026-08-18T09:00:00", datetime(2026, 8, 18, 9, 0, tzinfo=UTC)),
        ("2026-08-18T09:00:00+02:00", datetime(2026, 8, 18, 7, 0, tzinfo=UTC)),
    ],
)
def test_published_is_read_as_utc(published, want):
    """The scorer subtracts created_at from an aware `now`, so a naive value
    raises three stages later. A value stamped with the *wrong* zone raises
    nothing at all and shifts every velocity by that offset instead.
    """
    view = _view("a1", "T")
    view["post"]["published"] = published
    assert _source({("Hot", 1): [view]}).fetch(limit=10)[0].created_at == want
```

#### Finding 8: `CompositeSource` exception isolation

- **Location:** Task 3, Step 1 (`:758`); implementation at `:833`
- **Rule:** Mutation check — wrong branch handler. Also the plan's own Global Constraint at `:20`: "A mapping bug must crash, never be logged as an unreachable platform."
- **Why it fails:** Both isolation tests use `FailingSource`, which raises `SourceError`. Narrowing `except Exception` to `except SourceError` passes the whole suite — yet the implementation's comment at `:831` says the guard is broad precisely because "a source can raise anything its client library defines." Nothing proves that.

  The same blank spot hides the opposite problem, and this one is a genuine conflict rather than a coverage gap: `except Exception` swallows the `KeyError` that Task 2 goes to deliberate lengths to let escape (`:463`, `:477`, and the comment at `:551`). Composed under `build_source`, a Lemmy mapping bug is logged as `Skipping source lemmy` and the run finishes with fewer posts — exactly the outcome the Global Constraint forbids. The second test below fails against the planned implementation; resolving it means narrowing the guard to `(SourceError, httpx.HTTPError)`, which keeps the first test green, or relaxing the constraint. That is the planner's call, not a rewrite I should make.
- **Replacement:**

```python
class CrashingSource:
    """A source failing the way a client library fails: httpx and praw raise
    their own types, not SourceError. Narrowing the guard to SourceError
    takes the whole run down when one platform's transport misbehaves.
    """

    name = "crashy"

    def fetch(self, limit):
        raise httpx.ConnectError("connection refused")


def test_a_non_source_error_failure_is_isolated_too(caplog):
    composite = CompositeSource(
        [CrashingSource(), StubSource("lemmy", [_post("lemmy", "l1")])]
    )
    with caplog.at_level(logging.WARNING):
        posts = composite.fetch(limit=10)

    assert [post.source_id for post in posts] == ["l1"]
    assert "crashy" in caplog.text


def test_a_mapping_bug_in_a_child_source_is_not_logged_as_an_outage():
    """Global constraint: a mapping bug crashes, it is never reported as an
    unreachable platform. LemmySource lets KeyError escape fetch on purpose;
    a blanket `except Exception` here re-swallows it and the run quietly
    returns fewer posts, which is the exact failure Task 2 designs against.
    """

    class BuggySource:
        name = "lemmy"

        def fetch(self, limit):
            raise KeyError("posts")

    with pytest.raises(KeyError):
        CompositeSource([BuggySource()]).fetch(limit=10)
```

#### Finding 9: the CLI's switch from `RedditSource` to `build_source` is untested

- **Location:** Task 4, Step 4 (`:947`) — no test; Step 7 (`:983`) checks it as a manual `python -c` invocation
- **Rule:** Mutation check — missing side effect. Task 4 is described at `:867` as "the task that actually switches Reddit off," and reverting its one production line fails nothing.
- **Why it fails:** Reverting `zeitgeist/cli.py:87` to `source=RedditSource.from_settings(settings)` leaves the whole suite green. Every CLI test monkeypatches `run_pipeline` and asserts only on the printed error text, and `praw.Reddit` accepts empty-string credentials without complaining, so nothing raises. Step 5 (`:967`) edits the CLI env helper to set `SOURCES=lemmy` but adds no assertion that the setting reaches the pipeline. A one-line `python -c` in Step 7 is a manual check, not a regression guard.
- **Replacement:** add to `tests/test_cli.py`, after the Step 5 edit to `_set_minimal_settings_env`.

```python
def test_run_builds_the_source_from_sources_rather_than_hard_coding_reddit(
    monkeypatch, tmp_path
):
    """The point of the whole change. Reverting cli.py to RedditSource fails
    nothing otherwise: run_pipeline is stubbed in every other CLI test and
    praw accepts empty credentials without raising.
    """
    _set_minimal_settings_env(monkeypatch, tmp_path)
    captured: dict = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return tmp_path

    monkeypatch.setattr(cli_module, "run_pipeline", _capture)

    assert main(["run"]) == 0
    assert captured["source"].name == "lemmy"
```

#### Finding 10: `test_every_known_source_has_a_builder` checks keys, never builders

- **Location:** Task 4, Step 1 (`:888`)
- **Rule:** Mutation check — wrong argument. The registry's entire job is the name→builder mapping, and only the names are asserted.
- **Why it fails:** `set(BUILDERS) == set(KNOWN_SOURCES)` is a real drift guard, but a copy-paste leaving `"reddit": LemmySource.from_settings` satisfies it, and `test_build_source_builds_only_the_enabled_sources` only ever enables `lemmy`. `SOURCES=lemmy,reddit` — the configuration the Task 5 README explicitly documents — would then scrape Lemmy twice under two names, and every test still passes. No test in the plan ever builds more than one source.
- **Replacement:** add alongside the other Task 4 tests (needs `from zeitgeist.sources.reddit import RedditSource`).

```python
def test_build_source_builds_each_name_with_its_own_builder():
    """Matching keys prove nothing about the values. This is the multi-source
    configuration the README documents, and it is otherwise never built.
    """
    settings = Settings(
        _env_file=None,
        anthropic_api_key="key",
        sources="lemmy,reddit",
        reddit_client_id="id",
        reddit_client_secret="secret",
    )
    built = build_source(settings)._sources

    assert [type(source) for source in built] == [LemmySource, RedditSource]
    assert [source.name for source in built] == ["lemmy", "reddit"]
```

#### Finding 11: `.env.example` is rewritten with no test that its keys are read

- **Location:** Task 5, Step 1 (`:1015`); Step 3 (`:1077`) checks defaults manually
- **Rule:** "Test a script or document → run it, never grep its text." Absent coverage: Task 5 replaces every key in the file and adds no test.
- **Why it fails:** `Settings.model_config` sets `extra="ignore"`, so a misspelled key in `.env.example` is completely silent — the user copies it to `.env`, sets `LEMMY_INSTNACE=https://lemmy.ml`, and gets `lemmy.world` with no warning anywhere. Step 3's `python -c` asserts the *code's* defaults, not that the shipped file produces them, so it passes against a `.env.example` full of typos. Loading the file is the only thing that catches this, and it is cheap.
- **Replacement:** add to `tests/test_config.py` (requires `from pathlib import Path`, and Finding 1's autouse fixture so an exported variable cannot mask the file).

```python
def test_env_example_produces_the_documented_default_configuration():
    """extra="ignore" makes a misspelled key in .env.example invisible: the
    user sets the value, gets the default, and nothing says why. This also
    catches the file going stale against the README's claimed defaults.
    """
    example = Path(__file__).parent.parent / ".env.example"
    settings = Settings(_env_file=example)

    assert settings.sources == ["lemmy"]
    assert settings.lemmy_instance == "https://lemmy.world"
    assert settings.lemmy_include_nsfw is False
    assert settings.reddit_client_id == ""
    assert settings.post_limit == 500
    assert settings.topic_count == 5
```

---

One non-test defect, since it blocks Task 2 outright: `_to_post` at `:603-618` never passes `fetched_at` to `Post(...)`, and `Post.fetched_at` is a required field under `extra="forbid"` (`zeitgeist/models.py:47`). Every Lemmy test errors with a pydantic `ValidationError` rather than the assertions above. The tests do catch it, so it is not a test-quality finding — but the implementation block needs `fetched_at=fetched_at` before transcription.
