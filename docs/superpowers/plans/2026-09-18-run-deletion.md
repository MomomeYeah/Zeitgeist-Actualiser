# Run Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a finished run be deleted from its detail screen — its database rows, its output directory, and every cached view of it.

**Architecture:** One `run_records` row delete cascades to every child table. `DELETE /api/runs/{run_id}` composes two guards — `GenerationService.excluding` (no on-demand job in flight) around `RunService.delete` (not live or queued, row deleted under the runner's lock) — then removes `output/<run_id>/` outside both locks. The client adds `useDeleteRun` and a Delete `InlineConfirm` to `RunActions`' "over" branch, whose question carries the run's `render_count`.

**Tech Stack:** Python 3.14, FastAPI, SQLite, pytest; React 19, TanStack Query v5, React Router 7, MSW, vitest.

**Spec:** `docs/superpowers/specs/2026-09-18-run-deletion-design.md`

## Global Constraints

- The Definition of Done is all seven commands in `CLAUDE.md` passing: `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, `uv run pytest`, `npm --prefix web run lint`, `npm --prefix web run typecheck`, `npm --prefix web test`.
- Python 3.14: PEP 695 generics, not `typing.TypeVar`. Ruff rules `E, F, I, UP, B, SIM`, line length 88.
- No blanket `# type: ignore`; a narrow suppression needs a comment saying why.
- `store.py` knows rows and nothing about the filesystem; `zeitgeist/renders.py` owns the output layout and imports nothing from `zeitgeist.api`; `runner.py` and `generation.py` import nothing from `zeitgeist.api`.
- Every test that needs a database builds its own `Store` on `tmp_path`.
- Any change to a response model means regenerating `web/openapi.json` (`uv run python scripts/dump_openapi.py`) and `web/src/api/schema.ts` (`npm --prefix web run generate:types`) in the same task.
- Match the surrounding code's comment density: every new public function, method and class gets a docstring that says *why*, in the codebase's voice.
- Confirm copy, verbatim: `Delete run?` (0 memes), `Delete run and its 1 meme?`, `Delete run and its N memes?`.
- Every commit message ends with a blank line and `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. The `git commit -m` lines below show the subject only.
- 409 copy, verbatim: `Run {run_id} is queued or executing; abort it before deleting it.` and `Memes are still generating for run {run_id}; wait for them to finish before deleting it.` 404 copy: `No such run: {run_id}`.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `zeitgeist/store.py` | Modify | `UnknownRun` exception; `Store.delete_run` |
| `zeitgeist/renders.py` | Modify | `delete_run_files` — the run directory, contained to `output_dir` |
| `zeitgeist/runner.py` | Modify | `RunService.delete`; `enqueue(..., resuming=)` existence check |
| `zeitgeist/api/control.py` | Modify | `resume_run` passes `resuming=True`, maps `UnknownRun` → 404 |
| `zeitgeist/generation.py` | Modify | `RunBusy`; per-run in-flight tracking; `excluding`; `submit` claim-then-check |
| `zeitgeist/api/generate.py` | Modify | `UnknownRun` → 404 |
| `zeitgeist/api/schemas.py` | Modify | `RunDetail.render_count` |
| `zeitgeist/api/runs.py` | Modify | `render_count` in `read_run`; `DELETE /api/runs/{run_id}` |
| `web/openapi.json`, `web/src/api/schema.ts` | Regenerate | Contract |
| `web/src/test/factories.ts` | Modify | `makeRunDetail({ renderCount })` |
| `web/src/api/queries.ts` | Modify | `useDeleteRun` |
| `web/src/features/runs/RunActions.tsx` | Modify | The Delete control |
| `tests/api_factory.py` | Modify | `GatedGenerate` |
| Tests | Modify | `tests/test_store.py`, `tests/test_renders.py`, `tests/test_runner.py`, `tests/test_api_control.py`, `tests/test_generation.py`, `tests/test_api_generate.py`, `tests/test_api_runs.py`, `web/src/api/queries.test.tsx`, `web/src/features/runs/RunDetailPage.test.tsx` |

---

### Task 1: `Store.delete_run` and `UnknownRun`

**Files:**
- Modify: `zeitgeist/store.py` (exception beside `MissingCheckpoint` at ~line 70; method beside `abort_run` at ~line 329)
- Test: `tests/test_store.py` (append after `test_delete_render_reports_an_unknown_id`, ~line 1671)

**Interfaces:**
- Produces: `class UnknownRun(LookupError)` in `zeitgeist.store`; `Store.delete_run(self, run_id: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_store.py`, after `test_delete_render_reports_an_unknown_id`:

```python
# Every table that hangs off `run_records`. Named here rather than read from
# `sqlite_master` so a new child table is a decision this test is updated
# for, not one it silently absorbs.
_RUN_TABLES = (
    "run_records",
    "checkpoints",
    "run_stages",
    "run_topics",
    "renders",
    "log_lines",
    "topic_scores",
)


def _rows_per_table(store: Store, run_id: str) -> dict[str, int]:
    return {
        table: store._conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        for table in _RUN_TABLES
    }


def _fill_every_table(store: Store, run_id: str) -> None:
    """One row in every child table, each through the writer production
    uses — `_analyse` covers the checkpoint, `run_topics` and
    `topic_scores` in one transaction."""
    _analyse(store, run_id, [_topic("Cats", {"bluesky": 0.5})])
    store.record_stage(run_id, make_stage_record(Stage.ANALYSE))
    store.add_render(make_render_record(f"{run_id}-r", run_id=run_id, topic_id="cats"))
    _log(store, run_id, 1, "INFO", "hello")


def test_delete_run_removes_the_run_and_every_row_hanging_off_it(tmp_path):
    """The cascade is the whole mechanism. With foreign keys off — the
    SQLite default — this deletes one row and leaves six tables of
    orphans behind it."""
    store = _store(tmp_path)
    _fill_every_table(store, "doomed")
    _fill_every_table(store, "kept")
    # The fixture must actually reach every table, or a zero below proves
    # nothing about the cascade.
    assert all(count > 0 for count in _rows_per_table(store, "doomed").values())

    assert store.delete_run("doomed") is True

    assert _rows_per_table(store, "doomed") == dict.fromkeys(_RUN_TABLES, 0)
    assert all(count > 0 for count in _rows_per_table(store, "kept").values())


def test_delete_run_reports_an_unknown_id(tmp_path):
    """The endpoint 404s on it, so a silent success would be a lie."""
    store = _store(tmp_path)

    assert store.delete_run("nope") is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_store.py -k delete_run -v`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'delete_run'`.

- [ ] **Step 3: Implement**

In `zeitgeist/store.py`, after the `MissingCheckpoint` class:

```python
class UnknownRun(LookupError):
    """No `run_records` row for that id.

    Raised where a run vanished between a caller's check and its write —
    deleted from another tab — so the API can answer 404 rather than let
    the write recreate the row or trip a foreign key. A `LookupError`, like
    `UnknownTopic`, so it cannot be mistaken for a malformed request.

    Here rather than in `runner.py` or `generation.py` because both raise
    it, and both already import this module.
    """
```

In `Store`, after `abort_run`:

```python
    def delete_run(self, run_id: str) -> bool:
        """Remove the run and, by cascade, every row that hangs off it.
        False means there was no such run.

        One statement: every child table references `run_records` with
        `ON DELETE CASCADE`, and `__init__` turns enforcement on. The run's
        files are not this method's business — see
        `zeitgeist.renders.delete_run_files`.
        """
        cursor = self._conn.execute(
            "DELETE FROM run_records WHERE run_id = ?", (run_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_store.py -k delete_run -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/store.py tests/test_store.py
git commit -m "Add Store.delete_run, cascading to every child table"
```

---

### Task 2: `delete_run_files`

**Files:**
- Modify: `zeitgeist/renders.py` (new function after `delete_render`; add `import shutil`; extend the module docstring's first paragraph)
- Test: `tests/test_renders.py` (append)

**Interfaces:**
- Produces: `delete_run_files(output_dir: Path, run_id: str) -> None` in `zeitgeist.renders`. Raises `ValueError` for an id that does not name a direct child of `output_dir`; logs (does not raise) an `OSError` from removal.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_renders.py` (add `import logging` and `import pytest` at the top, and `delete_run_files` to the `zeitgeist.renders` import):

```python
def test_delete_run_files_removes_the_runs_directory_and_nothing_else(tmp_path):
    output = tmp_path / "output"
    _write_files(output, "run-1", "rnd1")
    _write_files(output, "run-2", "rnd2")

    delete_run_files(output, "run-1")

    assert not (output / "run-1").exists()
    assert render_paths(output, "run-2", "rnd2").full.is_file()


def test_delete_run_files_succeeds_when_the_run_never_wrote_a_file(tmp_path):
    """A run that died in ingest never created its directory."""
    output = tmp_path / "output"
    _write_files(output, "run-2", "rnd2")

    delete_run_files(output, "run-1")

    assert render_paths(output, "run-2", "rnd2").full.is_file()


@pytest.mark.parametrize(
    "run_id",
    ["..", "../victim", "", ".", "run-2/renders", "ABSOLUTE"],
)
def test_delete_run_files_refuses_an_id_that_is_not_one_run_directory(
    tmp_path, run_id
):
    """The id arrives in a URL. Anything that does not resolve to exactly
    one directory inside `output_dir` — its parent, a sibling, the output
    directory itself, something nested in a run, an absolute path — is
    refused before anything is removed."""
    output = tmp_path / "output"
    _write_files(output, "run-2", "rnd2")
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep", encoding="utf-8")
    if run_id == "ABSOLUTE":
        run_id = str(victim)

    with pytest.raises(ValueError):
        delete_run_files(output, run_id)

    assert (victim / "keep.txt").is_file()
    assert render_paths(output, "run-2", "rnd2").full.is_file()


def test_delete_run_files_logs_a_directory_it_cannot_remove(
    tmp_path, monkeypatch, caplog
):
    """The row is already gone by the time this runs, so the deletion has
    happened. A file held open on Windows is a warning, not a 500 for a
    request that succeeded. `rmtree` is replaced because a locked file
    cannot be produced portably from a test."""
    output = tmp_path / "output"
    _write_files(output, "run-1", "rnd1")

    def refuse(path, *args, **kwargs):
        raise PermissionError(f"in use: {path}")

    monkeypatch.setattr("zeitgeist.renders.shutil.rmtree", refuse)

    with caplog.at_level(logging.WARNING, logger="zeitgeist.renders"):
        delete_run_files(output, "run-1")

    assert "in use" in caplog.text
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_renders.py -v`
Expected: collection error — `ImportError: cannot import name 'delete_run_files'`.

- [ ] **Step 3: Implement**

In `zeitgeist/renders.py`, add `import shutil` to the imports. Change the module docstring's first paragraph to:

```
"""Where a render's two files live, and how a render — or a whole run's
output — is removed.

The database is authoritative for whether a render exists — but a render is
a row *and* a pair of PNGs, and two callers need all three gone together:
`DELETE /api/renders/{id}`, and the re-run that clears a topic's previous
model-written attempts. One function rather than two copies of
`unlink(missing_ok=True)`. Deleting a run removes its directory whole,
which also reclaims the orphans the render paths knowingly leave.
```

(Leave the second paragraph as it is.) After `delete_render`, add:

```python
def delete_run_files(output_dir: Path, run_id: str) -> None:
    """Remove `output/<run_id>/` and everything in it.

    Called after the run's row is gone, so the run no longer exists
    whatever happens here: a directory that cannot be removed is logged
    and left, invisible to every screen, rather than turned into an error
    for a deletion that already succeeded. A run that never wrote a file
    has no directory, which is not an error either.

    `run_id` arrives in a URL, so the target must resolve to a direct
    child of `output_dir` — not the directory itself, not its parent, not
    something nested inside a run — or nothing is removed. The endpoint
    only gets here for an id that named a real row, so this should never
    fire; it is what makes that a guarantee rather than an inference.
    """
    root = Path(output_dir).resolve()
    target = (root / run_id).resolve()
    if target.parent != root:
        raise ValueError(
            f"Run id {run_id!r} does not name a directory directly inside {root}"
        )
    if not target.exists():
        return
    try:
        shutil.rmtree(target)
    except OSError as exc:
        log.warning("Could not remove %s: %s", target, exc)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_renders.py -v`
Expected: all passed (4 new + 8 existing, with 6 parametrized cases).

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/renders.py tests/test_renders.py
git commit -m "Add delete_run_files, contained to the output directory"
```

---

### Task 3: `RunService.delete` and the resume re-check

**Files:**
- Modify: `zeitgeist/runner.py` (`enqueue` at ~line 277; new `delete` method after `abort` at ~line 379; import `UnknownRun` from `zeitgeist.store`)
- Modify: `zeitgeist/api/control.py` (`resume_run` at ~line 99)
- Test: `tests/test_runner.py` (append), `tests/test_api_control.py` (append after `test_resuming_a_run_twice_is_a_409_the_second_time`)

**Interfaces:**
- Consumes: `Store.delete_run`, `UnknownRun` (Task 1).
- Produces: `RunService.delete(self, run_id: str) -> None`, raising `RunAlreadyActive` (live or queued) or `UnknownRun` (no row); `RunService.enqueue(self, request: RunRequest, *, resuming: bool = False) -> QueuedRun`, raising `UnknownRun` when `resuming` and the row is gone.

- [ ] **Step 1: Write the failing runner tests**

In `tests/test_runner.py`, add `UnknownRun` to the `zeitgeist.store` import (`from zeitgeist.store import Store, UnknownRun`). Append:

```python
def test_deleting_a_finished_run_removes_its_row(tmp_path):
    store = _open_store(tmp_path)
    store.start_run("finished", make_run_config())
    store.abort_run("finished")
    service = RunService(_settings(tmp_path), store)

    service.delete("finished")

    assert store.get_run("finished") is None
    store.close()


def test_deleting_an_unknown_run_is_refused(tmp_path):
    store = _open_store(tmp_path)
    service = RunService(_settings(tmp_path), store)

    with pytest.raises(UnknownRun):
        service.delete("nope")
    store.close()


def test_deleting_the_executing_run_is_refused_and_leaves_it(tmp_path):
    """Its worker is still writing checkpoints and stage rows; deleting
    the row under it would fail every one of those writes on the foreign
    key."""
    gate = _Gate()
    store = _open_store(tmp_path)
    service = RunService(_settings(tmp_path), store, execute=gate)
    service.start()
    try:
        run_id = service.enqueue(RunRequest()).run_id
        assert gate.entered.wait(timeout=5)

        with pytest.raises(RunAlreadyActive):
            service.delete(run_id)

        assert store.get_run(run_id) is not None
    finally:
        gate.release.set()
        service.shutdown()
    store.close()


def test_deleting_a_waiting_run_is_refused_and_leaves_it(tmp_path):
    """A queued run's row exists before the worker reaches it, and the
    worker will start writing to it the moment it does."""
    gate = _Gate()
    store = _open_store(tmp_path)
    service = RunService(_settings(tmp_path), store, execute=gate)
    service.start()
    try:
        service.enqueue(RunRequest())
        assert gate.entered.wait(timeout=5)
        waiting = service.enqueue(RunRequest()).run_id

        with pytest.raises(RunAlreadyActive):
            service.delete(waiting)

        assert store.get_run(waiting) is not None
    finally:
        gate.release.set()
        service.shutdown()
    store.close()


def test_resuming_a_deleted_run_is_refused_rather_than_recreating_it(tmp_path):
    """`start_run` is an upsert. Without the check, a resume that lost the
    race to a delete opens a fresh row with no checkpoints behind it — the
    deleted run back as an empty shell."""
    store = _open_store(tmp_path)
    store.start_run("gone", make_run_config())
    service = RunService(_settings(tmp_path), store)
    service.delete("gone")

    with pytest.raises(UnknownRun):
        service.enqueue(
            RunRequest(run_id="gone", start_at=Stage.EVALUATE), resuming=True
        )

    assert store.get_run("gone") is None
    assert service.active() == ActiveRuns(current=None, queued=[])
    store.close()
```

- [ ] **Step 2: Write the failing API test**

In `tests/test_api_control.py`, append after `test_resuming_a_run_twice_is_a_409_the_second_time`:

```python
def test_a_resume_that_loses_the_race_to_a_delete_is_a_404(tmp_path, monkeypatch):
    """The interleaving the lock exists for, reproduced exactly: the
    delete lands after `resume_run`'s own `_run_or_404` has passed and
    before `enqueue` opens the row. Real `delete`, real `enqueue` — only
    the moment is chosen."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id="20260901T120000Z",
                evidence=[make_evidence(["p1"])],
            )
        ],
        execute=lambda settings, request, store, observer, token: None,
    )
    runner = app_of(client).state.runner
    enqueue = runner.enqueue

    def delete_first(request, **kwargs):
        assert request.run_id is not None  # A resume always names its run.
        runner.delete(request.run_id)
        return enqueue(request, **kwargs)

    monkeypatch.setattr(runner, "enqueue", delete_first)

    response = client.post(
        "/api/runs/20260901T120000Z/resume", json={"stage": "evaluate"}
    )
    runner.shutdown(timeout=10)

    assert response.status_code == 404
    assert client.get("/api/runs/20260901T120000Z").status_code == 404
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_runner.py tests/test_api_control.py -k "delet or race" -v`
Expected: runner tests FAIL with `AttributeError: 'RunService' object has no attribute 'delete'`; the API test FAILs the same way inside `delete_first`.

- [ ] **Step 4: Implement `RunService.delete` and the `resuming` check**

In `zeitgeist/runner.py`, change the store import to `from zeitgeist.store import Store, UnknownRun`.

Change `enqueue`'s signature and give it a docstring (it has none today; its body's comments stay as they are):

```python
    def enqueue(self, request: RunRequest, *, resuming: bool = False) -> QueuedRun:
        """Validate, open the run's row, and queue it.

        `resuming` is `resume_run`'s: the run must still exist. The endpoint
        checked it, but a delete from another tab can land between that
        check and the row write below, and `start_run` is an upsert that
        would open a fresh, checkpoint-less row for a run the user just
        deleted. The check sits inside `_lock`, which `delete` holds too,
        so the two cannot interleave. A flag rather than inferring a resume
        from `request.run_id`, which a new run may also carry.
        """
