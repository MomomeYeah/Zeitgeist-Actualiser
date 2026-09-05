# Execution Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a run startable, watchable and stoppable over HTTP — a worker thread, a queue, the write endpoints, and a live event stream — with no UI.

**Architecture:** The pipeline gains two optional seams that both default to no-ops: a `RunObserver` it reports progress to, and a `CancelToken` it checks at stage boundaries and inside its two long loops. A single worker thread drains a FIFO queue, owning its own `Store` because `sqlite3` connections are thread-bound. A logging handler attached for the run's duration writes two sinks — batched rows into `log_lines`, and a bounded `deque` the SSE generator polls. No pipeline code ever touches the event loop.

**Tech Stack:** Python 3.14, FastAPI, `threading`, `queue.Queue`, `collections.deque`, pydantic 2, sqlite3 (stdlib), pytest.

## Global Constraints

Copied from `docs/superpowers/specs/2026-09-02-web-ui-design.md`. Every task's requirements implicitly include this section.

- **Definition of Done, run before claiming any task complete:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, `uv run pytest`. All four must pass. **There is no red window — the tree is green at the start of every task and must be green at the end.** The frontend gate commands belong to phase 5 and must not be added.
- **No DEBUG line may carry reply text, post bodies or `author_key`.** Debug lines carry counts, ids, permalinks and elapsed times. `Item`'s docstring and `Reply.author_key` show the project is deliberate about not storing personal data, and a debug log that dumps reply text to disk would quietly undo it.
- **`ANTHROPIC_API_KEY` is never returned by any endpoint, in any form.** `GET /api/config/options` reports whether it is set as a boolean and nothing more.
- **Only the seven tuning fields are writable** — `bluesky_trend_limit`, `bluesky_posts_per_trend`, `bluesky_fetch_concurrency`, `meme_potential_weight`, `phrase_min_authors`, `distil_char_budget`, `distil_concurrency`. `PUT /api/settings` rejects every other field. `db_path`, `output_dir`, `templates_dir`, `font_path`, `anthropic_api_key`, `ollama_host`, `llm_provider`, `llm_model` and `sources` are not writable.
- **Both pipeline seams default to no-ops**, so a caller wanting neither — a test, or `scripts/run_pipeline.py` — constructs neither.
- **Stop-after-stage is checked at stage boundaries only**, so the current stage writes its checkpoint and the run stays resumable. That is what the button promises.
- **Abort raises `Aborted` from `check()`**, called inside the distil worker before each model call and inside `_render_all` between briefs.
- **`fetch_evidence` cannot be aborted mid-flight.** It is a single opaque `asyncio.run()` with no interior checkpoint. Abort during ingest takes effect when the fetch returns. Threading cancellation through `BlueskySource`'s async fan-out is deliberately out of scope.
- **The worker constructs its own `Store`.** The API's `Store` and the worker's are separate objects, because `sqlite3` connections are thread-bound.
- **The queue is in-memory.** A restart loses queued runs; that is the right trade against persisting a job table for a single-user local tool.
- **At most one run executes at a time**, which is what the New run screen's "queues it behind …" notice describes.
- **On server startup, any run still marked `running` is marked `interrupted`.** The process died mid-run; the UI should say so rather than showing a run that will never progress. An interrupted run is resumable from its last good checkpoint like any other.
- **`RunConfig` is frozen per run.** Changes to settings apply to new runs; a run in flight keeps the config it froze.
- **Never re-derive the trend-versus-meme blend.** `sentiment.rank_score` is the single place it is defined.
- **No migrations.** `SCHEMA_VERSION` stays 3; this phase adds no tables and no columns. `log_lines` already exists from phase 1.
- **Optionality expresses a real state, never a migration concession.**
- Python 3.14: PEP 695 generics (`def f[T: Bound](...)`), never `typing.TypeVar`.
- **`model_config = STRICT`** (`ConfigDict(extra="forbid")`, in `zeitgeist/models.py`) on every new pydantic model.
- ruff: line length 88, rules `E, F, I, UP, B, SIM`. `docs/` is excluded.
- ty: fix type errors at the root cause. No blanket `# type: ignore`; a narrow suppression needs a comment explaining why.
- **Tests are hermetic.** No network. Every model call goes through `FakeLLMProvider`. `tests/conftest.py`'s autouse fixture strips every environment variable `Settings` reads and repoints `DB_PATH` at a per-test path — if you add a `Settings` field that reads the environment, add its variable to `_SETTINGS_ENV_VARS`.
- **Fixtures are built through the real models**, never hand-written dicts. `tests/run_factory.py`, `tests/template_factory.py` and `tests/api_factory.py` are the established pattern.
- **No test may sleep to synchronise with a thread.** Use `threading.Event`, `Barrier` or a queue handoff. A test that sleeps is a test that flakes on a loaded CI box.

## What phases 1 and 2 left you

`Store` (`zeitgeist/store.py`, ~600 lines) already has, and you should not reimplement:

`init_schema`, `start_run(run_id, config)`, `finish_run(run_id, *, status, item_count, trends_found, topics_kept, phrases_found)`, `fail_run(run_id, error: RunError)`, `get_run(run_id) -> RunRecordRow | None`, `list_runs(limit, cursor=None)`, `render_counts(run_id)`, `recent_run_ids(limit)`, `topics_for_runs(run_ids)`, `topic_recurrence(label_slug)`, `log_lines(run_id, *, verbose)`, `previous_sub_scores(exclude_run_id)`, `write_run_topics(rows)`, `run_topics(run_id)`, `write_checkpoint(run_id, stage, models) -> int`, `write_analyse_checkpoint(run_id, topics, meme_potential_weight) -> int`, `read_checkpoint[T: BaseModel](run_id, stage, schema)`, `written_stages(run_id) -> set[Stage]`, `record_stage(run_id, record)`, `stages_for_run(run_id)`, `add_render(record)`, `get_render(render_id)`, `renders_for_run(run_id)`, `get_settings() -> dict[str, str]`, `set_setting(key, value)`, `clear_setting(key)`, `close()`. `MissingCheckpoint` is raised by `read_checkpoint`; `StoreSchemaError` by `init_schema`.

`Store.__init__(path, *, check_same_thread: bool = True)`. **The database already opens in WAL mode** (`store.py:77`) — phase 1 did that, so the spec's WAL bullet is already satisfied and needs no work.

Models: `zeitgeist/records.py` has `Stage`, `ORDER = [INGEST, ANALYSE, EVALUATE, GENERATE]`, `RunStatus = Literal["running", "ok", "failed", "aborted", "interrupted"]`, `StageStatus`, `RunConfig` (with `RunConfig.freeze(settings, template_ids)`), `RunError` (`kind`, `message`, `stage`), `RunRecordRow`, `StageRecord`, `AutoOrigin`, `ManualOrigin`, `Origin`, `RenderRecord`, `LogLine` (`seq`, `logged_at`, `level`, `logger`, `message`). `zeitgeist/projection.py` has `TopicRow` and `flatten`. `zeitgeist/models.py` has the pipeline domain and `STRICT`.

The API (`zeitgeist/api/`) has `create_app(settings) -> FastAPI` opening one `Store(settings.db_path, check_same_thread=False)` on `app.state.store`, the dependencies `get_store(request)` and `get_settings(request)`, and four routers — `runs.py`, `renders.py`, `topics.py`, `settings.py` — **mounted at the end of `create_app` with their imports inside the function body** to break the cycle (routers import `get_store` from `app.py`). `zeitgeist/api/runs.py` has the helper `_run_or_404(store, run_id) -> RunRecordRow`; `renders.py` has `_render_or_404`.

`zeitgeist/serve.py` is the console entry point: `main(argv=None) -> int`, flags `--host` (default `127.0.0.1`), `--port` (default `8000`), `--reload`. The reload path passes uvicorn the import string `"zeitgeist.serve:_app"` with `factory=True`; the non-reload path passes an app instance and catches `StoreSchemaError`.

`zeitgeist/llm/base.py` has the `LLMProvider` Protocol — **deliberately one method** — plus `LLMError`, `ContextLimitError`, `LLMCall` and `FakeLLMProvider`. `zeitgeist/llm/factory.py` has `build_provider(settings)`. `OllamaProvider.__init__(host, model, client=None, ...)` takes an injectable client and exposes `.host`.

`zeitgeist/settings_source.py` has `WRITABLE_KEYS` (the seven), `DEFAULT_DB_PATH`, `DOTENV_PATH` and `_dotenv_value(key)`.

Tests: `tests/api_factory.py` has `SeededRun`, `seed_run(store, spec)`, `api_settings(tmp_path)` and `seeded_client(tmp_path, *, runs=())`; `seeded_client` enters the app's lifespan and registers the client for teardown by an autouse fixture in `conftest.py`. `tests/run_factory.py` has `make_run_config`, `make_stage_record`, `make_render_record`, `make_dossier`, `make_topic`, `make_scored_topic`. `tests/test_pipeline.py` has `_FakeTrendSource`, `_template_library(tmp_path)` and `_settings(tmp_path, **overrides)`.

## File Structure

**Created:**

| File | Responsibility |
| --- | --- |
| `zeitgeist/progress.py` | The two pipeline seams: `RunObserver` and its null and recording implementations, `CancelToken`, and `Aborted`. Both seams in one module because they are the same idea — an optional hook the pipeline calls and a caller supplies — and a run that has one almost always has the other. |
| `zeitgeist/logcapture.py` | `RunLogBuffer` (the bounded deque the SSE generator drains) and `RunLogHandler` (the `logging.Handler` that feeds it and the batched row writer). No API imports; the worker owns it. |
| `zeitgeist/runner.py` | `RunService`: the FIFO queue, the worker thread, run lifecycle, and the per-run cancel tokens and log buffers. The one place that knows a run is executing. |
| `zeitgeist/llm/registry.py` | `available_models(settings)` — Anthropic's static list, Ollama's from `/api/tags`. Separate from `LLMProvider`, whose docstring deliberately keeps that Protocol to one method. |
| `zeitgeist/api/control.py` | The run-control router: `POST /api/runs`, resume, stop, abort, `GET /api/runs/active`, and the SSE stream. Everything that mutates or watches a run's execution. |
| `zeitgeist/api/options.py` | `GET /api/config/options`. One endpoint, but it assembles from four unrelated sources (providers, platforms, templates, `.env`) and does not belong in any existing router. |
| `tests/test_progress.py`, `tests/test_logcapture.py`, `tests/test_runner.py`, `tests/test_llm_registry.py`, `tests/test_api_control.py`, `tests/test_api_options.py` | One test module per new module. |

**Modified:** `zeitgeist/pipeline.py` (observer and token), `zeitgeist/analysis/distil.py` (`on_topic`, cancellation, DEBUG), `zeitgeist/sources/bluesky.py`, `zeitgeist/media/brief.py`, `zeitgeist/media/render.py` (DEBUG; render has no logger today), `zeitgeist/store.py` (`write_log_lines`, `reconcile_interrupted`), `zeitgeist/api/app.py` (mount the two routers, own the `RunService` lifecycle, reconcile on startup), `zeitgeist/api/settings.py` (`PUT`), `zeitgeist/api/schemas.py` (request and response models), `tests/test_pipeline.py`, `tests/test_analysis_distil.py`, `tests/test_store.py`, `tests/test_api_settings.py`, `README.md`.

`runner.py` is split from `api/` because it must not import from it: the worker is a pipeline concern that the API drives, not the other way round, and the same direction that keeps `store.py` free of API imports applies here. `control.py` is split from `runs.py` because `runs.py` is already five endpoints of read-only history and this adds six of execution control — different lifetimes, different failure modes, and phase 4 adds two more to a third router again.

**Deliberately not in this phase:** no on-demand generation executor and no `POST .../renders` or `DELETE /api/renders/{id}` — those are phase 4. No frontend. No change to `CLAUDE.md`'s four gate commands. No subprocess isolation for runs, and no cancellation inside `BlueskySource`'s async fan-out.

---

### Task 1: `RunObserver`, `NullObserver` and `RecordingObserver`

**Files:**
- Create: `zeitgeist/progress.py`, `tests/test_progress.py`

**Interfaces:**
- Produces:
  - `zeitgeist.progress.RunObserver` — a `Protocol` with `stage_started(stage)`, `stage_progress(stage, done, total, detail)`, `stage_finished(stage, payload_bytes)`, `topic_distilled(topic)`, `render_finished(render)`
  - `zeitgeist.progress.NullObserver` — every method a no-op
  - `zeitgeist.progress.ObservedEvent` — a frozen dataclass, `name: str` and `payload: tuple[object, ...]`
  - `zeitgeist.progress.RecordingObserver` — records every call as an `ObservedEvent` on `.events`, plus `.named(name)` returning every event of one kind

**Why `RecordingObserver` ships in `zeitgeist/` rather than `tests/`:** `FakeLLMProvider` lives beside the `LLMProvider` Protocol in `zeitgeist/llm/base.py`, for the reason that a double which drifts from its Protocol is worse than no double. The same argument applies here, and the spec names it "the progress analogue of `FakeLLMProvider`".

**Why `stage_finished` takes bytes, not a path:** checkpoints are rows now. `None` means the stage wrote no payload, which is a failed or skipped one.

**Why `render_finished` takes the whole `RenderRecord`:** the record already holds the outcome, including `status="failed"` and its error — which is how a per-meme `RenderError` reaches the UI as a tile with a message instead of vanishing.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_progress.py`:

```python
import inspect

from tests.run_factory import make_topic
from zeitgeist.progress import NullObserver, RecordingObserver, RunObserver
from zeitgeist.records import Stage


def test_the_null_observer_matches_the_protocol_method_for_method():
    """The whole point of a null implementation is that it can stand in
    everywhere the Protocol is accepted. `ty` checks assignability at the
    call sites that exist, but nothing checks that someone adding a sixth
    method to the Protocol remembers to add it here — and a `NullObserver`
    missing a method fails at call time, deep inside a run, rather than at
    startup.
    """
    protocol_methods = {
        name: inspect.signature(member)
        for name, member in vars(RunObserver).items()
        if callable(member) and not name.startswith("_")
    }
    assert protocol_methods, "no methods found on RunObserver; the scan is wrong"

    for name, signature in protocol_methods.items():
        assert hasattr(NullObserver, name), f"NullObserver is missing {name}"
        assert inspect.signature(getattr(NullObserver, name)) == signature, name


def test_the_recording_observer_keeps_events_in_call_order():
    """Order is the assertion these exist to enable: the pipeline's tests
    check that `topic_distilled` fires per topic *between* `stage_started`
    and `stage_finished`, which a set or a counter could not express.
    """
    observer = RecordingObserver()

    observer.stage_started(Stage.ANALYSE)
    observer.topic_distilled(make_topic("cats"))
    observer.topic_distilled(make_topic("dogs"))
    observer.stage_finished(Stage.ANALYSE, 99)

    assert [event.name for event in observer.events] == [
        "stage_started",
        "topic_distilled",
        "topic_distilled",
        "stage_finished",
    ]


def test_the_recording_observer_keeps_each_events_arguments():
    """A recorder that kept only names would let a test pass while the
    pipeline reported the wrong stage, the wrong topic, or a payload size of
    zero for a stage that wrote 1.3MB.
    """
    topic = make_topic("cats")
    observer = RecordingObserver()

    observer.stage_finished(Stage.INGEST, 2048)
    observer.topic_distilled(topic)

    assert observer.events[0].payload == (Stage.INGEST, 2048)
    assert observer.events[1].payload == (topic,)


def test_named_selects_one_kind_without_disturbing_the_stream():
    """`named` is a convenience the pipeline tests lean on heavily. If it
    filtered the stored list rather than returning a new one, the second
    assertion in any test using it would see a truncated history.
    """
    observer = RecordingObserver()
    observer.stage_started(Stage.INGEST)
    observer.topic_distilled(make_topic("cats"))

    distilled = observer.named("topic_distilled")

    assert [event.name for event in distilled] == ["topic_distilled"]
    assert len(observer.events) == 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_progress.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.progress'`

- [ ] **Step 3: Write the module**

Create `zeitgeist/progress.py`:

```python
"""The seams a run is watched and cancelled through.

Both default to no-ops, so a caller wanting neither — a test, or
`scripts/run_pipeline.py` — constructs neither and the pipeline behaves
exactly as it did before either existed.
"""

from dataclasses import dataclass, field
from typing import Protocol

from zeitgeist.models import Topic
from zeitgeist.records import RenderRecord, Stage


class RunObserver(Protocol):
    """What a watcher of a run is told, as it happens.

    Every method returns None and none may raise: an observer is a reporting
    seam, and a run must not fail because something watching it did.
    """

    def stage_started(self, stage: Stage) -> None: ...

    def stage_progress(
        self, stage: Stage, done: int, total: int, detail: str
    ) -> None: ...

    def stage_finished(self, stage: Stage, payload_bytes: int | None) -> None:
        """`payload_bytes` is the checkpoint's size rather than its path,
        because checkpoints are rows now. `None` is a stage that wrote no
        payload, which is a failed or a skipped one.
        """
        ...

    def topic_distilled(self, topic: Topic) -> None: ...

    def render_finished(self, render: RenderRecord) -> None:
        """The whole record rather than a brief and a path: it already holds
        the outcome, including `status="failed"` and its error, which is how
        a per-meme failure reaches the UI as a tile with a message rather
        than vanishing.
        """
        ...


class NullObserver:
    """The default. Every method does nothing."""

    def stage_started(self, stage: Stage) -> None:
        return None

    def stage_progress(
        self, stage: Stage, done: int, total: int, detail: str
    ) -> None:
        return None

    def stage_finished(self, stage: Stage, payload_bytes: int | None) -> None:
        return None

    def topic_distilled(self, topic: Topic) -> None:
        return None

    def render_finished(self, render: RenderRecord) -> None:
        return None


@dataclass(frozen=True)
class ObservedEvent:
    name: str
    payload: tuple[object, ...]


@dataclass
class RecordingObserver:
    """Test double recording the call sequence.

    Beside the Protocol rather than in `tests/` for the same reason
    `FakeLLMProvider` sits beside `LLMProvider`: a double that drifts from
    the interface it stands in for is worse than no double.
    """

    events: list[ObservedEvent] = field(default_factory=list)

    def stage_started(self, stage: Stage) -> None:
        self.events.append(ObservedEvent("stage_started", (stage,)))

    def stage_progress(
        self, stage: Stage, done: int, total: int, detail: str
    ) -> None:
        self.events.append(
            ObservedEvent("stage_progress", (stage, done, total, detail))
        )

    def stage_finished(self, stage: Stage, payload_bytes: int | None) -> None:
        self.events.append(ObservedEvent("stage_finished", (stage, payload_bytes)))

    def topic_distilled(self, topic: Topic) -> None:
        self.events.append(ObservedEvent("topic_distilled", (topic,)))

    def render_finished(self, render: RenderRecord) -> None:
        self.events.append(ObservedEvent("render_finished", (render,)))

    def named(self, name: str) -> list[ObservedEvent]:
        """Every event of one kind, in order. The pipeline's tests assert on
        one event type at a time far more often than on the whole stream.
        """
        return [event for event in self.events if event.name == name]
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_progress.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`
Expected: all four pass.

- [ ] **Step 6: Commit**

```bash
git add zeitgeist/progress.py tests/test_progress.py
git commit -m "Add the run observer seam

A Protocol the pipeline reports progress through, a null implementation
that is the default, and a recorder for tests. The recorder sits beside the
Protocol rather than in tests/, the way FakeLLMProvider sits beside
LLMProvider, because a double that drifts from its interface is worse than
no double.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `CancelToken` and `Aborted`

**Files:**
- Modify: `zeitgeist/progress.py`, `tests/test_progress.py`

**Interfaces:**
- Consumes: nothing from Task 1 beyond sharing its module.
- Produces:
  - `zeitgeist.progress.Aborted` — an `Exception`
  - `zeitgeist.progress.CancelToken` — `stop_after_stage()`, `abort()`, `check()` raising `Aborted`, and the read-only properties `stopping: bool` and `aborted: bool`

**The two cancellations are different, and conflating them is the bug these tests guard.** *Stop* lets the current stage finish and write its checkpoint, so the run stays resumable — that is what the button promises. *Abort* unwinds the current work immediately. So `check()` raises only for abort; a stopping token's `check()` returns normally, and the stage boundary reads `stopping` instead.

`stopping` is true after either call, because both mean this run is ending and the stage boundary must not begin another stage. `aborted` distinguishes them, and decides the terminal status.

**Thread safety:** written by the request thread handling `POST /api/runs/{id}/abort`, read by the worker thread. A `bool` assignment is atomic under the GIL, so no lock is needed — and that holds only because these flags are set once and never cleared. A token belongs to one run and is never reset, so there is no read-modify-write to lose.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_progress.py`. Merge the new names into the existing import block rather than adding a second `from zeitgeist.progress import ...` line, or isort's `I001` will fire:

```python
import threading

import pytest

from zeitgeist.progress import Aborted, CancelToken


def test_a_fresh_token_stops_nothing():
    """The default path. Every run that is never cancelled calls `check()`
    once per model call and once per brief, and every one of them must
    return."""
    token = CancelToken()

    token.check()

    assert token.stopping is False
    assert token.aborted is False


def test_stopping_does_not_raise_from_check():
    """Stop-after-stage promises the current stage completes and writes its
    checkpoint. A `check()` that raised for a stopping token would abandon
    the stage mid-flight and lose exactly the resumability the button
    promises — and no other test would notice, because the stage boundary
    reads `stopping` on a different code path.
    """
    token = CancelToken()

    token.stop_after_stage()

    token.check()
    assert token.stopping is True
    assert token.aborted is False


def test_aborting_raises_from_check():
    token = CancelToken()

    token.abort()

    with pytest.raises(Aborted):
        token.check()


def test_an_aborted_token_is_also_stopping():
    """The stage boundary reads `stopping` to decide whether to begin the
    next stage. An aborted token reporting `stopping is False` would start
    one more stage in the window between the abort and the next `check()`.
    """
    token = CancelToken()

    token.abort()

    assert token.stopping is True
    assert token.aborted is True


def test_a_flag_set_on_one_thread_is_seen_on_another():
    """This is the token's entire job: `POST /api/runs/{id}/abort` runs on a
    request thread and the pipeline reads it on the worker. A token that
    held state per thread — a thread-local, or a copy taken at
    construction — would pass every other test here and never cancel a real
    run.
    """
    token = CancelToken()
    seen = threading.Event()
    released = threading.Event()

    def watcher() -> None:
        released.wait(timeout=5)
        if token.aborted:
            seen.set()

    thread = threading.Thread(target=watcher)
    thread.start()
    token.abort()
    released.set()
    thread.join(timeout=5)

    assert seen.is_set()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_progress.py -k "token or stopping or abort" -v`
Expected: FAIL with `ImportError: cannot import name 'Aborted' from 'zeitgeist.progress'`

- [ ] **Step 3: Write the implementation**

In `zeitgeist/progress.py`, add `Aborted` immediately after the imports, before `RunObserver`:

```python
class Aborted(Exception):
    """Raised from `CancelToken.check()` when a run has been aborted.

    Its own type rather than a flag return, because it has to unwind out of
    the distil worker's thread pool and out of the render loop, both of
    which are several frames below the code that can act on it.
    """
```

And add `CancelToken` at the end of the module:

```python
class CancelToken:
    """Two different cancellations, deliberately not one flag.

    *Stop* lets the current stage finish and write its checkpoint, so the run
    stays resumable — which is what the button promises. *Abort* unwinds the
    current work now, and the run is whatever it managed to write.

    So `check()` raises only for abort. A stopping token's `check()` returns
    normally, and `stopping` is read at the stage boundary instead.

    Written by the request thread handling `POST /api/runs/{id}/abort` and
    read by the worker thread. No lock: a `bool` assignment is atomic under
    the GIL, and these flags are set once and never cleared — a token belongs
    to one run and is never reset, so there is no read-modify-write to lose.
    """

    def __init__(self) -> None:
        self._stopping = False
        self._aborted = False

    def stop_after_stage(self) -> None:
        self._stopping = True

    def abort(self) -> None:
        # Order matters for a reader that lands between the two assignments:
        # setting `_stopping` first leaves no window where `aborted` is true
        # but `stopping` is false, which is the window in which a stage
        # boundary would start one more stage.
        self._stopping = True
        self._aborted = True

    def check(self) -> None:
        if self._aborted:
            raise Aborted("run aborted")

    @property
    def stopping(self) -> bool:
        """True after either call: both mean this run is ending, and the
        stage boundary must not begin another stage.
        """
        return self._stopping

    @property
    def aborted(self) -> bool:
        """Which of the two happened, and so which terminal status the run
        gets.
        """
        return self._aborted
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_progress.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`
Expected: all four pass.

- [ ] **Step 6: Commit**

```bash
git add zeitgeist/progress.py tests/test_progress.py
git commit -m "Add the cancellation token

Stop and abort are deliberately not one flag: stop lets the current stage
write its checkpoint so the run stays resumable, abort unwinds now. check()
therefore raises only for abort, and the stage boundary reads stopping.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `distil_topics` reports each topic and honours the token

**Files:**
- Modify: `zeitgeist/analysis/distil.py`, `tests/test_analysis_distil.py`

**Interfaces:**
- Consumes: `zeitgeist.progress.CancelToken`, `Aborted` from Task 2.
- Produces:
  - `distil_topics(evidence, provider, settings, *, on_topic: Callable[[Topic], None] | None = None, token: CancelToken | None = None) -> list[Topic]` — both new arguments keyword-only and defaulting to `None`, so every existing caller is unchanged
  - `_distil_one(entry, provider, settings, token)` — the token threaded through to the worker

**Two traps here, and both are the reason this is its own task.**

**Trap one: `as_completed` would make topic ids nondeterministic.** Ids come from `unique_slug(entry.trend.display_name, used_ids)`, which suffixes on collision — two trends both called "Cats" become `cats` and `cats-2` — and `used_ids` accumulates in iteration order. Reporting topics as futures complete in *arbitrary* order would hand the same input different ids run to run, which would break resume (checkpoints key on the id) for no gain.

The fix is that `ThreadPoolExecutor.map` already returns a **lazy iterator that yields in submission order as results become available**. Consuming it lazily inside the `with` block — rather than wrapping it in `list(...)`, which drains it — reports topic *i* as soon as futures 0..*i* have resolved, while later trends are still running. That is incremental enough for the mid-analyse screen to append ranking rows, and it keeps ids identical to today's. **Do not switch to `as_completed`.**

**Trap two: `_distil_one` catches bare `Exception`, which would swallow `Aborted`.** Its `except Exception` exists to drop a single failed trend rather than fail the run — which is right for an `LLMError` and exactly wrong for a cancellation. `Aborted` must be re-raised before that handler, or aborting a run turns into "every trend failed" and surfaces as `DistilError` instead of an abort.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_analysis_distil.py`. Check the module's existing imports and helpers first — it already builds `TrendEvidence` and `DossierDraft` fixtures, and you should reuse them rather than write new ones. Merge new imports into the existing blocks or isort's `I001` will fire.

**Read the module's existing helpers before writing these.** It already has `_settings(**overrides)` — **which takes no `tmp_path`** — plus `_item`, `_reply(text, author, likes)`, `_evidence(name, *, replies=None, posts=1, status=...)` and `_draft(**overrides)`. Every test below uses them as they stand. Add only `_ScriptedProvider`.

```python
import threading
from collections.abc import Callable

from zeitgeist.models import Topic
from zeitgeist.progress import Aborted, CancelToken


class _ScriptedProvider:
    """A provider that runs a per-call hook and returns a per-call draft, so
    a test can control both the order two concurrent distillations finish in
    and which draft each one produced.

    `FakeLLMProvider` pops from a shared list with no lock, so it cannot
    script concurrent calls: two workers popping at once is a race, and the
    test would be asserting on whichever ordering it happened to get.

    The unmatched-prompt branch raises rather than returning a default: a
    double that accepts anything would let a mis-scripted test pass while
    verifying nothing.
    """

    name = "scripted"

    def __init__(
        self, script: dict[str, tuple[Callable[[], None] | None, DossierDraft]]
    ) -> None:
        self._script = script

    def complete(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        for marker, (hook, draft) in self._script.items():
            if marker in prompt:
                if hook is not None:
                    hook()
                return draft
        raise AssertionError("no script entry matched this prompt")


def test_a_topic_is_reported_while_later_trends_are_still_running():
    """This is the whole point of the callback: the mid-analyse screen appends
    ranking rows as they arrive. An implementation that collected every result
    and then called `on_topic` in a loop at the end would satisfy every other
    test in this file — same topics, same order, same count — and show the
    user nothing until the stage finished.

    So the assertion is an ordering across threads: the callback for the first
    trend must fire before the second trend's model call returns.
    """
    reported_cats = threading.Event()
    order: list[str] = []

    def dogs_call() -> None:
        order.append("dogs-call-start")
        reported_cats.wait(timeout=5)
        order.append("dogs-call-end")

    provider = _ScriptedProvider(
        {"Cats": (None, _draft()), "Dogs": (dogs_call, _draft())}
    )

    def on_topic(topic: Topic) -> None:
        order.append(f"reported:{topic.id}")
        if topic.id == "cats":
            reported_cats.set()

    distil_topics(
        [_evidence("Cats"), _evidence("Dogs")],
        provider,
        _settings(distil_concurrency=2),
        on_topic=on_topic,
    )

    assert order.index("reported:cats") < order.index("dogs-call-end")


def test_topic_ids_do_not_depend_on_which_trend_finishes_first():
    """Ids come from `unique_slug`, which suffixes on collision using a set
    that accumulates in iteration order. Reporting as futures *complete*
    rather than in submission order would give this input `a-trend` and
    `a-trend-2` in whichever order the pool happened to finish — so the same
    evidence would produce different ids run to run, and resume, which keys
    on the id, would break.

    Both trends share a label, because that is the only shape in which the
    bug is observable: with distinct display names `unique_slug` never
    collides, the ids are fixed by the names alone, and a half-fix that
    iterated by completion and then sorted the *list* back into evidence
    order would pass while assigning the ids the wrong way round.

    Here the second trend finishes first. The first must still get `a-trend`,
    and the drafts prove which topic is which.
    """
    second_done = threading.Event()
    first = _draft(what_happened="the first one")
    second = _draft(what_happened="the second one")

    provider = _ScriptedProvider(
        {
            "marker-first": (lambda: second_done.wait(timeout=5), first),
            "marker-second": (second_done.set, second),
        }
    )

    topics = distil_topics(
        [
            _evidence("A trend", replies=[_reply("marker-first")]),
            _evidence("A trend", replies=[_reply("marker-second")]),
        ],
        provider,
        _settings(distil_concurrency=2),
    )

    assert [(topic.id, topic.summary) for topic in topics] == [
        ("a-trend", "the first one"),
        ("a-trend-2", "the second one"),
    ]


def test_a_failed_trend_consumes_no_id():
    """`used_ids` must only record ids that were actually handed out.
    Pre-assigning a slug to every trend before distillation — a tempting way
    to make ids independent of completion order — would let a *failed* trend
    reserve `a-trend`, pushing the trend that succeeded to `a-trend-2` for no
    reason a reader of the output could reconstruct.

    Both trends share a label for the same reason as the test above: with
    distinct names there is no collision, so a pre-assigned id and a lazily
    assigned one are indistinguishable and the bug is invisible.

    `FakeLLMProvider` is safe here because `distil_concurrency=1` means only
    one worker ever pops from its response list; the race its own docstring
    warns about needs two.
    """
    provider = FakeLLMProvider(responses=[LLMError("no"), _draft()])

    topics = distil_topics(
        [_evidence("A trend"), _evidence("A trend")],
        provider,
        _settings(distil_concurrency=1),
    )

    assert [topic.id for topic in topics] == ["a-trend"]


def test_an_aborted_token_stops_the_stage_rather_than_failing_every_trend():
    """`_distil_one` catches bare `Exception` so one bad trend is dropped
    rather than failing the run. `Aborted` must escape that handler: caught,
    every trend would report as failed and the caller would see `DistilError`
    — "all trends failed distillation" — for a run the user deliberately
    cancelled. The two outcomes are indistinguishable to the worker, which
    would then record the wrong terminal status.
    """
    token = CancelToken()
    token.abort()
    provider = _ScriptedProvider({"Cats": (None, _draft())})

    with pytest.raises(Aborted):
        distil_topics(
            [_evidence("Cats")],
            provider,
            _settings(distil_concurrency=1),
            token=token,
        )


def test_a_trend_that_fails_is_not_reported():
    """The callback appends a ranking row. A dropped trend has no topic, so
    reporting one would put a row on the screen for something that does not
    exist in the checkpoint.
    """
    reported: list[str] = []
    provider = FakeLLMProvider(responses=[LLMError("no")])

    with pytest.raises(DistilError):
        distil_topics(
            [_evidence("Cats")],
            provider,
            _settings(distil_concurrency=1),
            on_topic=lambda topic: reported.append(topic.id),
        )

    assert reported == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analysis_distil.py -k "reported or ids or aborted or consumes" -v`
Expected: FAIL — `TypeError: distil_topics() got an unexpected keyword argument 'on_topic'`

- [ ] **Step 3: Thread the token into the worker**

In `zeitgeist/analysis/distil.py`, change `_distil_one` to take the token and re-raise `Aborted` before the broad handler:

```python
def _distil_one(
    entry: TrendEvidence,
    provider: LLMProvider,
    settings: Settings,
    token: CancelToken | None = None,
) -> tuple[DossierDraft, list[Phrase]] | None:
    replies = [reply for post in entry.posts for reply in post.replies]
    phrases = mine_phrases(
        replies, entry.trend, min_authors=settings.phrase_min_authors
    )
    # Built outside the try: a bug here must crash loudly, not be misreported
    # as a failed trend and silently skipped.
    prompt = _build_prompt(entry, replies, phrases, settings.distil_char_budget)
    if token is not None:
        token.check()
    try:
        return provider.complete(
            prompt, DossierDraft, system=DISTIL_SYSTEM, max_tokens=DISTIL_MAX_TOKENS
        ), phrases
    except Aborted:
        # Before the broad handler below, which exists to drop one failed
        # trend rather than fail the run. That is right for an LLMError and
        # exactly wrong for a cancellation: swallowed here, an abort would
        # surface as "all trends failed distillation".
        raise
    except Exception as exc:
        log.warning(
            "Distillation failed for %r; dropping: %s",
            entry.trend.display_name,
            exc,
        )
        return None
```

- [ ] **Step 4: Rewrite `distil_topics`' body**

Replace the `list(pool.map(...))` drain and the second loop with a single lazy pass:

```python
def distil_topics(
    evidence: list[TrendEvidence],
    provider: LLMProvider,
    settings: Settings,
    *,
    on_topic: Callable[[Topic], None] | None = None,
    token: CancelToken | None = None,
) -> list[Topic]:
    """Distil every trend. A single trend whose call fails is dropped, not
    fatal — but if every trend fails, that is a failed run, not an empty
    result; see `DistilError`.

    `on_topic` fires as each topic is built, so ranking rows can append
    during the stage rather than all at once when it ends.
    """
    if not evidence:
        return []

    topics: list[Topic] = []
    used_ids: set[str] = set()
    failures = 0

    with ThreadPoolExecutor(max_workers=settings.distil_concurrency) as pool:
        # `map` yields in submission order as results arrive, and consuming
        # it lazily *inside* the `with` is what lets a topic be reported
        # while later trends are still running — `list(...)` here would drain
        # the pool first and turn `on_topic` into a batch at the end.
        #
        # Deliberately not `as_completed`: `unique_slug` assigns ids from a
        # set that accumulates as we go, so completion-order iteration would
        # give identical evidence different topic ids from one run to the
        # next, and resume keys on the id.
        results = pool.map(
            lambda one: _distil_one(one, provider, settings, token), evidence
        )
        for entry, result in zip(evidence, results, strict=True):
            if result is None:
                failures += 1
                continue
            draft, phrases = result
            topic = Topic(
                id=unique_slug(entry.trend.display_name, used_ids),
                label=entry.trend.display_name,
                summary=draft.what_happened,
                item_ids=[post.item.source_id for post in entry.posts],
                trend_status=entry.trend.status,
                dossier=Dossier(**draft.model_dump(), recurring_phrases=phrases),
            )
            topics.append(topic)
            if on_topic is not None:
                on_topic(topic)

    if failures == len(evidence):
        raise DistilError(
            f"All {len(evidence)} trend(s) failed distillation; see the "
            "warnings above for each trend's error."
        )
    return topics
```

Add the imports this needs: `from collections.abc import Callable` and `from zeitgeist.progress import Aborted, CancelToken`.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/test_analysis_distil.py -v`
Expected: PASS — the new tests plus every pre-existing one in the module. **If a pre-existing test now fails, the change is wrong, not the test.**

- [ ] **Step 6: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`
Expected: all four pass.

- [ ] **Step 7: Commit**

```bash
git add zeitgeist/analysis/distil.py tests/test_analysis_distil.py
git commit -m "Report each topic as it distils, and honour the cancel token

pool.map already yields in submission order as results arrive, so consuming
it lazily reports a topic while later trends run without making ids depend
on completion order — which as_completed would, and resume keys on the id.

Aborted is re-raised ahead of the broad handler that drops one failed
trend, or cancelling a run would surface as every trend having failed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `run_pipeline` takes an observer and a token

**Files:**
- Modify: `zeitgeist/pipeline.py`, `pyproject.toml`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `RunObserver`, `NullObserver`, `RecordingObserver`, `CancelToken`, `Aborted` from Tasks 1–2; `distil_topics(..., on_topic=, token=)` from Task 3.
- Produces:
  - `run_pipeline(settings, source, provider, store, run_id, start_at=Stage.INGEST, template_ids=None, *, observer: RunObserver = NullObserver(), token: CancelToken | None = None) -> str`
  - `_render_all(briefs, templates, settings, run_dir, run_id, store, observer, token)`

**Who writes the terminal status.** `run_pipeline` still calls `store.finish_run(..., status="ok")` when it completes. It does **not** write a terminal status for stop or abort — the worker does, in Task 8, because the worker owns the token and can tell the two apart. On stop-after-stage `run_pipeline` returns normally without finishing the run; on abort `Aborted` propagates out of it.

**Which status a stopped run gets.** `RunStatus` is `running | ok | failed | aborted | interrupted` — there is no separate "stopped". Both stop-after-stage and abort therefore land on `aborted`. They differ in what was preserved, not in the label: a stopped run has its current stage's checkpoint written and is cleanly resumable, an aborted one is resumable from whatever the previous stage left.

**Where the stop boundary is.** Immediately before each stage's work begins, after the previous stage's checkpoint and `StageRecord` are written. A stop checked any later would abandon the stage mid-flight, which is the resumability the button promises.

**B008.** `observer: RunObserver = NullObserver()` is a function call in a default argument, which ruff's `B008` flags. `NullObserver` is genuinely immutable — it has no state at all — so declare it as such rather than restructuring the signature the spec specifies.

- [ ] **Step 1: Declare `NullObserver` immutable to ruff**

In `pyproject.toml`, extend the existing entry:

```toml
[tool.ruff.lint.flake8-bugbear]
extend-immutable-calls = [
    "fastapi.Depends",
    "fastapi.Query",
    "zeitgeist.progress.NullObserver",
]
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_pipeline.py`. It already has `_FakeTrendSource`, `_template_library` and `_settings`; reuse them. Read the module for how it builds evidence, drafts and brief choices, and reuse those helpers too.

The rewritten checkpoint-size test reads the `checkpoints` table directly, so this module needs `sqlite3`, and `ORDER` alongside the `Stage` it already imports. Merge these into the existing blocks:

```python
import sqlite3

from zeitgeist.progress import Aborted, CancelToken, RecordingObserver
from zeitgeist.records import ORDER


def test_every_stage_reports_started_and_finished(tmp_path):
    """The in-flight screen draws one card per stage and fills it from these
    two events. A stage that reported neither would render as pending for the
    whole run and then jump to done.
    """
    observer = RecordingObserver()

    run_pipeline(*_full_run_args(tmp_path), observer=observer)

    started = [event.payload[0] for event in observer.named("stage_started")]
    finished = [event.payload[0] for event in observer.named("stage_finished")]
    assert started == list(ORDER)
    assert finished == list(ORDER)


def test_every_stage_reports_the_size_of_the_checkpoint_it_wrote(tmp_path):
    """`stage_finished` carries payload bytes rather than a path because
    checkpoints are rows. `is not None and > 0` would pass for a hardcoded 1
    on every stage — which is exactly the "every stage card claims the same
    size" bug — so each reported number is checked against the row it
    describes, read out of the checkpoints table rather than back through the
    pipeline that reported it.
    """
    observer = RecordingObserver()
    run_id = "20260905T150000Z"

    run_pipeline(*_full_run_args(tmp_path, run_id=run_id), observer=observer)

    reported = {
        event.payload[0]: event.payload[1]
        for event in observer.named("stage_finished")
    }
    conn = sqlite3.connect(tmp_path / "data" / "z.db")
    try:
        written = {
            Stage(stage): len(payload.encode("utf-8"))
            for stage, payload in conn.execute(
                "SELECT stage, payload FROM checkpoints WHERE run_id = ?",
                (run_id,),
            )
        }
    finally:
        conn.close()

    assert set(written) == set(ORDER), "a stage wrote no checkpoint"
    assert {stage: reported[stage] for stage in written} == written


