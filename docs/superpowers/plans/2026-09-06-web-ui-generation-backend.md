# Generation Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the API contract — a topic can be turned into memes on demand, model-written or hand-written, including a topic that was never ranked, and a render can be deleted.

**Architecture:** A second, small executor beside phase 3's run worker: `GenerationService` validates a request on the request thread, writes `generating` rows so the client's tiles have real ids, and hands the work to a one-worker `ThreadPoolExecutor` that opens its own `Store`. A render is a row *and* a pair of PNGs, so `zeitgeist/renders.py` owns that three-part unit — path layout, deletion, and clearing a topic's previous model-written attempts — and the pipeline, the API and the executor all go through it.

**Tech Stack:** Python 3.14, FastAPI, `concurrent.futures.ThreadPoolExecutor`, pydantic 2 (discriminated unions), Pillow, sqlite3 (stdlib), pytest.

## Global Constraints

Copied from `docs/superpowers/specs/2026-09-02-web-ui-design.md`. Every task's requirements implicitly include this section.

- **Definition of Done, run before claiming any task complete:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, `uv run pytest`. All four must pass. **There is no red window — the tree is green at the start of every task and must be green at the end.** The three frontend gate commands belong to phase 5 and must not be added here; `web/` does not exist yet, and adding them turns this pull request red for a directory that is not supposed to exist.
- **This phase closes the API contract.** It is the last point at which a response model may change before a screen consumes it. Phase 5 generates TypeScript from the OpenAPI schema this phase finishes.
- **`ANTHROPIC_API_KEY` is never returned by any endpoint, in any form.**
- **No log line may carry reply text, post bodies or `author_key`.** Log lines carry counts, ids, template ids, topic ids and elapsed times. Caption text is the user's own input and may be logged; reply and post text may not.
- **The database is authoritative for whether a render exists.** A PNG deleted out from under its row is a 404 that says so, never a 500. A row deleted out from under a running job must not come back.
- **Optionality expresses a real state, never a migration concession.** A field is `| None` only where there genuinely is no value.
- **No migrations.** `SCHEMA_VERSION` stays 3. This phase adds no tables, no columns and no indexes — `renders` and `idx_renders_run_topic` already exist from phase 1.
- **Envelope only where there are aggregates to carry** (`zeitgeist/api/schemas.py`'s docstring). `POST .../renders` returns a bare `list[RenderRecord]`; there is nothing beyond the list.
- **Renders live at `output/<run_id>/renders/<render_id>.png`**, with the 96px thumbnail beside it at `<render_id>.thumb.png`. Image bytes never go in the database.
- **Thumbnails are generated, not scaled**, by the same code path that writes the render.
- **On-demand generation runs on a separate executor from the run worker.** The design shows tiles generating on topic detail while a run is in flight, so the two cannot share a worker. That means two concurrent callers of the LLM provider — free on Anthropic, contended on local Ollama where inference serialises on one GPU. Documented, not solved with a global lock.
- **Each thread that touches the store opens its own `Store`.** `sqlite3` connections are thread-bound.
- Python 3.14: PEP 695 generics (`def f[T: Bound](...)`), never `typing.TypeVar`.
- **`model_config = STRICT`** (`ConfigDict(extra="forbid")`, in `zeitgeist/models.py`) on every new pydantic model.
- ruff: line length 88, rules `E, F, I, UP, B, SIM`. `docs/` is excluded.
- ty: fix type errors at the root cause. No blanket `# type: ignore`; a narrow suppression needs a comment explaining why.
- **Tests are hermetic.** No network. Every model call goes through `FakeLLMProvider`. `tests/conftest.py`'s autouse fixture strips every environment variable `Settings` reads and repoints `DB_PATH` at a per-test path.
- **Fixtures are built through the real models**, never hand-written dicts. `tests/run_factory.py`, `tests/template_factory.py` and `tests/api_factory.py` are the established pattern.
- **No test may sleep to synchronise with a thread.** Use `threading.Event`, a `Barrier`, or `GenerationService.shutdown()`, which waits on the pool. A test that sleeps flakes on a loaded CI box.

## Decisions this phase is required to make

The spec leaves two questions open and names this phase as the one that answers them. Both answers are load-bearing below.

### 1. A re-run of `generate` clears the run's prior `auto` renders per topic; `manual` renders are never touched

The spec's "Re-running generate appends, it does not replace" says the fix needs a render-deletion path, and that "when that phase lands, it must decide whether a re-run first clears the run's prior `auto` renders for the topic, and it must leave `manual` renders untouched regardless."

It clears them, but only where the replacement rendered. The old CLI's fixed `{position:02d}-{topic_id}.png` filename meant a tuning pass replaced the one before it; `uuid4` ids removed that by accident rather than by design, and the tuning loop the spec documents — edit a prompt, re-render the same frozen topics, look at the output — wants the latest output, not a growing pile. Meme counts (`COUNT(*) FROM renders`) then read what the screen shows.

A pass whose render *fails* clears nothing. An unconditional clear would make the likeliest event in a tuning loop — a prompt edit that produces a caption too long for its box — destroy the output being tuned against and leave a failed row in its place. Failing this way keeps the previous render beside the failure, which is both less destructive and more informative.

`manual` is exempt because a person made it. The model's output is reproducible by running again; a hand-written caption is not. That asymmetry is the whole reason the `AutoOrigin`/`ManualOrigin` union exists.

`POST .../renders` is the exception in the other direction: it **appends**. It is an additive action someone took against one topic, not a re-run of a stage, and clearing on it would delete the render they are comparing against.

### 2. `status == "generating"` is the state in which the brief is not yet written

`RenderRecord.status` has carried `"generating"` since phase 1 with nothing writing it. This phase writes it: the rows are inserted before the POST returns, so the tiles the client draws have real ids and survive a refresh. For an `llm` request the brief does not exist yet, so the seeded row carries `caption_slots={}` and `AutoOrigin(rationale="")`, both filled in when the model answers.

This is not the placeholder-optionality the spec forbids. The record's *kind* is fixed at creation and never changes — which is what the spec's "created as one kind and never changes" argument protects, and it still holds. What changes is `status`, and the invariant is: **a `generating` record's `caption_slots` and `rationale` must not be read.** A `manual` request has its captions up front, so its seeded row carries the real ones from the start.

## What phases 1-3 left you

**`Store`** (`zeitgeist/store.py`) already has, and you must not reimplement: `init_schema`, `start_run`, `finish_run`, `fail_run`, `abort_run`, `reconcile_interrupted`, `get_run`, `list_runs`, `render_counts`, `recent_run_ids`, `topics_for_runs`, `topic_recurrence`, `log_lines`, `write_log_lines`, `previous_sub_scores`, `write_run_topics`, `run_topics`, `write_checkpoint`, `write_analyse_checkpoint`, `read_checkpoint[T: BaseModel]`, `written_stages`, `record_stage`, `stages_for_run`, `add_render`, `get_render`, `renders_for_run`, `get_settings`, `set_setting`, `clear_setting`, `close`. `MissingCheckpoint` is raised by `read_checkpoint`. `Store.__init__(path, *, check_same_thread=True)`; the database already opens in WAL mode.

**Models** (`zeitgeist/records.py`): `Stage`, `ORDER`, `RunStatus`, `StageStatus`, `RunConfig` (+ `RunConfig.freeze`), `RunError`, `RunRecordRow`, `StageRecord`, `AutoOrigin(rationale)`, `ManualOrigin()`, `Origin` (discriminated on `provenance`), `RenderRecord(id, run_id, topic_id, template_id, caption_slots, origin, status, error, created_at)`, `LogLine`. `zeitgeist/models.py` has `Topic`, `ScoredTopic(Topic)`, `MediaBrief(topic_id, template_id, caption_slots, rationale)`, `Dossier`, `STRICT`.

**Media** (`zeitgeist/media/`): `brief.generate_brief(topic, templates, provider) -> MediaBrief`, `brief.generate_briefs`, `brief.BriefChoice`, `brief.BriefError`, `brief.BRIEF_SYSTEM`; `render.render_meme(brief, manifest, templates_dir, out_path, font_path=None) -> Path`, `render.write_thumbnail(source, out_path) -> Path`, `render.RenderError`, `render.THUMBNAIL_PX = 96`; `templates.load_templates(dir) -> dict[str, TemplateManifest]`, `templates.select_templates(templates, ids)`, `templates.TemplateError`, `templates.Slot`, `templates.TemplateManifest`.

**Pipeline** (`zeitgeist/pipeline.py`): `run_pipeline(...)`, `new_run_id()`, and `_render_all(briefs, templates, settings, run_dir, run_id, store, observer, token) -> int`, which mints a `uuid4().hex` per brief, writes `<id>.png` and `<id>.thumb.png` under `run_dir / "renders"`, then calls `store.add_render` and `observer.render_finished` for each.

**Runner** (`zeitgeist/runner.py`): `RunService` with `enqueue`, `active`, `stop`, `abort`, `buffer`, `start`, `shutdown`; `RunRequest`, `QueuedRun`, `ActiveRuns`, `RunAlreadyActive`, `ExecuteFn`, `RUN_OVERRIDE_KEYS`, and the private `RunService._build_settings(overrides)` whose docstring explains why it rebuilds `Settings` rather than `model_copy`-ing it. **Task 6 extracts that method into a module-level function; read its docstring before touching it.**

**API** (`zeitgeist/api/`): `create_app(settings, *, execute=None) -> FastAPI` opening one `Store(settings.db_path, check_same_thread=False)`; dependencies `get_store`, `get_settings`, `get_runner`; routers `control.py` (POST /api/runs, resume, stop, abort, active, SSE), `runs.py` (the five read endpoints, plus helpers `_run_or_404(store, run_id)` and `resume_stage(store, run_id)`), `renders.py` (`_image_path`, `_render_or_404`, GET record, GET image), `topics.py`, `settings.py`, `options.py`. **Router imports live inside `create_app`'s body** to break the cycle, because routers import `get_store` from `app.py`.

**Tests**: `tests/api_factory.py` has `SeededRun`, `seed_run`, `api_settings(tmp_path)`, `seeded_client(tmp_path, *, runs=(), execute=None)` (which enters the lifespan and registers the client for teardown), `GatedExecute`, `LoggingGate`. `tests/run_factory.py` has `make_run_config`, `make_stage_record`, `make_render_record`, `make_dossier`, `make_topic`, `make_scored_topic`, `make_evidence`, `FIXED_TIME`. `tests/template_factory.py` has `make_slot`, `make_manifest`, `write_library`. `tests/test_pipeline.py` has `_FakeTrendSource`, `_template_library(tmp_path)`, `_settings(tmp_path, **overrides)`, `_store(tmp_path)`, `TEMPLATE_A = "shape_alpha"`, `TEMPLATE_B = "shape_beta"`.

## File Structure

**Created:**

| File | Responsibility |
| --- | --- |
| `zeitgeist/renders.py` | Where a render's two files live (`render_paths`), and how a render is removed as one unit of row-plus-files (`delete_render`, `clear_auto_renders`). Separate from `store.py`, which knows rows and deliberately nothing about the filesystem, and from `api/renders.py`, which is the HTTP layer over this. |
| `zeitgeist/generation.py` | The on-demand request models, the `GenerationJob` a worker executes, the pure `generate_renders(job, store)`, and `GenerationService`: the executor, its validation and its seeded `generating` rows. Imports nothing from `zeitgeist.api`, for the same reason `runner.py` does not. |
| `zeitgeist/api/generate.py` | `POST /api/runs/{run_id}/topics/{topic_id}/renders`. Its own router rather than an addition to `control.py`: it drives a different service with a different lifecycle, and its sibling `DELETE /api/renders/{id}` cannot live under the `/api/runs` prefix at all. |
| `tests/test_renders.py` | `zeitgeist/renders.py`'s tests. |
| `tests/test_generation.py` | `zeitgeist/generation.py`'s tests. |
| `tests/test_api_generate.py` | The POST endpoint's tests. |

**Modified:**

| File | Change |
| --- | --- |
| `zeitgeist/media/brief.py` | `check_slots` becomes public and replaces `_validate`; `generate_brief` and `generate_briefs` widen to accept any `Topic`, which is what briefing a never-ranked topic needs. |
| `zeitgeist/store.py` | `update_render`, `delete_render`, `renders_for_topic`; the thrice-repeated render column list becomes one constant. |
| `zeitgeist/api/renders.py` | `_image_path` delegates to `render_paths`; `DELETE /api/renders/{render_id}` is added. |
| `zeitgeist/api/runs.py` | `read_topic` uses `store.renders_for_topic` instead of filtering `renders_for_run` in Python. |
| `zeitgeist/api/app.py` | `create_app` grows a `generate` seam, builds a `GenerationService`, exposes `get_generator`, shuts the pool down in the lifespan, and mounts `generate.router`. |
| `zeitgeist/api/control.py` | Docstring correction: phase 4's two endpoints landed elsewhere. |
| `zeitgeist/pipeline.py` | `_render_all` clears the topic's prior `auto` renders once the new PNG is on disk. |
| `zeitgeist/runner.py` | `RunService._build_settings` becomes the module-level `resolve_settings(base, overrides)`; the method delegates. |
| `tests/api_factory.py` | `api_settings` and `seeded_client` take an optional `templates_dir`; `seeded_client` takes an optional `generate`. |
| `README.md` | The web UI section gains phase 4's paragraph. |
| `docs/superpowers/specs/2026-09-02-web-ui-design.md` | The open question in "Re-running generate appends, it does not replace" is marked answered. |

---

### Task 1: `generate_brief` briefs any topic, and slot validation becomes shareable

The below-the-cut `generate ↗` link briefs a topic that was never ranked. Such a topic exists in the `analyse` checkpoint as a plain `Topic`; only the top `top_count` are promoted to `ScoredTopic` in `evaluate`. `generate_brief` requires a `ScoredTopic` today and reads nothing a `Topic` lacks — it uses `id`, `label`, `summary` and `dossier`.

Separately, the hand-written render path has to reject captions that do not fit their template *before* a row is written, with the same rule the model path already applies. `_validate` is that rule; it becomes public and loses its `BriefChoice` coupling.

**Files:**
- Modify: `zeitgeist/media/brief.py`
- Test: `tests/test_media_brief.py`

**Interfaces:**
- Consumes: nothing from this plan.
- Produces:
  - `check_slots(template_id: str, caption_slots: dict[str, str], templates: dict[str, TemplateManifest]) -> str | None` — the problem, or None.
  - `generate_brief(topic: Topic, templates: dict[str, TemplateManifest], provider: LLMProvider) -> MediaBrief`
  - `generate_briefs(topics: Sequence[Topic], templates: dict[str, TemplateManifest], provider: LLMProvider) -> list[MediaBrief]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_media_brief.py`. Check the module's existing imports first and add only what is missing.

```python
from tests.run_factory import make_topic
from tests.template_factory import make_manifest, make_slot
from zeitgeist.llm.base import FakeLLMProvider
from zeitgeist.media.brief import BriefChoice, check_slots, generate_brief


def _library():
    return {
        "shape_alpha": make_manifest(
            "shape_alpha",
            slots=[make_slot("rejected"), make_slot("preferred")],
        )
    }


def test_a_topic_that_was_never_ranked_can_still_be_briefed():
    """A bare `Topic` — no `final_rank`, no `final_score` — briefs.

    The break this catches is a future edit reading a ScoredTopic-only
    field inside `generate_brief` or its helpers, which would raise
    `AttributeError` for exactly the below-the-cut topics the on-demand
    `generate` link exists to serve.

    It does *not* catch the annotation change this task makes: Python does
    not enforce annotations at runtime, so `generate_brief` already
    accepts a `Topic` today and this test would pass before the widening
    as well as after. `ty` is the gate for the annotation — see Step 5,
    where it is the command that fails if `generate_briefs` is left as
    `list[Topic]` against `run_pipeline`'s `list[ScoredTopic]`.
    """
    topic = make_topic("airport-cat")
    provider = FakeLLMProvider(
        responses=[
            BriefChoice(
                template_id="shape_alpha",
                caption_slots={"rejected": "queueing", "preferred": "the cat"},
                rationale="it fits",
            )
        ]
    )

    brief = generate_brief(topic, _library(), provider)

    assert brief.topic_id == "airport-cat"
    assert brief.caption_slots == {"rejected": "queueing", "preferred": "the cat"}


def test_check_slots_accepts_exactly_the_templates_slots():
    assert (
        check_slots("shape_alpha", {"rejected": "a", "preferred": "b"}, _library())
        is None
    )


def test_check_slots_names_the_missing_slot():
    problem = check_slots("shape_alpha", {"rejected": "a"}, _library())

    assert problem is not None
    assert "preferred" in problem


def test_check_slots_names_a_slot_the_template_does_not_have():
    problem = check_slots(
        "shape_alpha", {"rejected": "a", "preferred": "b", "middle": "c"}, _library()
    )

    assert problem is not None
    assert "middle" in problem


def test_check_slots_rejects_a_caption_that_is_only_whitespace():
    """A blank caption renders as an empty box, so it is a bad request
    rather than a render to attempt and fail."""
    problem = check_slots(
        "shape_alpha", {"rejected": "a", "preferred": "   "}, _library()
    )

    assert problem is not None
    assert "preferred" in problem


def test_check_slots_lists_the_library_when_the_template_is_unknown():
    problem = check_slots("no_such_template", {}, _library())

    assert problem is not None
    assert "shape_alpha" in problem
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_media_brief.py -k "never_ranked or check_slots" -v`
Expected: FAIL — `ImportError: cannot import name 'check_slots' from 'zeitgeist.media.brief'`.

Note that `test_a_topic_that_was_never_ranked_can_still_be_briefed` fails only on that import, not on the widening: annotations are not enforced at runtime. Its red-to-green transition is honest for `check_slots` and vacuous for the type change, which is why Step 5's `ty check` is the step that actually gates this task.

- [ ] **Step 3: Make `check_slots` public and widen the topic types**

In `zeitgeist/media/brief.py`, replace `_validate` with `check_slots`. `_validate` would become a one-line pass-through, so delete it.

```python
def check_slots(
    template_id: str,
    caption_slots: dict[str, str],
    templates: dict[str, TemplateManifest],
) -> str | None:
    """Why these captions do not fit that template, or None if they do.

    Shared by the model path and the hand-written one: `generate_brief`
    calls it on what the model returned, and the on-demand manual render
    calls it on the slots a person typed. Two copies of "every slot, no
    extras, none blank" would drift, and the manual path would then accept
    a brief the renderer goes on to reject — a failed tile for what should
    have been a 400.
    """
    manifest = templates.get(template_id)
    if manifest is None:
        return (
            f"template_id {template_id!r} is not in the library; "
            f"choose one of: {', '.join(sorted(templates))}"
        )

    expected = {slot.name for slot in manifest.slots}
    given = set(caption_slots)

    if missing := sorted(expected - given):
        return f"missing captions for slots: {', '.join(missing)}"
    if extra := sorted(given - expected):
        return f"unknown slots for {manifest.id!r}: {', '.join(extra)}"
    if blank := sorted(n for n, t in caption_slots.items() if not t.strip()):
        return f"blank captions for slots: {', '.join(blank)}"
    return None
```

Inside `generate_brief`, replace `problem = _validate(choice, templates)` with:

```python
        problem = check_slots(choice.template_id, choice.caption_slots, templates)
```

Change the two signatures. `generate_briefs` takes a `Sequence`, not a `list`, because `list` is invariant: `list[ScoredTopic]` is not a `list[Topic]` to a type checker, and `run_pipeline` passes exactly that.

```python
def generate_brief(
    topic: Topic,
    templates: dict[str, TemplateManifest],
    provider: LLMProvider,
) -> MediaBrief:
```

```python
def generate_briefs(
    topics: Sequence[Topic],
    templates: dict[str, TemplateManifest],
    provider: LLMProvider,
) -> list[MediaBrief]:
```

Update the imports at the top of the module: add `from collections.abc import Sequence`, and change `from zeitgeist.models import MediaBrief, ScoredTopic` to `from zeitgeist.models import MediaBrief, Topic`. Add one paragraph to the module docstring:

```
The topic is a `Topic`, not a `ScoredTopic`: the below-the-cut `generate`
link briefs a topic `evaluate` never ranked, and nothing here reads a
ranking.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_media_brief.py -v`
Expected: PASS, including every test that was already there.

- [ ] **Step 5: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Expected: all four pass. `ty` is what catches a missed variance problem in `run_pipeline`'s call to `generate_briefs`.

- [ ] **Step 6: Commit**

```bash
git add zeitgeist/media/brief.py tests/test_media_brief.py
git commit -m "feat: brief any topic, and share slot validation with the manual path"
```

---
### Task 2: `Store.update_render`, `delete_render` and `renders_for_topic`

Three accessors the rest of the phase needs. `update_render` rather than a second `add_render` is the one with a real argument behind it: `add_render` is `INSERT OR REPLACE`, so a render deleted while its job was still running would come back from the dead when that job finished.

**Files:**
- Modify: `zeitgeist/store.py`
- Modify: `zeitgeist/api/runs.py` (the `renders=[...]` comprehension in `read_topic`)
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: nothing from this plan.
- Produces:
  - `Store.update_render(record: RenderRecord) -> bool` — False means no such row.
  - `Store.delete_render(render_id: str) -> bool` — False means no such row.
  - `Store.renders_for_topic(run_id: str, topic_id: str) -> list[RenderRecord]` — oldest first.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_store.py`. It already has a `_store(tmp_path)` helper and imports builders from `tests/run_factory.py`; add `make_render_record` to that import, and `AutoOrigin, ManualOrigin` from `zeitgeist.records`, if they are not already there.

```python
def test_update_render_replaces_the_mutable_columns(tmp_path):
    """A generating render is finished in place: the brief arrives after
    the row does."""
    store = _store(tmp_path)
    store.add_render(
        make_render_record("rnd1", status="generating", caption_slots={})
    )

    updated = store.update_render(
        make_render_record(
            "rnd1",
            status="ready",
            caption_slots={"rejected": "a", "preferred": "b"},
            origin=AutoOrigin(rationale="the shape matches"),
        )
    )

    assert updated is True
    record = store.get_render("rnd1")
    assert record is not None
    assert record.status == "ready"
    assert record.caption_slots == {"rejected": "a", "preferred": "b"}
    assert record.origin == AutoOrigin(rationale="the shape matches")


def test_update_render_does_not_resurrect_a_deleted_row(tmp_path):
    """`add_render` is INSERT OR REPLACE, so finishing a job with it would
    bring back a render somebody deleted while it was still generating.
    That is why the finishing path is an UPDATE."""
    store = _store(tmp_path)
    store.add_render(make_render_record("rnd1", status="generating"))
    store.delete_render("rnd1")

    updated = store.update_render(make_render_record("rnd1", status="ready"))

    assert updated is False
    assert store.get_render("rnd1") is None


def test_update_render_cannot_move_a_render_to_another_run(tmp_path):
    """run_id, topic_id and created_at are fixed at insert. A job
    finishing writes the brief, not the identity."""
    store = _store(tmp_path)
    store.add_render(
        make_render_record("rnd1", run_id="run-1", topic_id="cat", status="generating")
    )

    store.update_render(
        make_render_record("rnd1", run_id="run-2", topic_id="dog", status="ready")
    )

    record = store.get_render("rnd1")
    assert record is not None
    assert (record.run_id, record.topic_id) == ("run-1", "cat")


def test_delete_render_removes_the_row(tmp_path):
    store = _store(tmp_path)
    store.add_render(make_render_record("rnd1"))

    assert store.delete_render("rnd1") is True
    assert store.get_render("rnd1") is None


def test_delete_render_reports_an_unknown_id(tmp_path):
    """The endpoint 404s on it, so a silent success would be a lie."""
    store = _store(tmp_path)

    assert store.delete_render("nope") is False


def test_renders_for_topic_excludes_other_topics_and_other_runs(tmp_path):
    store = _store(tmp_path)
    store.add_render(make_render_record("a", run_id="r1", topic_id="cat"))
    store.add_render(make_render_record("b", run_id="r1", topic_id="dog"))
    store.add_render(make_render_record("c", run_id="r2", topic_id="cat"))

    records = store.renders_for_topic("r1", "cat")

    assert [record.id for record in records] == ["a"]


def test_renders_for_topic_returns_oldest_first(tmp_path):
    """Topic detail's grid reads in creation order, so the newest tile is
    last rather than wherever SQLite happened to put it."""
    store = _store(tmp_path)
    store.add_render(
        make_render_record("second", created_at=datetime(2026, 9, 2, tzinfo=UTC))
    )
    store.add_render(
        make_render_record("first", created_at=datetime(2026, 9, 1, tzinfo=UTC))
    )

    ids = [r.id for r in store.renders_for_topic("20260901T120000Z", "airport-cat")]
    assert ids == ["first", "second"]
```

If `tests/test_store.py` has no `_store` helper, add:

```python
def _store(tmp_path) -> Store:
    store = Store(tmp_path / "z.db")
    store.init_schema()
    return store
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_store.py -k "update_render or delete_render or renders_for_topic" -v`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'update_render'`.

- [ ] **Step 3: Hoist the render column list**

In `zeitgeist/store.py`, the render columns are written out in two SELECTs today and would be three after this task. Put the constant beside `NON_PLATFORM_COMPONENTS` near the top of the module:

```python
# The renders columns, in the order `_render` unpacks them. One constant
# because three accessors select exactly this list, and a fourth added
# later with a column out of order would deserialise into the wrong fields
# without raising.
_RENDER_COLUMNS = (
    "id, run_id, topic_id, template_id, caption_slots, origin, "
    "status, error, created_at"
)
```

Rewrite `get_render` and `renders_for_run` to use it, e.g.:

```python
    def get_render(self, render_id: str) -> RenderRecord | None:
        row = self._conn.execute(
            f"SELECT {_RENDER_COLUMNS} FROM renders WHERE id = ?",
            (render_id,),
        ).fetchone()
        return None if row is None else _render(row)
```

- [ ] **Step 4: Add the three accessors**

After `renders_for_run` in `zeitgeist/store.py`:

```python
    def renders_for_topic(self, run_id: str, topic_id: str) -> list[RenderRecord]:
        """One topic's renders, oldest first. Served by
        `idx_renders_run_topic`, which schema 3 already creates."""
        rows = self._conn.execute(
            f"SELECT {_RENDER_COLUMNS} FROM renders "
            "WHERE run_id = ? AND topic_id = ? ORDER BY created_at, id",
            (run_id, topic_id),
        ).fetchall()
        return [_render(row) for row in rows]

    def update_render(self, record: RenderRecord) -> bool:
        """Overwrite an existing render's mutable columns. False means no
        such row.

        An UPDATE rather than a second `add_render`: `add_render` is
        INSERT OR REPLACE, so a render deleted while it was still
        `generating` would come back from the dead when its job finished.
        `WHERE id = ?` against a deleted row updates nothing and returns
        False, which is the right outcome — the row is gone because
        somebody removed it.

        `run_id`, `topic_id` and `created_at` are deliberately not in the
        SET list. They are fixed when the row is inserted, and a job
        finishing must not be able to move a render to another run.
        """
        cursor = self._conn.execute(
            "UPDATE renders SET template_id = ?, caption_slots = ?, origin = ?, "
            "status = ?, error = ? WHERE id = ?",
            (
                record.template_id,
                json.dumps(record.caption_slots),
                record.origin.model_dump_json(),
                record.status,
                record.error,
                record.id,
            ),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def delete_render(self, render_id: str) -> bool:
        """Remove the row. False means no such row.

        The two PNGs are not this method's business — `store.py` knows rows
        and deliberately nothing about the filesystem.
        `zeitgeist.renders.delete_render` is the unit that removes both
        together.
        """
        cursor = self._conn.execute("DELETE FROM renders WHERE id = ?", (render_id,))
        self._conn.commit()
        return cursor.rowcount > 0
```

- [ ] **Step 5: Use `renders_for_topic` in `read_topic`**

`zeitgeist/api/runs.py` filters `renders_for_run` in Python for exactly this. Replace the comprehension in `read_topic`'s `TopicDetail(...)` with:

```python
        renders=store.renders_for_topic(run_id, topic_id),
```

Remove `renders_for_run` from that handler only; other callers keep it.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_store.py tests/test_api_runs.py -v`
Expected: PASS. `test_api_runs.py` is included because step 5 changed how topic detail assembles its renders; its existing assertions must still hold unchanged.

- [ ] **Step 7: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

- [ ] **Step 8: Commit**

```bash
git add zeitgeist/store.py zeitgeist/api/runs.py tests/test_store.py
git commit -m "feat: store accessors for updating, deleting and listing a topic's renders"
```

---
### Task 3: `zeitgeist/renders.py` — a render is a row and two files

Two callers need to remove a render as one unit: the DELETE endpoint, and the re-run that clears a topic's previous model-written attempts. One function rather than two copies of `unlink(missing_ok=True)`. The same module owns the path layout, so moving `output/` to object storage later is one function rather than a grep.

**Files:**
- Create: `zeitgeist/renders.py`
- Modify: `zeitgeist/api/renders.py` (`_image_path` delegates)
- Test: `tests/test_renders.py`

**Interfaces:**
- Consumes: `Store.delete_render`, `Store.renders_for_topic` (Task 2).
- Produces:
  - `RenderPaths` — a frozen dataclass with `full: Path` and `thumb: Path`.
  - `render_paths(output_dir: Path, run_id: str, render_id: str) -> RenderPaths`
  - `delete_render(store: Store, output_dir: Path, record: RenderRecord) -> bool`
  - `clear_auto_renders(store: Store, output_dir: Path, run_id: str, topic_id: str) -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_renders.py`:

```python
from PIL import Image

from tests.run_factory import make_render_record
from zeitgeist.records import ManualOrigin
from zeitgeist.renders import clear_auto_renders, delete_render, render_paths
from zeitgeist.store import Store


def _store(tmp_path) -> Store:
    store = Store(tmp_path / "z.db")
    store.init_schema()
    return store


def _write_files(output_dir, run_id: str, render_id: str) -> None:
    paths = render_paths(output_dir, run_id, render_id)
    paths.full.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 20), "white").save(paths.full)
    Image.new("RGB", (8, 4), "white").save(paths.thumb)