```

Inside the `with self._lock:` block, directly after the `_is_live` check and before `self._store.start_run(...)`:

```python
            if resuming and self._store.get_run(run_id) is None:
                raise UnknownRun(f"No such run: {run_id}")
```

After the `abort` method, add:

```python
    def delete(self, run_id: str) -> None:
        """Delete a run that is neither executing nor queued.

        Under `_lock`, which `enqueue` holds while it opens or re-opens a
        row, so a resume from another tab cannot slip between the liveness
        check and the delete. Only the row goes here — one indexed DELETE,
        so `active()`, `stop()` and `abort()` wait no longer than they do
        for `enqueue` — and the files are removed by the caller after the
        lock is released.
        """
        with self._lock:
            if self._is_live(run_id):
                raise RunAlreadyActive(
                    f"Run {run_id} is queued or executing; abort it before "
                    "deleting it."
                )
            if not self._store.delete_run(run_id):
                raise UnknownRun(f"No such run: {run_id}")
```

- [ ] **Step 5: Wire `resume_run`**

In `zeitgeist/api/control.py`, add `from zeitgeist.store import Store, UnknownRun` (replacing the existing `from zeitgeist.store import Store`). In `resume_run`, pass the flag:

```python
        return runner.enqueue(
            RunRequest(
                run_id=run_id,
                start_at=stage,
                template_ids=(
                    body.template_ids
                    if body.template_ids is not None
                    else run.config.template_ids
                ),
                overrides=run.config.as_overrides(),
            ),
            resuming=True,
        )
