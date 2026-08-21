Verbatim reviewer output, Run 5 (cold, untuned, `Remedy:` contract fix).

Dispatched: one general-purpose subagent, model opus, prompt lifted from
`.claude/skills/reviewing-plan-tests/reviewer-prompt.md` with every
placeholder filled. Working root: a detached `git worktree` at `5ed6747`.
Only change from Run 4's prompt: the output contract's `Replacement:` field
became `Remedy:` with three permitted forms (rewrite / delete / add).
Everything below the rule is the reviewer's output exactly as returned.

---

Rubric read: C:\Users\gwynn\.claude\plugins\cache\claude-plugins-official\superpowers\6.2.0\skills\test-driven-development\writing-good-tests.md

```
1. Every test names the break it catches
2. Every test exercises the real thing
```

**Tests audited:** 37 (Tasks 1-5) — **Findings:** 9

### Finding 1: test_respects_the_limit (Lemmy)

- **Location:** Task 2, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:393`)
- **Rule:** Principle 1 — derive the expected value by hand. The `want` here was not derived from the fixture at all, and it does not match the plan's own implementation.
- **Why it fails:** `fetch(limit=5)` computes `per_sort = max(1, ceil(5/2)) = 3`. `_fetch_sort("Hot", 3)` returns `collected[:3]`, i.e. 3 views; `("Scaled", 1)` is absent from `pages` so that listing yields nothing. `fetch` returns 3 posts, and the assertion `== 5` fails. Step 4's "Expected: PASS, all tests" is wrong, and an executor transcribing this verbatim will hit a red test with no guidance on which side is correct. Worse, the test as written does not exercise the cap at all — it never reaches `if len(seen) >= limit`, so the early return that actually enforces `POST_LIMIT` is unprotected.
- **Remedy:** Rewrite —

```python
def test_respects_the_limit():
    """ceil(5/2) is 3 per listing, so the two together offer 6. Without the
    early return the pipeline would get one post more than POST_LIMIT.
    """
    pages = {
        ("Hot", 1): [_view(f"h{n}", f"T{n}") for n in range(50)],
        ("Scaled", 1): [_view(f"s{n}", f"V{n}") for n in range(50)],
    }
    assert len(_source(pages).fetch(limit=5)) == 5
```

### Finding 2: the CLI builds its source from SOURCES

- **Location:** Task 4, Step 5 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:967`)
- **Rule:** Mutation check — missing state change / wrong argument. Task 4's header calls this "the task that actually switches Reddit off", and no test covers it.
- **Why it fails:** Step 4 changes `zeitgeist/cli.py` from `source=RedditSource.from_settings(settings)` to `source=build_source(settings)`. Step 5 only edits the env helper in `tests/test_cli.py`; both existing CLI tests replace `run_pipeline` wholesale and never look at the `source=` argument. Revert Step 4 — the single most likely mistake, since it is one line buried in a nine-step task — and every test in the plan still passes. The failure only shows up on a real run, as a Reddit credential error on a machine configured for Lemmy only. `test_build_source_builds_only_the_enabled_sources` proves the registry works, not that the CLI calls it.
- **Remedy:** Add to `tests/test_cli.py` —

```python
def test_run_builds_the_source_from_the_sources_setting(monkeypatch, tmp_path):
    """The CLI used to hard-code RedditSource. If it still does, a
    Lemmy-only configuration silently fetches from Reddit instead.
    """
    _set_minimal_settings_env(monkeypatch, tmp_path)
    run_dir = tmp_path / "output" / "run-1"
    run_dir.mkdir(parents=True)
    captured: dict[str, object] = {}

    def _record(**kwargs):
        captured["source"] = kwargs["source"]
        return run_dir

    monkeypatch.setattr(cli_module, "run_pipeline", _record)

    assert main(["run"]) == 0
    assert captured["source"].name == "lemmy"
```

### Finding 3: the Lemmy request URL and `type_` parameter