def test_a_skipped_stage_reports_no_payload(tmp_path):
    """`None` is the documented meaning of "wrote no payload". A resumed run
    skips the stages before its start point, and a skipped stage reporting a
    stale size would show the resumed run re-writing checkpoints it did not
    touch.
    """
    run_id = "20260905T120000Z"
    run_pipeline(*_full_run_args(tmp_path, run_id=run_id))
    observer = RecordingObserver()

    run_pipeline(
        *_full_run_args(tmp_path, run_id=run_id),
        start_at=Stage.GENERATE,
        observer=observer,
    )

    sizes = {
        event.payload[0]: event.payload[1]
        for event in observer.named("stage_finished")
    }
    assert sizes[Stage.INGEST] is None
    assert sizes[Stage.ANALYSE] is None


def test_topics_are_reported_during_analyse_not_after_it(tmp_path):
    """The mid-analyse screen appends ranking rows as they arrive. Reporting
    them after `stage_finished(ANALYSE)` — which a batch at the end of the
    stage would do — puts every row on screen at the moment the stage
    completes, which is the behaviour this event exists to avoid.
    """
    observer = RecordingObserver()

    run_pipeline(*_full_run_args(tmp_path), observer=observer)

    names = [event.name for event in observer.events]
    analyse_finished = [
        index
        for index, event in enumerate(observer.events)
        if event.name == "stage_finished" and event.payload[0] is Stage.ANALYSE
    ][0]
    first_topic = names.index("topic_distilled")
    assert first_topic < analyse_finished


def test_every_render_is_reported_including_one_that_failed(tmp_path):
    """`render_finished` carries the whole record so a failed render reaches
    the UI as a tile with a message. Reporting only successes is how a
    per-meme failure vanishes — the exact outcome the record's `status` and
    `error` fields exist to prevent.
    """
    observer = RecordingObserver()

    run_pipeline(*_failing_render_args(tmp_path), observer=observer)

    statuses = [
        event.payload[0].status for event in observer.named("render_finished")
    ]
    assert "failed" in statuses


def test_stopping_after_a_stage_leaves_that_stages_checkpoint_written(tmp_path):
    """The promise of the stop button: the current stage finishes and the run
    stays resumable. A stop honoured *inside* a stage would leave no
    checkpoint for it, and resume would have to redo work the user already
    paid for.
    """
    token = CancelToken()
    store = _store(tmp_path)

    # Subclassed rather than proxied through `__getattr__`: `ty` cannot see
    # that a proxy satisfies `RunObserver`, and the gate covers tests.
    class _StopAfterIngest(RecordingObserver):
        def stage_finished(self, stage: Stage, payload_bytes: int | None) -> None:
            if stage is Stage.INGEST:
                token.stop_after_stage()
            super().stage_finished(stage, payload_bytes)

    run_pipeline(
        *_full_run_args(tmp_path, store=store, run_id="20260905T130000Z"),
        observer=_StopAfterIngest(),
        token=token,
    )

    assert Stage.INGEST in store.written_stages("20260905T130000Z")
    assert Stage.ANALYSE not in store.written_stages("20260905T130000Z")


def test_a_stopped_run_is_not_marked_finished(tmp_path):
    """The worker decides the terminal status, because only it can tell stop
    from abort. If `run_pipeline` called `finish_run(status="ok")` on the way
    out of a stop, a half-finished run would show as a successful one and its
    counts would be wrong.
    """
    token = CancelToken()
    token.stop_after_stage()
    store = _store(tmp_path)
    run_id = "20260905T140000Z"

    run_pipeline(*_full_run_args(tmp_path, store=store, run_id=run_id), token=token)

    record = store.get_run(run_id)
    assert record is not None
    assert record.status == "running"


def test_aborting_during_a_stage_propagates_out_of_the_pipeline(tmp_path):
    """The worker catches `Aborted` to write the terminal status. Swallowed
    inside `run_pipeline`, an aborted run would return normally and be
    recorded as a success.

    The abort is raised from inside the generate stage rather than before the
    run, because `abort()` also sets `stopping` — a token aborted up front is
    consumed by the stage boundary, which *returns* rather than raising, so a
    test written that way would assert on a path abort never takes and could
    never pass.
    """
    token = CancelToken()

    class _AbortOnGenerate(RecordingObserver):
        def stage_started(self, stage: Stage) -> None:
            if stage is Stage.GENERATE:
                token.abort()
            super().stage_started(stage)

    with pytest.raises(Aborted):
        run_pipeline(
            *_full_run_args(tmp_path),
            observer=_AbortOnGenerate(),
            token=token,
        )


def test_generate_reports_progress_before_each_brief(tmp_path):
    """The in-flight screen's generate card counts memes as they render, and
    `stage_progress` is the only event carrying that count. Deleting the call
    — or reporting `done` as one-based, or a constant total — leaves every
    other test in this module green while the card sits still until the stage
    ends.

    `done` is checked against the render events rather than a literal, because
    the number of briefs is a property of the fixture rather than of the
    behaviour under test; what matters is that it counts up from zero, once
    per brief, with the total fixed.
    """
    observer = RecordingObserver()

    run_pipeline(*_full_run_args(tmp_path), observer=observer)

    progress = [event.payload for event in observer.named("stage_progress")]
    rendered = [event.payload[0] for event in observer.named("render_finished")]

    assert rendered, "the fixture rendered nothing; the assertion is vacuous"
    assert [payload[0] for payload in progress] == [Stage.GENERATE] * len(rendered)
    assert [payload[1] for payload in progress] == list(range(len(rendered)))
    assert {payload[2] for payload in progress} == {len(rendered)}
    assert [payload[3] for payload in progress] == [
        record.topic_id for record in rendered
    ]
```

**No test asserts that the seams default to no-ops.** That is deliberate: every pre-existing test in `tests/test_pipeline.py` calls `run_pipeline` with neither, so a `None` default that was then dereferenced would fail all of them first. A test doing it again would add nothing and cost maintenance forever.

`_full_run_args(tmp_path, **overrides)` and `_failing_render_args(tmp_path)` are helpers you write, returning the positional arguments `run_pipeline` takes — settings, source, provider, store, run_id. The module already builds each of those pieces for its existing tests; factor the shared construction out rather than duplicating it, and give `_failing_render_args` a template whose image is missing so `render_meme` raises `RenderError`, which the module already exercises elsewhere.

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -k "reports or stopping or abort or progress" -v`
Expected: FAIL — `TypeError: run_pipeline() got an unexpected keyword argument 'observer'`

- [ ] **Step 4: Add the parameters and the stage boundary**

In `zeitgeist/pipeline.py`, add the imports:

```python
from zeitgeist.progress import Aborted, CancelToken, NullObserver, RunObserver
```

Change the signature:

```python
def run_pipeline(
    settings: Settings,
    source: TrendSource,
    provider: LLMProvider,
    store: Store,
    run_id: str,
    start_at: Stage = Stage.INGEST,
    template_ids: list[str] | None = None,
    *,
    observer: RunObserver = NullObserver(),
    token: CancelToken | None = None,
) -> str:
```

Add a boundary helper beside `_stage` and `_skip`:

```python
def _stopping(token: CancelToken | None) -> bool:
    """Whether to end the run rather than begin another stage.

    Read at stage boundaries only. A stop checked inside a stage would
    abandon it before its checkpoint was written, which is the resumability
    the stop button promises.
    """
    return token is not None and token.stopping
```

Then, at the top of each of the four stage bodies, before any work:

```python
    if _stopping(token):
        return run_id
```

and wrap each stage's existing work with the observer calls: `observer.stage_started(stage)` before, `observer.stage_finished(stage, size)` after the `_stage(...)` call, and `observer.stage_finished(stage, None)` after each `_skip(...)`.

Pass the callback and the token into distillation:

```python
        topics = distil_topics(
            evidence,
            provider,
            settings,
            on_topic=observer.topic_distilled,
            token=token,
        )
```

- [ ] **Step 5: Report and check inside the render loop**

Give `_render_all` the two extra parameters and use them:

```python
def _render_all(
    briefs: list[MediaBrief],
    templates: dict[str, TemplateManifest],
    settings: Settings,
    run_dir: Path,
    run_id: str,
    store: Store,
    observer: RunObserver,
    token: CancelToken | None,
) -> int:
```

Inside the loop, before each brief:

```python
    for index, brief in enumerate(briefs):
        if token is not None:
            token.check()
        observer.stage_progress(
            Stage.GENERATE, done=index, total=len(briefs), detail=brief.topic_id
        )
```

and after `store.add_render(record)`, report it. Bind the record to a name first so both the store and the observer get the same object:

```python
        record = RenderRecord(...)
        store.add_render(record)
        observer.render_finished(record)
```

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: PASS — the new tests plus every pre-existing one. **A pre-existing failure means the change is wrong, not the test.**

- [ ] **Step 7: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`
Expected: all four pass.

- [ ] **Step 8: Commit**

```bash
git add zeitgeist/pipeline.py pyproject.toml tests/test_pipeline.py
git commit -m "Give run_pipeline an observer and a cancel token

Both default to no-ops, so scripts/run_pipeline.py and every existing test
construct neither. The stop boundary sits at the top of each stage, after
the previous one's checkpoint is written, which is the resumability the
stop button promises. run_pipeline writes no terminal status for stop or
abort — the worker owns the token and is the only thing that can tell them
apart.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: The DEBUG statements the verbose toggle exists to reveal

**Files:**
- Modify: `zeitgeist/sources/bluesky.py`, `zeitgeist/analysis/distil.py`, `zeitgeist/media/brief.py`, `zeitgeist/media/render.py`
- Test: `tests/test_sources_bluesky.py`, `tests/test_analysis_distil.py`, `tests/test_media_brief.py`, `tests/test_media_render.py`

**Interfaces:** none — this task adds no callable surface.

**Why this exists.** The pipeline emits four INFO lines per run plus warnings, and nothing at DEBUG on the live path: the only `log.debug` left is in `consolidate.py`, which the 2026-08-26 rework took off the pipeline. So `GET /api/runs/{id}/log?verbose=true` — shipped in phase 2 — currently returns exactly what `verbose=false` does. This task gives the toggle something to reveal.

**The constraint that governs every line you add:** no DEBUG line may carry reply text, post bodies or `author_key`. `Item`'s docstring and `Reply.author_key` show the project is deliberate about not storing personal data, and a debug log that dumps reply text to disk would quietly undo it. **Debug lines carry counts, ids, permalinks and elapsed times.** A permalink is a public URL to a public post and is fine; the post's text is not.

`zeitgeist/media/render.py` has **no logger at all** today, despite the design's mockup showing its name in the log. Add one.

- [ ] **Step 1: Write the failing tests**

These use pytest's `caplog`. Add one test per module. **Assert on the structured record, never on the formatted string** — a test pinning exact wording is a change detector that fails when someone improves the message, and it would not catch the thing that matters.

Add to `tests/test_sources_bluesky.py`:

```python
import logging


def test_each_trend_logs_its_post_and_reply_counts_at_debug(caplog):
    """The verbose toggle's whole purpose on the ingest stage: seeing that a
    trend yielded three posts and forty replies is how you tell a thin fetch
    from a broken one.

    Asserted on `record.args` rather than on a record merely existing, and
    never on the formatted string. Existence is satisfied by
    `log.debug("fetched")`; the wrong-argument mutation — the two counts
    swapped, or the post count logged twice — is the one that makes the line
    lie while the toggle still appears to work. The literals below are what
    this module's stubbed client is seeded with; take them from that fixture,
    do not compute them from the source under test.
    """
    with caplog.at_level(logging.DEBUG, logger="zeitgeist.sources.bluesky"):
        source.fetch_evidence(settings)

    assert [
        record.args
        for record in caplog.records
        if record.levelno == logging.DEBUG
        and record.name == "zeitgeist.sources.bluesky"
    ] == [("A trend", 2, 3)]


def test_no_debug_record_carries_reply_text(caplog):
    """The project stores no personal data — `Reply.author_key` exists only
    to count distinct accounts, and `Item`'s docstring says so. A debug line
    that dumped reply text would put it on disk in `log_lines` and stream it
    to the browser, undoing that deliberately and invisibly.

    This asserts on the *arguments* rather than the rendered message so that
    a lazily-formatted line, which only interpolates when a handler is
    attached, cannot slip text through unexamined.
    """
    with caplog.at_level(logging.DEBUG, logger="zeitgeist.sources.bluesky"):
        source.fetch_evidence(settings)

    for record in caplog.records:
        rendered = record.getMessage()
        assert REPLY_TEXT not in rendered
        assert AUTHOR_KEY not in rendered
```

`REPLY_TEXT` and `AUTHOR_KEY` are distinctive sentinel strings you put into the fixture the test drives the source with — something like `"UNIQUE-REPLY-BODY-SENTINEL"` — so the assertion catches the text wherever it appears rather than matching on a substring that could occur by chance. Read the module for how it stubs the HTTP client and reuse that; **do not add a network call.**

Write the equivalent for the other three modules, driving each through its existing test entry point. **Each asserts on `record.args`, with hand-derived literals taken from that module's fixture** — an existence check cannot catch a wrong argument, which is the mutation these exist to stop:

- `tests/test_analysis_distil.py` — a DEBUG record per topic carrying the trend name, the reply count and the prompt *character count*, never the replies themselves. Its elapsed-time line is the one exception: a duration is not hand-derivable, so assert `record.args[0]` is the trend name and that `record.args[1]` is a `float`.
- `tests/test_media_brief.py` — a DEBUG record naming the topic, the chosen template id and the attempt number, since `_brief_one` retries once and which attempt succeeded is the thing you want when captions are poor.
- `tests/test_media_render.py` — a DEBUG record per slot carrying the slot name and the fitted font size, which is what you need when text overflows a box.

The reply-text assertion belongs on the distil module too, which is the one that actually handles reply bodies. For brief and render there is no reply text in scope, so a single DEBUG-exists test each is enough.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_sources_bluesky.py tests/test_analysis_distil.py tests/test_media_brief.py tests/test_media_render.py -k debug -v`
Expected: FAIL with "emitted no DEBUG records" on each.

- [ ] **Step 3: Add the statements**

`zeitgeist/sources/bluesky.py` — in `_evidence_for` (or wherever a single trend's posts and replies are assembled, around line 196–207), after the replies are gathered:

```python
        log.debug(
            "Trend %s: %d posts, %d replies",
            trend["topic"],
            len(items),
            sum(len(group) for group in replies),
        )
```

`zeitgeist/analysis/distil.py` — in `_distil_one`, around the `provider.complete` call:

```python
    started = time.monotonic()
    log.debug(
        "Distilling %r: %d replies, %d prompt chars",
        entry.trend.display_name,
        len(replies),
        len(prompt),
    )
```

and after a successful completion:

```python
        log.debug(
            "Distilled %r in %.1fs",
            entry.trend.display_name,
            time.monotonic() - started,
        )
```

`zeitgeist/media/brief.py` — in `_brief_one`, once a choice validates, carrying which attempt it was. The loop is `for _ in range(2)`; change it to `for attempt in range(1, 3)` and log:

```python
            log.debug(
                "Brief for %r: template %s on attempt %d",
                topic.label,
                choice.template_id,
                attempt,
            )
```

`zeitgeist/media/render.py` — add the logger at module scope, beneath the imports:

```python
log = logging.getLogger(__name__)
```

and in `_draw_slot`, once the font size is settled:

```python
    log.debug("Slot %s fitted at %dpt", slot.name, size)
```

Adjust each to the module's actual variable names — read the surrounding code rather than pasting blind. Add `import logging` and `import time` where they are missing.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_sources_bluesky.py tests/test_analysis_distil.py tests/test_media_brief.py tests/test_media_render.py -v`
Expected: PASS, including every pre-existing test in all four modules.

- [ ] **Step 5: Confirm the toggle now has something to filter**

Run: `uv run pytest tests/test_store.py -k log -v`
Expected: PASS. These are phase 2's tests over `Store.log_lines`; they seed rows directly and are unaffected, but a green run here confirms you have not disturbed the reader the toggle uses.

- [ ] **Step 6: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`
Expected: all four pass.

- [ ] **Step 7: Commit**

```bash
git add zeitgeist/sources/bluesky.py zeitgeist/analysis/distil.py zeitgeist/media/brief.py zeitgeist/media/render.py tests/
git commit -m "Give the verbose toggle something to reveal

Per-trend fetch and reply counts, per-topic distil timings, the chosen
template and which attempt produced it, and per-slot font fitting. render.py
had no logger at all, despite the design showing its name in the log.

Counts, ids, permalinks and elapsed times only: no reply text, no post
bodies, no author_key. A debug line carrying those would put them in
log_lines and stream them to the browser, undoing the project's deliberate
choice not to store personal data.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Log capture — the ring buffer, the handler, and batched rows

**Files:**
- Create: `zeitgeist/logcapture.py`, `tests/test_logcapture.py`
- Modify: `zeitgeist/store.py`, `tests/test_store.py`

**Interfaces:**
- Produces:
  - `zeitgeist.logcapture.CapturedLine` — a frozen dataclass: `seq: int`, `logged_at: datetime`, `level: str`, `logger: str`, `message: str`
  - `zeitgeist.logcapture.RunLogBuffer` — `append(line)` and `since(seq) -> list[CapturedLine]`; a bounded `deque`
  - `zeitgeist.logcapture.RunLogHandler(logging.Handler)` — `__init__(run_id, buffer, store, batch_size=50)`, `emit(record)`, `flush()`, and `attach()` / `detach()` as a context manager via `capture_run_log(...)`
  - `zeitgeist.logcapture.capture_run_log(run_id, store, *, maxlen=2000) -> AbstractContextManager[RunLogBuffer]`
  - `Store.write_log_lines(run_id: str, lines: Sequence[CapturedLine]) -> None` — one transaction for the batch

**Why two sinks.** The `log_lines` table is what makes the post-mortem block work for a run that failed last week. The bounded in-memory deque is what the SSE stream reads. They are written from the same `emit`, so a line cannot reach one and miss the other.

**Why a deque and no lock.** `append` and `popleft` are atomic under the GIL, so the handler can write from the worker thread while the SSE generator reads from the event loop's thread with no lock. That is the one place the thread boundary needs care, and keeping the handler free of any reference to the loop is what lets the same handler work under `TestClient` and under the dev harness. **Do not add a `Lock`, an `asyncio.Queue`, or `loop.call_soon_threadsafe`** — each would couple the handler to a running loop.

**Why batched rows.** A DEBUG run emits several hundred lines; a transaction each would be gratuitous. Lines accumulate in a pending list and flush at `batch_size` or on `detach`.

**Why the handler is safe as a plain handler:** the queue guarantees one run at a time, so there is never a second run's handler attached to the `zeitgeist` logger simultaneously.

**`seq` is assigned by the handler, not the database.** It orders lines within a run, and two lines can share a timestamp at the resolution the handler records — `LogLine`'s own docstring says the live log's ordering has to be total. The handler owns a counter starting at 1.

- [ ] **Step 1: Write the failing store test**

Add to `tests/test_store.py`:

```python
def test_a_batch_of_log_lines_round_trips(tmp_path):
    """The writer phase 2's reader was built against. `Store.log_lines`
    already has tests, but they seed rows with hand-written SQL because no
    writer existed — so nothing yet proves the two agree on column order,
    and a mismatch would surface as levels appearing in the message column.
    """
    store = _store(tmp_path)
    store.start_run("20260905T120000Z", make_run_config())

    store.write_log_lines(
        "20260905T120000Z",
        [
            CapturedLine(
                seq=1,
                logged_at=datetime(2026, 9, 5, 12, tzinfo=UTC),
                level="INFO",
                logger="zeitgeist.pipeline",
                message="Fetched 3 trends",
            ),
            CapturedLine(
                seq=2,
                logged_at=datetime(2026, 9, 5, 12, tzinfo=UTC),
                level="DEBUG",
                logger="zeitgeist.media.render",
                message="Slot top fitted at 48pt",
            ),
        ],
    )

    lines = store.log_lines("20260905T120000Z", verbose=True)
    assert [(line.seq, line.level, line.logger) for line in lines] == [
        (1, "INFO", "zeitgeist.pipeline"),
        (2, "DEBUG", "zeitgeist.media.render"),
    ]
    assert lines[0].message == "Fetched 3 trends"


def test_writing_no_lines_is_not_an_error(tmp_path):
    """`detach` flushes whatever is pending, which is routinely nothing — a
    run that ended right after a batch boundary. An empty `executemany` is
    fine, but an implementation building a VALUES list by hand would produce
    invalid SQL for the empty case and only fail on that timing.
    """
    store = _store(tmp_path)
    store.start_run("20260905T120000Z", make_run_config())

    store.write_log_lines("20260905T120000Z", [])

    assert store.log_lines("20260905T120000Z", verbose=True) == []
```

- [ ] **Step 2: Write the failing capture tests**

Create `tests/test_logcapture.py`:

```python
import logging
import threading
from datetime import UTC, datetime

from tests.run_factory import make_run_config
from zeitgeist.logcapture import CapturedLine, RunLogBuffer, capture_run_log
from zeitgeist.store import Store


def _store(tmp_path) -> Store:
    store = Store(tmp_path / "z.db")
    store.init_schema()
    return store


class _CountingStore(Store):
    """Records the size of each batch handed to `write_log_lines`.

    A subclass rather than an assignment over the instance method: assigning
    needs a `type: ignore[method-assign]` that the project's suppression rule
    would then have to justify, and the override still calls `super()`, so
    every row really is written and the rows themselves stay assertable.
    """

    def __init__(self, path) -> None:
        super().__init__(path)
        self.batches: list[int] = []

    def write_log_lines(self, run_id: str, lines) -> None:
        self.batches.append(len(lines))
        super().write_log_lines(run_id, lines)


def _line(seq: int, message: str = "hello") -> CapturedLine:
    return CapturedLine(
        seq=seq,
        logged_at=datetime(2026, 9, 5, 12, tzinfo=UTC),
        level="INFO",
        logger="zeitgeist.pipeline",
        message=message,
    )


def test_the_buffer_returns_only_lines_after_the_given_seq():
    """The SSE generator polls with the last seq it sent. A `since` that
    returned everything would resend the whole log every quarter second, and
    the browser would render duplicates for the life of the run.
    """
    buffer = RunLogBuffer(maxlen=10)
    for seq in (1, 2, 3):
        buffer.append(_line(seq))

    assert [line.seq for line in buffer.since(1)] == [2, 3]


def test_the_buffer_drops_the_oldest_lines_when_it_is_full():
    """Bounded on purpose: a DEBUG run emits several hundred lines and the
    buffer lives for the run's duration. Unbounded, a long run's buffer would
    grow without limit in a process that is also serving requests.
    """
    buffer = RunLogBuffer(maxlen=2)
    for seq in (1, 2, 3):
        buffer.append(_line(seq))

    assert [line.seq for line in buffer.since(0)] == [2, 3]


def test_a_client_that_missed_evicted_lines_still_advances():
    """A slow client asks for everything after seq 1 when the buffer has
    already evicted through seq 5. Returning nothing would stall it forever
    on a seq that will never come back; it must get what is still held.
    """
    buffer = RunLogBuffer(maxlen=2)
    for seq in (1, 2, 3, 4, 5):
        buffer.append(_line(seq))

    assert [line.seq for line in buffer.since(1)] == [4, 5]


def test_captured_lines_reach_both_the_buffer_and_the_table(tmp_path):
    """The two sinks exist for different readers — the table for a run that
    failed last week, the buffer for the stream watching one now — and both
    are fed from the same `emit`. An implementation writing only one would
    pass whichever half of the suite tested the other.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.capture")

    with capture_run_log("r1", store) as buffer:
        log.info("first")
        log.info("second")

    assert [line.message for line in buffer.since(0)] == ["first", "second"]
    assert [line.message for line in store.log_lines("r1", verbose=True)] == [
        "first",
        "second",
    ]


def test_lines_are_written_in_batches_rather_than_one_row_at_a_time(tmp_path):
    """A DEBUG run emits several hundred lines and a transaction each would
    be gratuitous. This pins the batching by counting writes: an
    implementation flushing per record would pass every content assertion
    above while doing 200 transactions.
    """
    store = _CountingStore(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.batch")

    with capture_run_log("r1", store, batch_size=5):
        for index in range(12):
            log.info("line %d", index)

    assert max(store.batches) > 1
    assert sum(store.batches) == 12
    assert [line.message for line in store.log_lines("r1", verbose=True)] == [
        f"line {index}" for index in range(12)
    ]


def test_the_handler_detaches_when_the_run_ends(tmp_path):
    """One run at a time is what makes a plain handler safe. A handler left
    attached would capture the *next* run's lines into the previous run's
    rows — and worse, keep a closed `Store` alive after the worker moved on.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.detach")

    with capture_run_log("r1", store):
        log.info("during")
    log.info("after")

    assert [line.message for line in store.log_lines("r1", verbose=True)] == [
        "during"
    ]


def test_the_handler_detaches_even_when_the_run_raises(tmp_path):
    """Runs fail, and an abort unwinds through here. A handler detached only
    on the success path would leak onto the logger for the life of the
    process the first time a run failed.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.raising")
    before = len(logging.getLogger("zeitgeist").handlers)

    try:
        with capture_run_log("r1", store):
            log.info("during")
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert len(logging.getLogger("zeitgeist").handlers) == before
    assert [line.message for line in store.log_lines("r1", verbose=True)] == [
        "during"
    ]


def test_debug_lines_are_captured_so_the_toggle_can_filter_them(tmp_path):
    """The server always captures at DEBUG and the toggle filters what is
    *returned* — that is what makes flipping it work retroactively on lines
    already recorded. A handler set to INFO would make the toggle a
    permanent no-op no matter what the endpoint does.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.level")

    with capture_run_log("r1", store):
        log.debug("quiet")
        log.info("loud")

    assert [line.level for line in store.log_lines("r1", verbose=True)] == [
        "DEBUG",
        "INFO",
    ]
    assert [line.level for line in store.log_lines("r1", verbose=False)] == ["INFO"]


def test_lines_written_from_a_worker_thread_are_visible_to_the_reader(tmp_path):
    """The buffer is the seam between the worker thread and the event loop:
    the handler appends on the worker, the SSE generator reads from the loop.
    A buffer using thread-local state, or one built per reader, would pass
    every single-threaded test here and stream nothing during a real run.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.threaded")
    done = threading.Event()

    with capture_run_log("r1", store) as buffer:

        def worker() -> None:
            log.info("from the worker")
            done.set()

        thread = threading.Thread(target=worker)
        thread.start()
        assert done.wait(timeout=5)
        thread.join(timeout=5)

        assert [line.message for line in buffer.since(0)] == ["from the worker"]
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_logcapture.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zeitgeist.logcapture'`

- [ ] **Step 4: Add `Store.write_log_lines`**

In `zeitgeist/store.py`, beside `log_lines`. It must not import from `zeitgeist.logcapture` — that would invert the dependency — so type the parameter structurally against what it reads:

```python
    def write_log_lines(self, run_id: str, lines: Sequence[LogLine]) -> None:
        """One transaction for the whole batch.

        A DEBUG run emits several hundred lines and a transaction each would
        be gratuitous. `executemany` handles the empty case, which is routine:
        a run ending just after a batch boundary flushes nothing.
        """
        with self._conn:
            self._conn.executemany(
                "INSERT INTO log_lines "
                "(run_id, seq, logged_at, level, logger, message) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        line.seq,
                        line.logged_at.isoformat(),
                        line.level,
                        line.logger,
                        line.message,
                    )
                    for line in lines
                ],
            )
```

`CapturedLine` is structurally identical to `LogLine`, so annotating `Sequence[LogLine]` keeps `store.py` free of any import from `logcapture` while `ty` still checks the fields this reads. Add the `CapturedLine` import to `tests/test_store.py` only.

- [ ] **Step 5: Write `zeitgeist/logcapture.py`**

```python
"""Two sinks for one run's log, written from the same handler.

The `log_lines` table is what makes the post-mortem block work for a run
that failed last week. The bounded in-memory buffer is what the SSE stream
reads. Both are fed from `emit`, so a line cannot reach one and miss the
other.
"""

import logging
from collections import deque
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from zeitgeist.store import Store

LOGGER_NAME = "zeitgeist"
DEFAULT_MAXLEN = 2000
DEFAULT_BATCH_SIZE = 50


@dataclass(frozen=True)
class CapturedLine:
    """One captured line. Structurally identical to `records.LogLine`, which
    is what the store reads back — kept separate so `logcapture` depends on
    `store` and never the reverse.
    """

    seq: int
    logged_at: datetime
    level: str
    logger: str
    message: str


class RunLogBuffer:
    """The seam between the worker thread and the event loop.

    A `deque` with a `maxlen`: `append` and `popleft` are atomic under the
    GIL, so the handler writes from the worker while the SSE generator reads
    from the loop with no lock. Deliberately holds no reference to any event
    loop — `loop.call_soon_threadsafe` into an `asyncio.Queue` would couple
    the handler to a running loop, and the same handler has to work under
    `TestClient` and under the dev harness. A quarter-second of polling
    latency on a log line is invisible.
    """

    def __init__(self, maxlen: int = DEFAULT_MAXLEN) -> None:
        self._lines: deque[CapturedLine] = deque(maxlen=maxlen)

    def append(self, line: CapturedLine) -> None:
        self._lines.append(line)

    def since(self, seq: int) -> list[CapturedLine]:
        """Every held line after `seq`.

        A client whose `seq` was evicted gets what is still held rather than
        nothing: returning nothing would stall it forever on a sequence
        number that will never come back.
        """
        return [line for line in tuple(self._lines) if line.seq > seq]


class RunLogHandler(logging.Handler):
    """Writes one run's lines to a buffer and, in batches, to the store.

    Safe as a plain handler because the queue guarantees one run at a time,
    so a second run's handler is never attached simultaneously.
    """

    def __init__(
        self,
        run_id: str,
        buffer: RunLogBuffer,
        store: Store,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        super().__init__(level=logging.DEBUG)
        self._run_id = run_id
        self._buffer = buffer
        self._store = store
        self._batch_size = batch_size
        self._pending: list[CapturedLine] = []
        # Starts at 1, and is the handler's rather than the database's:
        # two lines can share a timestamp at the resolution recorded here,
        # and the live log's ordering has to be total.
        self._seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        self._seq += 1
        line = CapturedLine(
            seq=self._seq,
            logged_at=datetime.fromtimestamp(record.created, UTC),
            level=record.levelname,
            logger=record.name,
            message=record.getMessage(),
        )
        self._buffer.append(line)
        self._pending.append(line)
        if len(self._pending) >= self._batch_size:
            self.flush()

    def flush(self) -> None:
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        self._store.write_log_lines(self._run_id, batch)


@contextmanager
def capture_run_log(
    run_id: str,
    store: Store,
    *,
    maxlen: int = DEFAULT_MAXLEN,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Iterator[RunLogBuffer]:
    """Attach a handler for one run's duration, and detach it after.

    The `finally` is load-bearing: runs fail, and an abort unwinds through
    here. A handler detached only on the success path would leak onto the
    `zeitgeist` logger for the life of the process the first time a run
    failed, and capture the next run's lines into the previous run's rows.
    """
    buffer = RunLogBuffer(maxlen=maxlen)
    handler = RunLogHandler(run_id, buffer, store, batch_size=batch_size)
    logger = logging.getLogger(LOGGER_NAME)
    # The server always captures at DEBUG and the toggle filters what is
    # *returned*, which is what lets flipping it work retroactively on lines
    # already recorded. A logger left at WARNING would make the toggle a
    # permanent no-op no matter what the endpoint does.
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield buffer
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        handler.flush()
```

Note `Sequence` is imported for the store's annotation; drop it here if `logcapture` does not use it, and let ruff's `F401` tell you.

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/test_logcapture.py tests/test_store.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`
Expected: all four pass.

- [ ] **Step 8: Commit**

```bash
git add zeitgeist/logcapture.py zeitgeist/store.py tests/test_logcapture.py tests/test_store.py
git commit -m "Capture a run's log to rows and to a ring buffer

One handler, two sinks: the table for a run that failed last week, the
bounded deque for the stream watching one now. The deque is the thread
boundary and needs no lock, because append and popleft are atomic under the
GIL — and it holds no reference to any event loop, so the same handler
works under TestClient and under the dev harness.

Rows go in batches: a DEBUG run emits several hundred lines and a
transaction each would be gratuitous.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Startup reconciliation

**Files:**
- Modify: `zeitgeist/store.py`, `zeitgeist/api/app.py`, `tests/test_store.py`, `tests/test_api_app.py`

**Interfaces:**
- Produces:
  - `Store.reconcile_interrupted() -> list[str]` — marks every run still `running` as `interrupted`, returning the ids it changed
  - `Store.abort_run(run_id: str) -> None` — records a terminal `aborted` status, with no counts and no error

**Why.** The queue is in-memory and the worker dies with the process. A run left at `running` in `run_records` is one the UI would poll forever, drawing an in-flight card for something that will never progress. Marking it `interrupted` on startup says what actually happened. An interrupted run is resumable from its last good checkpoint like any other — nothing about the checkpoints is disturbed.

**It returns the ids rather than a count** because the caller logs them, and "interrupted 20260905T120000Z" is a far more useful startup line than "interrupted 1 run".

- [ ] **Step 1: Write the failing store tests**

Add to `tests/test_store.py`:

```python
def test_reconciling_marks_a_running_run_interrupted(tmp_path):
    """The process died mid-run. Left at `running`, the UI polls it forever
    and draws an in-flight card for a run with no worker behind it."""
    store = _store(tmp_path)
    store.start_run("20260905T120000Z", make_run_config())

    changed = store.reconcile_interrupted()

    assert changed == ["20260905T120000Z"]
    record = store.get_run("20260905T120000Z")
    assert record is not None
    assert record.status == "interrupted"


def test_reconciling_leaves_finished_runs_alone(tmp_path):
    """This runs on every startup, over the whole table. A predicate matching
    more than `status = 'running'` would rewrite the history of every run the
    user has ever made, on every restart, silently.
    """
    store = _store(tmp_path)
    store.start_run("ok-run", make_run_config())
    store.finish_run(
        "ok-run",
        status="ok",
        item_count=1,
        trends_found=1,
        topics_kept=1,
        phrases_found=0,
    )
    store.start_run("failed-run", make_run_config())
    store.fail_run(
        "failed-run",
        RunError(kind="DistilError", message="no", stage=Stage.ANALYSE),
    )

    assert store.reconcile_interrupted() == []

    # Guarded rather than dereferenced inline: `get_run` returns
    # `RunRecordRow | None`, and `ty` covers tests as part of the gate.
    finished = store.get_run("ok-run")
    failed = store.get_run("failed-run")
    assert finished is not None
    assert failed is not None
    assert (finished.status, failed.status) == ("ok", "failed")


def test_reconciling_an_already_reconciled_database_changes_nothing(tmp_path):
    """Restarts happen back to back during development, and `--reload`
    restarts on every save. A second pass must be a no-op rather than
    re-stamping rows or reporting the same run again.
    """
    store = _store(tmp_path)
    store.start_run("20260905T120000Z", make_run_config())
    store.reconcile_interrupted()

    assert store.reconcile_interrupted() == []


def test_aborting_a_run_records_it_without_counts(tmp_path):
    """`finish_run` requires the four counts and a run that ended early has
    none. Routing an abort through it would mean inventing zeros, which the
    Runs list would render as a run that found nothing — indistinguishable
    from a real empty result.
    """
    store = _store(tmp_path)
    store.start_run("20260905T120000Z", make_run_config())

    store.abort_run("20260905T120000Z")

    record = store.get_run("20260905T120000Z")
    assert record is not None
    assert record.status == "aborted"
    assert record.item_count is None


def test_aborting_a_run_that_already_finished_changes_nothing(tmp_path):
    """The worker calls this on both the stop and the abort path, and an
    abort can land after the pipeline already wrote `ok`. Relabelling a
    completed run as aborted would lose a successful run's outcome — and the
    counts with it.
    """
    store = _store(tmp_path)
    store.start_run("20260905T120000Z", make_run_config())
    store.finish_run(
        "20260905T120000Z",
        status="ok",
        item_count=4,
        trends_found=2,
        topics_kept=1,
        phrases_found=0,
    )

    store.abort_run("20260905T120000Z")

    record = store.get_run("20260905T120000Z")
    assert record is not None
    assert record.status == "ok"
    assert record.item_count == 4


def test_reconciling_preserves_the_checkpoints_a_resume_needs(tmp_path):
    """An interrupted run is resumable from its last good checkpoint like any
    other. A reconciliation that cleared partial state — the tempting reading
    of "clean up the dead run" — would throw away the ingest payload the user
    waited minutes for.
    """
    store = _store(tmp_path)
    store.start_run("20260905T120000Z", make_run_config())
    store.write_analyse_checkpoint(
        "20260905T120000Z", [make_topic("cats")], meme_potential_weight=0.3
    )

    store.reconcile_interrupted()

    assert Stage.ANALYSE in store.written_stages("20260905T120000Z")
    assert store.run_topics("20260905T120000Z")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_store.py -k reconcil -v`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'reconcile_interrupted'`

- [ ] **Step 3: Implement it**

In `zeitgeist/store.py`, beside `fail_run`:

```python
    def reconcile_interrupted(self) -> list[str]:
        """Mark every run still `running` as `interrupted`, returning the ids.

        Runs on server startup. The queue is in-memory and the worker dies
        with the process, so a row left at `running` is one the UI would poll
        forever. The checkpoints are untouched: an interrupted run resumes
        from its last good one like any other.
        """
        with self._conn:
            rows = self._conn.execute(
                "SELECT run_id FROM run_records WHERE status = 'running' "
                "ORDER BY started_at"
            ).fetchall()
            if not rows:
                return []
            self._conn.execute(
                "UPDATE run_records SET status = 'interrupted', finished_at = ? "
                "WHERE status = 'running'",
                (_now(),),
            )
        return [row["run_id"] for row in rows]
```

Check how `_now()` and row access are spelled in the surrounding methods and match them — `store.py` uses a row factory, so `row["run_id"]` may instead be `row[0]`.

Then add `abort_run` beside `fail_run`:

```python
    def abort_run(self, run_id: str) -> None:
        """Record that a run was stopped or aborted by the user.

        Its own method rather than a status argument to `finish_run`, for the
        reason `fail_run`'s docstring gives: `finish_run` requires the four
        counts, and a run that ended early has none to record. Stop and abort
        share this status — `RunStatus` has no separate "stopped" — and differ
        in what was preserved, not in the label.

        The `status = 'running'` guard makes this idempotent. The worker calls
        it on both the stop and the abort path, and an abort can land after
        `run_pipeline` has already written `ok`; a run that reached a terminal
        status must not be relabelled.
        """
        self._conn.execute(
            "UPDATE run_records SET status = 'aborted', finished_at = ? "
            "WHERE run_id = ? AND status = 'running'",
            (_now(), run_id),
        )
        self._conn.commit()
```

- [ ] **Step 4: Wire it into startup**

In `zeitgeist/api/app.py`'s `create_app`, immediately after `store.init_schema()`:

```python
    interrupted = store.reconcile_interrupted()
    if interrupted:
        log.info(
            "Marked %d run(s) interrupted after an unclean shutdown: %s",
            len(interrupted),
            ", ".join(interrupted),
        )
```

Add `import logging` and a module-level `log = logging.getLogger(__name__)` if `app.py` has neither.

**Reconcile in `create_app`, not in the lifespan.** `create_app` already opens the store and calls `init_schema` there, for the reason its comment gives: `TestClient` runs the lifespan only when used as a context manager. Reconciliation belongs with schema initialisation, before the first request can observe a stale `running` row.

- [ ] **Step 5: Write the failing app test**

Add to `tests/test_api_app.py`:

```python
def test_a_run_left_running_by_a_crash_is_interrupted_on_startup(tmp_path):
    """End to end, because the store test alone cannot show that anything
    calls it. A `reconcile_interrupted` that existed but was never wired in
    would pass every test in `test_store.py` and leave the UI polling a dead
    run forever.
    """
    settings = api_settings(tmp_path)
    store = Store(settings.db_path)
    store.init_schema()
    store.start_run("20260905T120000Z", make_run_config())
    store.close()

    client = seeded_client(tmp_path)

    body = client.get("/api/runs/20260905T120000Z").json()
    assert body["run"]["status"] == "interrupted"
```

`seeded_client` builds its own app over the same `tmp_path` database, so the run seeded above is present when `create_app` runs. Check `tests/api_factory.py` for the exact helper names before writing this.

- [ ] **Step 6: Run to verify everything passes**

Run: `uv run pytest tests/test_store.py tests/test_api_app.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`
Expected: all four pass.

- [ ] **Step 8: Commit**

```bash
git add zeitgeist/store.py zeitgeist/api/app.py tests/test_store.py tests/test_api_app.py
git commit -m "Reconcile interrupted runs, and record aborted ones

The queue is in-memory and the worker dies with the process, so a row left
at running is one the UI polls forever. Marking it interrupted says what
happened; the checkpoints are untouched, so it resumes like any other run.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: `RunService` — the queue, the worker thread and run lifecycle