```

and add, directly after the `except RunnerUnavailable` branch:

```python
    except UnknownRun as exc:
        # Deleted from another tab after `_run_or_404` above passed. Caught
        # ahead of `ValueError` for clarity only — it is a `LookupError`.
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/test_runner.py tests/test_api_control.py -v`
Expected: all passed, including every existing resume test (which now travel the `resuming=True` path against rows that exist).

- [ ] **Step 7: Commit**

```bash
git add zeitgeist/runner.py zeitgeist/api/control.py tests/test_runner.py tests/test_api_control.py
git commit -m "Add RunService.delete, and stop a resume from recreating a deleted run"
```

---

### Task 4: Generation in-flight tracking and `excluding`

**Files:**
- Modify: `zeitgeist/generation.py` (`RunBusy` after `GenerationRefused` ~line 228; `GenerationService.__init__`, `submit`, `_run`; new `_claim`, `_release`, `excluding`)
- Modify: `zeitgeist/api/generate.py` (map `UnknownRun` → 404)
- Modify: `tests/api_factory.py` (add `GatedGenerate` after `GatedExecute`)
- Test: `tests/test_generation.py` (append), `tests/test_api_generate.py` (append)

**Interfaces:**
- Consumes: `UnknownRun`, `Store.delete_run` (Task 1).
- Produces: `class RunBusy(RuntimeError)` in `zeitgeist.generation`; `GenerationService.excluding(self, run_id: str) -> Iterator[None]` (a `contextlib.contextmanager`), raising `RunBusy` on entry if a job for `run_id` is in flight; `submit` raising `UnknownRun` while `run_id` is excluded or once its row is gone. `tests.api_factory.GatedGenerate` — a `GenerateFn` with `entered` and `release` events.

- [ ] **Step 1: Add `GatedGenerate` to the test factory**

In `tests/api_factory.py`, after `GatedExecute`:

```python
@dataclass
class GatedGenerate:
    """A generation job that blocks until released, so a test can hold a
    job in flight without sleeping. The on-demand counterpart of
    `GatedExecute`, here for the same reason: the generation unit tests and
    the deletion API tests both need it."""

    entered: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)

    def __call__(self, job, store) -> None:
        self.entered.set()
        assert self.release.wait(timeout=5), "release was never set"