def test_render_paths_puts_both_files_under_the_runs_render_directory(tmp_path):
    paths = render_paths(tmp_path, "run-1", "abc")

    assert paths.full == tmp_path / "run-1" / "renders" / "abc.png"
    assert paths.thumb == tmp_path / "run-1" / "renders" / "abc.thumb.png"


def test_delete_render_removes_the_row_and_both_files(tmp_path):
    store = _store(tmp_path)
    record = make_render_record("rnd1", run_id="run-1")
    store.add_render(record)
    _write_files(tmp_path / "output", "run-1", "rnd1")

    assert delete_render(store, tmp_path / "output", record) is True

    paths = render_paths(tmp_path / "output", "run-1", "rnd1")
    assert store.get_render("rnd1") is None
    assert not paths.full.exists()
    assert not paths.thumb.exists()


def test_delete_render_succeeds_when_the_png_is_already_gone(tmp_path):
    """The row is what makes a render exist. A PNG deleted out from under
    it must not turn a delete into a crash."""
    store = _store(tmp_path)
    record = make_render_record("rnd1", run_id="run-1")
    store.add_render(record)

    assert delete_render(store, tmp_path / "output", record) is True
    assert store.get_render("rnd1") is None


def test_delete_render_reports_a_row_that_had_already_gone(tmp_path):
    """Two tabs racing the same delete: the second must be able to tell
    that it removed nothing."""
    store = _store(tmp_path)
    record = make_render_record("rnd1", run_id="run-1")

    assert delete_render(store, tmp_path / "output", record) is False