**Files:**
- Create: `zeitgeist/runner.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: `RunObserver`, `CancelToken`, `Aborted`, `NullObserver` (Tasks 1–2); `capture_run_log`, `RunLogBuffer` (Task 6); `run_pipeline` (Task 4); `Store.abort_run` (Task 7); `build_trend_source` from `zeitgeist/sources/__init__.py`; `build_provider` from `zeitgeist/llm/factory.py`.
- Produces:
  - `zeitgeist.runner.RUN_OVERRIDE_KEYS: frozenset[str]`
  - `zeitgeist.runner.RunRequest` — `run_id: str | None = None`, `start_at: Stage = Stage.INGEST`, `template_ids: list[str] | None = None`, `overrides: dict[str, str] = {}`
  - `zeitgeist.runner.QueuedRun` — `run_id: str`, `position: int` (0 means executing now)
  - `zeitgeist.runner.ActiveRuns` — `current: str | None`, `queued: list[str]`
  - `zeitgeist.runner.ExecuteFn` — `Callable[[Settings, RunRequest, Store, RunObserver, CancelToken], None]`
  - `zeitgeist.runner.RunService` — `__init__(settings, *, execute=None)`, `start()`, `shutdown(timeout=5.0)`, `enqueue(request) -> QueuedRun`, `active() -> ActiveRuns`, `stop(run_id) -> bool`, `abort(run_id) -> bool`, `buffer(run_id) -> RunLogBuffer | None`

**`runner.py` must not import from `zeitgeist.api`.** The worker is a pipeline concern the API drives, not the reverse — the same direction that keeps `store.py` free of API imports. That is why `RunRequest` is defined here rather than in `api/schemas.py`.

**The worker owns its `Store`.** `sqlite3` connections are thread-bound, so the API's `Store` and the worker's are separate objects. The worker constructs one when its thread starts and closes it when the thread ends.

**`execute` is the seam tests drive.** The default builds a source and a provider from the run's frozen settings and calls `run_pipeline`. A test injects a callable that blocks on an `Event` instead, which is how the queue's ordering and the stop/abort routing get tested without a real pipeline, a real model, or a sleep.

**Terminal status, which only the worker can decide:**

| What happened | Status written |
| --- | --- |
| `run_pipeline` returned and the token is not stopping | `run_pipeline` already wrote `ok` |
| `run_pipeline` returned and the token *is* stopping | `aborted` |
| `Aborted` propagated | `aborted` |
| Any other exception | `failed`, with a `RunError` naming the exception class and the stage |

`RunStatus` has no separate "stopped", so stop-after-stage and abort share `aborted`. They differ in what was preserved, not in the label.

**Overrides are allowlisted.** `RUN_OVERRIDE_KEYS` is the seven tunables plus `llm_provider`, `llm_model`, `sources` and `topic_count` — what the New run screen offers and what "Re-run config" reposts. Anything else raises `ValueError`, so a request cannot set `db_path`, `output_dir` or `anthropic_api_key` for a run.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_runner.py`:

```python
import threading

import pytest

from tests.run_factory import make_run_config
from zeitgeist.config import Settings
from zeitgeist.progress import Aborted
from zeitgeist.records import Stage
from zeitgeist.runner import RunRequest, RunService
from zeitgeist.store import Store


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        db_path=tmp_path / "z.db",
        output_dir=tmp_path / "output",
    )


class _Gate:
    """A run that blocks until released, so a test can hold the worker in a
    known state without sleeping.

    It opens the run row itself. The real executor reaches `run_pipeline`,
    and `run_pipeline` is what calls `store.start_run`; a fake that skips
    that leaves `run_records` empty, and both `abort_run` and `fail_run` are
    `UPDATE ... WHERE run_id = ?`, so every terminal-status assertion would
    read back `None` no matter what the worker did.
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.run_ids: list[str] = []
        self.raise_on_release: Exception | None = None

    def __call__(self, settings, request, store, observer, token) -> None:
        run_id = request.run_id or ""
        store.start_run(run_id, make_run_config())
        self.run_ids.append(run_id)
        self.entered.set()
        assert self.release.wait(timeout=5)
        if self.raise_on_release is not None:
            raise self.raise_on_release


def _service(tmp_path, execute) -> RunService:
    service = RunService(_settings(tmp_path), execute=execute)
    service.start()
    return service


def test_a_run_starts_immediately_when_the_worker_is_idle(tmp_path):
    """`POST /api/runs` reports position 0 for a run that begins now and a
    positive one for a run that waits, and the New run screen renders a
    "queues it behind" notice off that number. A service always reporting 0
    would hide the queue entirely."""
    gate = _Gate()
    service = _service(tmp_path, gate)
    try:
        queued = service.enqueue(RunRequest())

        assert queued.position == 0
        assert gate.entered.wait(timeout=5)
    finally:
        gate.release.set()
        service.shutdown()


def test_a_second_run_waits_behind_the_first(tmp_path):
    """At most one run executes at a time, which is the whole reason the
    queue exists: two concurrent pipelines would contend on one GPU and
    interleave their log lines into each other's rows."""
    gate = _Gate()
    service = _service(tmp_path, gate)
    try:
        service.enqueue(RunRequest())
        assert gate.entered.wait(timeout=5)

        second = service.enqueue(RunRequest())

        assert second.position == 1
        assert service.active().current is not None
        assert service.active().queued == [second.run_id]
    finally:
        gate.release.set()
        service.shutdown()


def test_queued_runs_execute_in_the_order_they_were_posted(tmp_path):
    """FIFO. A queue drained in any other order would run the user's newest
    request last, which is the opposite of what a queue notice promises."""
    gate = _Gate()
    service = _service(tmp_path, gate)
    try:
        first = service.enqueue(RunRequest())
        assert gate.entered.wait(timeout=5)
        second = service.enqueue(RunRequest())
        third = service.enqueue(RunRequest())
        gate.release.set()
        service.shutdown(timeout=10)
    finally:
        gate.release.set()

    assert gate.run_ids == [first.run_id, second.run_id, third.run_id]


def test_a_completed_run_leaves_the_queue(tmp_path):
    """`GET /api/runs/active` drives the sidebar's in-flight card. A run that
    stayed listed after finishing would pin that card forever."""
    gate = _Gate()
    service = _service(tmp_path, gate)
    gate.release.set()
    service.enqueue(RunRequest())
    service.shutdown(timeout=10)

    assert service.active().current is None
    assert service.active().queued == []


def test_an_aborted_run_is_recorded_as_aborted(tmp_path):
    """Only the worker can tell abort from success: `run_pipeline` lets
    `Aborted` propagate rather than writing a status. Uncaught here, the run
    would keep the `running` row it started with and be reconciled to
    `interrupted` on the next restart — the wrong story entirely."""
    gate = _Gate()
    gate.raise_on_release = Aborted("run aborted")
    service = _service(tmp_path, gate)
    gate.release.set()
    queued = service.enqueue(RunRequest())
    service.shutdown(timeout=10)

    store = Store(_settings(tmp_path).db_path)
    store.init_schema()
    record = store.get_run(queued.run_id)
    store.close()
    assert record is not None
    assert record.status == "aborted"


def test_a_run_that_raises_is_recorded_as_failed_with_its_error(tmp_path):
    """The Runs screen renders "RenderError in generate" from these two
    fields. A worker that caught the exception and wrote a bare `failed`
    would leave the post-mortem block with nothing to show."""
    gate = _Gate()
    gate.raise_on_release = RuntimeError("boom")
    service = _service(tmp_path, gate)
    gate.release.set()
    queued = service.enqueue(RunRequest())
    service.shutdown(timeout=10)

    store = Store(_settings(tmp_path).db_path)
    store.init_schema()
    record = store.get_run(queued.run_id)
    store.close()
    assert record is not None
    assert record.status == "failed"
    assert record.error is not None
    assert record.error.kind == "RuntimeError"


def test_one_run_failing_does_not_stop_the_worker(tmp_path):
    """A worker whose loop exited on the first exception would leave every
    queued run stuck forever, and the only symptom would be a queue that
    never drains — with the traceback already swallowed into a run row."""
    gate = _Gate()
    gate.raise_on_release = RuntimeError("boom")
    service = _service(tmp_path, gate)
    gate.release.set()
    service.enqueue(RunRequest())
    second = service.enqueue(RunRequest())
    service.shutdown(timeout=10)

    assert second.run_id in gate.run_ids


def test_aborting_the_current_run_trips_its_token(tmp_path):
    """The endpoint's only job is to reach the token the worker handed the
    pipeline. A service keeping tokens per request rather than per run would
    return True and cancel nothing."""
    seen: list[bool] = []

    def execute(settings, request, store, observer, token) -> None:
        entered.set()
        assert released.wait(timeout=5)
        seen.append(token.aborted)

    entered = threading.Event()
    released = threading.Event()
    service = RunService(_settings(tmp_path), execute=execute)
    service.start()
    try:
        queued = service.enqueue(RunRequest())
        assert entered.wait(timeout=5)

        assert service.abort(queued.run_id) is True
    finally:
        released.set()
        service.shutdown(timeout=10)

    assert seen == [True]


def test_stopping_the_current_run_trips_stopping_but_not_aborted(tmp_path):
    """Two buttons, two meanings. A stop routed to `abort()` would unwind the
    stage mid-flight and lose the checkpoint the stop button promises to
    write."""
    seen: list[tuple[bool, bool]] = []

    def execute(settings, request, store, observer, token) -> None:
        entered.set()
        assert released.wait(timeout=5)
        seen.append((token.stopping, token.aborted))

    entered = threading.Event()
    released = threading.Event()
    service = RunService(_settings(tmp_path), execute=execute)
    service.start()
    try:
        queued = service.enqueue(RunRequest())
        assert entered.wait(timeout=5)

        assert service.stop(queued.run_id) is True
    finally:
        released.set()
        service.shutdown(timeout=10)

    assert seen == [(True, False)]


def test_a_run_stopped_after_a_stage_is_recorded_as_aborted(tmp_path):
    """`run_pipeline` returns normally on a stop, without writing a terminal
    status: only the worker holds the token and can tell a stop from a clean
    completion. Left unwritten, the run keeps the `running` row it started
    with and the next startup reconciles it to `interrupted` — a crash story
    for a run the user deliberately stopped.

    Distinct from the abort test above, which reaches the `except Aborted`
    branch: this one reaches `if token.stopping`, and deleting that branch
    fails nothing else in the suite.
    """
    entered = threading.Event()
    released = threading.Event()

    def execute(settings, request, store, observer, token) -> None:
        store.start_run(request.run_id or "", make_run_config())
        entered.set()
        assert released.wait(timeout=5)
        # A stop is honoured at a stage boundary: the pipeline returns rather
        # than raising, which is what returning here stands in for.

    service = RunService(_settings(tmp_path), execute=execute)
    service.start()
    queued = service.enqueue(RunRequest())
    assert entered.wait(timeout=5)
    assert service.stop(queued.run_id) is True
    released.set()
    service.shutdown(timeout=10)

    store = Store(_settings(tmp_path).db_path)
    store.init_schema()
    record = store.get_run(queued.run_id)
    store.close()
    assert record is not None
    assert record.status == "aborted"


def test_aborting_an_unknown_run_reports_that_it_did_nothing(tmp_path):
    """The endpoint turns this into a 404. A service returning True for a run
    it has never heard of would tell the user a finished run was aborting."""
    gate = _Gate()
    gate.release.set()
    service = _service(tmp_path, gate)
    try:
        assert service.abort("nope") is False
        assert service.stop("nope") is False
    finally:
        service.shutdown(timeout=10)


def test_a_run_gets_a_log_buffer_for_its_duration(tmp_path):
    """The SSE endpoint reads this buffer. A service that created one per
    request, or returned None while a run was executing, would stream an
    empty log for every run."""
    buffers: list[object] = []

    def execute(settings, request, store, observer, token) -> None:
        buffers.append(service.buffer(request.run_id or ""))
        entered.set()
        assert released.wait(timeout=5)

    entered = threading.Event()
    released = threading.Event()
    service = RunService(_settings(tmp_path), execute=execute)
    service.start()
    try:
        service.enqueue(RunRequest())
        assert entered.wait(timeout=5)
    finally:
        released.set()
        service.shutdown(timeout=10)

    assert buffers and buffers[0] is not None


def test_an_override_outside_the_allowlist_is_refused(tmp_path):
    """`db_path`, `output_dir` and `anthropic_api_key` are not run options.
    A request able to set them could point a run at another database or hand
    it a key, neither of which the New run screen offers."""
    gate = _Gate()
    gate.release.set()
    service = _service(tmp_path, gate)
    try:
        with pytest.raises(ValueError):
            service.enqueue(RunRequest(overrides={"db_path": "/tmp/elsewhere.db"}))
    finally:
        service.shutdown(timeout=10)


def test_an_allowlisted_override_reaches_the_run(tmp_path):
    """The New run screen's config cards are these overrides. Dropped on the
    way through, every run would silently use `.env`'s values and the screen
    would be decorative."""
    seen: list[int] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(settings.topic_count)

    service = RunService(_settings(tmp_path), execute=execute)
    service.start()
    service.enqueue(RunRequest(overrides={"topic_count": "9"}))
    service.shutdown(timeout=10)

    assert seen == [9]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zeitgeist.runner'`

- [ ] **Step 3: Write `zeitgeist/runner.py`**

```python
"""The single worker thread that executes runs, and the queue in front of it.

Imports nothing from `zeitgeist.api`: the worker is a pipeline concern the
API drives, not the reverse — the same direction that keeps `store.py` free
of API imports. `RunRequest` is defined here for that reason rather than in
`api/schemas.py`.
"""

import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from zeitgeist.config import Settings
from zeitgeist.llm.factory import build_provider
from zeitgeist.logcapture import RunLogBuffer, capture_run_log
from zeitgeist.models import STRICT
from zeitgeist.pipeline import new_run_id, run_pipeline
from zeitgeist.progress import Aborted, CancelToken, NullObserver, RunObserver
from zeitgeist.records import RunError, Stage
from zeitgeist.settings_source import WRITABLE_KEYS
from zeitgeist.sources import build_trend_source
from zeitgeist.store import Store

log = logging.getLogger(__name__)

# What the New run screen offers, and what "Re-run config" reposts. Anything
# outside this cannot be set per run: a request able to write `db_path` or
# `anthropic_api_key` would point a run at another database or hand it a key,
# neither of which is a run option.
RUN_OVERRIDE_KEYS = WRITABLE_KEYS | {
    "llm_provider",
    "llm_model",
    "sources",
    "topic_count",
}

SHUTDOWN = object()


class RunRequest(BaseModel):
    """What to run. `run_id` is set only for a resume, which reuses the
    existing run's checkpoints; a new run gets its id from `new_run_id()`.
    """

    model_config = STRICT

    run_id: str | None = None
    start_at: Stage = Stage.INGEST
    template_ids: list[str] | None = None
    overrides: dict[str, str] = {}


class QueuedRun(BaseModel):
    """`position` 0 means executing now; higher means waiting behind that
    many runs, which is what the "queues it behind" notice reads.
    """

    model_config = STRICT

    run_id: str
    position: int


class ActiveRuns(BaseModel):
    model_config = STRICT

    current: str | None
    queued: list[str]


ExecuteFn = Callable[
    [Settings, RunRequest, Store, RunObserver, CancelToken], None
]


def _execute(
    settings: Settings,
    request: RunRequest,
    store: Store,
    observer: RunObserver,
    token: CancelToken,
) -> None:
    """The real run. Injectable so tests can drive the queue without a
    pipeline, a model or a sleep."""
    run_pipeline(
        settings,
        build_trend_source(settings),
        build_provider(settings),
        store,
        request.run_id or new_run_id(),
        start_at=request.start_at,
        template_ids=request.template_ids,
        observer=observer,
        token=token,
    )


class RunService:
    """One worker thread, one FIFO queue, at most one run executing.

    The worker constructs its own `Store` because `sqlite3` connections are
    thread-bound: the API's and the worker's are separate objects.

    The queue is in-memory. A restart loses queued runs, which for a
    single-user local tool is the right trade against persisting a job table.
    """

    def __init__(self, settings: Settings, *, execute: ExecuteFn | None = None) -> None:
        self._settings = settings
        self._execute = execute or _execute
        self._queue: queue.Queue[Any] = queue.Queue()
        self._thread: threading.Thread | None = None
        # Guards the three dicts below, which the request threads read and
        # the worker writes. Short critical sections only — never held across
        # a run.
        self._lock = threading.Lock()
        self._current: str | None = None
        self._waiting: list[str] = []
        self._tokens: dict[str, CancelToken] = {}
        self._buffers: dict[str, RunLogBuffer] = {}

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._work, name="zeitgeist-runner", daemon=True
        )
        self._thread.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        """Drain what is queued, then stop the worker.

        Called from the app's lifespan. Queued runs execute rather than being
        discarded, because a shutdown that dropped them would look identical
        to one that ran them.
        """
        if self._thread is None:
            return
        self._queue.put(SHUTDOWN)
        self._thread.join(timeout=timeout)
        self._thread = None

    def enqueue(self, request: RunRequest) -> QueuedRun:
        unknown = sorted(set(request.overrides) - RUN_OVERRIDE_KEYS)
        if unknown:
            raise ValueError(f"Not settable per run: {', '.join(unknown)}")

        run_id = request.run_id or new_run_id()
        request = request.model_copy(update={"run_id": run_id})
        with self._lock:
            position = (0 if self._current is None else 1) + len(self._waiting)
            if self._current is not None or self._waiting:
                self._waiting.append(run_id)
            self._tokens[run_id] = CancelToken()
        self._queue.put(request)
        return QueuedRun(run_id=run_id, position=position)

    def active(self) -> ActiveRuns:
        with self._lock:
            return ActiveRuns(current=self._current, queued=list(self._waiting))

    def stop(self, run_id: str) -> bool:
        return self._signal(run_id, lambda token: token.stop_after_stage())

    def abort(self, run_id: str) -> bool:
        return self._signal(run_id, lambda token: token.abort())

    def buffer(self, run_id: str) -> RunLogBuffer | None:
        with self._lock:
            return self._buffers.get(run_id)

    def _signal(self, run_id: str, apply: Callable[[CancelToken], None]) -> bool:
        with self._lock:
            token = self._tokens.get(run_id)
        if token is None:
            return False
        apply(token)
        return True

    def _work(self) -> None:
        store = Store(self._settings.db_path)
        store.init_schema()
        try:
            while True:
                item = self._queue.get()
                if item is SHUTDOWN:
                    return
                self._run_one(item, store)
        finally:
            store.close()

    def _run_one(self, request: RunRequest, store: Store) -> None:
        run_id = request.run_id or new_run_id()
        with self._lock:
            self._current = run_id
            if run_id in self._waiting:
                self._waiting.remove(run_id)
            token = self._tokens[run_id]

        try:
            settings = self._settings.model_copy(
                update={
                    key: value for key, value in request.overrides.items()
                }
            )
            with capture_run_log(run_id, store) as buffer:
                with self._lock:
                    self._buffers[run_id] = buffer
                self._execute(settings, request, store, NullObserver(), token)
                if token.stopping:
                    self._aborted(store, run_id)
        except Aborted:
            self._aborted(store, run_id)
        except Exception as exc:  # noqa: BLE001 - one run's failure is a row
            log.exception("Run %s failed", run_id)
            store.fail_run(
                run_id,
                RunError(
                    kind=type(exc).__name__,
                    message=str(exc),
                    stage=request.start_at,
                ),
            )
        finally:
            with self._lock:
                self._current = None
                self._buffers.pop(run_id, None)

    def _aborted(self, store: Store, run_id: str) -> None:
        """Stop and abort share `aborted`: `RunStatus` has no separate
        "stopped", and the two differ in what was preserved rather than in
        the label.

        `Store.abort_run` is idempotent on a run that already reached a
        terminal status, which matters because an abort can land after
        `run_pipeline` has already written `ok`.
        """
        store.abort_run(run_id)
```

**Note `build_trend_source`, not `build_source`.** `zeitgeist/sources/__init__.py` exports both, and `build_source` builds the *dormant* item sources (Lemmy, Wikipedia) that no live pipeline stage consumes — its own comment says so. `build_trend_source` is what `scripts/run_pipeline.py` calls and what the live path needs.

**`model_copy(update=...)` will not do for the overrides.** It bypasses validation entirely, so `"9"` stays the string `"9"` and `topic_count` ends up the wrong type with no error raised anywhere. Build a fresh `Settings` instead, so the overrides arrive as constructor arguments — the highest-precedence layer, which is exactly what a per-run override should be:

```python
            settings = Settings(
                **(self._settings.model_dump() | dict(request.overrides))
            )
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_runner.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`
Expected: all four pass.

- [ ] **Step 6: Commit**

```bash
git add zeitgeist/runner.py tests/test_runner.py
git commit -m "Add the run queue and its worker thread

One thread, one FIFO queue, at most one run executing — which is what the
New run screen's queue notice describes. The worker owns its own Store,
because sqlite3 connections are thread-bound.

Only the worker can tell stop from abort from failure, so it writes the
terminal status. Stop and abort share aborted: RunStatus has no separate
stopped, and the two differ in what was preserved rather than in the label.

Overrides are allowlisted to what the New run screen offers, so a request
cannot point a run at another database or hand it an API key.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: `POST /api/runs` and `GET /api/runs/active`

**Files:**
- Create: `zeitgeist/api/control.py`, `tests/test_api_control.py`
- Modify: `zeitgeist/api/app.py`, `zeitgeist/api/schemas.py`, `tests/api_factory.py`

**Interfaces:**
- Consumes: `RunService`, `RunRequest`, `QueuedRun`, `ActiveRuns` from Task 8.
- Produces:
  - `zeitgeist.api.app.get_runner(request) -> RunService` — the dependency, beside `get_store` and `get_settings`
  - `zeitgeist.api.schemas.StartRunBody` — `template_ids: list[str] | None = None`, `overrides: dict[str, str] = {}`
  - `zeitgeist.api.control.router` — mounted in `create_app`
  - `tests.api_factory.seeded_client(tmp_path, *, runs=(), execute=None)` — a new keyword-only argument threading a fake executor into the app's `RunService`

**`create_app` owns the service's lifecycle.** It constructs the `RunService` and puts it on `app.state.runner`; the lifespan calls `start()` on entry and `shutdown()` on exit. **The thread starts in the lifespan, not in `create_app`** — unlike the store, which `create_app` opens because two of `test_api_app.py`'s tests build no client. A thread started at construction would outlive every test that builds an app and never enters it, and the suite would accumulate one live worker per such test.

**Why `overrides` is `dict[str, str]`.** The values arrive from a form as strings and are validated by `Settings` when the worker builds the run's config, which is the one place that knows each field's real type. Typing it `dict[str, Any]` would move that validation nowhere useful and let a JSON number through unchecked.

- [ ] **Step 1: Add the dependency and the lifecycle**

In `zeitgeist/api/app.py`, beside `get_store`:

```python
def get_runner(request: Request) -> RunService:
    return request.app.state.runner