```

- [ ] **Step 2: Write the failing unit tests**

In `tests/test_generation.py`, add `from tests.api_factory import GatedGenerate`, add `RunBusy` to the `zeitgeist.generation` import, and change the store import to `from zeitgeist.store import MissingCheckpoint, Store, UnknownRun`. Append:

```python
MANUAL = ManualGeneration(template_id=TEMPLATE, caption_slots=SLOTS)


def test_a_run_cannot_be_excluded_while_a_job_for_it_is_in_flight(tmp_path):
    """The job would write PNGs under the run's directory after the delete
    removed it, recreating a directory nothing would ever reclaim."""
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    gate = GatedGenerate()
    service = _service(tmp_path, store, generate=gate)
    try:
        service.submit("run-1", "airport-cat", MANUAL)
        assert gate.entered.wait(timeout=5)

        with pytest.raises(RunBusy), service.excluding("run-1"):
            pass
    finally:
        gate.release.set()
        service.shutdown()
    store.close()


def test_a_run_can_be_excluded_once_its_jobs_have_finished(tmp_path):
    """The count comes back down when a job ends. Without that, the first
    meme ever generated for a run would make it undeletable for the life
    of the process."""
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    service = _service(tmp_path, store, generate=RecordingGenerate())
    service.submit("run-1", "airport-cat", MANUAL)
    service.shutdown()  # Waits for the job.

    with service.excluding("run-1"):
        pass
    store.close()


def test_a_refused_submit_does_not_leave_its_run_busy(tmp_path):
    """`submit` claims the run before it validates anything, so every path
    out of it that does not hand a job to the pool must let go again."""
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    service = _service(tmp_path, store, generate=RecordingGenerate())

    with pytest.raises(UnknownTopic):
        service.submit("run-1", "no-such-topic", MANUAL)

    with service.excluding("run-1"):
        pass
    service.shutdown()
    store.close()


def test_submit_is_refused_for_a_run_that_is_being_deleted(tmp_path):
    """Otherwise its seed lands after the row is gone and fails on the
    foreign key as a 500."""
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    service = _service(tmp_path, store, generate=RecordingGenerate())

    with service.excluding("run-1"), pytest.raises(UnknownRun):
        service.submit("run-1", "airport-cat", MANUAL)

    assert store.renders_for_topic("run-1", "airport-cat") == []
    service.shutdown()
    store.close()


def test_excluding_one_run_leaves_another_free(tmp_path):
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    store.start_run("run-2", make_run_config())
    store.write_analyse_checkpoint("run-2", [make_topic("airport-cat")], 0.3)
    service = _service(tmp_path, store, generate=RecordingGenerate())

    with service.excluding("run-1"):
        records = service.submit("run-2", "airport-cat", MANUAL)

    assert [r.run_id for r in records] == ["run-2"]
    service.shutdown()
    store.close()


def test_submit_names_a_run_that_no_longer_exists(tmp_path):
    """A delete that finished between the endpoint's own existence check
    and this call. Without the check, `read_checkpoint` answers first with
    `MissingCheckpoint` — a 409 claiming the run never analysed."""
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    store.delete_run("run-1")
    service = _service(tmp_path, store, generate=RecordingGenerate())

    with pytest.raises(UnknownRun):
        service.submit("run-1", "airport-cat", MANUAL)
    service.shutdown()
    store.close()