def test_clear_auto_renders_removes_the_topics_model_written_renders(tmp_path):
    store = _store(tmp_path)
    for rid in ("a", "b"):
        store.add_render(make_render_record(rid, run_id="run-1", topic_id="cat"))
        _write_files(tmp_path / "output", "run-1", rid)

    cleared = clear_auto_renders(store, tmp_path / "output", "run-1", "cat")

    assert cleared == 2
    assert store.renders_for_topic("run-1", "cat") == []
    assert not render_paths(tmp_path / "output", "run-1", "a").full.exists()
    assert not render_paths(tmp_path / "output", "run-1", "b").thumb.exists()


def test_clear_auto_renders_never_touches_a_hand_written_render(tmp_path):
    """The model's output is reproducible by running again; a caption
    somebody typed is not. That asymmetry is the whole reason the origin
    union has two members."""
    store = _store(tmp_path)
    store.add_render(make_render_record("auto", run_id="run-1", topic_id="cat"))
    store.add_render(
        make_render_record(
            "hand", run_id="run-1", topic_id="cat", origin=ManualOrigin()
        )
    )
    _write_files(tmp_path / "output", "run-1", "hand")

    cleared = clear_auto_renders(store, tmp_path / "output", "run-1", "cat")

    assert cleared == 1
    assert [r.id for r in store.renders_for_topic("run-1", "cat")] == ["hand"]
    assert render_paths(tmp_path / "output", "run-1", "hand").full.exists()


def test_clear_auto_renders_leaves_another_topic_alone(tmp_path):
    store = _store(tmp_path)
    store.add_render(make_render_record("cat1", run_id="run-1", topic_id="cat"))
    store.add_render(make_render_record("dog1", run_id="run-1", topic_id="dog"))

    clear_auto_renders(store, tmp_path / "output", "run-1", "cat")

    assert [r.id for r in store.renders_for_topic("run-1", "dog")] == ["dog1"]