- **Location:** Task 2, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:398`)
- **Rule:** Principle 1 — test the contract your code makes at its boundary (the query you emit). Mutation check — wrong constant or argument.
- **Why it fails:** `StubClient.get(self, url, params)` discards `url` entirely, and no test reads `params["type_"]`. Two mutations the plan itself flags as fatal go uncaught: changing the path to `/api/v4/post/list` (Task 2 records "`/api/v4` is 404") and changing `type_` from `"All"` to `"Local"`, which would drop every federated post and quietly reduce the source to one instance's own content — the exact premise the README rewrite in Task 5 sells. Dropping `self._instance` for a hardcoded host is equally invisible. The `instance.rstrip("/")` in `__init__` is checked only indirectly, by a private-attribute assertion in Task 4.
- **Remedy:** Add to `tests/test_sources_lemmy.py` —

```python
def test_requests_the_v3_listing_on_the_configured_instance():
    """/api/v4 is 404, and type_=Local would drop the federated posts that
    make querying a single instance worthwhile at all.
    """

    class RecordingClient(StubClient):
        def __init__(self, pages):
            super().__init__(pages)
            self.urls: list[str] = []

        def get(self, url, params):
            self.urls.append(url)
            return super().get(url, params)

    client = RecordingClient({("Hot", 1): [_view("a1", "T")]})
    # Trailing slash: unstripped, every URL would carry a double slash.
    source = LemmySource(instance="https://sh.itjust.works/", client=client)
    source.fetch(limit=1)

    assert client.urls[0] == "https://sh.itjust.works/api/v3/post/list"
    assert client.calls[0]["type_"] == "All"
```

### Finding 4: _bare_settings does not isolate the ambient environment

- **Location:** Task 1, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:63`)
- **Rule:** Project convention — hermetic by construction; a test whose outcome depends on the ambient environment is a defect.
- **Why it fails:** `_env_file=None` disables the dotenv file only. `pydantic-settings` still reads `os.environ`, which outranks field defaults. I checked `tests/conftest.py` in this checkout: it defines `sample_posts` and `fixture_now` and nothing else — there is no autouse fixture stripping settings variables, and `pyproject.toml` configures no env plugin. So four of Task 1's tests are decided by the developer's shell: `test_sources_defaults_to_lemmy_only` and `test_lemmy_settings_have_usable_defaults` break under an exported `SOURCES` or `LEMMY_INSTANCE`, `test_reddit_runs_without_credentials_when_disabled` breaks under an exported `REDDIT_CLIENT_ID`, and `test_enabling_reddit_without_credentials_is_rejected` stops raising entirely when both Reddit variables are exported — the case that hides a real regression rather than merely reporting one. The docstring's promise of "a fresh checkout's starting point" is not delivered by the code beneath it.
- **Remedy:** Rewrite the helper block at the top of the added `tests/test_config.py` section —

```python
@pytest.fixture(autouse=True)
def _no_ambient_settings_env(monkeypatch):
    """Settings reads os.environ, which `_env_file=None` does not disable.
    An exported REDDIT_CLIENT_ID would decide whether the
    "runs without credentials" tests pass, based on who ran them.
    """
    for name in (
        "SOURCES",
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "REDDIT_USER_AGENT",
        "LEMMY_INSTANCE",
        "LEMMY_INCLUDE_NSFW",
        "SUBREDDITS",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def _bare_settings(**overrides) -> Settings:
    """No .env, no ambient vars, no Reddit credentials — a fresh checkout."""
    return Settings(_env_file=None, anthropic_api_key="key", **overrides)
```

### Finding 5: test_respects_the_limit (Composite)

- **Location:** Task 3, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:739`)
- **Rule:** Mutation check — missing side effect. The test cannot fail for the break it is named after.
- **Why it fails:** `limit=6` over two sources gives `per_source = 3`, so the sources supply exactly 6 posts between them and the total is 6 whether or not `if len(seen) >= limit: return list(seen.values())` exists. Delete that early return and every Task 3 test still passes. The cap only bites when `ceil(limit / n)` overshoots, which the chosen limit avoids. `test_divides_the_budget_across_sources` already covers the division, so as written this test duplicates it.
- **Remedy:** Rewrite —

```python
def test_respects_the_limit():
    """ceil(5/2) is 3 each, so the sources together offer 6. Without the
    cap the pipeline would receive one post more than POST_LIMIT.
    """
    sources = [
        StubSource("lemmy", [_post("lemmy", f"l{n}") for n in range(20)]),
        StubSource("reddit", [_post("reddit", f"r{n}") for n in range(20)]),
    ]
    assert len(CompositeSource(sources).fetch(limit=5)) == 5
```

### Finding 6: CompositeSource deduplication

- **Location:** Task 3, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:747`)
- **Rule:** Mutation check — missing state change.
- **Why it fails:** No fixture ever presents the same `(platform, source_id)` twice, so deleting the `if key in seen: continue` guard — or replacing the whole `seen` dict with a list — fails nothing. `test_same_id_on_different_platforms_is_not_a_duplicate` proves `platform` is part of the key but says nothing about whether duplicates are collapsed at all; it passes identically under an implementation that never deduplicates. Duplicates are the realistic case the moment a second Lemmy instance is added, since federation means both return the same `ap_id`, and a doubled post inflates every cluster it lands in.
- **Remedy:** Add to `tests/test_sources_composite.py` —