```

In `create_app`, after the store is opened and reconciled:

```python
    runner = RunService(settings, execute=execute)
```

and inside the lifespan, replacing the current body:

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # The worker thread starts here rather than in `create_app`, unlike
        # the store: an app that is built and never entered — which two tests
        # in test_api_app.py do deliberately — must not leave a live thread
        # behind.
        runner.start()
        try:
            yield
        finally:
            runner.shutdown()
            store.close()
```

Then set `app.state.runner = runner` beside the other two, and mount the new router at the end alongside the existing four.

To let tests inject a fake executor, give `create_app` one keyword-only argument:

```python
def create_app(settings: Settings, *, execute: ExecuteFn | None = None) -> FastAPI:
```

and pass it straight through where the service is constructed, as shown above. Production calls `create_app(settings)` with one argument as before, and `execute=None` makes `RunService` use the real pipeline.

- [ ] **Step 2: Thread it through the test factory**

In `tests/api_factory.py`, add the same keyword-only argument to `seeded_client` and pass it to `create_app`. **Do not change the existing positional parameters** — every API test module calls `seeded_client(tmp_path)` or `seeded_client(tmp_path, runs=[...])`, and those call sites must keep working untouched.

Also add two executor doubles beside `SeededRun`. Both open the run row, and that is the point: the real executor reaches `run_pipeline`, and `run_pipeline` is what calls `store.start_run`. A double that skipped it would leave `run_records` empty, so every endpoint guarded by `_run_or_404` — the event stream among them — would answer 404 for a run that is executing, and every terminal-status assertion in `test_runner.py` would read back `None`.

`tests/api_factory.py` needs `import logging`, `import threading`, `field` added to its `dataclasses` import, and `make_run_config` added to its `tests.run_factory` import.

```python
@dataclass
class GatedExecute:
    """A run that blocks until released, so a test can hold the worker in a
    known state without sleeping. Lives here rather than in one test module
    because both the control tests and the SSE tests need it.

    It opens the run row, because the real executor reaches `run_pipeline`
    and `run_pipeline` is what calls `store.start_run`. Without that, every
    endpoint guarded by `_run_or_404` — the event stream among them —
    answers 404 for a run that is executing.
    """

    entered: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    run_ids: list[str] = field(default_factory=list)

    def __call__(self, settings, request, store, observer, token) -> None:
        run_id = request.run_id or ""
        store.start_run(run_id, make_run_config())
        self.run_ids.append(run_id)
        self.entered.set()
        self.release.wait(timeout=5)


@dataclass
class LoggingGate:
    """A run that opens its row, logs one line, then blocks until released.

    The line has to be emitted while the run is still executing, because the
    worker drops the buffer the moment it ends — so a stream opened after the
    run finished can never carry it.
    """

    message: str = "hello from the run"
    entered: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)

    def __call__(self, settings, request, store, observer, token) -> None:
        store.start_run(request.run_id or "", make_run_config())
        logging.getLogger("zeitgeist.testing.sse").info(self.message)
        self.entered.set()
        self.release.wait(timeout=5)
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_api_control.py`:

```python
from tests.api_factory import GatedExecute, seeded_client


def test_posting_a_run_returns_the_id_it_will_have(tmp_path):
    """The New run screen navigates straight to the run's detail page. A
    response without the id would leave it with nowhere to go, and polling
    the runs list for "the newest one" races a second tab.
    """
    gate = GatedExecute()
    gate.release.set()
    client = seeded_client(tmp_path, execute=gate)

    response = client.post("/api/runs", json={})

    assert response.status_code == 202
    assert response.json()["run_id"]


def test_a_run_started_immediately_reports_position_zero(tmp_path):
    """The screen shows a "queues it behind N" notice only when the number is
    positive. A response that always reported a position would show that
    notice for a run starting right now."""
    gate = GatedExecute()
    client = seeded_client(tmp_path, execute=gate)
    try:
        body = client.post("/api/runs", json={}).json()

        assert body["position"] == 0
    finally:
        gate.release.set()


def test_a_second_run_reports_the_queue_it_is_behind(tmp_path):
    """This number is the notice. Reporting 0 for a queued run would promise
    the user it had started when it had not."""
    gate = GatedExecute()
    client = seeded_client(tmp_path, execute=gate)
    try:
        client.post("/api/runs", json={})
        assert gate.entered.wait(timeout=5)

        body = client.post("/api/runs", json={}).json()

        assert body["position"] == 1
    finally:
        gate.release.set()


def test_the_active_endpoint_reports_the_running_run_and_the_queue(tmp_path):
    """The sidebar's in-flight card polls this. An endpoint reporting only
    the current run would leave a queued one invisible until it started."""
    gate = GatedExecute()
    client = seeded_client(tmp_path, execute=gate)
    try:
        first = client.post("/api/runs", json={}).json()
        assert gate.entered.wait(timeout=5)
        second = client.post("/api/runs", json={}).json()

        body = client.get("/api/runs/active").json()

        assert body["current"] == first["run_id"]
        assert body["queued"] == [second["run_id"]]
    finally:
        gate.release.set()


def test_the_active_endpoint_reports_nothing_when_idle(tmp_path):
    """The common case, and the one that decides whether the card renders at
    all. An endpoint 404ing or erroring when idle would break every poll on a
    quiet server."""
    client = seeded_client(tmp_path)

    body = client.get("/api/runs/active").json()

    assert body["current"] is None
    assert body["queued"] == []


def test_overrides_reach_the_run(tmp_path):
    """The four config cards on the New run screen are these overrides.
    Dropped in the router, every run would use `.env` and the cards would be
    decorative."""
    seen: list[int] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(settings.topic_count)

    client = seeded_client(tmp_path, execute=execute)

    client.post("/api/runs", json={"overrides": {"topic_count": "9"}})
    client.app.state.runner.shutdown(timeout=10)

    assert seen == [9]


def test_a_posted_template_selection_reaches_the_run(tmp_path):
    """The New run screen's template picker is this field. Dropped in the
    router, every run would render against the whole library and the picker
    would be decorative — and the resume endpoint's own test would not
    notice, because that is a different call site with its own body model.
    """
    seen: list[list[str] | None] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(request.template_ids)

    client = seeded_client(tmp_path, execute=execute)

    client.post("/api/runs", json={"template_ids": ["drake"]})
    client.app.state.runner.shutdown(timeout=10)

    assert seen == [["drake"]]


def test_an_override_outside_the_allowlist_is_a_400(tmp_path):
    """`db_path` and `anthropic_api_key` are not run options. The service
    raises ValueError; a router that let it escape would return 500 and tell
    the user the server was broken rather than the request."""
    client = seeded_client(tmp_path)

    response = client.post(
        "/api/runs", json={"overrides": {"db_path": "/tmp/elsewhere.db"}}
    )

    assert response.status_code == 400


def test_the_api_key_is_not_accepted_as_an_override(tmp_path):
    """Named separately from the test above because this one is the reason
    the allowlist exists at all: a request able to set it would put a secret
    into a run's frozen config."""
    client = seeded_client(tmp_path)

    response = client.post(
        "/api/runs", json={"overrides": {"anthropic_api_key": "sk-ant-nope"}}
    )

    assert response.status_code == 400
```

- [ ] **Step 4: Run to verify they fail**

Run: `uv run pytest tests/test_api_control.py -v`
Expected: FAIL with 404s — the router does not exist.

- [ ] **Step 5: Write the router**

Create `zeitgeist/api/control.py`:

```python
"""Starting, watching and stopping runs.

Split from `runs.py`, which is five endpoints of read-only history: these
mutate execution, fail differently, and phase 4 adds two more of its own.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from zeitgeist.api.app import get_runner
from zeitgeist.api.schemas import StartRunBody
from zeitgeist.runner import ActiveRuns, QueuedRun, RunRequest, RunService

router = APIRouter(prefix="/api/runs", tags=["control"])


@router.post("", response_model=QueuedRun, status_code=status.HTTP_202_ACCEPTED)
def start_run(
    body: StartRunBody, runner: RunService = Depends(get_runner)
) -> QueuedRun:
    """202 rather than 201: the run is queued, and for a queued one there is
    nothing at its URL yet."""
    try:
        return runner.enqueue(
            RunRequest(
                template_ids=body.template_ids,
                overrides=body.overrides,
            )
        )
    except ValueError as exc:
        # The allowlist refused a field. That is the request's fault, not the
        # server's, and letting it escape as a 500 would say the opposite.
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/active", response_model=ActiveRuns)
def read_active(runner: RunService = Depends(get_runner)) -> ActiveRuns:
    return runner.active()
```

**Mount `control.router` before `runs.router` in `create_app`.** `runs.py` owns `GET /api/runs/{run_id}`, and `/api/runs/active` would otherwise be captured by that path parameter and 404 as an unknown run. Add a comment saying so at the mount site, because the ordering is load-bearing and invisible.

Add to `zeitgeist/api/schemas.py`:

```python
class StartRunBody(BaseModel):
    """What `POST /api/runs` accepts.

    `overrides` is `str`-valued because the values come from a form and are
    validated by `Settings` when the worker freezes the run's config — the
    one place that knows each field's real type.
    """

    model_config = STRICT

    template_ids: list[str] | None = None
    overrides: dict[str, str] = {}
```

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/test_api_control.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 7: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`
Expected: all four pass. Every pre-existing API test must still pass — `seeded_client` gained an argument but kept its existing ones.

- [ ] **Step 8: Commit**

```bash
git add zeitgeist/api/control.py zeitgeist/api/app.py zeitgeist/api/schemas.py tests/
git commit -m "Serve starting a run, and what is running now

202 rather than 201: the run is queued, and a queued run has nothing at its
URL yet. The position is the queue notice the New run screen renders.

control.router mounts before runs.router, because /api/runs/{run_id} would
otherwise capture /api/runs/active and 404 it as an unknown run.

The worker thread starts in the lifespan rather than in create_app, so an
app that is built and never entered leaves no thread behind.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Resume, stop and abort

**Files:**
- Modify: `zeitgeist/api/control.py`, `zeitgeist/api/schemas.py`, `tests/run_factory.py`, `tests/test_api_control.py`

**Interfaces:**
- Consumes: `RunService.stop`, `.abort`, `.enqueue`; `resume_stage` from `zeitgeist/api/runs.py` (phase 2).
- Produces:
  - `zeitgeist.api.schemas.ResumeBody` — `stage: Stage | None = None`, `template_ids: list[str] | None = None`
  - `tests.run_factory.make_evidence(source_ids, *, name="A trend", replies=(), status="trending") -> TrendEvidence`
  - `POST /api/runs/{run_id}/resume`, `POST /api/runs/{run_id}/stop`, `POST /api/runs/{run_id}/abort`

**`template_ids` on resume is the tuning loop.** The loop this replaces is `--resume-from generate --templates drake`: edit a prompt or a manifest, re-render the same frozen topics, look at the output. The design's "Resume from &lt;stage&gt;" button takes no options, so without this there is no way to resume with the template library narrowed — which is exactly the loop.

**`stage` defaults to the computed one.** Phase 2's `resume_stage(store, run_id)` already works out the first stage with no checkpoint; a resume that names no stage uses it. A resume naming a stage the run cannot honour — one whose prior checkpoints are missing — is a 409, not a 500.

**Stop and abort are 404 when the run is not executing.** `RunService.stop` and `.abort` return `False` for a run it has never heard of or has already finished, and a router reporting success for those would tell the user a finished run was aborting.

- [ ] **Step 1: Add an evidence factory**

`test_resuming_without_a_stage_uses_the_computed_one` needs a run whose INGEST checkpoint exists, and `seed_run` writes one only when `SeededRun.evidence` is non-empty. Three test modules already hand-roll a `TrendEvidence` builder; this is the fourth caller, which is what `run_factory` is for.

Add to `tests/run_factory.py`:

```python
def make_evidence(
    source_ids: list[str],
    *,
    name: str = "A trend",
    replies: Sequence[Reply] = (),
    status: TrendStatus = "trending",
) -> TrendEvidence:
    """One trend's evidence, for tests that need an ingest checkpoint.

    `source_ids` are the post ids the topic's `item_ids` will match against,
    which is what makes a seeded run's topic detail able to find its replies.
    """
    return TrendEvidence(
        trend=TrendInfo(
            topic_id=f"id-{name}",
            display_name=name,
            description="Something happened.",
            category="news",
            post_count=len(source_ids),
            started_at=FIXED_NOW,
            status=status,
        ),
        posts=[
            PostEvidence(
                item=Item(
                    source_id=source_id,
                    title="a post",
                    permalink=f"https://bsky.app/profile/x/post/{source_id}",
                    fetched_at=FIXED_NOW,
                    metrics=BlueskyMetrics(
                        like_count=1,
                        reply_count=len(replies),
                        repost_count=0,
                        trend=name,
                        status=status,
                        created_at=FIXED_NOW,
                    ),
                ),
                replies=list(replies),
            )
            for source_id in source_ids
        ],
    )
```

`FIXED_NOW` is whatever fixed datetime the module already uses for its other builders — read it and reuse it rather than adding a second. A fixture dated relative to `now` would make any comparison against the current time pass or fail depending on the hour the suite runs. Extend the module's existing import block with `BlueskyMetrics`, `Item`, `PostEvidence`, `Reply`, `TrendEvidence` and `TrendInfo` from `zeitgeist.models`, and `Sequence` from `collections.abc`.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_api_control.py`. It already imports `GatedExecute` and `seeded_client`; extend that block rather than adding a second `from tests.api_factory import ...` line, or isort's `I001` will fire.

```python
import threading

from tests.api_factory import GatedExecute, SeededRun, seeded_client
from tests.run_factory import make_evidence, make_run_config
from zeitgeist.records import Stage


def test_resuming_reuses_the_runs_existing_id(tmp_path):
    """Resume continues a run rather than starting a new one — its
    checkpoints are the whole point. A resume that allocated a fresh id would
    write a second run's rows and leave the first stranded at `interrupted`
    forever.
    """
    seen: list[str] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(request.run_id or "")

    client = seeded_client(
        tmp_path,
        runs=[SeededRun(run_id="20260901T120000Z")],
        execute=execute,
    )

    response = client.post(
        "/api/runs/20260901T120000Z/resume", json={"stage": "generate"}
    )
    client.app.state.runner.shutdown(timeout=10)

    assert response.status_code == 202
    assert seen == ["20260901T120000Z"]


def test_resuming_without_a_stage_uses_the_computed_one(tmp_path):
    """The button posts no stage. A router requiring one would make the
    button unusable, and defaulting to `ingest` would silently redo the
    minutes of fetching that the run's checkpoints already hold.

    The run is seeded with its ingest evidence as well as its topics, so
    INGEST and ANALYSE are written and EVALUATE is not — making the computed
    stage EVALUATE rather than either end of `ORDER`, so a router hardcoding
    one fails here. The default `SeededRun` will not do: with no evidence it
    writes no INGEST checkpoint, `resume_stage` returns `None`, and the
    endpoint 409s before the default is ever consulted.
    """
    seen: list[Stage] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(request.start_at)

    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id="20260901T120000Z",
                evidence=[make_evidence(["p1"])],
            )
        ],
        execute=execute,
    )

    client.post("/api/runs/20260901T120000Z/resume", json={})
    client.app.state.runner.shutdown(timeout=10)

    assert seen == [Stage.EVALUATE]


def test_resuming_carries_the_narrowed_template_library(tmp_path):
    """This is the tuning loop the design's button cannot otherwise express:
    edit a manifest, re-render the same frozen topics against one template.
    Dropped here, resume would re-render against the whole library every
    time and the loop would be no faster than a fresh run.
    """
    seen: list[list[str] | None] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(request.template_ids)

    client = seeded_client(
        tmp_path,
        runs=[SeededRun(run_id="20260901T120000Z")],
        execute=execute,
    )

    client.post(
        "/api/runs/20260901T120000Z/resume",
        json={"stage": "generate", "template_ids": ["drake"]},
    )
    client.app.state.runner.shutdown(timeout=10)

    assert seen == [["drake"]]


def test_resuming_an_unknown_run_is_a_404(tmp_path):
    client = seeded_client(tmp_path)

    response = client.post("/api/runs/nope/resume", json={})

    assert response.status_code == 404


def test_resuming_a_run_with_no_checkpoints_is_refused(tmp_path):
    """A source outage writes nothing, so there is nothing to resume from —
    phase 2's `resume_stage` returns `None` for exactly this. Enqueuing it
    anyway would start a run that fails on its first checkpoint read, and the
    user would see a second failure rather than a refusal.
    """
    client = seeded_client(
        tmp_path,
        runs=[SeededRun(run_id="20260901T120000Z", topics=[], status="failed")],
    )

    response = client.post("/api/runs/20260901T120000Z/resume", json={})

    assert response.status_code == 409


def test_stop_trips_stopping_and_abort_trips_aborted(tmp_path):
    """Two buttons, two meanings, and 202 from both. A stop wired to
    `runner.abort` would answer 202 exactly as it does now while unwinding
    the stage mid-flight and losing the checkpoint the stop button promises —
    so what gets asserted is the token the worker handed the run, not the
    status code. Task 8 pins this at the service; nothing else pins it at the
    seam the button actually goes through.
    """
    flags: dict[str, tuple[bool, bool]] = {}
    entered = threading.Event()
    released = threading.Event()

    def execute(settings, request, store, observer, token) -> None:
        run_id = request.run_id or ""
        store.start_run(run_id, make_run_config())
        entered.set()
        assert released.wait(timeout=5)
        flags[run_id] = (token.stopping, token.aborted)

    client = seeded_client(tmp_path, execute=execute)

    stopped = client.post("/api/runs", json={}).json()
    assert entered.wait(timeout=5)
    assert client.post(f"/api/runs/{stopped['run_id']}/stop").status_code == 202
    released.set()
    client.app.state.runner.shutdown(timeout=10)

    entered.clear()
    released.clear()
    client.app.state.runner.start()
    aborted = client.post("/api/runs", json={}).json()
    assert entered.wait(timeout=5)
    assert client.post(f"/api/runs/{aborted['run_id']}/abort").status_code == 202
    released.set()
    client.app.state.runner.shutdown(timeout=10)

    assert flags[stopped["run_id"]] == (True, False)
    assert flags[aborted["run_id"]] == (True, True)


def test_stopping_a_run_that_is_not_executing_is_a_404(tmp_path):
    """The inline abort confirmation is drawn from a poll that can be a
    moment stale. Reporting success for a run that already finished would
    leave the UI showing "aborting…" for a run that is done.
    """
    client = seeded_client(tmp_path, runs=[SeededRun(run_id="20260901T120000Z")])

    assert client.post("/api/runs/20260901T120000Z/stop").status_code == 404
    assert client.post("/api/runs/20260901T120000Z/abort").status_code == 404
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_api_control.py -k "resum or stop or abort" -v`
Expected: FAIL with 404s.

- [ ] **Step 4: Write the endpoints**

Add to `zeitgeist/api/control.py`:

```python
@router.post(
    "/{run_id}/resume",
    response_model=QueuedRun,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume_run(
    run_id: str,
    body: ResumeBody,
    store: Store = Depends(get_store),
    runner: RunService = Depends(get_runner),
) -> QueuedRun:
    _run_or_404(store, run_id)
    stage = body.stage or resume_stage(store, run_id)
    if stage is None:
        # `resume_stage` returns None when nothing was written at all, which
        # is what a source outage looks like. Enqueuing anyway would start a
        # run that fails on its first checkpoint read, and the user would see
        # a second failure instead of a refusal.
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id} wrote no checkpoints; there is nothing to "
            "resume from.",
        )
    return runner.enqueue(
        RunRequest(
            run_id=run_id,
            start_at=stage,
            template_ids=body.template_ids,
        )
    )


@router.post("/{run_id}/stop", status_code=status.HTTP_202_ACCEPTED)
def stop_run(run_id: str, runner: RunService = Depends(get_runner)) -> dict[str, str]:
    """Finish the current stage, write its checkpoint, then end. The run
    stays resumable, which is what the button promises."""
    if not runner.stop(run_id):
        raise HTTPException(status_code=404, detail=f"Run {run_id} is not running")
    return {"run_id": run_id, "requested": "stop"}


@router.post("/{run_id}/abort", status_code=status.HTTP_202_ACCEPTED)
def abort_run(run_id: str, runner: RunService = Depends(get_runner)) -> dict[str, str]:
    """End now. Ingest is the exception: `fetch_evidence` is one opaque
    `asyncio.run()` with no interior checkpoint, so an abort during it takes
    effect when the fetch returns — which is what the UI's "aborting…" state
    is for."""
    if not runner.abort(run_id):
        raise HTTPException(status_code=404, detail=f"Run {run_id} is not running")
    return {"run_id": run_id, "requested": "abort"}
```