```

- [ ] **Step 3: Write the failing endpoint test**

In `tests/test_api_generate.py`, append:

```python
def test_generating_for_a_run_that_is_being_deleted_is_a_404(tmp_path):
    client = _client(tmp_path)

    with app_of(client).state.generator.excluding(RUN):
        response = client.post(
            _url(),
            json={"mode": "manual", "template_id": TEMPLATE, "caption_slots": SLOTS},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == f"No such run: {RUN}"
```

- [ ] **Step 4: Run to verify they fail**

Run: `uv run pytest tests/test_generation.py tests/test_api_generate.py -v`
Expected: collection error — `ImportError: cannot import name 'RunBusy'` (and the endpoint test, once that exists, fails with `AttributeError: ... 'excluding'`).

- [ ] **Step 5: Implement**

In `zeitgeist/generation.py`:

Imports — change `from collections.abc import Callable` to `from collections.abc import Callable, Iterator`, add `from contextlib import contextmanager`, and change `from zeitgeist.store import Store` to `from zeitgeist.store import Store, UnknownRun`.

After `GenerationRefused`:

```python
class RunBusy(RuntimeError):
    """A generation job for the run is still in flight, so the run cannot
    be deleted yet. The endpoint answers 409: nothing is wrong with the
    request, it has only come too early."""
```

In `GenerationService.__init__`, after `self._lock = threading.Lock()`:

```python
        # Jobs submitted and not yet finished, per run, and the runs being
        # deleted right now — both under `_lock`. The stored `generating`
        # status cannot stand in for the first: nothing reconciles those
        # rows after a restart, so a run whose server died mid-job would
        # hold them forever and could never be deleted.
        self._in_flight: dict[str, int] = {}
        self._deleting: set[str] = set()
```

Add these methods after `shutdown`:

```python
    def _claim(self, run_id: str) -> None:
        """Count a job against `run_id`, unless the run is being deleted."""
        with self._lock:
            if run_id in self._deleting:
                raise UnknownRun(f"No such run: {run_id}")
            self._in_flight[run_id] = self._in_flight.get(run_id, 0) + 1

    def _release(self, run_id: str) -> None:
        with self._lock:
            remaining = self._in_flight.get(run_id, 0) - 1
            if remaining > 0:
                self._in_flight[run_id] = remaining
            else:
                self._in_flight.pop(run_id, None)

    @contextmanager
    def excluding(self, run_id: str) -> Iterator[None]:
        """Hold off new jobs for `run_id` while it is deleted.

        Refuses with `RunBusy` if a job is already in flight: it would
        write PNGs under the run's directory after the delete removed it.
        Otherwise `submit` refuses the run until this exits. With
        `submit`'s claim-then-check, every interleaving is covered: its
        claim lands first and this refuses; this lands first and the claim
        is refused; or the delete finishes first and `submit` finds no row.
        """
        with self._lock:
            if self._in_flight.get(run_id, 0):
                raise RunBusy(
                    f"Memes are still generating for run {run_id}; wait for "
                    "them to finish before deleting it."
                )
            self._deleting.add(run_id)
        try:
            yield
        finally:
            with self._lock:
                self._deleting.discard(run_id)
```

In `submit`, add to the docstring's last paragraph: "`UnknownRun` means the run is being deleted, or already has been." Then restructure the body so that everything after `pool = self._ensure_pool()` runs inside a claim. The complete new body:

```python
        pool = self._ensure_pool()
        # Claimed before anything is read, so a delete arriving from here
        # on is refused rather than removing the run under this request.
        self._claim(run_id)
        handed_off = False
        try:
            if self._store.get_run(run_id) is None:
                raise UnknownRun(f"No such run: {run_id}")

            settings = resolve_settings(self._store, self._settings, {})

            topics = self._store.read_checkpoint(run_id, Stage.ANALYSE, Topic)
            topic = next((t for t in topics if t.id == topic_id), None)
            if topic is None:
                raise UnknownTopic(f"No such topic in {run_id}: {topic_id}")

            templates = load_templates(settings.templates_dir)
            if (
                request.template_id is not None
                and request.template_id not in templates
            ):
                raise GenerationRefused(
                    f"template_id {request.template_id!r} is not in the library; "
                    f"choose one of: {', '.join(sorted(templates))}"
                )

            provider: LLMProvider | None = None
            if isinstance(request, ManualGeneration):
                problem = check_slots(
                    request.template_id, request.caption_slots, templates
                )
                if problem is not None:
                    raise GenerationRefused(problem)
            else:
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
                request.template_id or "(the model's choice)",
            )
            try:
                pool.submit(self._run, run_id, job)
            except RuntimeError as exc:
                self._fail_unfinished(self._store, job, exc)
                raise GenerationUnavailable(str(exc)) from exc
            handed_off = True
            return records
        finally:
            # Once the pool has the job, `_run` releases it when the job
            # ends. Every other way out of here must release it now.
            if not handed_off:
                self._release(run_id)
```

Before replacing, diff this against the current body: apart from the claim, the `get_run` check, the `try`/`finally`, `pool.submit(self._run, run_id, job)` and the line wraps the extra indent forces, it must be identical. Keep any comments the current body carries in the same places.

Change `_run` to take the run id and release it:

```python
    def _run(self, run_id: str, job: GenerationJob) -> None:
```

and extend its `finally`:

```python
        finally:
            store.close()
            self._release(run_id)
```

Add one sentence to `_run`'s docstring: "Releases the run's claim when the job ends, however it ends, so `excluding` stops refusing its deletion."

In `zeitgeist/api/generate.py`, change the store import to `from zeitgeist.store import MissingCheckpoint, Store, UnknownRun`, and add directly after the `except UnknownTopic` branch:

```python
    except UnknownRun as exc:
        # Deleted — or being deleted — since `_run_or_404` above passed.
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/test_generation.py tests/test_api_generate.py -v`
Expected: all passed, existing tests included.

- [ ] **Step 7: Commit**

```bash
git add zeitgeist/generation.py zeitgeist/api/generate.py tests/api_factory.py tests/test_generation.py tests/test_api_generate.py
git commit -m "Track generation jobs per run so a run is not deleted under one"
```

---

### Task 5: `DELETE /api/runs/{run_id}` and `RunDetail.render_count`

**Files:**
- Modify: `zeitgeist/api/schemas.py` (`RunDetail` ~line 125)
- Modify: `zeitgeist/api/runs.py` (`read_run` ~line 85; new endpoint after `read_run`; module docstring)
- Regenerate: `web/openapi.json`, `web/src/api/schema.ts`
- Modify: `web/src/test/factories.ts` (`makeRunDetail` ~line 147)
- Test: `tests/test_api_runs.py` (append), `tests/test_api_generate.py` (append)

**Interfaces:**
- Consumes: `RunService.delete`, `RunAlreadyActive` (Task 3); `GenerationService.excluding`, `RunBusy` (Task 4); `UnknownRun` (Task 1); `delete_run_files` (Task 2); `GatedGenerate` (Task 4).
- Produces: `DELETE /api/runs/{run_id}` → 204 / 404 / 409; `RunDetail.render_count: int`; TS `RunDetail["render_count"]: number`; `makeRunDetail({ renderCount?: number })`, defaulting to 0.

- [ ] **Step 1: Write the failing API tests**

In `tests/test_api_runs.py`, add `GatedExecute` to the `tests.api_factory` import and `from zeitgeist.renders import render_paths`. Append:

```python
def test_run_detail_counts_the_memes_that_exist(tmp_path):
    """What the Delete confirm tells the user they will lose. A generating
    or failed row is not a meme anyone can see."""
    run_id = "20260901T120000Z"
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id=run_id,
                renders=[
                    make_render_record("a", run_id=run_id, status="ready"),
                    make_render_record("b", run_id=run_id, status="ready"),
                    make_render_record("c", run_id=run_id, status="generating"),
                    make_render_record(
                        "d", run_id=run_id, status="failed", error="no fit"
                    ),
                ],
            )
        ],
    )

    assert client.get(f"/api/runs/{run_id}").json()["render_count"] == 2