def test_clear_auto_renders_leaves_the_same_topic_in_another_run_alone(tmp_path):
    """Renders belong to the run that made them. Re-running one run must
    not reach into another run's output."""
    store = _store(tmp_path)
    store.add_render(make_render_record("old", run_id="run-0", topic_id="cat"))
    store.add_render(make_render_record("new", run_id="run-1", topic_id="cat"))

    clear_auto_renders(store, tmp_path / "output", "run-1", "cat")

    assert [r.id for r in store.renders_for_topic("run-0", "cat")] == ["old"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_renders.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zeitgeist.renders'`.

- [ ] **Step 3: Write the module**

Create `zeitgeist/renders.py`:

```python
"""Where a render's two files live, and how a render is removed.

The database is authoritative for whether a render exists — but a render is
a row *and* a pair of PNGs, and two callers need all three gone together:
`DELETE /api/renders/{id}`, and the re-run that clears a topic's previous
model-written attempts. One function rather than two copies of
`unlink(missing_ok=True)`.

Separate from `store.py`, which knows rows and deliberately nothing about
the filesystem, and from `api/renders.py`, which is the HTTP layer over
this. Nothing here imports `zeitgeist.api`.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from zeitgeist.records import RenderRecord
from zeitgeist.store import Store

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderPaths:
    """A render's two files. `thumb` is the 96px copy the Runs list and the
    topic grid draw; `full` is what the meme view shows."""

    full: Path
    thumb: Path


def render_paths(output_dir: Path, run_id: str, render_id: str) -> RenderPaths:
    """`output/<run_id>/renders/<render_id>.png` and its thumbnail.

    The single definition of that layout. `_render_all`, the on-demand
    executor, image serving and deletion all resolve a render's files
    through here, so swapping the local directory for real object storage
    later touches one function.
    """
    directory = Path(output_dir) / run_id / "renders"
    return RenderPaths(
        full=directory / f"{render_id}.png",
        thumb=directory / f"{render_id}.thumb.png",
    )


def delete_render(store: Store, output_dir: Path, record: RenderRecord) -> bool:
    """Remove the row and both files. False means the row had already gone.

    The row goes first, deliberately. A crash between the two leaves two
    orphaned PNGs that nothing references — invisible, and reclaimed by
    deleting the run directory. The other order would leave a row pointing
    at files that no longer exist, which topic detail draws as a broken
    tile forever.

    A missing PNG is not an error: the row is what makes a render exist,
    and `missing_ok=True` reaches the same end state either way.
    """
    removed = store.delete_render(record.id)
    paths = render_paths(output_dir, record.run_id, record.id)
    paths.full.unlink(missing_ok=True)
    paths.thumb.unlink(missing_ok=True)
    return removed


def clear_auto_renders(
    store: Store, output_dir: Path, run_id: str, topic_id: str
) -> int:
    """Remove this run's model-written renders for one topic, returning how
    many went. Hand-written renders are never touched.

    This is what makes a re-run of `generate` replace its previous attempt
    rather than pile a second one on top of it — the behaviour the old
    CLI's fixed `{position:02d}-{topic_id}.png` filename had by accident,
    restored deliberately now that there is a deletion path to do it
    properly. Without it the tuning loop leaves three renders behind one
    topic after three passes, and the meme count reads 3 where the screen
    shows the latest.

    `manual` is exempt because a person made it. The model's output is
    reproducible by running again; a hand-written caption is not.
    """
    doomed = [
        record
        for record in store.renders_for_topic(run_id, topic_id)
        if record.origin.provenance == "auto"
    ]
    for record in doomed:
        delete_render(store, output_dir, record)
    if doomed:
        log.debug(
            "Cleared %d previous auto render(s) for %s/%s",
            len(doomed),
            run_id,
            topic_id,
        )
    return len(doomed)
```

- [ ] **Step 4: Point `api/renders.py` at the shared layout**

Replace `_image_path` in `zeitgeist/api/renders.py`:

```python
def _image_path(settings: Settings, record: RenderRecord, size: ImageSize) -> Path:
    """The layout lives in `zeitgeist.renders`, which the deletion path and
    the pipeline resolve through too — one definition, several callers."""
    paths = render_paths(settings.output_dir, record.run_id, record.id)
    return paths.full if size == "full" else paths.thumb
```

Add `from zeitgeist.renders import render_paths` to its imports.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_renders.py tests/test_api_renders.py -v`
Expected: PASS. `test_api_renders.py` is included because it proves the delegation did not change where images are served from.

- [ ] **Step 6: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

- [ ] **Step 7: Commit**

```bash
git add zeitgeist/renders.py zeitgeist/api/renders.py tests/test_renders.py
git commit -m "feat: one definition of a render's files, and one way to remove one"
```

---

### Task 4: a re-run of `generate` replaces its previous attempt

Decision 1 from the top of this plan, implemented. `_render_all` clears the topic's prior `auto` renders once the new PNG is on disk — and only when the new render actually succeeded.

That condition is the whole subtlety. Clearing unconditionally means a bad prompt edit, which is the likeliest thing to happen in a tuning loop, deletes the output you were tuning against and leaves a failed row where it was. Clearing on success leaves the previous render beside the failure instead, so the screen shows both what you had and what broke.

`generate_briefs` produces at most one brief per topic, so within one pass no brief can clear another's output. If that ever changes, this clears per topic and would need to move.

**Files:**
- Modify: `zeitgeist/pipeline.py` (`_render_all`)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `clear_auto_renders` (Task 3).
- Produces: nothing new. `_render_all`'s signature is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline.py`. It already has `_settings`, `_store`, `_template_library`, `_FakeTrendSource`, `TEMPLATE_A`. Read the existing resume tests first and follow how they seed checkpoints; the sketch below assumes `run_pipeline` is driven twice against the same `run_id`, the second time with `start_at=Stage.GENERATE`.

```python
def test_re_running_generate_replaces_the_previous_auto_render(tmp_path):
    """The tuning loop re-renders frozen topics. Three passes must leave
    one render behind the topic, not three — which is what the meme count
    on every screen reads."""
    settings = _settings(tmp_path)
    store = _store(tmp_path)
    provider = FakeLLMProvider(
        responses=[
            BriefChoice(
                template_id=TEMPLATE_A,
                caption_slots={"rejected": "first", "preferred": "pass"},
                rationale="first",
            ),
            BriefChoice(
                template_id=TEMPLATE_A,
                caption_slots={"rejected": "second", "preferred": "pass"},
                rationale="second",
            ),
        ]
    )
    topic = ScoredTopic(**make_topic("airport-cat").model_dump(), final_rank=1)
    run_id = "20260901T120000Z"
    store.write_checkpoint(run_id, Stage.EVALUATE, [topic])
    store.write_analyse_checkpoint(run_id, [topic], settings.meme_potential_weight)

    for _ in range(2):
        run_pipeline(
            settings,
            _FakeTrendSource([]),
            provider,
            store,
            run_id,
            start_at=Stage.GENERATE,
        )

    renders = store.renders_for_topic(run_id, "airport-cat")
    assert len(renders) == 1
    assert renders[0].caption_slots["rejected"] == "second"


def test_re_running_generate_leaves_a_hand_written_render_alone(tmp_path):
    """Hand-written renders survive every re-run. Nothing else can
    reproduce them."""
    settings = _settings(tmp_path)
    store = _store(tmp_path)
    run_id = "20260901T120000Z"
    store.add_render(
        make_render_record(
            "hand", run_id=run_id, topic_id="airport-cat", origin=ManualOrigin()
        )
    )
    topic = ScoredTopic(**make_topic("airport-cat").model_dump(), final_rank=1)
    store.write_checkpoint(run_id, Stage.EVALUATE, [topic])
    store.write_analyse_checkpoint(run_id, [topic], settings.meme_potential_weight)

    run_pipeline(
        settings,
        _FakeTrendSource([]),
        FakeLLMProvider(
            responses=[
                BriefChoice(
                    template_id=TEMPLATE_A,
                    caption_slots={"rejected": "a", "preferred": "b"},
                    rationale="r",
                )
            ]
        ),
        store,
        run_id,
        start_at=Stage.GENERATE,
    )

    ids = [r.id for r in store.renders_for_topic(run_id, "airport-cat")]
    assert "hand" in ids
    assert len(ids) == 2


def test_a_failed_re_render_leaves_the_previous_good_one_in_place(tmp_path):
    """A bad prompt edit is the likeliest event in a tuning loop, and it
    must not destroy the output being tuned against.

    This is what makes the clearing conditional: an unconditional clear
    passes every other test in this task and loses the last good render
    exactly when you most want it.
    """
    settings = _settings(tmp_path)
    store = _store(tmp_path)
    run_id = "20260901T120000Z"
    topic = ScoredTopic(**make_topic("airport-cat").model_dump(), final_rank=1)
    store.write_checkpoint(run_id, Stage.EVALUATE, [topic])
    store.write_analyse_checkpoint(run_id, [topic], settings.meme_potential_weight)
    provider = FakeLLMProvider(
        responses=[
            BriefChoice(
                template_id=TEMPLATE_A,
                caption_slots={"rejected": "fits", "preferred": "fine"},
                rationale="r",
            ),
            # Far too long for a 180x80 box at the minimum font size, so
            # render_meme raises RenderError and this pass produces a
            # failed row rather than an image.
            BriefChoice(
                template_id=TEMPLATE_A,
                caption_slots={"rejected": "x " * 400, "preferred": "fine"},
                rationale="r",
            ),
        ]
    )

    for _ in range(2):
        run_pipeline(
            settings, _FakeTrendSource([]), provider, store, run_id,
            start_at=Stage.GENERATE,
        )

    renders = {r.status: r for r in store.renders_for_topic(run_id, "airport-cat")}
    assert set(renders) == {"ready", "failed"}
    assert renders["ready"].caption_slots["rejected"] == "fits"
    assert render_paths(settings.output_dir, run_id, renders["ready"].id).full.is_file()


def test_the_replacement_render_keeps_its_image_on_disk(tmp_path):
    """Clearing happens after the new PNG is written, so the surviving row
    always has files behind it.

    The count assertion is load-bearing: without it, a clear that never
    ran would leave two rows and `[0]` would be the *older* one, whose
    files are also still present — so the test would pass against the
    behaviour it exists to reject.
    """
    settings = _settings(tmp_path)
    store = _store(tmp_path)
    run_id = "20260901T120000Z"
    topic = ScoredTopic(**make_topic("airport-cat").model_dump(), final_rank=1)
    store.write_checkpoint(run_id, Stage.EVALUATE, [topic])
    store.write_analyse_checkpoint(run_id, [topic], settings.meme_potential_weight)
    provider = FakeLLMProvider(
        responses=[
            BriefChoice(
                template_id=TEMPLATE_A,
                caption_slots={"rejected": f"pass {n}", "preferred": "x"},
                rationale="r",
            )
            for n in (1, 2)
        ]
    )

    for _ in range(2):
        run_pipeline(
            settings, _FakeTrendSource([]), provider, store, run_id,
            start_at=Stage.GENERATE,
        )

    renders = store.renders_for_topic(run_id, "airport-cat")
    assert len(renders) == 1
    paths = render_paths(settings.output_dir, run_id, renders[0].id)
    assert paths.full.is_file()
    assert paths.thumb.is_file()
```

Add to `tests/test_pipeline.py`'s imports: `from tests.run_factory import make_render_record, make_topic`, `from zeitgeist.records import ManualOrigin`, `from zeitgeist.renders import render_paths`. `FakeLLMProvider`, `BriefChoice`, `ScoredTopic` and `Stage` are already imported there.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -k "re_running_generate or replacement_render or failed_re_render" -v`
Expected: FAIL — `assert 2 == 1` on the first test: the second pass appends rather than replaces. `test_a_failed_re_render_leaves_the_previous_good_one_in_place` passes already, because appending is one of the two behaviours that satisfy it; it turns red only if you then write the clear unconditionally, which is exactly the mistake it exists to catch.

- [ ] **Step 3: Clear the topic's prior auto renders in `_render_all`**

In `zeitgeist/pipeline.py`, add `from zeitgeist.renders import clear_auto_renders` to the imports, then insert one call in `_render_all`'s loop, immediately before `store.add_render(record)`:

```python
        # The tuning loop re-runs generate against frozen topics, and the
        # old CLI's fixed `{position:02d}-{topic_id}.png` filename meant a
        # second pass replaced the first. `uuid4` ids do not, so this does
        # it explicitly.
        #
        # Only a *successful* render replaces its predecessor. Clearing
        # unconditionally would mean a bad prompt edit — the single most
        # likely thing to happen in a tuning loop — destroys the last good
        # output and leaves a failed row in its place, which is the worst
        # outcome available. Failing this way instead leaves the previous
        # render beside the failure, so you can see both what you had and
        # what broke.
        #
        # It also runs after the new PNG is on disk, so the surviving row
        # always has files behind it and an abort in between costs
        # nothing that was not already replaced.
        #
        # Hand-written renders are never touched — see clear_auto_renders.
        # `generate_briefs` produces at most one brief per topic, so no
        # brief in this loop can clear another's output.
        if error is None:
            clear_auto_renders(store, settings.output_dir, run_id, brief.topic_id)
        store.add_render(record)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: PASS. Watch the pre-existing resume tests: any that assert a render count across two passes were asserting the old append behaviour and must be updated to the replacement behaviour, with a comment pointing at Decision 1 in this plan.

- [ ] **Step 5: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

- [ ] **Step 6: Commit**

```bash
git add zeitgeist/pipeline.py tests/test_pipeline.py
git commit -m "feat: re-running generate replaces its previous attempt, sparing manual renders"
```

---
### Task 5: `zeitgeist/generation.py` — the request models and the work itself

The request shapes, the job a worker executes, and `generate_renders(job, store)` — the whole of the model-written and hand-written paths, as a plain function over a job and a store. No threads yet: this task is testable by building a job by hand and calling it, which is also how Task 6's fake seam is shaped.

**Files:**
- Create: `zeitgeist/generation.py`
- Test: `tests/test_generation.py`

**Interfaces:**
- Consumes: `generate_brief` (Task 1); `render_paths` (Task 3); `Store.update_render` (Task 2). `check_slots` is not used here — validating a hand-written request belongs on the request thread, in Task 6.
- Produces:
  - `MAX_RENDERS: int = 4`
  - `LLMGeneration(mode: Literal["llm"], template_id: str, count: int)` — `count` bounded `1..MAX_RENDERS`, default 1.
  - `ManualGeneration(mode: Literal["manual"], template_id: str, caption_slots: dict[str, str])`
  - `GenerationRequest = LLMGeneration | ManualGeneration`
  - `GenerationJob` — frozen dataclass: `settings`, `request`, `topic`, `templates`, `records`, `provider`.
  - `generate_renders(job: GenerationJob, store: Store) -> None`
  - `GenerateFn = Callable[[GenerationJob, Store], None]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_generation.py`:

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tests.run_factory import make_render_record, make_topic
from tests.template_factory import make_manifest, make_slot, write_library
from zeitgeist.config import Settings
from zeitgeist.generation import (
    MAX_RENDERS,
    GenerationJob,
    LLMGeneration,
    ManualGeneration,
    generate_renders,
)
from zeitgeist.llm.base import FakeLLMProvider, LLMError
from zeitgeist.media.brief import BriefChoice
from zeitgeist.media.templates import load_templates
from zeitgeist.records import AutoOrigin, ManualOrigin, RenderRecord
from zeitgeist.renders import render_paths
from zeitgeist.store import Store

TEMPLATE = "shape_alpha"
SLOTS = {"rejected": "queueing forever", "preferred": "the airport cat"}


def _settings(tmp_path) -> Settings:
    """The settings every job in this module runs under.

    `anthropic_api_key` is set because `GenerationService.submit` calls
    `build_provider` on the request thread, and `llm_provider` defaults to
    `"anthropic"`, whose factory raises `ValueError` on an empty key —
    which `conftest`'s autouse fixture guarantees, since it strips
    `ANTHROPIC_API_KEY` from the environment for every test. Without this
    every `LLMGeneration` test would die in `submit` before reaching the
    behaviour it names. It stays hermetic: `AnthropicProvider.__init__`
    only constructs the SDK client and makes no network call, and every
    test here supplies its own `FakeLLMProvider` for the actual work.
    """
    return Settings(
        _env_file=None,
        output_dir=tmp_path / "output",
        db_path=tmp_path / "z.db",
        anthropic_api_key="key",
        templates_dir=write_library(
            tmp_path / "templates",
            make_manifest(
                TEMPLATE,
                slots=[
                    make_slot("rejected", box=(10, 10, 190, 90)),
                    make_slot("preferred", box=(10, 110, 190, 190)),
                ],
            ),
        ),
    )


def _store(tmp_path) -> Store:
    store = Store(tmp_path / "z.db")
    store.init_schema()
    return store


def _seeded(store: Store, rid: str, **overrides) -> RenderRecord:
    """A row as `GenerationService._seed` would have written it.

    The defaults are merged rather than splatted alongside `**overrides`,
    which would raise `TypeError: got multiple values for 'caption_slots'`
    the moment a test overrides one of them — and the manual tests do.
    """
    defaults: dict = dict(
        run_id="run-1",
        topic_id="airport-cat",
        template_id=TEMPLATE,
        status="generating",
        caption_slots={},
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    record = make_render_record(rid, **(defaults | overrides))
    store.add_render(record)
    return record


def _job(tmp_path, request, records, provider=None) -> GenerationJob:
    settings = _settings(tmp_path)
    return GenerationJob(
        settings=settings,
        request=request,
        topic=make_topic("airport-cat"),
        templates=load_templates(settings.templates_dir),
        records=records,
        provider=provider,
    )


def test_a_hand_written_render_becomes_ready_with_the_captions_given(tmp_path):
    store = _store(tmp_path)
    record = _seeded(store, "rnd1", caption_slots=SLOTS, origin=ManualOrigin())

    generate_renders(
        _job(
            tmp_path,
            ManualGeneration(template_id=TEMPLATE, caption_slots=SLOTS),
            [record],
        ),
        store,
    )

    finished = store.get_render("rnd1")
    assert finished is not None
    assert finished.status == "ready"
    assert finished.caption_slots == SLOTS
    assert finished.origin == ManualOrigin()


def test_a_hand_written_render_writes_both_files(tmp_path):
    """Thumbnails are generated by the same code path that writes the
    render, so the grid never scales an 800KB PNG down to 42px."""
    store = _store(tmp_path)
    record = _seeded(store, "rnd1", caption_slots=SLOTS, origin=ManualOrigin())
    job = _job(
        tmp_path,
        ManualGeneration(template_id=TEMPLATE, caption_slots=SLOTS),
        [record],
    )

    generate_renders(job, store)

    paths = render_paths(job.settings.output_dir, "run-1", "rnd1")
    assert paths.full.is_file()
    assert paths.thumb.is_file()


def test_a_model_written_render_records_the_rationale_it_came_back_with(tmp_path):
    """The full-size view shows WHY THIS TEMPLATE, so the rationale has to
    survive from the brief onto the row."""
    store = _store(tmp_path)
    record = _seeded(store, "rnd1")
    provider = FakeLLMProvider(
        responses=[
            BriefChoice(
                template_id=TEMPLATE,
                caption_slots=SLOTS,
                rationale="the contrast fits the joke",
            )
        ]
    )

    generate_renders(
        _job(tmp_path, LLMGeneration(template_id=TEMPLATE), [record], provider),
        store,
    )

    finished = store.get_render("rnd1")
    assert finished is not None
    assert finished.status == "ready"
    assert finished.caption_slots == SLOTS
    assert finished.origin == AutoOrigin(rationale="the contrast fits the joke")


def test_the_model_is_only_offered_the_template_the_panel_named(tmp_path):
    """The choice was already made in the UI, so the prompt's library is
    narrowed to one and the model writes captions rather than picking.

    This test builds its own two-template library rather than using
    `_settings`. With the module's usual one-template library, `job.
    templates` and the narrowed `{template_id: ...}` hold the same single
    entry, so deleting the narrowing in `_brief_for` would produce an
    identical prompt and this test could not fail for the behaviour it
    names.
    """
    store = _store(tmp_path)
    settings = Settings(
        _env_file=None,
        output_dir=tmp_path / "output",
        db_path=tmp_path / "z.db",
        anthropic_api_key="key",
        templates_dir=write_library(
            tmp_path / "templates",
            *(
                make_manifest(
                    tid,
                    slots=[
                        make_slot("rejected", box=(10, 10, 190, 90)),
                        make_slot("preferred", box=(10, 110, 190, 190)),
                    ],
                )
                for tid in (TEMPLATE, "shape_other")
            ),
        ),
    )
    provider = FakeLLMProvider(
        responses=[
            BriefChoice(template_id=TEMPLATE, caption_slots=SLOTS, rationale="r")
        ]
    )

    generate_renders(
        GenerationJob(
            settings=settings,
            request=LLMGeneration(template_id=TEMPLATE),
            topic=make_topic("airport-cat"),
            templates=load_templates(settings.templates_dir),
            records=[_seeded(store, "rnd1")],
            provider=provider,
        ),
        store,
    )

    prompt = provider.calls[0].prompt
    assert f"id={TEMPLATE}" in prompt
    assert "id=shape_other" not in prompt
    assert prompt.count("id=") == 1


def test_each_requested_render_gets_its_own_brief(tmp_path):
    """count=2 is two model calls and two rows, not one brief drawn twice
    — the panel offers a count so you can compare captions."""
    store = _store(tmp_path)
    records = [_seeded(store, "a"), _seeded(store, "b")]
    provider = FakeLLMProvider(
        responses=[
            BriefChoice(
                template_id=TEMPLATE,
                caption_slots={"rejected": text, "preferred": "x"},
                rationale="r",
            )
            for text in ("first", "second")
        ]
    )

    generate_renders(
        _job(tmp_path, LLMGeneration(template_id=TEMPLATE, count=2), records, provider),
        store,
    )

    finished = store.renders_for_topic("run-1", "airport-cat")
    assert len(provider.calls) == 2
    assert sorted(r.caption_slots["rejected"] for r in finished) == ["first", "second"]


def test_a_brief_that_never_validates_leaves_a_failed_row_carrying_why(tmp_path):
    """A failed tile with a message, rather than a tile that vanishes. The
    record already holds the outcome; nothing else has to."""
    store = _store(tmp_path)
    provider = FakeLLMProvider(responses=[LLMError("the model is down")])

    generate_renders(
        _job(
            tmp_path,
            LLMGeneration(template_id=TEMPLATE),
            [_seeded(store, "rnd1")],
            provider,
        ),
        store,
    )

    finished = store.get_render("rnd1")
    assert finished is not None
    assert finished.status == "failed"
    assert finished.error is not None
    assert "the model is down" in finished.error


def test_one_failed_brief_does_not_stop_the_next_one(tmp_path):
    """Per-render failure, exactly as `_render_all` already does per
    brief: three of five rendered is a real outcome."""
    store = _store(tmp_path)
    records = [_seeded(store, "a"), _seeded(store, "b")]
    provider = FakeLLMProvider(
        responses=[
            LLMError("transient"),
            BriefChoice(template_id=TEMPLATE, caption_slots=SLOTS, rationale="r"),
        ]
    )

    generate_renders(
        _job(tmp_path, LLMGeneration(template_id=TEMPLATE, count=2), records, provider),
        store,
    )

    statuses = {r.id: r.status for r in store.renders_for_topic("run-1", "airport-cat")}
    assert statuses == {"a": "failed", "b": "ready"}


def test_a_caption_too_long_for_its_box_leaves_a_failed_row(tmp_path):
    """RenderError is per meme. The row carries the message the tile
    shows instead of the image."""
    store = _store(tmp_path)
    slots = {"rejected": "x " * 400, "preferred": "y"}
    record = _seeded(store, "rnd1", caption_slots=slots, origin=ManualOrigin())

    generate_renders(
        _job(
            tmp_path,
            ManualGeneration(template_id=TEMPLATE, caption_slots=slots),
            [record],
        ),
        store,
    )

    finished = store.get_render("rnd1")
    assert finished is not None
    assert finished.status == "failed"
    assert finished.error is not None


def test_a_render_deleted_while_generating_stays_deleted(tmp_path):
    """The database is authoritative for whether a render exists. A job
    finishing must not bring back a row somebody removed."""
    store = _store(tmp_path)
    record = _seeded(store, "rnd1", caption_slots=SLOTS, origin=ManualOrigin())
    store.delete_render("rnd1")

    generate_renders(
        _job(
            tmp_path,
            ManualGeneration(template_id=TEMPLATE, caption_slots=SLOTS),
            [record],
        ),
        store,
    )

    assert store.get_render("rnd1") is None


def test_count_above_the_cap_is_refused_by_the_model():
    """The panel's grid is 4-up, and a count of 50 is a request for fifty
    model calls on one click."""
    with pytest.raises(ValidationError):
        LLMGeneration(template_id=TEMPLATE, count=MAX_RENDERS + 1)


def test_count_below_one_is_refused_by_the_model():
    with pytest.raises(ValidationError):
        LLMGeneration(template_id=TEMPLATE, count=0)


def test_a_manual_request_has_no_count_field():
    """Captions somebody typed describe exactly one meme. A count beside
    them would be a representable state with no meaning — `STRICT` forbids
    extras, which is what makes that unrepresentable rather than ignored."""
    with pytest.raises(ValidationError):
        ManualGeneration(template_id=TEMPLATE, caption_slots=SLOTS, count=2)
```

Add `MAX_RENDERS` to the `zeitgeist.generation` import so the cap test asserts against the constant rather than restating it — a raised cap should not need this test edited, only its boundary re-checked.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_generation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zeitgeist.generation'`.

- [ ] **Step 3: Write the models and the job**

Create `zeitgeist/generation.py` with this first half:

```python
"""On-demand meme generation: what topic detail's two panels drive.

Separate from `RunService` deliberately. The design shows tiles generating
on topic detail while a run is in flight, so the two cannot share a worker.
That means two concurrent callers of the LLM provider — free on Anthropic,
contended on local Ollama, where inference serialises on one GPU.
Documented rather than solved with a global lock.

Imports nothing from `zeitgeist.api`, for the same reason `runner.py` does
not: generation is a pipeline concern the API drives, not the reverse. The
request models live here rather than in `api/schemas.py` on that same rule,
exactly as `RunRequest` does.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from zeitgeist.config import Settings
from zeitgeist.llm.base import LLMProvider
from zeitgeist.media.brief import BriefError, generate_brief
from zeitgeist.media.render import RenderError, render_meme, write_thumbnail
from zeitgeist.media.templates import TemplateManifest
from zeitgeist.models import STRICT, MediaBrief, Topic
from zeitgeist.records import AutoOrigin, ManualOrigin, Origin, RenderRecord
from zeitgeist.renders import render_paths
from zeitgeist.store import Store

log = logging.getLogger(__name__)

MAX_RENDERS = 4
"""Renders per request. The design's grid is 4-up, and the panel offers a
count rather than an unbounded field: `count=50` is fifty model calls on a
single click, on a provider that may be one local GPU."""


class LLMGeneration(BaseModel):
    """Ask the model to write `count` briefs against one named template.

    The template is named rather than chosen, because the panel already
    made that choice. The model writes captions for it and explains them.
    """

    model_config = STRICT

    mode: Literal["llm"] = "llm"
    template_id: str
    count: Annotated[int, Field(ge=1, le=MAX_RENDERS)] = 1


class ManualGeneration(BaseModel):
    """Render captions a person typed.

    No `count`: the captions describe exactly one meme, and a count beside
    them would be a representable state with no meaning. No model call, so
    nothing to explain either — the row's `ManualOrigin` has no rationale
    field at all.
    """

    model_config = STRICT

    mode: Literal["manual"] = "manual"
    template_id: str
    caption_slots: dict[str, str]


GenerationRequest = LLMGeneration | ManualGeneration
"""The two panels. Discriminated on `mode` where it crosses the wire — see
`api/generate.py`, which is the only place that needs the discriminator;
inside this module the union is narrowed with `isinstance`."""


@dataclass(frozen=True)
class GenerationJob:
    """Everything a worker needs, resolved on the request thread.

    Resolved up front rather than looked up in the worker, so an unknown
    template, a missing topic or an unusable provider is a 4xx before any
    row exists — not a failed tile the user has to read to find out their
    request was malformed.
    """

    settings: Settings
    request: GenerationRequest
    topic: Topic
    templates: dict[str, TemplateManifest]
    # Already inserted, already `generating`. The worker fills them in.
    records: list[RenderRecord]
    # None for a manual job, which makes no model call. A real state, not
    # a placeholder: building a provider for a hand-written render would
    # refuse a request that needs no API key at all.
    provider: LLMProvider | None


GenerateFn = Callable[[GenerationJob, Store], None]
```

- [ ] **Step 4: Write `generate_renders` and its two helpers**

Append to `zeitgeist/generation.py`:

```python
def generate_renders(job: GenerationJob, store: Store) -> None:
    """Fill in every seeded record. One render's failure is one row.

    Injectable through `GenerationService(generate=...)` so an API test can
    drive the endpoint without Pillow or a model, the same seam
    `RunService` gives `_execute`.
    """
    for record in job.records:
        try:
            brief = _brief_for(job)
        except BriefError as exc:
            log.warning("Could not brief %s: %s", record.topic_id, exc)
            store.update_render(
                record.model_copy(update={"status": "failed", "error": str(exc)})
            )
            continue
        _draw(job, store, record, brief)


def _brief_for(job: GenerationJob) -> MediaBrief:
    """The captions to draw, however they were arrived at."""
    request = job.request
    if isinstance(request, ManualGeneration):
        # A transport object for the renderer, not a record of provenance:
        # the row's ManualOrigin carries that, and it has no rationale
        # field. Empty here rather than invented copy.
        return MediaBrief(
            topic_id=job.topic.id,
            template_id=request.template_id,
            caption_slots=dict(request.caption_slots),
            rationale="",
        )
    if job.provider is None:
        raise BriefError("An llm generation job was built with no provider")
    # Narrowed to the one template the panel named. `generate_brief`
    # validates the model's answer against this library, so a model that
    # names anything else is retried and then fails, rather than rendering
    # onto a template nobody asked for.
    return generate_brief(
        job.topic,
        {request.template_id: job.templates[request.template_id]},
        job.provider,
    )


def _draw(
    job: GenerationJob, store: Store, record: RenderRecord, brief: MediaBrief
) -> None:
    """Composite the brief, write both files, and finish the row.

    `update_render` rather than `add_render`: a render deleted while this
    job was running must stay deleted, and an UPDATE against a missing row
    is a no-op. The PNG written just above is then orphaned, which is
    invisible and reclaimed with the run directory.
    """
    paths = render_paths(job.settings.output_dir, record.run_id, record.id)
    error: str | None = None
    try:
        render_meme(
            brief,
            job.templates[brief.template_id],
            job.settings.templates_dir,
            paths.full,
            job.settings.font_path,
        )
        write_thumbnail(paths.full, paths.thumb)
    except RenderError as exc:
        log.warning("Could not render %s: %s", record.topic_id, exc)
        error = str(exc)

    store.update_render(
        record.model_copy(
            update={
                "template_id": brief.template_id,
                "caption_slots": dict(brief.caption_slots),
                "origin": _origin(job.request, brief),
                "status": "failed" if error else "ready",
                "error": error,
            }
        )
    )


def _origin(request: GenerationRequest, brief: MediaBrief) -> Origin:
    """Fixed by which panel asked. A hand-written render has no template
    choice to justify — the person made it."""
    if isinstance(request, ManualGeneration):
        return ManualOrigin()
    return AutoOrigin(rationale=brief.rationale)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_generation.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

- [ ] **Step 7: Commit**

```bash
git add zeitgeist/generation.py tests/test_generation.py
git commit -m "feat: the model-written and hand-written render paths"
```

---
### Task 6: `GenerationService` — validation, seeded rows, and the executor

The service that turns a request into rows and a job. It validates on the request thread so failures are 4xx rather than failed tiles; it writes `generating` rows before returning so the client's tiles have real ids; and it hands the work to a one-worker pool whose thread opens its own `Store`.

`RunService._build_settings` becomes a module-level function first, because this service needs exactly the same layering and duplicating that docstring's reasoning would guarantee the two drift.

**Files:**
- Modify: `zeitgeist/runner.py` (extract `resolve_settings`)
- Modify: `zeitgeist/generation.py` (append the service)
- Test: `tests/test_runner.py`, `tests/test_generation.py`

**Interfaces:**
- Consumes: `generate_renders`, `GenerationJob`, `GenerationRequest` (Task 5); `check_slots` (Task 1); `Store.read_checkpoint`, `Store.add_render`.
- Produces:
  - `resolve_settings(base: Settings, overrides: dict[str, str]) -> Settings` in `zeitgeist/runner.py`
  - `UnknownTopic(LookupError)`, `GenerationRefused(ValueError)`
  - `GenerationService(settings, store, *, generate: GenerateFn | None = None)` with `submit(run_id, topic_id, request) -> list[RenderRecord]` and `shutdown(*, wait: bool = True) -> None`. One injectable seam, not two — see the note after Step 4 for why there is no `worker_store`.

- [ ] **Step 1: Write the failing test for the settings extraction**

Append to `tests/test_runner.py`:

```python
def test_resolve_settings_picks_up_a_value_written_to_the_settings_table(tmp_path):
    """The base snapshot is fixed when the service is constructed. A field
    the settings screen writes afterwards must still reach the next run —
    and the next generation job, which layers the same way."""
    store = Store(Path(os.environ["DB_PATH"]))
    store.init_schema()
    store.set_setting("distil_concurrency", "7")

    resolved = resolve_settings(Settings(_env_file=None), {})

    assert resolved.distil_concurrency == 7


def test_resolve_settings_lets_an_override_outrank_the_table(tmp_path):
    store = Store(Path(os.environ["DB_PATH"]))
    store.init_schema()
    store.set_setting("distil_concurrency", "7")

    resolved = resolve_settings(Settings(_env_file=None), {"distil_concurrency": "2"})

    assert resolved.distil_concurrency == 2


def test_resolve_settings_keeps_fields_a_run_cannot_set(tmp_path):
    """`output_dir` and `db_path` may hold programmatic values the API was
    constructed with. Only the run-settable fields resolve afresh."""
    base = Settings(_env_file=None, output_dir=tmp_path / "somewhere")

    resolved = resolve_settings(base, {})

    assert resolved.output_dir == tmp_path / "somewhere"
```

Add `from zeitgeist.runner import resolve_settings` to that module's imports; `os`, `Path`, `Settings` and `Store` are already there or need adding.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_runner.py -k resolve_settings -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_settings'`.

- [ ] **Step 3: Extract `resolve_settings`**

In `zeitgeist/runner.py`, move the body of `RunService._build_settings` to a module-level function, carrying its docstring across verbatim and adding one paragraph about the second caller. Place it after `RUN_OVERRIDE_KEYS`:

```python
def resolve_settings(base: Settings, overrides: dict[str, str]) -> Settings:
    """Build a per-run `Settings`: `base` for everything not run-settable,
    `overrides` for what is, and the normal precedence chain for the rest.

    Only the fields *outside* `RUN_OVERRIDE_KEYS` are taken from `base`.
    Those are the fields a run cannot set for itself — `db_path`,
    `output_dir`, `anthropic_api_key` and the rest — and the API's own
    `Settings` may carry programmatic values for them that must survive.
    Splatting *every* field would pin every run-settable field at its value
    from the caller's construction: `init_settings` outranks everything
    else in `Settings.settings_customise_sources`, so a value written to
    the settings table afterwards (`PUT /api/settings`) would never reach a
    run started later. Leaving those fields out lets them resolve through
    the normal precedence chain instead, picking up the table's current
    value when the request itself does not override them.

    Building a fresh `Settings` rather than `model_copy(update=...)`, which
    bypasses validation entirely: `"9"` would stay the string `"9"` for
    `topic_count`, with no error raised anywhere. Constructing instead runs
    the overrides through pydantic as constructor arguments — the
    highest-precedence layer, which is exactly what a per-run override
    should be — so they arrive coerced to the right type, and an invalid
    one (an unknown source, a non-numeric count) raises `ValueError` here.

    A module-level function rather than a `RunService` method because
    `GenerationService` needs the identical layering: an on-demand render
    is a new action taken now, against the settings in force now, and a
    second copy of the reasoning above would drift from this one.
    """
    snapshot = base.model_dump(exclude=set(RUN_OVERRIDE_KEYS))
    return Settings(**(snapshot | dict(overrides)))
```

Replace the method with a delegating one-liner, keeping a short docstring pointing at the function:

```python
    def _build_settings(self, overrides: dict[str, str]) -> Settings:
        """This service's own settings, layered with the request's
        overrides. See `resolve_settings`."""
        return resolve_settings(self._settings, overrides)
```

- [ ] **Step 4: Write the failing tests for the service**

Append to `tests/test_generation.py`:

```python
def _service(tmp_path, store, **kwargs) -> GenerationService:
    return GenerationService(_settings(tmp_path), store, **kwargs)


def _seed_topics(store: Store, *topics) -> None:
    store.write_analyse_checkpoint("run-1", list(topics), 0.3)


@dataclass
class RecordingGenerate:
    """Captures the job instead of doing the work, so a test can assert
    what the request thread resolved without a model or Pillow."""

    jobs: list[GenerationJob] = field(default_factory=list)

    def __call__(self, job: GenerationJob, store: Store) -> None:
        self.jobs.append(job)


def test_submit_returns_generating_rows_that_are_already_in_the_database(tmp_path):
    """The tiles the client draws need real ids and must survive a
    refresh, so the rows exist before the response does."""
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    service = _service(tmp_path, store, generate=RecordingGenerate())

    records = service.submit(
        "run-1", "airport-cat", ManualGeneration(template_id=TEMPLATE, caption_slots=SLOTS)
    )
    service.shutdown()

    assert [r.status for r in records] == ["generating"]
    assert store.get_render(records[0].id) is not None


def test_submit_writes_one_row_per_requested_render(tmp_path):
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    service = _service(tmp_path, store, generate=RecordingGenerate())

    records = service.submit(
        "run-1", "airport-cat", LLMGeneration(template_id=TEMPLATE, count=3)
    )
    service.shutdown()

    assert len(records) == 3
    assert len({r.id for r in records}) == 3


def test_a_generating_auto_row_carries_no_captions_and_no_rationale_yet(tmp_path):
    """`generating` is the state in which the brief is not yet written.
    Consumers must not read either field until it is."""
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    service = _service(tmp_path, store, generate=RecordingGenerate())

    records = service.submit("run-1", "airport-cat", LLMGeneration(template_id=TEMPLATE))
    service.shutdown()

    assert records[0].caption_slots == {}
    assert records[0].origin == AutoOrigin(rationale="")


def test_a_generating_manual_row_already_carries_its_captions(tmp_path):
    """Nothing has to be discovered for a hand-written render, so the row
    is complete from the start except for its status."""
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    service = _service(tmp_path, store, generate=RecordingGenerate())

    records = service.submit(
        "run-1",
        "airport-cat",
        ManualGeneration(template_id=TEMPLATE, caption_slots=SLOTS),
    )
    service.shutdown()

    assert records[0].caption_slots == SLOTS
    assert records[0].origin == ManualOrigin()


def test_submit_briefs_a_topic_that_was_never_ranked(tmp_path):
    """The below-the-cut `generate` link. The topic is in the analyse
    checkpoint, which holds every topic, not just the kept ones."""
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"), make_topic("below-the-cut"))
    recorder = RecordingGenerate()
    service = _service(tmp_path, store, generate=recorder)

    service.submit("run-1", "below-the-cut", LLMGeneration(template_id=TEMPLATE))
    service.shutdown()

    assert recorder.jobs[0].topic.id == "below-the-cut"


def test_submit_refuses_a_topic_the_run_never_saw(tmp_path):
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    service = _service(tmp_path, store, generate=RecordingGenerate())

    with pytest.raises(UnknownTopic):
        service.submit("run-1", "no-such-topic", LLMGeneration(template_id=TEMPLATE))


def test_submit_refuses_a_template_that_is_not_in_the_library(tmp_path):
    """Refused before any row exists, so a typo costs nothing and leaves
    nothing behind."""
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    service = _service(tmp_path, store, generate=RecordingGenerate())

    with pytest.raises(GenerationRefused):
        service.submit("run-1", "airport-cat", LLMGeneration(template_id="nope"))

    assert store.renders_for_topic("run-1", "airport-cat") == []


def test_submit_refuses_hand_written_captions_that_do_not_fit_the_template(tmp_path):
    """The same rule the model's answer is held to. Accepting these would
    turn a bad request into a failed tile."""
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    service = _service(tmp_path, store, generate=RecordingGenerate())

    with pytest.raises(GenerationRefused):
        service.submit(
            "run-1",
            "airport-cat",
            ManualGeneration(template_id=TEMPLATE, caption_slots={"rejected": "only"}),
        )

    assert store.renders_for_topic("run-1", "airport-cat") == []


def test_submit_raises_missing_checkpoint_when_the_run_never_analysed(tmp_path):
    """A run that died in ingest has nothing to brief from, and the
    endpoint has to say that rather than 404 the topic."""
    store = _store(tmp_path)
    service = _service(tmp_path, store, generate=RecordingGenerate())

    with pytest.raises(MissingCheckpoint):
        service.submit("run-1", "airport-cat", LLMGeneration(template_id=TEMPLATE))


def test_a_manual_job_is_built_with_no_provider(tmp_path):
    """A hand-written render makes no model call, so it must not need an
    API key to be accepted."""
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    recorder = RecordingGenerate()
    service = _service(tmp_path, store, generate=recorder)

    service.submit(
        "run-1",
        "airport-cat",
        ManualGeneration(template_id=TEMPLATE, caption_slots=SLOTS),
    )
    service.shutdown()

    assert recorder.jobs[0].provider is None


def test_on_demand_generation_appends_rather_than_replacing(tmp_path):
    """The opposite of a re-run of the generate stage: this is an additive
    action somebody took, and clearing would delete what they are
    comparing against."""
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    store.add_render(
        make_render_record("older", run_id="run-1", topic_id="airport-cat")
    )
    service = _service(tmp_path, store, generate=RecordingGenerate())

    service.submit("run-1", "airport-cat", LLMGeneration(template_id=TEMPLATE))
    service.shutdown()

    ids = [r.id for r in store.renders_for_topic("run-1", "airport-cat")]
    assert "older" in ids
    assert len(ids) == 2


def test_a_job_that_raises_leaves_every_unfinished_row_failed(tmp_path):
    """A crash in the worker must not leave tiles spinning forever. The
    backstop reads the database rather than the in-memory records, so a
    row the job already finished is left alone."""
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))

    def explode(job: GenerationJob, store: Store) -> None:
        raise RuntimeError("the worker fell over")

    service = _service(tmp_path, store, generate=explode)
    records = service.submit(
        "run-1", "airport-cat", LLMGeneration(template_id=TEMPLATE, count=2)
    )
    service.shutdown()

    finished = [store.get_render(r.id) for r in records]
    assert all(f is not None and f.status == "failed" for f in finished)
    assert all(f is not None and f.error is not None for f in finished)


def test_a_job_that_raises_leaves_an_already_finished_row_alone(tmp_path):
    """The backstop reads each row back rather than trusting the in-memory
    records: a render the job already finished before it fell over must
    keep its real outcome, not be overwritten to failed.

    Without this, dropping the `status != "generating"` half of the guard
    in `_fail_unfinished` would break nothing — the test above raises
    before any record is finished, so every row is still generating when
    the backstop runs.
    """
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))

    def finish_first_then_explode(job: GenerationJob, store: Store) -> None:
        first, _second = job.records
        store.update_render(first.model_copy(update={"status": "ready"}))
        raise RuntimeError("the worker fell over")

    service = _service(tmp_path, store, generate=finish_first_then_explode)
    records = service.submit(
        "run-1", "airport-cat", LLMGeneration(template_id=TEMPLATE, count=2)
    )
    service.shutdown()

    first, second = (store.get_render(r.id) for r in records)
    assert first is not None and first.status == "ready"
    assert second is not None and second.status == "failed"


def test_a_submitted_job_really_renders_when_nothing_is_injected(tmp_path):
    """The one test that wires `submit` to the real `generate_renders`.

    Every other service test injects a fake, so the default in
    `GenerationService.__init__` — `generate or generate_renders` — is
    otherwise never exercised: pointing it at a no-op, or forgetting to
    put `records` on the job, would break nothing in the suite while
    leaving every tile in the browser generating forever.
    """
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    service = _service(tmp_path, store)

    records = service.submit(
        "run-1",
        "airport-cat",
        ManualGeneration(template_id=TEMPLATE, caption_slots=SLOTS),
    )
    service.shutdown()

    finished = store.get_render(records[0].id)
    assert finished is not None
    assert finished.status == "ready"
    assert render_paths(
        _settings(tmp_path).output_dir, "run-1", records[0].id
    ).full.is_file()


```

There is deliberately no test asserting that the worker opened its own connection. The draft had one, injecting a `worker_store` factory and counting its calls — an assertion about the double rather than about the service, which passes whenever the double is wired up and says nothing about correctness. The behaviour it was reaching for is already covered by `test_a_submitted_job_really_renders_when_nothing_is_injected`: `_store(tmp_path)` opens with `check_same_thread=True`, so a `_run` that reused `self._store` raises `sqlite3.ProgrammingError` on the pool thread, `_run`'s handler marks the rows failed, and that test's `status == "ready"` assertion goes red. With no test needing the seam, `GenerationService` does not take a `worker_store` parameter at all.

Add to `tests/test_generation.py`'s imports: `pytest`, `from dataclasses import dataclass, field`, `from zeitgeist.generation import GenerationRefused, GenerationService, UnknownTopic`, `from zeitgeist.store import MissingCheckpoint`, `from tests.run_factory import make_render_record`.

- [ ] **Step 5: Run them to verify they fail**

Run: `uv run pytest tests/test_generation.py -k "submit or worker or job_that_raises or generating_" -v`
Expected: FAIL — `ImportError: cannot import name 'GenerationService'`.

- [ ] **Step 6: Write the service**

Append to `zeitgeist/generation.py`. Add these imports at the top of the module: `import threading`, `from concurrent.futures import ThreadPoolExecutor`, `from datetime import UTC, datetime`, `from uuid import uuid4`, `from zeitgeist.llm.factory import build_provider`, `from zeitgeist.media.brief import check_slots`, `from zeitgeist.media.templates import load_templates`, `from zeitgeist.records import Stage`, `from zeitgeist.runner import resolve_settings`, `from zeitgeist.models import Topic`.

```python
class UnknownTopic(LookupError):
    """No topic with that id in the run's `analyse` checkpoint.

    A `LookupError` rather than a `ValueError` so the endpoint can map it
    to 404 ahead of the 400 that `GenerationRefused` and `build_provider`
    both raise: a topic that is not there is a different story from a
    request that is malformed.
    """


class GenerationRefused(ValueError):
    """The request named a template that is not in the library, or captions
    that do not fit the template's slots.

    A `ValueError` subclass so an endpoint catching `ValueError` — which is
    also what `build_provider` raises for a missing API key — gives all of
    them the 400 they deserve.
    """


class GenerationService:
    """The on-demand executor and everything it validates first.

    One worker, deliberately. The run worker is the other concurrent caller
    of the LLM provider, and a second generation thread would make three
    against a local Ollama that serialises on one GPU. "Small" is the
    spec's word for it.

    No `start()`, unlike `RunService`. A run worker has to be running
    before any request arrives because it drains a queue; a generation pool
    has nothing to do until a request arrives, so the pool is created on
    first use and `ThreadPoolExecutor` spawns no thread before then. An app
    that is built and never entered therefore leaves no thread behind,
    which is the same property `RunService.start` living in the lifespan
    buys.
    """

    def __init__(
        self,
        settings: Settings,
        store: Store,
        *,
        generate: GenerateFn | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._generate = generate or generate_renders
        self._pool: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()

    def _ensure_pool(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._pool is None:
                self._pool = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="zeitgeist-generate"
                )
            return self._pool

    def shutdown(self, *, wait: bool = True) -> None:
        """Close the pool, waiting for what is in flight. Called from the
        app's lifespan, and from tests that need a job to have finished
        without sleeping for it."""
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=wait)

    def submit(
        self, run_id: str, topic_id: str, request: GenerationRequest
    ) -> list[RenderRecord]:
        """Validate, write the `generating` rows, and queue the work.

        Everything that can be refused is refused here, on the request
        thread, before a single row exists: the topic, the template, the
        captions and the provider. A request that gets past this line has
        rows the client can draw, and any failure after it is a per-render
        outcome the row itself carries.

        `MissingCheckpoint` propagates: a run that never analysed has
        nothing to brief from, which is a different answer from "no such
        topic".
        """
        settings = resolve_settings(self._settings, {})

        # The analyse checkpoint holds *every* topic, not just the kept
        # ones, which is exactly what the below-the-cut `generate` link
        # needs — evaluate's payload would 404 a topic that was ranked and
        # not selected.
        topics = self._store.read_checkpoint(run_id, Stage.ANALYSE, Topic)
        topic = next((t for t in topics if t.id == topic_id), None)
        if topic is None:
            raise UnknownTopic(f"No such topic in {run_id}: {topic_id}")

        templates = load_templates(settings.templates_dir)
        if request.template_id not in templates:
            raise GenerationRefused(
                f"template_id {request.template_id!r} is not in the library; "
                f"choose one of: {', '.join(sorted(templates))}"
            )

        provider: LLMProvider | None = None
        if isinstance(request, ManualGeneration):
            # The same rule the model's answer is held to. Refusing here
            # turns a bad request into a 400 rather than a failed tile the
            # user has to open to understand.
            problem = check_slots(request.template_id, request.caption_slots, templates)
            if problem is not None:
                raise GenerationRefused(problem)
        else:
            # On the request thread so a missing ANTHROPIC_API_KEY is a
            # 400 with a message, not a row that silently fails a second
            # later. Both providers hold thread-safe clients — `distil.py`
            # already shares one across a thread pool.
            provider = build_provider(settings)

        records = self._seed(run_id, topic_id, request)
        job = GenerationJob(
            settings=settings,
            request=request,
            topic=topic,
            templates=templates,
            records=records,
            provider=provider,
        )
        log.info(
            "Queued %d %s render(s) for %s/%s on template %s",
            len(records),
            request.mode,
            run_id,
            topic_id,
            request.template_id,
        )
        self._ensure_pool().submit(self._run, job)
        return records

    def _seed(
        self, run_id: str, topic_id: str, request: GenerationRequest
    ) -> list[RenderRecord]:
        """Insert one `generating` row per requested render.

        Written before `submit` returns, not when the job finishes: the
        database is authoritative for whether a render exists, so a tile
        with no row behind it would vanish on the next reload.

        For an `llm` request the brief does not exist yet, so the row
        carries `caption_slots={}` and an empty rationale, both filled in
        by `_draw`. The record's *kind* is still fixed at creation, which
        is the invariant the origin union protects; what changes is
        `status`. A `generating` record's captions and rationale must not
        be read.

        This *appends*. A re-run of the generate stage clears a topic's
        prior auto renders (see `zeitgeist.renders.clear_auto_renders`),
        but an on-demand request is an additive action somebody took, and
        clearing here would delete the render they asked for this one to
        be compared against.
        """
        count = 1 if isinstance(request, ManualGeneration) else request.count
        captions = (
            dict(request.caption_slots)
            if isinstance(request, ManualGeneration)
            else {}
        )
        origin: Origin = (
            ManualOrigin()
            if isinstance(request, ManualGeneration)
            else AutoOrigin(rationale="")
        )

        records = [
            RenderRecord(
                id=uuid4().hex,
                run_id=run_id,
                topic_id=topic_id,
                template_id=request.template_id,
                caption_slots=captions,
                origin=origin,
                status="generating",
                error=None,
                created_at=datetime.now(UTC),
            )
            for _ in range(count)
        ]
        for record in records:
            self._store.add_render(record)
        return records

    def _run(self, job: GenerationJob) -> None:
        """The worker side. Opens and closes its own `Store`.

        A connection per job rather than one per pool thread: `sqlite3`
        connections are thread-bound, `ThreadPoolExecutor` gives no hook to
        open one when it spawns a thread, and a job takes seconds to
        minutes while opening a connection takes milliseconds. Thread-local
        storage would buy nothing and would hold a connection open for the
        process's lifetime.

        `job.settings` rather than `self._settings`: the job carries the
        settings this work was resolved under, and reaching past it to the
        service's base snapshot would be a second, quieter source of truth
        for the same value.
        """
        store = Store(job.settings.db_path)
        try:
            self._generate(job, store)
        except Exception as exc:  # noqa: BLE001 - one job's failure is a row
            log.exception("Generation job for topic %s failed", job.topic.id)
            self._fail_unfinished(store, job, exc)
        finally:
            store.close()

    def _fail_unfinished(
        self, store: Store, job: GenerationJob, exc: Exception
    ) -> None:
        """Backstop for a job that raised out of `generate_renders`.

        Reads each row back rather than trusting the in-memory records: the
        job may have finished some of them before it fell over, and a row
        somebody deleted meanwhile must stay deleted. Without this a
        crashed job leaves tiles spinning forever, with nothing to
        distinguish them from work still in progress.
        """
        for record in job.records:
            current = store.get_render(record.id)
            if current is None or current.status != "generating":
                continue
            store.update_render(
                current.model_copy(
                    update={
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_generation.py tests/test_runner.py -v`
Expected: PASS.

- [ ] **Step 8: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Expected: all four pass. If `ty` objects to `request.template_id` on the union, it is because both members declare it — they do, so the access is safe; do not add an ignore, check the member models instead.

- [ ] **Step 9: Commit**

```bash
git add zeitgeist/generation.py zeitgeist/runner.py tests/test_generation.py tests/test_runner.py
git commit -m "feat: the on-demand generation service and its executor"
```

---
### Task 7: `POST /api/runs/{run_id}/topics/{topic_id}/renders`

The endpoint, its router, and the wiring that gives the app a `GenerationService`. The test factory grows two parameters so a test can own its template library and stub the executor.

**Files:**
- Create: `zeitgeist/api/generate.py`
- Modify: `zeitgeist/api/app.py`
- Modify: `zeitgeist/api/control.py` (docstring only)
- Modify: `tests/api_factory.py`
- Test: `tests/test_api_generate.py`

**Interfaces:**
- Consumes: `GenerationService`, `GenerationRequest`, `UnknownTopic`, `GenerateFn` (Tasks 5-6); `_run_or_404` (existing, `zeitgeist/api/runs.py`). `GenerationRefused` is deliberately *not* imported: it is a `ValueError` subclass, and the handler catches `ValueError` so that `build_provider`'s refusal gets the same 400.
- Produces:
  - `get_generator(request: Request) -> GenerationService` in `zeitgeist/api/app.py`
  - `create_app(settings, *, execute=None, generate=None) -> FastAPI`
  - `api_settings(tmp_path, *, templates_dir: Path | None = None, anthropic_api_key: str | None = None) -> Settings`
  - `seeded_client(tmp_path, *, runs=(), execute=None, generate=None, templates_dir=None, anthropic_api_key=None) -> TestClient`

- [ ] **Step 1: Extend the test factory**

In `tests/api_factory.py`, change the two functions. Nothing else in the module changes.

Both new parameters default to `None`, which reproduces today's behaviour exactly, so the 50-odd existing call sites are untouched.

```python
def api_settings(
    tmp_path: Path,
    *,
    templates_dir: Path | None = None,
    anthropic_api_key: str | None = None,
) -> Settings:
    ...
    return Settings(
        _env_file=None,
        db_path=Path(os.environ["DB_PATH"]),
        output_dir=tmp_path / "output",
        **({} if templates_dir is None else {"templates_dir": templates_dir}),
        **(
            {}
            if anthropic_api_key is None
            else {"anthropic_api_key": anthropic_api_key}
        ),
    )
```

Add to its docstring:

```
`templates_dir` lets a test own its template library outright, the way
`test_pipeline.py` already does: a generation test that named a shipped
template would break when the library changed, for reasons that have
nothing to do with generation.

`anthropic_api_key` exists because `GenerationService.submit` builds a
provider on the request thread, and `llm_provider` defaults to
"anthropic", whose factory raises on an empty key — which this suite
guarantees, since `conftest` strips `ANTHROPIC_API_KEY` for every test.
A test posting `mode: "llm"` without it gets a 400 from the endpoint's
`except ValueError` branch rather than the 202 it is asserting on. It
stays hermetic: `AnthropicProvider.__init__` only constructs the SDK
client and makes no network call, and such tests inject a `generate`
seam so nothing ever calls through it.
```

```python
def seeded_client(
    tmp_path: Path,
    *,
    runs: Sequence[SeededRun] = (),
    execute: ExecuteFn | None = None,
    generate: GenerateFn | None = None,
    templates_dir: Path | None = None,
    anthropic_api_key: str | None = None,
) -> TestClient:
    ...
    settings = api_settings(
        tmp_path,
        templates_dir=templates_dir,
        anthropic_api_key=anthropic_api_key,
    )
    store = Store(settings.db_path)
    store.init_schema()
    for spec in runs:
        seed_run(store, spec)
    store.close()
    client = TestClient(create_app(settings, execute=execute, generate=generate))
    client.__enter__()
    _open_clients.append(client)
    return client
```

Add to its docstring, beside the existing `execute` paragraph:

```
`generate` does the same for the `GenerationService`, so a test can drive
the endpoint without Pillow or a model. `templates_dir` and
`anthropic_api_key` pass straight through to `api_settings`; see its
docstring for why the second one is needed.
```

Import `GenerateFn` from `zeitgeist.generation`.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_api_generate.py`:

```python
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.api_factory import SeededRun, seeded_client
from tests.run_factory import make_render_record, make_topic
from tests.template_factory import make_manifest, make_slot, write_library
from zeitgeist.generation import GenerationJob
from zeitgeist.store import Store

TEMPLATE = "shape_alpha"
SLOTS = {"rejected": "queueing forever", "preferred": "the airport cat"}
RUN = "20260901T120000Z"


@dataclass
class RecordingGenerate:
    jobs: list[GenerationJob] = field(default_factory=list)

    def __call__(self, job: GenerationJob, store: Store) -> None:
        self.jobs.append(job)


def _library(tmp_path) -> Path:
    return write_library(
        tmp_path / "templates",
        make_manifest(
            TEMPLATE,
            slots=[
                make_slot("rejected", box=(10, 10, 190, 90)),
                make_slot("preferred", box=(10, 110, 190, 190)),
            ],
        ),
    )


def _client(tmp_path, *, topics=None, generate=None, renders=()):
    """A client whose app can accept an `llm` request.

    `anthropic_api_key` is set because `submit` builds a provider on the
    request thread before the injected `generate` seam is ever reached;
    without it every `mode: "llm"` post comes back 400 instead of 202. No
    network call is made — see `api_settings`.
    """
    return seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id=RUN,
                topics=topics if topics is not None else [make_topic("airport-cat")],
                renders=list(renders),
            )
        ],
        generate=generate or RecordingGenerate(),
        templates_dir=_library(tmp_path),
        anthropic_api_key="key",
    )