Import `_run_or_404` and `resume_stage` from `zeitgeist.api.runs`, and `get_store` from `zeitgeist.api.app`.

Add to `zeitgeist/api/schemas.py`:

```python
class ResumeBody(BaseModel):
    """`stage` omitted means the computed resume point — the button posts no
    stage. `template_ids` narrows the library for this resume only, which is
    the tuning loop: edit a manifest, re-render the same frozen topics.
    """

    model_config = STRICT

    stage: Stage | None = None
    template_ids: list[str] | None = None
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/test_api_control.py -v`
Expected: PASS, 16 tests.

- [ ] **Step 6: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`
Expected: all four pass.

- [ ] **Step 7: Commit**

```bash
git add zeitgeist/api/control.py zeitgeist/api/schemas.py tests/run_factory.py tests/test_api_control.py
git commit -m "Serve resume, stop and abort

Resume reuses the run's id and its checkpoints, and defaults to the stage
phase 2 already computes. Its optional template_ids is the tuning loop the
design's button cannot otherwise express: edit a manifest, re-render the
same frozen topics against one template.

A run that wrote no checkpoints is a 409 rather than a queued run that will
fail on its first read.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: `GET /api/runs/{id}/events` — the SSE stream

**Files:**
- Modify: `zeitgeist/api/control.py`, `tests/test_api_control.py`

**Interfaces:**
- Consumes: `RunService.buffer(run_id)` and `RunLogBuffer.since(seq)`. The generator tracks its own cursor from the last line it sent, which is why `RunLogBuffer` needs no `latest_seq`.
- Produces: `GET /api/runs/{run_id}/events` — `text/event-stream`, emitting `log` and `tick` events

**The shape of the stream.** Two event types. A `log` event carries one batch of new lines as JSON. A `tick` carries nothing but a sequence number and tells the client to invalidate its queries — the observer has already written `run_records`, `run_stages` and `run_topics` from the worker thread, so the client refetches rather than being handed the data twice.

**Polling, not pushing.** The generator does `await asyncio.sleep(POLL_SECONDS)` between drains of the buffer. A quarter-second of latency on a log line is invisible, and this keeps the logging handler free of any reference to the event loop — which is what lets the same handler work under `TestClient` and under the dev harness. **Do not replace this with `loop.call_soon_threadsafe` into an `asyncio.Queue`.**

**The stream must end.** When the run is no longer executing and the buffer has been drained, the generator returns. A stream that never closed would hold a connection per watched run for the life of the process, and `TestClient` would block forever reading it.

**Testing SSE under `TestClient`.** Use `client.stream("GET", url)` and read `response.iter_lines()` with a bound on how many lines you consume, so a generator that fails to terminate fails the test rather than hanging it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api_control.py`:

**A note on how these are written, because the obvious version does not work.** The worker drops a run's buffer when the run ends, so a stream opened *after* the run finished can never carry its log lines — the historical endpoint serves those. Any test asserting on streamed lines therefore has to hold the run open while it reads, and release it from inside the read loop. That is what `LoggingGate` and the `release_after` argument below are for.

```python
import json

from tests.api_factory import LoggingGate, SeededRun, seeded_client
from zeitgeist.records import LogLine


def _events(client, url, *, release_after=None, limit=400):
    """Read an SSE response into (event, data) pairs until it closes.

    `release_after` is called once, after the first batch of events has been
    read, to let a gated run finish — otherwise the stream would stay open
    for as long as the run does and this would never return.

    Bounded, so a generator that fails to terminate fails the test in a few
    seconds rather than hanging it. Do not raise the bound to make a test
    pass; a stream that will not close is the bug.
    """
    collected: list[tuple[str, str]] = []
    released = False
    with client.stream("GET", url) as response:
        assert response.status_code == 200
        name = ""
        for index, line in enumerate(response.iter_lines()):
            if index > limit:
                raise AssertionError("stream did not end")
            if line.startswith("event:"):
                name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                collected.append((name, line.removeprefix("data:").strip()))
                if release_after is not None and not released:
                    released = True
                    release_after()
    return collected


def _logged(events):
    return [
        line["message"]
        for name, data in events
        if name == "log"
        for line in json.loads(data)
    ]


def test_the_stream_carries_the_runs_log_lines(tmp_path):
    """The live log is the reason this endpoint exists. A stream emitting
    only ticks would leave the client polling the historical log endpoint it
    was built to replace.
    """
    gate = LoggingGate()
    client = seeded_client(tmp_path, execute=gate)
    body = client.post("/api/runs", json={}).json()
    assert gate.entered.wait(timeout=5)

    events = _events(
        client,
        f"/api/runs/{body['run_id']}/events",
        release_after=gate.release.set,
    )

    assert "hello from the run" in _logged(events)


def test_the_stream_ends_when_the_run_ends(tmp_path):
    """A stream that never closed would hold one connection per watched run
    for the life of the process — and because the browser reconnects on
    close, one that stayed open after the run finished would never let it
    stop watching either.

    The bound inside `_events` is what turns "never closes" into a failure;
    reaching this assertion at all is the result.
    """
    gate = LoggingGate()
    client = seeded_client(tmp_path, execute=gate)
    body = client.post("/api/runs", json={}).json()
    assert gate.entered.wait(timeout=5)

    events = _events(
        client,
        f"/api/runs/{body['run_id']}/events",
        release_after=gate.release.set,
    )

    assert events


def test_a_line_is_sent_once(tmp_path):
    """The generator polls with the last seq it sent. Draining from 0 each
    time would resend the whole log on every tick, and the browser would
    render the run's output over and over for the life of the run.
    """
    gate = LoggingGate(message="only once")
    client = seeded_client(tmp_path, execute=gate)
    body = client.post("/api/runs", json={}).json()
    assert gate.entered.wait(timeout=5)

    events = _events(
        client,
        f"/api/runs/{body['run_id']}/events",
        release_after=gate.release.set,
    )

    assert _logged(events).count("only once") == 1


def test_every_poll_emits_a_tick_the_client_can_invalidate_on(tmp_path):
    """A tick carries no data of its own: the observer has already written
    `run_records`, `run_stages` and `run_topics` from the worker thread, and
    the tick is what tells the client to refetch them. Without it the stream
    would deliver log lines and nothing else, and the stage cards would never
    advance until the page was reloaded — which no other test here would
    notice, because they all filter for `log`.
    """
    client = seeded_client(tmp_path, runs=[SeededRun(run_id="20260901T120000Z")])

    events = _events(client, "/api/runs/20260901T120000Z/events")

    ticks = [json.loads(data) for name, data in events if name == "tick"]
    assert ticks
    assert all(set(tick) == {"seq"} for tick in ticks)


def test_a_streamed_line_carries_everything_the_log_viewer_renders(tmp_path):
    """The viewer colours by level, groups by logger and orders by seq, and
    the historical endpoint returns all five fields. A stream sending only
    the message would make the live log and the post-mortem log two different
    things, and the verbose toggle would have nothing to filter on until the
    run ended.
    """
    gate = LoggingGate()
    client = seeded_client(tmp_path, execute=gate)
    body = client.post("/api/runs", json={}).json()
    assert gate.entered.wait(timeout=5)

    events = _events(
        client,
        f"/api/runs/{body['run_id']}/events",
        release_after=gate.release.set,
    )

    lines = [
        line for name, data in events if name == "log" for line in json.loads(data)
    ]
    [line] = [line for line in lines if line["message"] == gate.message]
    # Parity with `LogLine` rather than a literal key set: the invariant is
    # that the live stream and the historical endpoint carry the same fields,
    # so adding one to both should keep this passing and adding it to only
    # one should not. A hardcoded set would fire on the former, which is a
    # decision rather than a bug.
    assert set(line) == set(LogLine.model_fields)
    assert line["level"] == "INFO"
    assert line["logger"] == "zeitgeist.testing.sse"


def test_streaming_an_unknown_run_is_a_404(tmp_path):
    """The client opens this from a run detail page. A stream that opened
    for any id would leave a mistyped URL hanging rather than erroring."""
    client = seeded_client(tmp_path)

    response = client.get("/api/runs/nope/events")

    assert response.status_code == 404


def test_streaming_a_finished_run_ends_immediately(tmp_path):
    """A completed run has no buffer — the worker drops it when the run ends,
    and the historical log endpoint serves it instead. This must close rather
    than wait forever for a run that will never emit anything, which is the
    case a client hitting an old run's detail page produces.

    No `release_after` here: there is nothing holding this stream open, and
    needing one would mean the terminating condition was wrong.
    """
    client = seeded_client(tmp_path, runs=[SeededRun(run_id="20260901T120000Z")])

    events = _events(client, "/api/runs/20260901T120000Z/events")

    assert _logged(events) == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_api_control.py -k stream -v`
Expected: FAIL with 404s.

- [ ] **Step 3: Write the endpoint**

Add to `zeitgeist/api/control.py`:

```python
import asyncio
import json
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse

POLL_SECONDS = 0.25


def _sse(name: str, data: str) -> str:
    return f"event: {name}\ndata: {data}\n\n"


@router.get("/{run_id}/events")
def stream_events(
    run_id: str,
    store: Store = Depends(get_store),
    runner: RunService = Depends(get_runner),
) -> StreamingResponse:
    """Log lines and progress ticks, until the run ends.

    Polls the run's buffer rather than being pushed to. A quarter-second of
    latency on a log line is invisible, and polling keeps the logging handler
    free of any reference to the event loop — which is what lets the same
    handler work under `TestClient` and under the dev harness.

    A tick carries no payload. The observer has already written
    `run_records`, `run_stages` and `run_topics` from the worker thread, so
    the client refetches rather than being handed the same data twice.
    """
    _run_or_404(store, run_id)

    async def generate() -> AsyncIterator[str]:
        seq = 0
        while True:
            buffer = runner.buffer(run_id)
            executing = runner.active().current == run_id
            if buffer is not None:
                lines = buffer.since(seq)
                if lines:
                    seq = lines[-1].seq
                    yield _sse(
                        "log",
                        json.dumps(
                            [
                                {
                                    "seq": line.seq,
                                    "logged_at": line.logged_at.isoformat(),
                                    "level": line.level,
                                    "logger": line.logger,
                                    "message": line.message,
                                }
                                for line in lines
                            ]
                        ),
                    )
            yield _sse("tick", json.dumps({"seq": seq}))
            if not executing and buffer is None:
                # The worker drops the buffer when the run ends, so this is
                # the run being over *and* its last lines already drained.
                # A stream that stayed open would hold a connection per
                # watched run for the life of the process.
                return
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(generate(), media_type="text/event-stream")
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_api_control.py -v`
Expected: PASS, 23 tests.

If a stream test hangs rather than failing, the terminating condition is wrong — fix the generator, **not** the test's bound. The bound is what turns a hang into a failure, and removing it would make this suite hang on CI instead.

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`
Expected: all four pass.

- [ ] **Step 6: Commit**

```bash
git add zeitgeist/api/control.py tests/test_api_control.py
git commit -m "Stream a run's log lines and progress ticks

Polls the run's ring buffer rather than being pushed to: a quarter-second
of latency on a log line is invisible, and polling keeps the logging
handler free of any reference to the event loop, which is what lets the
same handler work under TestClient and under the dev harness.

A tick carries no payload — the observer has already written the rows, so
the client invalidates and refetches rather than being handed them twice.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: The model registry and `GET /api/config/options`

**Files:**
- Create: `zeitgeist/llm/registry.py`, `zeitgeist/api/options.py`, `tests/test_llm_registry.py`, `tests/test_api_options.py`
- Modify: `zeitgeist/api/app.py`, `zeitgeist/api/schemas.py`

**Interfaces:**
- Produces:
  - `zeitgeist.llm.registry.ANTHROPIC_MODELS: tuple[str, ...]`
  - `zeitgeist.llm.registry.ollama_models(host: str, client: Any = None, timeout: float = 2.0) -> list[str]`
  - `zeitgeist.llm.registry.available_models(settings, client=None) -> dict[str, list[str]]`
  - `zeitgeist.api.schemas.PlatformOption`, `TemplateOption`, `ConfigOptions`
  - `zeitgeist.api.options.router`

**Why this is not a method on `LLMProvider`.** That Protocol's docstring says keeping it to one method is what makes the local-versus-cloud comparison honest — swapping backends changes one config value and nothing else. Model discovery is a configuration concern, not a per-call one, and adding a second method would force every implementation and every test double to grow one.

**Anthropic's list is static; Ollama's is queried.** Anthropic publishes no list endpoint the app can practically use and its models change rarely, so a constant is honest. Ollama's `/api/tags` reports what has actually been pulled locally, so a model the user pulled appears in the dropdown without a code change — which is the difference between a usable local setup and one that needs a Python edit per model.

**A failed Ollama query returns an empty list, never raises.** The settings screen must render when Ollama is not running; a 500 there would make the whole screen unreachable because a local daemon happened to be down.

**`ANTHROPIC_API_KEY` is reported as a boolean and never returned.**

- [ ] **Step 1: Write the failing registry tests**

Create `tests/test_llm_registry.py`:

```python
from typing import Any

import httpx
import pytest

from zeitgeist.config import Settings
from zeitgeist.llm.registry import available_models, ollama_models


class _FakeClient:
    """Stands in for `httpx.Client`. The suite is hermetic: no test here may
    reach a real Ollama, and a test that did would pass or fail according to
    whether the developer happened to have one running."""

    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error
        self.urls: list[str] = []

    def get(self, url: str, timeout: float | None = None) -> Any:
        self.urls.append(url)
        if self._error is not None:
            raise self._error
        return httpx.Response(200, json=self._payload)


def test_ollama_models_are_read_from_what_is_installed():
    """The point of querying rather than hardcoding: a model the user pulled
    must appear without a code change. A static list would leave the dropdown
    permanently wrong for anyone running local models."""
    client = _FakeClient({"models": [{"name": "qwen3.5"}, {"name": "llama3"}]})

    assert ollama_models("http://localhost:11434", client=client) == [
        "qwen3.5",
        "llama3",
    ]


def test_ollama_being_down_yields_no_models_rather_than_an_error():
    """The settings screen must render when Ollama is not running. Letting
    the connection error escape would make the whole screen unreachable
    because a local daemon happened to be stopped."""
    client = _FakeClient(error=httpx.ConnectError("refused"))

    assert ollama_models("http://localhost:11434", client=client) == []


def test_a_malformed_ollama_reply_yields_no_models():
    """`/api/tags` is an external contract this project does not own. A reply
    without the shape we expect must degrade to an empty dropdown, not a
    KeyError that 500s the settings screen."""
    client = _FakeClient({"unexpected": True})

    assert ollama_models("http://localhost:11434", client=client) == []


def test_available_models_reports_both_providers(tmp_path):
    """The New run screen swaps the model list when the provider changes, so
    it needs both at once. Returning only the configured provider's models
    would make that swap require a second request the screen does not make.
    """
    client = _FakeClient({"models": [{"name": "qwen3.5"}]})
    settings = Settings(_env_file=None, db_path=tmp_path / "z.db")

    models = available_models(settings, client=client)

    # Presence rather than equality against `ANTHROPIC_MODELS`: comparing the
    # function's output to the constant it is built from is true whatever
    # either one says, and pinning the exact list would fire the next time
    # Anthropic ships a model.
    assert set(models) == {"anthropic", "ollama"}
    assert models["anthropic"]
    assert models["ollama"] == ["qwen3.5"]
```

- [ ] **Step 2: Write `zeitgeist/llm/registry.py`**

```python
"""Which models each provider offers.

Not a method on `LLMProvider`: that Protocol's docstring says keeping it to
one method is what makes the local-versus-cloud comparison honest, and model
discovery is a configuration concern rather than a per-call one.
"""

import logging
from typing import Any

from zeitgeist.config import Settings

log = logging.getLogger(__name__)

# Static because Anthropic publishes no list endpoint this app can practically
# use, and the set changes rarely. Ollama's is queried instead, because what
# is installed locally is exactly what changes often.
ANTHROPIC_MODELS: tuple[str, ...] = (
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-4-5-20251001",
)

TIMEOUT_SECONDS = 2.0


def ollama_models(
    host: str, client: Any = None, timeout: float = TIMEOUT_SECONDS
) -> list[str]:
    """What Ollama has pulled locally, or nothing if it cannot be asked.

    Never raises. The settings screen has to render when Ollama is not
    running, and a 500 there would make the screen unreachable because a
    local daemon happened to be stopped.

    The timeout is short on purpose: this is called to draw a dropdown, and
    a stopped daemon should cost a moment, not the request's whole budget.
    """
    if client is None:
        import httpx

        client = httpx.Client()
    try:
        response = client.get(f"{host.rstrip('/')}/api/tags", timeout=timeout)
        payload = response.json()
        return [entry["name"] for entry in payload["models"]]
    except Exception as exc:  # noqa: BLE001 - an empty dropdown, never a 500
        log.debug("Could not list Ollama models at %s: %s", host, exc)
        return []


def available_models(settings: Settings, client: Any = None) -> dict[str, list[str]]:
    """Both providers' models, so the New run screen can swap its list when
    the provider changes without a second request."""
    return {
        "anthropic": list(ANTHROPIC_MODELS),
        "ollama": ollama_models(settings.ollama_host, client=client),
    }
```

- [ ] **Step 3: Write the failing options tests**

Create `tests/test_api_options.py`:

```python
import json

import pytest

from tests.api_factory import api_settings, seeded_client


@pytest.fixture(autouse=True)
def _no_real_ollama(monkeypatch):
    """`read_options` calls `available_models`, which builds its own
    `httpx.Client` and gets `/api/tags`. Left alone, every test in this
    module reaches whatever Ollama the developer happens to be running:
    `conftest` strips `OLLAMA_HOST`, so the host falls back to the real
    default and the result depends on who runs the suite — exactly the
    hermeticity the autouse fixture exists to guarantee.

    `test_llm_registry.py` injects a fake client for this reason; this module
    has no seam to inject through, so the host is pointed at a port nothing
    listens on instead. `ollama_models` swallows the refusal and reports an
    empty list, which is the CI shape.
    """
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")


def test_a_stopped_ollama_leaves_the_dropdown_empty_rather_than_500ing(tmp_path):
    """The settings screen has to render when Ollama is not running. The
    registry's own test proves `ollama_models` swallows the error; this
    proves the endpoint above it does not reintroduce one."""
    client = seeded_client(tmp_path)

    response = client.get("/api/config/options")

    assert response.status_code == 200
    assert response.json()["models"]["ollama"] == []


def test_the_api_key_is_reported_as_a_boolean_and_never_returned(
    tmp_path, monkeypatch
):
    """The spec is explicit: the key itself is never returned. The New run
    screen needs to know whether the Anthropic provider is usable, and a
    boolean is the whole of what that needs.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")
    client = seeded_client(tmp_path)

    response = client.get("/api/config/options")

    assert response.json()["anthropic_key_present"] is True
    assert "sk-ant-secret-value" not in response.text


def test_the_key_is_absent_when_it_is_unset(tmp_path):
    """The inverse, and the one that decides whether the screen offers the
    Anthropic provider at all. A field hardcoded True would offer a provider
    that fails on its first call."""
    client = seeded_client(tmp_path)

    assert client.get("/api/config/options").json()["anthropic_key_present"] is False


def test_platforms_report_which_are_actually_usable(tmp_path):
    """Lemmy and Wikipedia are dormant: their code and tests remain but no
    live stage consumes a flat item list, and `Settings` rejects them. A
    screen offering them would let the user configure a run that cannot
    start.
    """
    client = seeded_client(tmp_path)

    platforms = {p["name"]: p["enabled"] for p in client.get(
        "/api/config/options"
    ).json()["platforms"]}

    assert platforms["bluesky"] is True
    assert platforms["lemmy"] is False


def test_templates_report_the_slots_their_manifests_declare(tmp_path):
    """The manual generation panel in phase 4 draws one caption input per
    slot. Reporting ids alone — or the key with an empty list, which
    `"slots" in template` cannot tell apart, because `TemplateOption` declares
    the field and so FastAPI always emits it — would leave that panel unable
    to render a form for a template it had not hardcoded.

    The expectation is read out of the manifests on disk rather than written
    here as `["rejected", "preferred"]`. Those names are a manifest author's
    to change, so a literal would fire on a deliberate edit while catching no
    bug. It reads `templates_dir` — the same directory the endpoint loads
    from, so the two cannot drift — but parses it here directly rather than
    through `load_templates`, which is part of what is under test.
    """
    library = api_settings(tmp_path).templates_dir
    manifests = {
        path.stem: [slot["name"] for slot in json.loads(path.read_text())["slots"]]
        for path in library.glob("*.json")
    }
    client = seeded_client(tmp_path)

    templates = {
        template["id"]: template["slots"]
        for template in client.get("/api/config/options").json()["templates"]
    }

    assert manifests, "no shipped manifests found; the assertion is vacuous"
    assert templates == manifests


def test_the_env_defaults_report_the_configured_value(tmp_path, monkeypatch):
    """The New run screen pre-fills its cards from these. A field reported
    with the wrong value is worse than a blank one: the user sees a number
    that is not what the next run would actually use.

    The value is set here and read back, rather than asserting a key is
    present — presence is guaranteed by the comprehension over
    `RUN_OVERRIDE_KEYS` and would pass for a dict of hardcoded zeros.
    """
    monkeypatch.setenv("TOPIC_COUNT", "9")
    client = seeded_client(tmp_path)

    defaults = client.get("/api/config/options").json()["defaults"]

    assert defaults["topic_count"] == "9"
    assert "anthropic_api_key" not in defaults
```

- [ ] **Step 4: Write `zeitgeist/api/options.py`**

```python
"""What the New run and settings screens offer as choices.