def test_deleting_a_run_removes_it_everywhere(tmp_path):
    run_id = "20260901T120000Z"
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id=run_id,
                renders=[make_render_record("rnd1", run_id=run_id)],
            )
        ],
    )
    png = render_paths(tmp_path / "output", run_id, "rnd1").full
    png.parent.mkdir(parents=True)
    png.write_bytes(b"not really a png")

    response = client.delete(f"/api/runs/{run_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/api/runs/{run_id}").status_code == 404
    assert client.get("/api/renders/rnd1").status_code == 404
    assert client.get("/api/runs").json()["runs"] == []
    assert not (tmp_path / "output" / run_id).exists()


def test_deleting_an_unknown_run_is_a_404(tmp_path):
    client = seeded_client(tmp_path)

    response = client.delete("/api/runs/nope")

    assert response.status_code == 404
    assert response.json()["detail"] == "No such run: nope"


def test_a_run_in_flight_cannot_be_deleted_until_it_is_over(tmp_path):
    gate = GatedExecute()
    client = seeded_client(tmp_path, execute=gate)
    runner = app_of(client).state.runner
    try:
        run_id = client.post("/api/runs", json={}).json()["run_id"]
        assert gate.entered.wait(timeout=5)

        refused = client.delete(f"/api/runs/{run_id}")

        assert refused.status_code == 409
        assert refused.json()["detail"] == (
            f"Run {run_id} is queued or executing; abort it before deleting it."
        )
        assert client.get(f"/api/runs/{run_id}").status_code == 200
    finally:
        gate.release.set()
        runner.shutdown(timeout=10)

    # The refusal was about the run being live, not about the run.
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
```

In `tests/test_api_generate.py`, add `GatedGenerate` to the `tests.api_factory` import and append:

```python
def test_a_run_cannot_be_deleted_while_its_memes_are_generating(tmp_path):
    gate = GatedGenerate()
    client = _client(tmp_path, generate=gate)
    try:
        posted = client.post(
            _url(),
            json={"mode": "manual", "template_id": TEMPLATE, "caption_slots": SLOTS},
        )
        assert posted.status_code == 202
        assert gate.entered.wait(timeout=5)

        refused = client.delete(f"/api/runs/{RUN}")

        assert refused.status_code == 409
        assert refused.json()["detail"] == (
            f"Memes are still generating for run {RUN}; wait for them to "
            "finish before deleting it."
        )
        assert client.get(f"/api/runs/{RUN}").status_code == 200
    finally:
        gate.release.set()
        app_of(client).state.generator.shutdown()

    assert client.delete(f"/api/runs/{RUN}").status_code == 204
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_api_runs.py tests/test_api_generate.py -k "delet or memes_that_exist" -v`
Expected: FAIL — `KeyError: 'render_count'` and 405 Method Not Allowed for the DELETEs.

- [ ] **Step 3: Implement `render_count`**

In `zeitgeist/api/schemas.py`, add to `RunDetail` after `resume_stage`:

```python
    # Ready renders only, as every count here is: what the Delete confirm
    # tells the user goes with the run. A generating or failed row is not a
    # meme anyone can see.
    render_count: int
```

In `zeitgeist/api/runs.py`, `read_run` becomes:

```python
@router.get("/{run_id}", response_model=RunDetail)
def read_run(run_id: str, store: Store = Depends(get_store)) -> RunDetail:
    run = _run_or_404(store, run_id)
    return RunDetail(
        run=run,
        stages=store.stages_for_run(run_id),
        resume_stage=resume_stage(store, run_id),
        render_count=sum(store.render_counts(run_id).values()),
    )
```

- [ ] **Step 4: Implement the endpoint**

In `zeitgeist/api/runs.py`, change the imports:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from zeitgeist.api.app import get_generator, get_runner, get_settings, get_store
```

and add:

```python
from zeitgeist.config import Settings
from zeitgeist.generation import GenerationService, RunBusy
from zeitgeist.renders import delete_run_files
from zeitgeist.runner import RunAlreadyActive, RunService
from zeitgeist.store import MissingCheckpoint, Store, UnknownRun, run_cursor
```

(replacing the existing `zeitgeist.store` import). Change the module docstring to:

```python
"""Everything scoped to one run: the list, the detail, the ranking, one
topic's dossier, the log — and deleting it.
"""
```

After `read_run`, add:

```python
@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_run(
    run_id: str,
    runner: RunService = Depends(get_runner),
    generator: GenerationService = Depends(get_generator),
    settings: Settings = Depends(get_settings),
) -> Response:
    """204 and no body. The row goes first, cascading to everything that
    hangs off it, then the run's directory.

    Refused with a 409 while anything is still writing to the run: the run
    worker, if it is executing or queued, or an on-demand generation job.
    `excluding` holds new generation jobs off for as long as the row delete
    takes; `RunService.delete` does the liveness check and the delete under
    the lock `enqueue` takes, so a resume cannot interleave. The directory
    is removed after both are released — the run no longer exists by then,
    so nothing can write to it again.
    """
    try:
        with generator.excluding(run_id):
            runner.delete(run_id)
    except UnknownRun as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RunAlreadyActive, RunBusy) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    delete_run_files(settings.output_dir, run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 5: Run the API tests**

Run: `uv run pytest tests/test_api_runs.py tests/test_api_generate.py -v`
Expected: all passed.

- [ ] **Step 6: Regenerate the contract and the client types**

```bash
uv run python scripts/dump_openapi.py
npm --prefix web run generate:types
```

- [ ] **Step 7: Carry `render_count` into the frontend factory**

In `web/src/test/factories.ts`, `makeRunDetail`'s options gain:

```ts
    /** Ready memes, which the Delete confirm counts. Most screens ignore it. */
    renderCount?: number;
```

and the returned object gains, after `resume_stage`:

```ts
    render_count: options.renderCount ?? 0,