def _url(topic_id: str = "airport-cat") -> str:
    return f"/api/runs/{RUN}/topics/{topic_id}/renders"


def test_a_model_written_request_is_accepted_and_returns_generating_rows(tmp_path):
    """202 and the tiles' real ids, so the client can draw them
    immediately and they survive a refresh."""
    client = _client(tmp_path)

    response = client.post(
        _url(), json={"mode": "llm", "template_id": TEMPLATE, "count": 2}
    )

    assert response.status_code == 202
    body = response.json()
    assert len(body) == 2
    assert {row["status"] for row in body} == {"generating"}
    assert {row["origin"]["provenance"] for row in body} == {"auto"}


def test_a_hand_written_request_returns_the_captions_that_were_posted(tmp_path):
    client = _client(tmp_path)

    body = client.post(
        _url(),
        json={"mode": "manual", "template_id": TEMPLATE, "caption_slots": SLOTS},
    ).json()

    assert len(body) == 1
    assert body[0]["caption_slots"] == SLOTS
    assert body[0]["origin"] == {"provenance": "manual"}


def test_the_new_renders_appear_on_topic_detail(tmp_path):
    """The endpoint's whole point: the grid the panel sits above reads
    them back from the run's topic detail."""
    client = _client(tmp_path)

    created = client.post(
        _url(), json={"mode": "llm", "template_id": TEMPLATE}
    ).json()
    detail = client.get(f"/api/runs/{RUN}/topics/airport-cat").json()

    assert [r["id"] for r in detail["renders"]] == [created[0]["id"]]