```python
def test_the_same_post_from_two_sources_is_kept_once():
    """Federated instances return the same ap_id, so one post can arrive
    from two sources. Counting it twice inflates its cluster.
    """
    sources = [
        StubSource("lemmy-a", [_post("lemmy", "shared"), _post("lemmy", "a1")]),
        StubSource("lemmy-b", [_post("lemmy", "shared"), _post("lemmy", "b1")]),
    ]
    posts = CompositeSource(sources).fetch(limit=10)
    assert [post.source_id for post in posts] == ["shared", "a1", "b1"]
```

### Finding 7: test_mapping_bug_in_to_post_propagates_not_swallowed

- **Location:** Task 2, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:477`)
- **Rule:** Project convention — mocks are rare and must justify themselves; Principle 2 — exercise the real thing. Baseline confirmed by `grep -rl "patch(" tests/`: one file, `tests/test_sources_reddit.py`.
- **Why it fails:** The behaviour under test — a mapping error escaping rather than being logged as a listing skip — is reachable with real objects. A view missing `counts` makes the real `_to_post` raise a real `KeyError` on the real path. Patching `_to_post` out replaces the function whose behaviour is the subject, and it couples the test to the module-level name, so a later refactor inlining the mapping turns a passing test into a green no-op rather than a failure. The plan names no real behaviour the patch replaces and no reason the real thing will not do. It also drags in the only `unittest.mock` import in the new file.
- **Remedy:** Rewrite (and drop `from unittest.mock import patch` from the file header, or ruff `F401` fails the lint step) —

```python
def test_mapping_bug_propagates_rather_than_looking_like_an_outage():
    """Only transport failure is tolerated. If the guard around _fetch_sort
    widened to `except Exception`, a broken mapping would be logged as a
    skipped listing and the run would quietly return fewer posts.
    """
    broken = _view("a1", "T")
    del broken["counts"]
    # Scaled has real data, so a swallowing implementation returns s1
    # instead of raising — the failure names the actual regression.
    pages = {("Hot", 1): [broken], ("Scaled", 1): [_view("s1", "Fine")]}
    with pytest.raises(KeyError, match="counts"):
        _source(pages).fetch(limit=10)
```

### Finding 8: test_stops_paging_on_an_empty_page

- **Location:** Task 2, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:384`)
- **Rule:** Warning sign — the test can only fail through a crash. The mutation it guards produces a hang, not a red test.
- **Why it fails:** Remove `if not views: break` from `_fetch_sort` and `collected` never grows past 1 while `budget` is 250, so `while len(collected) < budget` spins forever, appending to `self.calls` until the process runs out of memory. The assertion at the end is never reached. That is not a failing test, it is a wedged suite with no diagnostic — and it wedges CI too. The implementation comment at line 595 also mis-states this as "the loop would keep requesting until the budget was met"; the budget is never met, which is the whole problem.
- **Remedy:** Rewrite —

```python
def test_stops_paging_on_an_empty_page():
    """The budget is never met on a listing shorter than it, so only an
    empty page ends the loop. Without that check it spins forever.
    """

    class BoundedClient(StubClient):
        def get(self, url, params):
            if len(self.calls) >= 8:
                raise AssertionError("kept paging past an exhausted listing")
            return super().get(url, params)

    source = LemmySource(
        instance="https://lemmy.world",
        client=BoundedClient({("Hot", 1): [_view("a1", "Only one")]}),
    )
    source.fetch(limit=500)
    assert len(source._client.calls) <= 4
```

### Finding 9: test_created_at_is_timezone_aware_when_the_instance_omits_the_zone

- **Location:** Task 2, Step 1 (`docs/superpowers/plans/2026-08-18-pluggable-sources.md:345`)
- **Rule:** Principle 1 — derive the expected value by hand; a literal is available and is not used. Mutation check — wrong constant or argument.
- **Why it fails:** `assert post.created_at.tzinfo is not None` passes for *any* zone. Mutate `_parse_published` to `parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)` — the tempting "assume the local zone" fallback — and the test stays green while every post's age, and therefore every velocity in `_mean_velocity`, shifts by the developer's UTC offset. The comparison the test exists to protect happens in the scorer, and UTC is the assumption that makes it correct; nothing pins it.
- **Remedy:** Rewrite —

```python
def test_created_at_is_timezone_aware_when_the_instance_omits_the_zone():
    """The scorer subtracts created_at from an aware `now`; a naive value
    would raise there instead of here. Asserting the whole value also pins
    the zone assumed: a local-time fallback shifts every post's age.
    """
    view = _view("a1", "T")
    view["post"]["published"] = "2026-08-18T09:00:00"
    post = _source({("Hot", 1): [view]}).fetch(limit=10)[0]
    assert post.created_at == datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
```