```

- [ ] **Step 8: Run the full gate**

Run all seven commands from Global Constraints.
Expected: all pass. `uv run pytest` includes `test_checked_in_openapi_matches_the_app`; `npm --prefix web run typecheck` confirms `schema.ts` matches `openapi.json`.

- [ ] **Step 9: Commit**

```bash
git add zeitgeist/api/schemas.py zeitgeist/api/runs.py web/openapi.json web/src/api/schema.ts web/src/test/factories.ts tests/test_api_runs.py tests/test_api_generate.py
git commit -m "Add DELETE /api/runs/{run_id} and the run's meme count"
```

---

### Task 6: `useDeleteRun` and the Delete control

**Files:**
- Modify: `web/src/api/queries.ts` (new hook after `useDeleteRender`)
- Modify: `web/src/features/runs/RunActions.tsx`
- Test: `web/src/api/queries.test.tsx` (append a `describe("useDeleteRun")`), `web/src/features/runs/RunDetailPage.test.tsx` (append inside `describe("RunDetailPage")`, after `"reports a refused action rather than swallowing it"`)

**Interfaces:**
- Consumes: `DELETE /api/runs/{run_id}`, `RunDetail.render_count`, `makeRunDetail({ renderCount })` (Task 5).
- Produces: `useDeleteRun(runId: string): UseMutationResult<void, ApiError, void>`.

- [ ] **Step 1: Write the failing hook tests**

In `web/src/api/queries.test.tsx`, add `useDeleteRun` to the `@/api/queries` import. Append:

```tsx
describe("useDeleteRun", () => {
  const RUN = "20260829T090000Z";

  /**
   * Answers each of the run's own reads once and holds every later one
   * open. A refetch then sits at `fetchStatus: "fetching"` for good, so a
   * check made after the mutation cannot miss one that came and went.
   */
  function serveRunOnce() {
    let runCalls = 0;
    let rankingCalls = 0;
    server.use(
      http.get("/api/runs/:runId", async () => {
        runCalls += 1;
        if (runCalls > 1) await new Promise(() => undefined);
        return HttpResponse.json(makeRunDetail({ runId: RUN }));
      }),
      http.get("/api/runs/:runId/topics", async () => {
        rankingCalls += 1;
        if (rankingCalls > 1) await new Promise(() => undefined);
        return HttpResponse.json([makeRankedTopic()]);
      }),
    );
  }

  it("does not refetch the run's own queries, which the page is still showing", async () => {
    // Refetched, the detail 404s and the page draws "No such run." for a
    // frame before it navigates away.
    serveRunOnce();
    server.use(
      http.delete("/api/runs/:runId", () => new HttpResponse(null, { status: 204 })),
    );

    const { result } = renderHook(
      () => ({
        run: useRun(RUN),
        ranking: useRanking(RUN),
        remove: useDeleteRun(RUN),
        client: useQueryClient(),
      }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.run.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.ranking.isSuccess).toBe(true));

    await act(async () => {
      await result.current.remove.mutateAsync();
    });

    const { client } = result.current;
    expect(client.getQueryState(queryKeys.run(RUN))?.fetchStatus).toBe("idle");
    expect(client.getQueryState(queryKeys.ranking(RUN))?.fetchStatus).toBe("idle");
    // ...but stale, so arriving back at the run asks the server again
    // rather than drawing a deleted run from cache.
    expect(client.getQueryState(queryKeys.run(RUN))?.isInvalidated).toBe(true);
  });

  it("refreshes the runs list and the topics index, which both just lost a run", async () => {
    let listCalls = 0;
    let indexCalls = 0;
    server.use(
      http.get("/api/runs", () => {
        listCalls += 1;
        return HttpResponse.json(makeRunPage());
      }),
      http.get("/api/topics", () => {
        indexCalls += 1;
        return HttpResponse.json(makeTopicIndex());
      }),
      http.delete("/api/runs/:runId", () => new HttpResponse(null, { status: 204 })),
    );

    const { result } = renderHook(
      () => ({ runs: useRuns(), topics: useTopicIndex(), remove: useDeleteRun(RUN) }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.runs.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.topics.isSuccess).toBe(true));

    await act(async () => {
      await result.current.remove.mutateAsync();
    });

    await waitFor(() => expect(listCalls).toBe(2));
    await waitFor(() => expect(indexCalls).toBe(2));
  });

  it("counts a run that is already gone as deleted", async () => {
    // Deleted in another tab. The end state asked for is the one the
    // server reports.
    server.use(
      http.delete("/api/runs/:runId", () =>
        HttpResponse.json({ detail: `No such run: ${RUN}` }, { status: 404 }),
      ),
    );

    const { result } = renderHook(() => useDeleteRun(RUN), {
      wrapper: renderWithProviders.Wrapper,
    });

    await act(async () => {
      await result.current.mutateAsync();
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("passes any other refusal through for the page to show", async () => {
    server.use(
      http.delete("/api/runs/:runId", () =>
        HttpResponse.json({ detail: "Memes are still generating" }, { status: 409 }),
      ),
    );

    const { result } = renderHook(() => useDeleteRun(RUN), {
      wrapper: renderWithProviders.Wrapper,
    });

    await act(async () => {
      await result.current.mutateAsync().catch(() => undefined);
    });

    await waitFor(() => expect(result.current.error?.status).toBe(409));
    expect(result.current.error?.detail).toBe("Memes are still generating");
  });
});
```

Check the existing imports cover `makeRunPage`, `makeTopicIndex`, `makeRankedTopic`, `makeRunDetail`, `useRuns`, `useRun`, `useRanking`, `useTopicIndex` (all are imported at the top of the file today) and that `ApiError` exposes `status` and `detail` (it does — `client.ts:12`).

- [ ] **Step 2: Write the failing page tests**

In `web/src/features/runs/RunDetailPage.test.tsx`, inside `describe("RunDetailPage")`, directly after the test `"reports a refused action rather than swallowing it"`:

```tsx
  describe("deleting a finished run", () => {
    function serveOver(renderCount = 0) {
      server.use(
        http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
        http.get("/api/runs/:runId", () =>
          HttpResponse.json(makeRunDetail({ runId: RUN_ID, renderCount })),
        ),
        http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
        http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
      );
    }

    function renderRoutes() {
      return renderWithProviders(
        <Routes>
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="*" element={<Landed />} />
        </Routes>,
        { route: `/runs/${RUN_ID}` },
      );
    }

    it("offers Delete once a run is over", async () => {
      serveOver();
      renderRoutes();

      expect(await screen.findByRole("button", { name: "Delete" })).toBeEnabled();
    });

    it("offers no Delete while the run is live", async () => {
      // Abort first. The worker is still writing to a live run, and the
      // server would refuse anyway.
      server.use(...liveRun());
      renderDetail();

      await screen.findByRole("button", { name: "Abort" });
      expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    });

    it.each([
      [0, "Delete run?"],
      [1, "Delete run and its 1 meme?"],
      [3, "Delete run and its 3 memes?"],
    ])("with %i memes, asks %j before deleting anything", async (count, question) => {
      const user = userEvent.setup();
      let deletes = 0;
      serveOver(count);
      server.use(
        http.delete("/api/runs/:runId", () => {
          deletes += 1;
          return new HttpResponse(null, { status: 204 });
        }),
      );
      renderRoutes();

      await user.click(await screen.findByRole("button", { name: "Delete" }));

      expect(screen.getByText(question)).toBeInTheDocument();
      expect(deletes).toBe(0);
    });

    it.each([204, 404])(
      "deletes this run on yes and lands on the runs list when the server answers %i",
      async (status) => {
        // 404: deleted in another tab, which is the outcome asked for.
        const user = userEvent.setup();
        let deleted = "";
        serveOver();
        server.use(
          http.delete("/api/runs/:runId", ({ params }) => {
            deleted = String(params.runId);
            return status === 204
              ? new HttpResponse(null, { status })
              : HttpResponse.json({ detail: `No such run: ${deleted}` }, { status });
          }),
        );
        renderRoutes();

        await user.click(await screen.findByRole("button", { name: "Delete" }));
        await user.click(screen.getByRole("button", { name: "yes" }));

        expect(await screen.findByText("landed on /runs")).toBeInTheDocument();
        expect(deleted).toBe(RUN_ID);
      },
    );

    it("says why when the server will not delete, and stays on the run", async () => {
      const user = userEvent.setup();
      const detail = `Memes are still generating for run ${RUN_ID}; wait for them to finish before deleting it.`;
      serveOver();
      server.use(
        http.delete("/api/runs/:runId", () =>
          HttpResponse.json({ detail }, { status: 409 }),
        ),
      );
      renderRoutes();

      await user.click(await screen.findByRole("button", { name: "Delete" }));
      await user.click(screen.getByRole("button", { name: "yes" }));

      expect(await screen.findByText(detail)).toBeInTheDocument();
      expect(screen.queryByText(/^landed on/)).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Delete" })).toBeEnabled();
    });
  });
```

`liveRun`, `renderDetail`, `Landed`, `RUN_ID`, `makeActiveRuns`, `makeRunDetail`, `Routes` and `Route` are all already in scope in this file.

- [ ] **Step 3: Run to verify they fail**

Run: `npm --prefix web test -- src/api/queries.test.tsx src/features/runs/RunDetailPage.test.tsx`
Expected: FAIL — `useDeleteRun` is not exported; the page tests find no `Delete` button.

- [ ] **Step 4: Implement `useDeleteRun`**

In `web/src/api/queries.ts`, after `useDeleteRender`:

```ts
/**
 * Delete a run — its rows, its memes and its directory, server-side.
 *
 * A 404 counts as done, as it does for a render: deleted in another tab is
 * the end state asked for, and the page must still leave rather than sit
 * there with an error nobody can act on.
 *
 * The run's own queries are marked stale but not refetched. The detail
 * page is still mounted when this succeeds — it navigates away in the
 * caller's `onSuccess`, which runs after this one — and a refetch of a run
 * that no longer exists answers 404, which drew "No such run." for a frame
 * on the way out. Stale is still needed: without it, pressing Back within
 * the stale time drew the deleted run from cache, Delete button and all.
 *
 * Everything else under `["runs"]` — the list and `active` — is refreshed,
 * with a predicate that leaves this run's keys alone, and so is the topics
 * index, which drew this run's topics. Render records are marked stale the
 * way `useDeleteRender` marks its own.
 */
export function useDeleteRun(runId: string) {
  const client = useQueryClient();
  return useMutation<void, ApiError, void>({
    mutationFn: async () => {
      try {
        await apiDelete(`/api/runs/${encodeURIComponent(runId)}`);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return;
        throw error;
      }
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.run(runId), refetchType: "none" });
      void client.invalidateQueries({
        queryKey: ["runs"],
        predicate: (query) => query.queryKey[1] !== runId,
      });
      void client.invalidateQueries({ queryKey: ["topics"] });
      void client.invalidateQueries({ queryKey: ["renders"], refetchType: "none" });
    },
  });
}
```

- [ ] **Step 5: Implement the Delete control**

In `web/src/features/runs/RunActions.tsx`:

Imports become:

```tsx
import { useRef } from "react";
import { useNavigate } from "react-router-dom";

import type { RunDetail } from "@/api/types";
import { useAbortRun, useDeleteRun, useResumeRun, useStopRun } from "@/api/queries";
```

(the remaining imports unchanged). Above the component, add:

```tsx
/** The confirm's question: what goes with the run, counted. */
function deleteQuestion(memes: number): string {
  if (memes === 0) return "Delete run?";
  return `Delete run and its ${memes} ${memes === 1 ? "meme" : "memes"}?`;
}
```

Append to the component's doc comment, before its closing `*/`:

```
 *
 * Over, a third control: **Delete**, the same swap-in-place confirm in
 * Abort's contrast tone, because it destroys what a run cost minutes and
 * real model calls to make. Its question counts the memes that go with the
 * run — `detail.render_count`, ready renders only — since the hand-written
 * ones are the one part of a run nothing can reproduce. It is absent while
 * the run is live, like Resume: abort first. It carries Resume's pending
 * guard, so a second confirm cannot draw a 409 in the moment before the
 * page leaves. On success it navigates to the Runs list rather than handing
 * focus to the header, which is going too; a refused delete hands focus
 * home like the others, and its sentence joins the failure line — still at
 * most one error per mount, since Delete lives only in the "over" mount
 * beside Resume.
```

In the body, after `const resume = useResumeRun(runId);`:

```tsx
  const remove = useDeleteRun(runId);
  const navigate = useNavigate();
```

and change `failure` to:

```tsx
  const failure = stop.error ?? abort.error ?? resume.error ?? remove.error ?? null;
```

In the "over" branch, after the `detail.resume_stage !== null && (...)` block:

```tsx
          <InlineConfirm
            label="Delete"
            question={deleteQuestion(detail.render_count)}
            disabled={remove.isPending || remove.isSuccess}
            onConfirm={() =>
              remove.mutate(undefined, {
                onSuccess: () => void navigate("/runs"),
                onError: keepFocus,
              })
            }
          />
```

- [ ] **Step 6: Run to verify they pass**

Run: `npm --prefix web test -- src/api/queries.test.tsx src/features/runs/RunDetailPage.test.tsx`
Expected: all passed.

- [ ] **Step 7: Run the full gate**

Run all seven commands from Global Constraints.
Expected: all pass.

- [ ] **Step 8: Check it in the real app**

Start both dev servers (the VS Code task, or `uv run python -m zeitgeist.serve` and `npm --prefix web run dev`), open a finished run, and confirm: Delete sits after Re-run config and Resume; the question counts its memes; `yes` lands on the Runs list with the run gone, no "No such run." flash on the way; pressing Back shows "No such run."; the run's `output/<run_id>/` directory is gone.

- [ ] **Step 9: Commit**

```bash
git add web/src/api/queries.ts web/src/api/queries.test.tsx web/src/features/runs/RunActions.tsx web/src/features/runs/RunDetailPage.test.tsx
git commit -m "Add Delete to a finished run's header"
```