def test_generating_a_topic_that_was_never_ranked(tmp_path):
    """The below-the-cut `generate` link posts here for a topic the
    evaluate stage did not keep."""
    client = _client(
        tmp_path, topics=[make_topic("airport-cat"), make_topic("below-the-cut")]
    )

    response = client.post(
        _url("below-the-cut"), json={"mode": "llm", "template_id": TEMPLATE}
    )

    assert response.status_code == 202
    assert response.json()[0]["topic_id"] == "below-the-cut"


def test_an_unknown_run_is_a_404(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        "/api/runs/nope/topics/airport-cat/renders",
        json={"mode": "llm", "template_id": TEMPLATE},
    )

    assert response.status_code == 404


def test_an_unknown_topic_is_a_404(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        _url("no-such-topic"), json={"mode": "llm", "template_id": TEMPLATE}
    )

    assert response.status_code == 404


def test_an_unknown_template_is_a_400_naming_the_library(tmp_path):
    client = _client(tmp_path)

    response = client.post(_url(), json={"mode": "llm", "template_id": "nope"})

    assert response.status_code == 400
    assert TEMPLATE in response.json()["detail"]


def test_captions_that_do_not_fit_the_template_are_a_400(tmp_path):
    """A bad request, not a failed tile: nothing is written."""
    client = _client(tmp_path)

    response = client.post(
        _url(),
        json={
            "mode": "manual",
            "template_id": TEMPLATE,
            "caption_slots": {"rejected": "only one"},
        },
    )

    assert response.status_code == 400
    assert client.get(f"/api/runs/{RUN}/topics/airport-cat").json()["renders"] == []