One endpoint, but it assembles from four unrelated sources — providers,
platforms, templates and `.env` — and belongs in none of the resource
routers.
"""

from fastapi import APIRouter, Depends

from zeitgeist.api.app import get_settings
from zeitgeist.api.schemas import ConfigOptions, PlatformOption, TemplateOption
from zeitgeist.config import KNOWN_SOURCES, TREND_SOURCES, Settings
from zeitgeist.llm.registry import available_models
from zeitgeist.media.templates import load_templates
from zeitgeist.runner import RUN_OVERRIDE_KEYS

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/options", response_model=ConfigOptions)
def read_options(settings: Settings = Depends(get_settings)) -> ConfigOptions:
    templates = load_templates(settings.templates_dir)
    return ConfigOptions(
        models=available_models(settings),
        platforms=[
            PlatformOption(name=name, enabled=name in TREND_SOURCES)
            for name in KNOWN_SOURCES
        ],
        templates=[
            TemplateOption(
                id=manifest.id, slots=[slot.name for slot in manifest.slots]
            )
            for manifest in templates.values()
        ],
        # Only the fields a run may actually override. Reporting every
        # `Settings` field would put `anthropic_api_key` in the response,
        # which is the one thing this endpoint must never return.
        defaults={
            key: str(getattr(settings, key)) for key in sorted(RUN_OVERRIDE_KEYS)
        },
        anthropic_key_present=bool(settings.anthropic_api_key),
    )
```

Add to `zeitgeist/api/schemas.py`:

```python
class PlatformOption(BaseModel):
    """`enabled` is False for the dormant platforms — Lemmy and Wikipedia
    have code and tests but no live stage consumes a flat item list, and
    `Settings` rejects them. Reported rather than hidden so the screen can
    say why they are unavailable."""

    model_config = STRICT

    name: str
    enabled: bool


class TemplateOption(BaseModel):
    model_config = STRICT

    id: str
    slots: list[str]


class ConfigOptions(BaseModel):
    """`anthropic_key_present` is a boolean and the key itself is never
    returned, in any form."""

    model_config = STRICT

    models: dict[str, list[str]]
    platforms: list[PlatformOption]
    templates: list[TemplateOption]
    defaults: dict[str, str]
    anthropic_key_present: bool
```

Mount `options.router` in `create_app` alongside the others. **Check `TemplateManifest`'s and its slots' real attribute names** in `zeitgeist/media/templates.py` before writing the comprehension — `manifest.id` and `slot.name` are what `pipeline.py` and `brief.py` use, but confirm rather than assume.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/test_llm_registry.py tests/test_api_options.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 6: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`
Expected: all four pass.

- [ ] **Step 7: Commit**

```bash
git add zeitgeist/llm/registry.py zeitgeist/api/options.py zeitgeist/api/app.py zeitgeist/api/schemas.py tests/
git commit -m "Serve the choices the config screens offer

Anthropic's models are a constant because it publishes no list endpoint
this app can use and the set changes rarely; Ollama's come from /api/tags,
so a model the user pulled appears without a code change. A stopped Ollama
yields an empty list rather than a 500 that would make the settings screen
unreachable.

The API key is reported as a boolean, and the defaults are restricted to
what a run may override — reporting every Settings field would put the key
itself in the response.

Not a method on LLMProvider: that Protocol stays at one method deliberately,
and model discovery is a configuration concern rather than a per-call one.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: `PUT /api/settings`

**Files:**
- Modify: `zeitgeist/api/settings.py`, `zeitgeist/api/schemas.py`, `tests/test_api_settings.py`

**Interfaces:**
- Consumes: `WRITABLE_KEYS`, `Store.set_setting`, `Store.clear_setting`, and phase 2's `_source(key, stored)`.
- Produces:
  - `zeitgeist.api.schemas.SettingsUpdate` — `values: dict[str, str]`
  - `PUT /api/settings` returning the same `list[SettingField]` the `GET` does

**Only the seven tunables.** Anything else is a 400 — `db_path`, `output_dir`, `templates_dir`, `font_path`, `anthropic_api_key`, `ollama_host`, `llm_provider`, `llm_model` and `sources` are not exposed. A UI that can rewrite where the database lives, or that stores an API key in a table, is a different and worse thing than a tuning screen.

**Values are validated before they are stored.** A `bluesky_trend_limit` of `"banana"`, or a `meme_potential_weight` of `2.0`, must be refused at the endpoint rather than written and then blowing up when the next run constructs `Settings`. Build a candidate `Settings` with the proposed values and let pydantic reject it.

**An empty string clears the row**, so the `.env` fallback applies again — that is the "Reset to .env" button, which the design describes as deleting the row rather than writing a default.

**The response is the same shape as `GET`**, so the screen can re-render its source chips from the write's own reply rather than issuing a second request. A key that was just set reports `SET HERE`; one just cleared reports whatever layer now supplies it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api_settings.py`. Two of these assert against the settings table and a freshly built `Settings` rather than through `GET /api/settings`, because that endpoint reports `getattr` on the app's *startup* `Settings` object, which no write reaches — an assertion through the GET reads the same value whatever the endpoint did. Extend the module's existing import block with:

```python
import os
from pathlib import Path

from zeitgeist.config import Settings
from zeitgeist.store import Store
```

Then the tests:

```python
def test_a_written_value_is_stored_and_reported_as_set_here(tmp_path):
    """The screen's whole feedback loop: save, and the chip changes. A write
    that stored the value but reported the old source would leave the user
    unable to tell whether it took."""
    client = seeded_client(tmp_path)

    body = client.put(
        "/api/settings", json={"values": {"bluesky_trend_limit": "11"}}
    ).json()

    fields = {field["key"]: field for field in body}
    assert fields["bluesky_trend_limit"]["value"] == 11
    assert fields["bluesky_trend_limit"]["source"] == "settings"


def test_a_written_value_survives_into_a_new_settings_object(tmp_path):
    """The point of the table: the next run picks the value up. A write that
    only touched the response would change the screen and nothing else.

    Asserted on a freshly built `Settings` rather than on `GET /api/settings`,
    because that is what "the next run" actually is — the worker constructs
    one per run and `SettingsTableSource` reads the table at construction.
    The GET reports `getattr` on the app's *startup* `Settings`, which no
    write reaches, so a GET-based assertion here could never pass.
    """
    client = seeded_client(tmp_path)

    client.put("/api/settings", json={"values": {"phrase_min_authors": "7"}})

    assert Settings(_env_file=None).phrase_min_authors == 7


def test_an_empty_value_clears_the_row_so_the_fallback_applies(tmp_path):
    """"Reset to .env" deletes the row rather than writing a default —
    writing the default back would pin the value and make a later `.env`
    edit invisible, which is the opposite of what the button says."""
    client = seeded_client(tmp_path)
    client.put("/api/settings", json={"values": {"phrase_min_authors": "7"}})

    body = client.put(
        "/api/settings", json={"values": {"phrase_min_authors": ""}}
    ).json()

    # Compared against a freshly built Settings rather than the literal 3:
    # that literal is the field's default, which the code is free to change,
    # so a test pinning it would fail for a decision rather than a bug.
    fields = {field["key"]: field for field in body}
    assert fields["phrase_min_authors"]["value"] == (
        Settings(_env_file=None).phrase_min_authors
    )
    assert fields["phrase_min_authors"]["source"] != "settings"


def test_a_field_outside_the_seven_is_refused(tmp_path):
    """A UI that can rewrite where the database lives is a different and
    worse thing than a tuning screen."""
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"db_path": "/tmp/elsewhere.db"}}
    )

    assert response.status_code == 400


def test_the_api_key_cannot_be_written(tmp_path):
    """Named separately because this is the one the allowlist exists for:
    storing a key in the settings table would put it in the database in
    plain text, and `GET /api/settings` would then have to know to hide a
    field it otherwise reports."""
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"anthropic_api_key": "sk-ant-nope"}}
    )

    assert response.status_code == 400


def test_a_refused_field_writes_nothing_at_all(tmp_path):
    """A request naming one good field and one bad one must write neither.
    Applying the valid half would leave the screen showing a partial save
    with a 400 beside it, and no way to tell which half landed.

    Asserted against the settings table rather than `GET /api/settings`: the
    GET reports `getattr` on the app's startup `Settings`, which no write can
    change, so a GET-based assertion here reads 3 whether the endpoint wrote
    nothing, the good half, or both.
    """
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings",
        json={"values": {"phrase_min_authors": "7", "db_path": "/tmp/x.db"}},
    )

    assert response.status_code == 400
    store = Store(Path(os.environ["DB_PATH"]))
    try:
        assert store.get_settings() == {}
    finally:
        store.close()


def test_a_value_that_settings_would_reject_is_refused(tmp_path):
    """`meme_potential_weight` is `ge=0.0, le=1.0`. Stored unvalidated, 2.0
    would be written happily and then fail when the *next run* built its
    Settings — surfacing as a broken run rather than a rejected save.
    """
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"meme_potential_weight": "2.0"}}
    )

    assert response.status_code == 400


def test_a_non_numeric_value_is_refused(tmp_path):
    """Same failure mode, cruder input. The form is a text box."""
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"bluesky_trend_limit": "banana"}}
    )

    assert response.status_code == 400
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_api_settings.py -k "written or refused or cleared or cannot" -v`
Expected: FAIL — 405 Method Not Allowed.

- [ ] **Step 3: Write the endpoint**

Add to `zeitgeist/api/settings.py`:

```python
@router.put("", response_model=list[SettingField])
def write_settings(
    body: SettingsUpdate,
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> list[SettingField]:
    """Write the seven tunables, then report every field's new state.

    Same response shape as the `GET`, so the screen re-renders its source
    chips from this reply rather than issuing a second request.
    """
    unknown = sorted(set(body.values) - WRITABLE_KEYS)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Not writable through settings: {', '.join(unknown)}",
        )

    # Validate before writing anything. Stored unvalidated, a
    # meme_potential_weight of 2.0 would be accepted here and fail when the
    # *next run* built its Settings — a broken run rather than a rejected
    # save. Validating a candidate object is also how the endpoint stays
    # ignorant of each field's type.
    proposed = {
        key: value for key, value in body.values.items() if value != ""
    }
    if proposed:
        try:
            Settings(**(settings.model_dump() | proposed))
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=exc.errors()) from exc

    # Only after every field has been accepted: a request naming one good
    # field and one bad one must write neither, or the screen shows a
    # partial save with a 400 beside it.
    for key, value in body.values.items():
        if value == "":
            # "Reset to .env" deletes the row so the fallback applies again.
            # Writing the default back would pin the value and make a later
            # .env edit invisible.
            store.clear_setting(key)
        else:
            store.set_setting(key, value)

    return read_settings(store=store, settings=Settings())
```

The final line rebuilds `Settings` rather than reusing the injected one, because the injected object was constructed at app startup and predates this write — reusing it would report the values the screen just replaced. Check `read_settings`' actual parameter names in the file and call it accordingly.

Add to `zeitgeist/api/schemas.py`:

```python
class SettingsUpdate(BaseModel):
    """An empty string clears that field's row so the `.env` fallback
    applies again, which is what "Reset to .env" does."""

    model_config = STRICT

    values: dict[str, str]
```

Add the imports `HTTPException` from `fastapi` and `ValidationError` from `pydantic`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_api_settings.py -v`
Expected: PASS, including phase 2's existing tests.

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`
Expected: all four pass.

- [ ] **Step 6: Commit**

```bash
git add zeitgeist/api/settings.py zeitgeist/api/schemas.py tests/test_api_settings.py
git commit -m "Serve writing the seven tunable settings

Values are validated by building a candidate Settings before anything is
written, so a weight of 2.0 is a rejected save rather than a run that
breaks later. A request naming one good field and one bad one writes
neither.

An empty value clears the row so the .env fallback applies again, which is
what "Reset to .env" means — writing the default back would pin the value
and make a later .env edit invisible.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 14: Documentation

**Files:**
- Modify: `README.md`

**Interfaces:** none — this task changes no code.

- [ ] **Step 1: Extend the web UI section**

`README.md` gained a `## The web UI` section in phase 2, covering starting the server, `--host`/`--port`/`--reload`, `/docs` and `/openapi.json`, and the phase-5 TypeScript command. Extend it — do not rewrite it — with what phase 3 adds.

Cover, in the README's existing voice:

- **Runs are now startable over HTTP.** `POST /api/runs` queues one; `scripts/run_pipeline.py` still works and is still the harness for scripted runs.
- **One run at a time.** A second `POST` queues behind the first, and the response's `position` says how far back. The queue is in-memory, so a restart loses what was queued — deliberately, rather than persisting a job table for a single-user tool.
- **Stop versus abort.** Stop finishes the current stage and writes its checkpoint, so the run stays resumable. Abort ends now. **Aborting during ingest takes effect when the fetch returns**, because `fetch_evidence` is one opaque `asyncio.run()` with no interior checkpoint — worth stating, because it is a surprise otherwise.
- **Resume, and the tuning loop.** `POST /api/runs/{id}/resume` reuses the run's checkpoints and defaults to the computed stage. Its optional `template_ids` narrows the library for that resume, which replaces `--resume-from generate --templates drake`.
- **A run interrupted by a restart** is marked `interrupted` on the next startup and resumes like any other. `--reload` kills a run in flight, which is why it is off by default.
- **The live log.** `GET /api/runs/{id}/events` streams log lines and progress ticks over SSE while a run executes; `GET /api/runs/{id}/log?verbose=` serves the history afterwards. The server always captures at DEBUG and `verbose` filters what is returned, so flipping it works retroactively on lines already recorded.
- **Settings.** `PUT /api/settings` writes the seven tunables; an empty value clears the row so `.env` applies again. Changes apply to new runs — a run in flight keeps the config it froze.

A short `curl` example of starting a run and watching it is worth including, since it is how this phase is exercised before any UI exists.

**Do not** document `POST .../renders` or `DELETE /api/renders/{id}` — those are phase 4. **Do not** add the three npm gate commands; `web/` does not exist until phase 5, and adding them now would turn every pull request red for a directory that is not supposed to exist yet.

- [ ] **Step 2: Verify the documented commands work**

Point `DB_PATH` at a scratch file so this does not touch a real database, start the server, and exercise the two endpoints a reader will try first:

```bash
DB_PATH=/tmp/zg-doc-check.db uv run zeitgeist --port 8123 &
```

Then confirm `GET /api/runs/active` returns `{"current": null, "queued": []}` and `GET /api/config/options` returns 200, and stop the server. Do **not** `POST /api/runs` here — that would start a real run against a real model.

- [ ] **Step 3: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`
Expected: all four pass.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "Document starting, watching and stopping runs

Covers the queue and its one-at-a-time guarantee, the difference between
stop and abort — including that an abort during ingest waits for the fetch
to return — resume and the template-narrowing tuning loop it replaces, and
that the server always captures at DEBUG so the verbose toggle works
retroactively.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Verification

After Task 14, confirm the phase's stated end condition: **a run startable, watchable and stoppable over HTTP, with no UI.**

This needs a real model and so belongs to the repository's owner, not to an implementer.

- [ ] **Start from a clean database**

```bash
rm -f data/zeitgeist.db && rm -rf output
```

- [ ] **Start the server and queue a run**

```bash
uv run zeitgeist --port 8123 &
curl -s -XPOST localhost:8123/api/runs -H 'content-type: application/json' -d '{}' | jq
curl -s localhost:8123/api/runs/active | jq
```

Expected: a `run_id` with `position: 0`, then `current` naming that run.

- [ ] **Watch it**

```bash
RUN=$(curl -s localhost:8123/api/runs/active | jq -r .current)
curl -sN "localhost:8123/api/runs/$RUN/events" | head -40
```

Expected: `log` events carrying real lines from the run, interleaved with `tick` events, and the stream closing when the run ends.

- [ ] **Confirm the verbose toggle now does something**

```bash
curl -s "localhost:8123/api/runs/$RUN/log" | jq length
curl -s "localhost:8123/api/runs/$RUN/log?verbose=true" | jq length
```

Expected: the verbose count is meaningfully larger. Before this phase they were equal, because nothing logged at DEBUG.

- [ ] **Confirm no personal data reached the log**

```bash
curl -s "localhost:8123/api/runs/$RUN/log?verbose=true" | jq -r '.[].message' | grep -iE 'author_key|did:plc' && echo "LEAK" || echo "clean"
```

Expected: `clean`.

- [ ] **Queue two and stop one**

```bash
curl -s -XPOST localhost:8123/api/runs -d '{}' -H 'content-type: application/json' | jq
curl -s -XPOST localhost:8123/api/runs -d '{}' -H 'content-type: application/json' | jq .position
RUN=$(curl -s localhost:8123/api/runs/active | jq -r .current)
curl -s -XPOST "localhost:8123/api/runs/$RUN/stop" | jq
```

Expected: the second reports `position: 1`; the stopped run reaches `aborted` with its current stage's checkpoint written, and the queued run then starts.

- [ ] **Resume it**

```bash
curl -s "localhost:8123/api/runs/$RUN" | jq .resume_stage
curl -s -XPOST "localhost:8123/api/runs/$RUN/resume" -H 'content-type: application/json' -d '{}' | jq
```

Expected: the run resumes from its computed stage and completes.

- [ ] **Confirm an interrupted run is reconciled**

Start a run, kill the server mid-run (`Ctrl-C`), restart it, and read that run.

Expected: status `interrupted`, and a `resume_stage` it can be resumed from.

- [ ] **Confirm the key never appears**

```bash
curl -s localhost:8123/api/config/options | grep -i 'sk-ant' && echo "LEAK" || echo "clean"
```

Expected: `clean`.

---

## Notes for the executor

**There is no red window in this phase.** Every task starts and ends with all four gate commands green. A failure that is not yours is a signal something is wrong, not something to work around.

**Threading is the risk in this plan, and sleeping is how it gets hidden.** Every test that crosses a thread boundary uses `threading.Event` with a timeout — `entered.wait(timeout=5)` — so a broken implementation fails in five seconds instead of passing on a fast machine and failing on CI. **Never** replace one of these with `time.sleep`, and never widen a timeout to make a flaky test pass: a test that needs longer than five seconds to observe a flag set on another thread is telling you the flag is not reaching it.

**Do not add write endpoints beyond this phase's.** `POST .../renders` and `DELETE /api/renders/{id}` are phase 4. An endpoint built early has no consumer, no test that means anything, and a contract nobody has reviewed against the screens that will use it.

**Do not touch the `CLAUDE.md` gate commands.** They grow from four to seven in phase 5, alongside the Vite scaffold that makes the extra three runnable. Adding them now turns every pull request red for a directory that is not supposed to exist yet.

**Two things this phase surfaces that are worth carrying into later phases rather than solving here:**

- On-demand generation runs on a **separate** executor, not this queue — the design shows tiles generating on topic detail while a run is in flight. That is phase 4's, and it means two concurrent callers of the LLM provider: free on Anthropic, contended on local Ollama where inference serialises on one GPU. Documented rather than solved with a global lock.
- The settings screen draws three source chips but there are four layers, because a shell variable outranks the settings table. `GET /api/settings` has returned `environment` as a fourth value since phase 2, and phase 6 needs a fourth chip or a deliberate decision to fold it into one of the three.

**If a test in this plan seems wrong, say so rather than weakening it.** Several assert properties the spec argues for at length: that stop leaves the current stage's checkpoint written, that an abort is not reported as "every trend failed", that topic ids do not depend on which trend finishes first, and that no DEBUG line carries reply text. Changing one to make it pass would remove the thing it exists to protect.