def test_a_count_above_the_cap_is_a_422(tmp_path):
    """The bound is on the model, so it reaches phase 5 through the
    OpenAPI schema rather than as a rule the client has to know."""
    client = _client(tmp_path)

    response = client.post(
        _url(), json={"mode": "llm", "template_id": TEMPLATE, "count": 99}
    )

    assert response.status_code == 422


def test_an_unknown_mode_is_a_422(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        _url(), json={"mode": "telepathy", "template_id": TEMPLATE}
    )

    assert response.status_code == 422


def test_a_run_that_never_analysed_is_a_409(tmp_path):
    """A run that died in ingest has nothing to brief from. Saying "no
    such topic" would send the user looking for the wrong problem."""
    client = seeded_client(
        tmp_path,
        runs=[SeededRun(run_id=RUN, topics=[])],
        generate=RecordingGenerate(),
        templates_dir=_library(tmp_path),
    )

    response = client.post(
        _url(), json={"mode": "llm", "template_id": TEMPLATE}
    )

    assert response.status_code == 409


def test_posting_does_not_disturb_the_topics_existing_renders(tmp_path):
    """On-demand generation appends. The render being compared against
    must still be there afterwards, alongside the new one.

    The new render's id is asserted too, and the post's status code
    checked: without both, a `submit` that did nothing at all would leave
    `older` in place and pass this test.
    """
    client = _client(
        tmp_path,
        renders=[make_render_record("older", run_id=RUN, topic_id="airport-cat")],
    )

    response = client.post(_url(), json={"mode": "llm", "template_id": TEMPLATE})
    assert response.status_code == 202
    created_id = response.json()[0]["id"]

    detail = client.get(f"/api/runs/{RUN}/topics/airport-cat").json()
    ids = {r["id"] for r in detail["renders"]}
    assert ids == {"older", created_id}


def test_the_generation_pool_does_not_outlive_the_app(tmp_path):
    """`ThreadPoolExecutor`'s workers are not daemon threads, and the pool
    spawns one on first use. An app whose lifespan forgets
    `generator.shutdown()` leaks that thread per app, which surfaces as a
    test suite or a server that will not exit.

    Built and entered by hand rather than through `seeded_client`, which
    defers the lifespan's exit to `conftest`'s autouse fixture — this test
    has to observe the world *after* shutdown, inside its own body.
    """
    settings = api_settings(
        tmp_path, templates_dir=_library(tmp_path), anthropic_api_key="key"
    )
    store = Store(settings.db_path)
    store.init_schema()
    seed_run(store, SeededRun(run_id=RUN, topics=[make_topic("airport-cat")]))
    store.close()

    with TestClient(create_app(settings, generate=RecordingGenerate())) as client:
        assert (
            client.post(
                _url(), json={"mode": "llm", "template_id": TEMPLATE}
            ).status_code
            == 202
        )

    assert not [
        thread
        for thread in threading.enumerate()
        if thread.name.startswith("zeitgeist-generate")
    ]
```

That last test needs `import threading`, `from fastapi.testclient import TestClient`, `from tests.api_factory import api_settings, seed_run`, `from zeitgeist.api import create_app` and `from zeitgeist.store import Store` added to the module's imports.

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/test_api_generate.py -v`
Expected: FAIL — `TypeError: seeded_client() got an unexpected keyword argument 'generate'` until step 1 is in, then 404s from the unmounted route.

- [ ] **Step 4: Write the router**

Create `zeitgeist/api/generate.py`:

```python
"""On-demand generation: turning a topic into memes after its run ended.

Its own router rather than an addition to `control.py`, which owns run
execution. This drives a different service with a different lifecycle, and
its sibling `DELETE /api/renders/{id}` cannot live under the `/api/runs`
prefix at all — so "both of phase 4's endpoints in one module" was never
available, and splitting by responsibility keeps each router about one
thing.
"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status

from zeitgeist.api.app import get_generator, get_store
from zeitgeist.api.runs import _run_or_404
from zeitgeist.generation import GenerationRequest, GenerationService, UnknownTopic
from zeitgeist.records import RenderRecord
from zeitgeist.store import MissingCheckpoint, Store

router = APIRouter(prefix="/api/runs", tags=["generation"])


@router.post(
    "/{run_id}/topics/{topic_id}/renders",
    response_model=list[RenderRecord],
    status_code=status.HTTP_202_ACCEPTED,
)
def create_renders(
    run_id: str,
    topic_id: str,
    body: Annotated[GenerationRequest, Body(discriminator="mode")],
    store: Store = Depends(get_store),
    generator: GenerationService = Depends(get_generator),
) -> list[RenderRecord]:
    """202, and the rows come back `generating`.

    The rows are written before this returns rather than when the job
    finishes: the database is authoritative for whether a render exists,
    so a tile with no row behind it would vanish on the next reload. A
    `generating` row's `caption_slots` and — for an auto render — its
    rationale are not filled in yet and must not be read.

    A bare list rather than an envelope, per `api/schemas.py`: there are no
    aggregates to carry.
    """
    _run_or_404(store, run_id)
    try:
        return generator.submit(run_id, topic_id, body)
    except MissingCheckpoint as exc:
        # Distinct from the 404 below: the run exists and the topic may
        # well have too, but the run died before analyse wrote anything,
        # so there is no dossier to brief from. Answering "no such topic"
        # would send the user looking for the wrong problem.
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id} has no analyse checkpoint; there is nothing "
            "to brief from.",
        ) from exc
    except UnknownTopic as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # GenerationRefused (an unknown template, captions that do not fit)
        # and build_provider's "ANTHROPIC_API_KEY is required" alike: both
        # are the request's fault against the current configuration, not
        # the server's, and a 500 would say the opposite. This must stay
        # last — GenerationRefused is a ValueError subclass.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

`Body(discriminator="mode")` is the supported way to accept a discriminated union as a request body; a bare `Annotated[..., Field(discriminator=...)]` alias would be read as a query parameter instead. It is also what puts both variants into the OpenAPI schema, which is how phase 5's generated client learns the two shapes and the `count` bound.

- [ ] **Step 5: Wire the service into the app**

In `zeitgeist/api/app.py`, add the dependency beside the other three:

```python
def get_generator(request: Request) -> GenerationService:
    return request.app.state.generator
```

In `create_app`, change the signature and build the service after the runner:

```python
def create_app(
    settings: Settings,
    *,
    execute: ExecuteFn | None = None,
    generate: GenerateFn | None = None,
) -> FastAPI:
```

```python
    # The app's own Store, like RunService's, so `submit` can write a run's
    # `generating` rows on the request thread before the ids are handed
    # back. The pool's worker opens its own connection.
    generator = GenerationService(settings, store, generate=generate)
```

In the lifespan's `finally`, before `store.close()`:

```python
            generator.shutdown()
```

Set the state and mount the router:

```python
    app.state.generator = generator
```

```python
    from zeitgeist.api import generate as generate_router
```

```python
    app.include_router(generate_router.router)
```

Mount it beside `control_router`. Order is not load-bearing here — `POST /{run_id}/topics/{topic_id}/renders` collides with no existing path — but keeping the two `/api/runs` mutating routers together is where a reader will look for them.

Add the imports: `from zeitgeist.generation import GenerateFn, GenerationService`.

- [ ] **Step 6: Correct `control.py`'s docstring**

Its second line reads "phase 4 adds two more of its own", which is now wrong. Replace the docstring's last sentence with:

```
Split from `runs.py`, which is five endpoints of read-only history: these
mutate execution and fail differently. Phase 4's two mutating endpoints
went elsewhere — `api/generate.py` drives a different service, and
`DELETE /api/renders/{id}` belongs under its own prefix.
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_api_generate.py tests/test_api_app.py -v`
Expected: PASS. `test_api_app.py` is included because `create_app` changed; its two tests that build an app without entering the lifespan must still leave no thread behind.

- [ ] **Step 8: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

- [ ] **Step 9: Commit**

```bash
git add zeitgeist/api/generate.py zeitgeist/api/app.py zeitgeist/api/control.py tests/api_factory.py tests/test_api_generate.py
git commit -m "feat: POST a topic's renders, model-written or hand-written"
```

---

### Task 8: `DELETE /api/renders/{render_id}`

The last endpoint. Small, because Task 3 already built the unit it calls.

**Files:**
- Modify: `zeitgeist/api/renders.py`
- Test: `tests/test_api_renders.py`

**Interfaces:**
- Consumes: `delete_render`, `render_paths` (Task 3); `_render_or_404` (existing).
- Produces: `DELETE /api/renders/{render_id}` → 204.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api_renders.py`. It already has `_write_png(tmp_path, run_id, render_id, suffix="")`.

```python
def test_deleting_a_render_removes_the_row(tmp_path):
    client = seeded_client(
        tmp_path, runs=[SeededRun(renders=[make_render_record("rnd1")])]
    )

    response = client.delete("/api/renders/rnd1")

    assert response.status_code == 204
    assert client.get("/api/renders/rnd1").status_code == 404


def test_deleting_a_render_removes_both_files(tmp_path):
    """Row and files go together. An orphaned PNG is invisible; an
    orphaned row draws as a broken tile forever."""
    client = seeded_client(
        tmp_path, runs=[SeededRun(renders=[make_render_record("rnd1")])]
    )
    _write_png(tmp_path, "20260901T120000Z", "rnd1")
    _write_png(tmp_path, "20260901T120000Z", "rnd1", suffix=".thumb")

    client.delete("/api/renders/rnd1")

    directory = tmp_path / "output" / "20260901T120000Z" / "renders"
    assert not (directory / "rnd1.png").exists()
    assert not (directory / "rnd1.thumb.png").exists()


def test_deleting_a_render_whose_png_is_already_gone_still_succeeds(tmp_path):
    """The row is what makes a render exist, so a missing file cannot turn
    a delete into a 500."""
    client = seeded_client(
        tmp_path, runs=[SeededRun(renders=[make_render_record("rnd1")])]
    )

    assert client.delete("/api/renders/rnd1").status_code == 204


def test_deleting_an_unknown_render_is_a_404(tmp_path):
    client = seeded_client(tmp_path, runs=[SeededRun()])

    assert client.delete("/api/renders/nope").status_code == 404


def test_a_deleted_render_leaves_the_topics_others_alone(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                renders=[make_render_record("keep"), make_render_record("drop")]
            )
        ],
    )

    client.delete("/api/renders/drop")

    detail = client.get(
        "/api/runs/20260901T120000Z/topics/airport-cat"
    ).json()
    assert [r["id"] for r in detail["renders"]] == ["keep"]


def test_deleting_a_render_lowers_the_topics_meme_count(tmp_path):
    """The count is COUNT(*) over renders at query time, which is the
    whole reason it is not a column somebody has to keep correct here."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                renders=[make_render_record("a"), make_render_record("b")]
            )
        ],
    )

    client.delete("/api/renders/a")

    rows = client.get("/api/runs/20260901T120000Z/topics").json()
    assert rows[0]["render_count"] == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_api_renders.py -k delet -v`
Expected: FAIL — 405 Method Not Allowed, because only GET is registered on that path.

- [ ] **Step 3: Add the endpoint**

In `zeitgeist/api/renders.py`, add `Response` to the `fastapi` imports, `status` alongside them, and `delete_render` to the `zeitgeist.renders` import. Then append:

```python
@router.delete("/{render_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_render(
    render_id: str,
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> Response:
    """204 and no body. The row goes first, then both files.

    A render whose PNG is already missing still deletes cleanly: the row is
    what makes it exist, and the end state is the same either way.

    The meme count every screen shows is `COUNT(*)` over `renders` at query
    time, so nothing else has to be told this happened — which is the
    reason that count is not a column.
    """
    record = _render_or_404(store, render_id)
    delete_render(store, settings.output_dir, record)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

Also extend the module docstring's second paragraph:

```
Deletion lives here rather than beside `POST .../renders` in
`api/generate.py`, because it is addressed by render id and belongs under
this prefix. `zeitgeist.renders.delete_render` is the row-and-files unit
both the endpoint and a re-run of the generate stage go through.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_api_renders.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

- [ ] **Step 6: Commit**

```bash
git add zeitgeist/api/renders.py tests/test_api_renders.py
git commit -m "feat: DELETE a render, its PNG and its thumbnail"
```

---

### Task 9: Documentation

The API contract is now complete, and two documents describe a world where it is not. The spec also poses a question this phase answered and should not leave open for the next reader.

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-09-02-web-ui-design.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing code depends on.

- [ ] **Step 1: Add phase 4's paragraph to the README**

In `README.md`'s "The web UI" section, after the phase 3 bullet list and before the "Starting a run and watching it" snippet, add:

```markdown
Phase 4 completes the API. Memes can now be generated for a topic on
demand, long after its run ended:

- **Two ways to make a meme.** `POST /api/runs/{id}/topics/{topic_id}/renders`
  takes either `{"mode": "llm", "template_id": ..., "count": N}` — the model
  writes the captions for the template you name, up to four at a time — or
  `{"mode": "manual", "template_id": ..., "caption_slots": {...}}`, which
  draws captions you wrote yourself. It answers 202 with the render rows
  already created and `status: "generating"`; poll the topic to watch them
  finish.
- **Any topic, not just the ranked ones.** A topic the evaluate stage left
  below the cut can still be generated for: the request reads the run's
  `analyse` checkpoint, which holds every topic.
- **Generation runs off the run worker.** A second, single-threaded
  executor, so a meme can be generated while a run is in flight. On
  Anthropic that is free; against a local Ollama the two contend for one
  GPU and simply take longer.
- **Deleting a render.** `DELETE /api/renders/{id}` removes the row, the
  PNG and the thumbnail. Meme counts are a `COUNT(*)` at query time, so
  they follow immediately.
- **Re-running `generate` now replaces rather than appends.** A resume from
  the generate stage clears each topic's previous *model-written* renders
  once the new one is on disk, which is what the old CLI's fixed filenames
  used to do. Renders you wrote by hand are never touched — the model's
  output is reproducible by running again, and yours is not.
- **A re-render that fails clears nothing.** If your edited prompt produces
  a caption too long for its box, the previous render stays where it is and
  the failure appears beside it, so you can see both. On-demand generation
  is the other exception and always appends, because it is something you
  asked for on top of what is already there.
```

Then change the line above the `openapi-typescript` snippet — it currently says the schema is not final. The contract is now closed, so it should read:

```markdown
The API contract is complete as of this phase. Phase 5 generates its
TypeScript types from the same schema:
```

- [ ] **Step 2: Mark the spec's open question answered**

In `docs/superpowers/specs/2026-09-02-web-ui-design.md`, at the end of the "Re-running generate appends, it does not replace" section, append:

```markdown
**Answered in phase 4.** It does clear them, on one condition. A re-run of
`generate` removes each topic's prior `auto` renders — row, PNG and
thumbnail — once the replacement is on disk *and rendered successfully*,
and never touches a `manual` render. A pass whose render fails clears
nothing, so a prompt edit that overflows a caption box leaves the previous
render in place beside the failure rather than destroying the output being
tuned against. On-demand generation through `POST .../renders` is the other
exception and always appends, because it is an additive action somebody
took rather than a stage re-running. See
`zeitgeist/renders.py:clear_auto_renders` and
`docs/superpowers/plans/2026-09-06-web-ui-generation-backend.md`.
```

- [ ] **Step 3: Check the phase table is still accurate**

The spec's API surface table marks both of this phase's endpoints "4". Confirm the paths there match what was built:
`POST /api/runs/{id}/topics/{topic_id}/renders` and `DELETE /api/renders/{id}`. If they do, change nothing; the table is a record of what was planned, and it was right.

- [ ] **Step 4: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Expected: all four pass. `docs/` is excluded from ruff, so only the README's fenced blocks matter, and only to a human.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/superpowers/specs/2026-09-02-web-ui-design.md
git commit -m "docs: phase 4's endpoints, and the re-run decision it was asked to make"
```

---

## Verification

After every task, and before opening the pull request:

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Then check the contract by hand, because phase 5 is generated from it and a wrong shape is much cheaper to find now:

```bash
uv run zeitgeist
```

With a completed run's id and one of its topic ids:

```bash
curl -s -XPOST "localhost:8000/api/runs/$RUN/topics/$TOPIC/renders" -H 'content-type: application/json' -d '{"mode":"llm","template_id":"drake","count":2}' | jq
```

Expect 202, two rows, `"status": "generating"`, `"provenance": "auto"`, an empty `caption_slots` and an empty `rationale`. Poll until they finish:

```bash
curl -s "localhost:8000/api/runs/$RUN/topics/$TOPIC" | jq '.renders[] | {id, status, template_id}'
```

Expect `ready` (or `failed` with a message), real captions, and a non-empty rationale on each. Fetch one image:

```bash
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' "localhost:8000/api/renders/$RENDER/image?size=thumb"
```

Expect `200 image/png`. Then delete it and confirm the count follows:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -XDELETE "localhost:8000/api/renders/$RENDER"
curl -s "localhost:8000/api/runs/$RUN/topics" | jq '.[] | {topic: .topic.topic_id, render_count}'
```

Expect `204`, then a count one lower than before. Finally, confirm both new endpoints and the `count` bound appear in the schema phase 5 will generate from:

```bash
curl -s localhost:8000/openapi.json | jq '.paths | keys[] | select(contains("renders"))'
```

## Notes for the executor

- **Do not add the three npm gate commands.** They belong to phase 5, along with the `web/` directory that makes them runnable. Adding them here turns this pull request red.
- **`SCHEMA_VERSION` stays 3.** If you find yourself wanting a column, stop and re-read Task 2 — every accessor this phase needs is served by the existing table and its `idx_renders_run_topic` index.
- **Do not add a `PendingOrigin`.** A `generating` auto render's empty rationale is a documented transient state (Decision 2), not a gap in the model. A third union member would reach the OpenAPI schema and every screen that reads `provenance`.
- **Do not let `_render_all` clear on-demand renders selectively.** `clear_auto_renders` takes out every `auto` render for the (run, topic) pair, including ones a person requested from the panel. That is deliberate: `auto` means model-written and reproducible, `manual` means hand-written and not, and that is the only distinction the union draws.
- **Do not make the clear in `_render_all` unconditional.** The `if error is None:` guard is the difference between a failed tuning pass leaving your last good render beside the failure and it destroying that render. `test_a_failed_re_render_leaves_the_previous_good_one_in_place` is the only thing standing between the two, and it passes in the *pre-implementation* state as well, so it will not turn red to warn you — read it before you touch that branch.
- **`GenerationService` takes one injectable seam, `generate`.** If you find yourself adding a `worker_store` factory to make a test work, the test is probably asserting on the double rather than on the service. The connection-per-job behaviour is covered by `test_a_submitted_job_really_renders_when_nothing_is_injected`, through the `check_same_thread=True` connection the test's own `_store` opens.
- **The `except ValueError` clause in `create_renders` must stay last.** `GenerationRefused` is a `ValueError` subclass, and `UnknownTopic` is a `LookupError`; reordering silently turns a 404 into a 400 or vice versa.
- **When a test needs a job to have finished, call `service.shutdown()`.** It waits on the pool. Never sleep.
- **Watch `tests/test_pipeline.py` in Task 4.** Any existing test that ran `generate` twice against one run and asserted a growing render count was asserting the behaviour Decision 1 reverses. Update it and say why in a comment; do not weaken it into passing.

## Landing the work

One branch off `main`, one pull request, merged before phase 5 begins. Every commit above lands green under the four-command Definition of Done.

Before handing this plan to an executor, run the `reviewing-plan-tests` skill over it: the test code in this document is transcribed verbatim into the suite, so a weak test here becomes a weak test in the repository. That gate is separate from the machine-checked Definition of Done.
