# Generation Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make memes from the browser — the two generation panels on topic
detail, the rendered grid with every tile state, the inline delete confirm,
the below-the-cut `generate ↗`, and the nothing-rendered-yet row. This is
phase 7 of `docs/superpowers/specs/2026-09-02-web-ui-design.md`, and it ends
with the design built.

**Architecture:** One Python task first. The design's LLM panel defaults to
"Let the LLM choose", and phase 4's contract makes `template_id` required, so
Task 1 makes the template optional on the request and on the render record
until the model picks one (schema version 5). After that, seven React tasks:
the mutation and polling hooks; `InlineConfirm`'s tile variant; the grid and
its tile states; the LLM panel; the manual panel; the below-the-cut link;
delete on the full-size view. The last task walks all of it against a real
run.

**Tech Stack:** Python 3.14, FastAPI, pydantic 2, SQLite. React 19,
TypeScript 5.7, Vite 7, TanStack Query 5, React Router 7, CSS Modules,
Vitest + Testing Library + MSW.

## Global Constraints

- **Definition of Done.** All seven commands pass before any task is
  reported finished: `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run ty check`, `uv run pytest`, `npm --prefix web run lint`,
  `npm --prefix web run typecheck`, `npm --prefix web test`. **No red
  window:** the tree is green at the start of every task and at the end of it.
- **Python 3.14.** PEP 695 generics (`def f[T: Bound](...)`), never
  `typing.TypeVar`.
- **ruff.** Rules `E, F, I, UP, B, SIM`, line length 88.
- **ty.** No blanket `# type: ignore`. A narrow suppression needs a comment
  saying why.
- **`model_config = STRICT`** on every pydantic model.
- **Optionality expresses a real state, never a migration concession.** A
  field is `| None` only where there genuinely is no value.
- **No migrations.** Bumping `SCHEMA_VERSION` means deleting
  `data/zeitgeist.db`. `StoreSchemaError` refusing a mismatched file is the
  whole strategy.
- **TypeScript.** No `any`, no `!`, no `as`. `eslint.config.js` enforces all
  three. `src/api/client.ts` is the one file exempt from the assertion rule.
  Anything that needs to narrow untyped JSON goes there or uses a
  `value is T` predicate. `noUncheckedIndexedAccess` is on, so `array[0]` is
  `T | undefined`, including in tests.
- **No raw colours in `.module.css`.** `src/styles/no-raw-colours.test.ts`
  fails on any `#hex` or `rgba(` outside `tokens.css`, with
  `StageBar.module.css` the one documented exception. **No new tokens either**
  — the spec's rule for this app's undesigned states. Where the handoff
  names an in-between value (accent at 40%, white at 12%), the nearest
  existing token is used and the choice is named in a comment.
- **No `styles.foo` without a matching class.** The same test file checks
  every static `styles.x` against its paired stylesheet.
- **Contract drift is a gate, twice.** `uv run pytest` asserts
  `web/openapi.json` matches the app; `npm --prefix web run typecheck`
  asserts `web/src/api/schema.ts` matches `web/openapi.json`. After any
  model change run `uv run python scripts/dump_openapi.py` and then
  `npm --prefix web run generate:types`.
- **Tests are hermetic.** `tests/conftest.py` strips every environment
  variable `Settings` reads. No network. Every model call goes through
  `FakeLLMProvider`. No test sleeps to synchronise with a thread —
  `GenerationService.shutdown()` waits on the pool.
- **MSW declares every response.** `src/test/server.ts` has no default
  handlers and `setup.ts` sets `onUnhandledRequest: "error"`.
- **Fixtures come from factories.** `tests/run_factory.py`,
  `tests/template_factory.py`, `tests/api_factory.py` and
  `web/src/test/factories.ts`. Never a hand-written dict or object literal
  standing in for a contract type. Request bodies a test *posts* are the
  exception, because a test pinning what a screen sends must spell it out.
- **No modals.** Every confirmation swaps in place.
- **Copy is final.** Where this plan quotes UI text it is the design's own
  wording, or the spec's for the states the design did not draw, transcribed
  exactly: `Ask the LLM`, `Writes fresh briefs from the dossier, then renders
  them. Costs a model call each.`, `Template`, `optional`, `Let the LLM
  choose`, `picks the templates that suit funny / riffing`, `How many`,
  `Generate 3 memes`, `Write it yourself`, `Straight to the renderer. No model
  call.`, `change ▾`, `type a caption…`, `Render`, `Rendered from this
  topic`, `2 from …829T090000Z · 1 generating`, `Delete this render?`, `yes`,
  `no`, `writing brief…`, `Nothing rendered yet — use the panel above`,
  `generate ↗`.

---

## Decisions this phase is required to make

Items 1–3 were put to the user before this plan was written. Their answers
are recorded here with the reasoning, so an implementer does not reopen
them.

### 1. The model can choose the template — a contract change, made first

The handoff's LLM panel defaults to **Let the LLM choose**, with the
template tiles as optional overrides. Phase 4 made
`LLMGeneration.template_id` required. Its docstring says "the panel already
made that choice", which is the opposite of what the panel's default does.
`generate_brief` already picks from any library it is handed, because the
pipeline's generate stage has always worked that way. So the fix is
`template_id: str | None = None` on the request, with `None` meaning the
whole library.

That leaves the seeded row. `GenerationService._seed` writes a `generating`
row before the POST returns, and `RenderRecord.template_id` is `str`. When
the model is choosing, no template exists yet. `RenderRecord.template_id`
becomes `str | None`:

- **None** on a `generating` row whose request left the choice to the model.
- **None** on a `failed` row whose brief failed before the model chose.
- **A template id** on every other row, written by `_draw` from the brief.

Both `None` cases are real states, not placeholders: a template genuinely has
not been chosen. That is why this is `| None` rather than an empty-string
sentinel extending phase 4's "must not be read" rule to a third field. The
`renders.template_id` column loses its `NOT NULL`, and `SCHEMA_VERSION` goes
to 5. The generating tile's footer reads `choosing… · auto` until the row
names a template.

The below-the-cut `generate ↗` uses the same path. A ranking row has no room
to ask which template, and "let the model choose" is the panel's own
default, so the link posts `{mode: "llm", template_id: null, count: 1}`.

### 2. HOW MANY is `1` / `3`, default 3 — `MAX_RENDERS` stays 4

The design draws `1 / 3 / 5`. Phase 4 capped a request at `MAX_RENDERS = 4`
so that one click cannot start an unbounded run of model calls on what may
be a single local GPU. The user kept the cap, so the `5` pill goes. `3`
stays the default, and the button reads `Generate 3 memes`. No backend
change.

### 3. Template tiles are stripes

The 60px preview on each template tile stays the stripe placeholder the
mockup draws. Nothing serves a blank template's image, and adding an
endpoint for it is a contract addition this phase does not need. The tile
still says what matters: the id and its slot count.

### 4. The generating bar sweeps rather than claiming 45%

The mockup's generating tile draws a bar 45% full. Nothing reports how far
along a brief is, so a fixed 45% would be a number made up for the screen.
The bar is an indeterminate sweep: a 45%-wide accent segment moving across
the track. It stops under `prefers-reduced-motion`.

### 5. Only a ready tile asks before its `✕` acts

The handoff draws the confirm on a ready tile, and says the generating
tile's `✕` "acts as cancel". What each `✕` does:

| Tile | `✕` | Why |
| --- | --- | --- |
| ready | asks — `Delete this render?` `yes` / `no` | A PNG someone may want. |
| generating | cancels at once | Nothing has been made yet, so only the wait is lost. |
| failed | dismisses at once | No image to lose; the tile only carries a reason. |

Cancel and dismiss are both `DELETE /api/renders/{id}`. On a generating row
the job keeps running server-side. `generation._draw` then updates a row
that no longer exists, which is a no-op, so the result is discarded and the
tile never comes back. The orphaned PNG is reclaimed with the run directory,
as `_draw`'s docstring already says.

### 6. `writing brief…` only where there is a brief to write

The mockup draws `writing brief…` on a tile labelled `drake · manual`. A
hand-written render has no brief; its captions arrived with the request.
Model renders say `writing brief…`, and hand-written ones say `rendering…`.

### 7. The `Track — not built yet` tile is not drawn

The spec's "Deferred" section keeps music output out of scope, with no
pipeline behind it. A tile announcing an output type with no plan to build
it is a promise the app cannot keep. Its absence is recorded in the spec by
Task 9.

### 8. Placeholders come from the request in flight, not from the cache

"Both buttons immediately append placeholder tiles to the rendered grid in
the generating state, one per requested meme." The POST answers in
milliseconds with real `generating` rows, but the gap is real, and the rows
need ids a placeholder does not have.

So the placeholders are drawn from each generate mutation's own
`variables` while it is pending: TanStack Query 5's "optimistic update via
the UI" pattern. The page owns both panels' mutations and hands the grid
what is pending. When the reply lands, `onSuccess` writes the rows into the
cached topic detail. TanStack awaits `onSuccess` before the mutation stops
being pending, so the placeholders give way to the real rows with no gap in
between. Nothing is written to the cache that the server did not send, so
there is nothing to roll back when a request is refused. The placeholder
simply goes, and the panel shows the server's sentence.

### 9. Topic detail polls while anything is generating

The only live thing on topic detail is a render finishing. `useTopicDetail`
polls every 1.5s while any row is `generating` and stops when none is, like
`useActiveRun`. When the number still generating drops, it invalidates the
runs and topics caches. Each of them counts ready renders only
(`render_count`, `render_ids`), and one just became ready.

### 10. The grid header grows the counts it now has

Phase 5's hint was `2 from …829T090000Z`, counting ready renders. With
generating and failed rows on screen, the design's
`2 from run_0829T0900 · 1 generating` form applies, plus `· 1 failed` when
there is one. Each extra clause appears only when its count is non-zero, so
a settled topic reads exactly as it did in phase 5.

### 11. The full-size view gets its Delete

The spec's full-size meme view has "a ghost **Delete** carrying the same
inline confirm as the tile". Phase 5 built that view read-only, and deletion
is this phase's. On success it returns to the topic the render came from.

---

## What phases 1–6 left you

Read these before starting. Every one is load-bearing for some task below.

**Backend**

- `zeitgeist/generation.py` — `MAX_RENDERS`, `LLMGeneration`,
  `ManualGeneration`, `GenerationRequest`, `GenerationJob`,
  `generate_renders`, `_brief_for`, `_draw`, `GenerationService` (`submit`,
  `_seed`, `_run`, `_fail_unfinished`, `shutdown`), `UnknownTopic`,
  `GenerationRefused`.
- `zeitgeist/api/generate.py` — `POST /api/runs/{run_id}/topics/{topic_id}/renders`
  (202 with `generating` rows; 404 unknown topic; 409 no analyse
  checkpoint; 400 for an unknown template, bad captions or a missing API
  key).
- `zeitgeist/api/renders.py` — `GET /api/renders/{id}`, `.../image`,
  `DELETE /api/renders/{id}` (204; 404 for no such render).
- `zeitgeist/records.py` — `RenderRecord`, `AutoOrigin`, `ManualOrigin`,
  `Origin`.
- `zeitgeist/media/brief.py` — `generate_brief(topic, templates, provider)`
  picks from whatever library it is given and validates the answer against
  it.
- `zeitgeist/schema.py` — `SCHEMA_VERSION = 4`, the `renders` DDL.
- `zeitgeist/store.py` — `add_render`, `add_renders`, `get_render`,
  `renders_for_topic`, `update_render`, `delete_render`, and `_render`,
  which reads a row back.
- `tests/test_generation.py` — `TEMPLATE`, `SLOTS`, `_settings`, `_store`,
  `_seeded`, `_job`, `_service`, `_seed_topics`, `RecordingGenerate`.
- `tests/test_api_generate.py` — `_client`, `_url`, `RecordingGenerate`.
- `tests/run_factory.py` — `make_render_record`, `make_topic`.

**Frontend**

- `src/api/client.ts` — `apiGet`, `apiSend` (POST/PUT, parses the reply),
  `imageUrl`, `ApiError`.
- `src/api/types.ts` — every alias; `TemplateOption` (`id`, `slots`).
- `src/api/queries.ts` — `queryKeys`, `useTopicDetail`, `useConfigOptions`,
  `useRanking`, `ACTIVE_POLL_MS`; the mutation hooks as a pattern.
- `src/components/` — `InlineConfirm` (Abort's and Resume's confirm; its
  docstring already names phase 7's delete), `MemeTile` (34/42/96, failed on
  `onError`), `SectionLabel`, `QueryBoundary`, `Chip`.
- `src/features/topics/TopicDetailPage.tsx` and `RenderGrid.tsx` (ready
  renders only, with a note that phase 7 draws the rest).
- `src/features/runs/RankRow.tsx` — `generate ↗` as text inside the row's
  own link, with a note that phase 7 makes it an action.
- `src/features/renders/RenderDetailPage.tsx` — the full-size view.
- `src/test/` — `render.tsx` (`renderWithProviders`, `.Wrapper`),
  `server.ts`, `setup.ts`, `factories.ts` (`makeRenderRecord`,
  `makeTopicDetail`, `makeConfigOptions`, `makeRankedTopic`,
  `makeRunDetail`).
- `src/styles/tokens.css` — `--contrast-confirm` was added for "phase 7's
  render tile".

**Design sources**

- `docs/superpowers/UI/README.md` — screen 6 "Topic detail", the
  **Generation** and **Rendered from this topic** paragraphs, and
  "Interactions & Behavior" (Delete a render, Generate, Below-the-cut rows).
- `docs/superpowers/UI/Zeitgeist Mockups.dc.html`, option `2e`
  (lines 986–1033): the two panels and the grid's tile states, with exact
  values.
- The spec's "Empty states" (nothing rendered yet) and "Full-size meme view"
  (the Delete).

---

## File Structure

**Created**

| File | Responsibility |
| --- | --- |
| `web/src/features/topics/RenderTile.tsx` + `.module.css` | One grid tile in each of its states, and `GeneratingTile`, which the grid also uses for placeholders. |
| `web/src/features/topics/RenderGrid.test.tsx` | The grid and its tiles, in isolation. |
| `web/src/features/topics/GeneratePanels.tsx` + `.module.css` | The `1fr 340px` pair. |
| `web/src/features/topics/LlmPanel.tsx` + `.module.css` | Ask the LLM: choose-or-override, how many, generate. |
| `web/src/features/topics/ManualPanel.tsx` + `.module.css` | Write it yourself: template picker, one field per slot, render. |
| `web/src/features/topics/GeneratePanels.test.tsx` | Both panels, through the real page. |

**Modified**

| File | Change |
| --- | --- |
| `zeitgeist/generation.py` | `LLMGeneration.template_id` optional; `_brief_for` offers the whole library for `None`; `submit` validates only a named template. |
| `zeitgeist/records.py` | `RenderRecord.template_id: str \| None`. |
| `zeitgeist/schema.py` | `renders.template_id` nullable; `SCHEMA_VERSION` → 5. |
| `tests/run_factory.py` | `make_render_record(template_id: str \| None)`. |
| `tests/test_generation.py`, `tests/test_api_generate.py` | Tests for letting the model choose. |
| `web/openapi.json`, `web/src/api/schema.ts` | Regenerated. |
| `web/src/api/client.ts` | `apiDelete`. |
| `web/src/api/types.ts` | `LLMGeneration`, `ManualGeneration`, `GenerationRequest`. |
| `web/src/api/queries.ts` | `useTopicDetail` polls while generating; `useGenerateRenders`, `GenerateMutation`, `useDeleteRender`, `GENERATION_POLL_MS`. |
| `web/src/components/InlineConfirm.tsx` + `.module.css` | `variant="tile"`, `ariaLabel`, `resting`. |
| `web/src/components/MemeTile.tsx` + `.module.css` | A `"grid"` size that fills its tile. |
| `web/src/features/topics/RenderGrid.tsx` + `.module.css` | Every state, placeholders, header counts, nothing-rendered-yet. |
| `web/src/features/topics/TopicDetailPage.tsx` | Owns the two mutations; mounts the panels; hands the grid what is pending. |
| `web/src/features/runs/RankRow.tsx` + `.module.css` | The row stops being one anchor; `generate ↗` becomes a button that generates. |
| `web/src/features/renders/RenderDetailPage.tsx` + `.module.css` | A null template's label; Delete. |
| `web/src/test/factories.ts` | `makeRenderRecord({ templateId: null })`. |
| Existing tests | `TopicDetailPage.test.tsx`, `RunDetailPage.test.tsx`, `RenderDetailPage.test.tsx`, `InlineConfirm.test.tsx`, `MemeTile.test.tsx`, `client.test.ts`, `queries.test.tsx`. |
| `README.md` | Schema version; generating memes from the browser. |
| `docs/superpowers/specs/2026-09-02-web-ui-design.md` | The phase 7 entry. |

---

### Task 1: the model may choose, and a render may not have a template yet

The one contract change this phase needs, made once and regenerated once.
See "Decisions", 1.

**Files:**
- Modify: `zeitgeist/generation.py` (`LLMGeneration`, `_brief_for`, `submit`, `_seed`)
- Modify: `zeitgeist/records.py` (`RenderRecord`)
- Modify: `zeitgeist/schema.py` (`SCHEMA_VERSION`, `renders` DDL)
- Modify: `tests/run_factory.py` (`make_render_record`)
- Modify: `web/openapi.json`, `web/src/api/schema.ts` (regenerated)
- Modify: `web/src/test/factories.ts` (`makeRenderRecord`)
- Modify: `web/src/features/topics/RenderGrid.tsx`, `web/src/features/renders/RenderDetailPage.tsx` (a null template)
- Modify: `README.md` (the schema version sentence; the phase 4 bullet)
- Test: `tests/test_generation.py`, `tests/test_api_generate.py`, `web/src/features/renders/RenderDetailPage.test.tsx`

**Interfaces:**
- Consumes: `generate_brief`, `GenerationService`, `RenderRecord`, `make_render_record`, `makeRenderRecord` as they stand.
- Produces:
  - `LLMGeneration(mode="llm", template_id: str | None = None, count: int = 1)`.
  - `RenderRecord.template_id: str | None`.
  - `SCHEMA_VERSION == 5`.
  - `make_render_record(..., template_id: str | None = "drake")`.
  - In `web/src/api/schema.ts`: `LLMGeneration.template_id` accepts `string | null`, and `RenderRecord.template_id` is `string | null`.
  - `makeRenderRecord({ templateId?: string | null })` — `undefined` means `"drake"`, and `null` means a render with no template.

- [ ] **Step 1: Write the failing generation tests**

Add to `tests/test_generation.py`, after
`test_the_model_is_only_offered_the_template_the_panel_named`:

```python
OTHER = "shape_other"


def _settings_with(tmp_path, *template_ids: str) -> Settings:
    """`_settings`, but with a library of several templates.

    Letting the model choose is only observable against more than one
    template: with a library of one, "the whole library" and "the template
    named" are the same prompt, and a test could not tell them apart.
    """
    return Settings(
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
                for tid in template_ids
            ),
        ),
    )


def _choosing_job(tmp_path, records, provider) -> GenerationJob:
    """A job whose request left the template to the model."""
    settings = _settings_with(tmp_path, TEMPLATE, OTHER)
    return GenerationJob(
        settings=settings,
        request=LLMGeneration(),
        topic=make_topic("airport-cat"),
        templates=load_templates(settings.templates_dir),
        records=records,
        provider=provider,
    )


def test_letting_the_model_choose_offers_it_the_whole_library(tmp_path):
    """The panel's default. A job that narrowed to one template here would
    make "Let the LLM choose" a synonym for whichever template the code
    happened to reach first."""
    store = _store(tmp_path)
    provider = FakeLLMProvider(
        responses=[BriefChoice(template_id=OTHER, caption_slots=SLOTS, rationale="r")]
    )

    generate_renders(
        _choosing_job(tmp_path, [_seeded(store, "rnd1", template_id=None)], provider),
        store,
    )

    prompt = provider.calls[0].prompt
    assert f"id={TEMPLATE}" in prompt
    assert f"id={OTHER}" in prompt


def test_a_render_the_model_chose_for_records_the_template_it_chose(tmp_path):
    """The seeded row names no template; the finished one names the model's
    pick, which is what the tile's footer and the full-size view show.

    The model picks `OTHER`, not the first template in the library, so a
    job that filled the row in from the library instead of from the brief
    would name the wrong one.
    """
    store = _store(tmp_path)
    provider = FakeLLMProvider(
        responses=[BriefChoice(template_id=OTHER, caption_slots=SLOTS, rationale="r")]
    )

    generate_renders(
        _choosing_job(tmp_path, [_seeded(store, "rnd1", template_id=None)], provider),
        store,
    )

    finished = store.get_render("rnd1")
    assert finished is not None
    assert finished.status == "ready"
    assert finished.template_id == OTHER
```

And after `test_a_generating_manual_row_already_carries_its_captions`:

```python
def test_a_request_that_names_no_template_seeds_rows_without_one(tmp_path):
    """The model has not chosen yet, so the row names no template — read
    back from the database, because the column has to accept that. A
    `NOT NULL` left on it refuses the insert with an `IntegrityError`
    before a single row exists."""
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    service = _service(tmp_path, store, generate=RecordingGenerate())

    records = service.submit("run-1", "airport-cat", LLMGeneration(count=2))
    service.shutdown()

    stored = [store.get_render(record.id) for record in records]
    assert [row.template_id if row else "missing" for row in stored] == [None, None]
```

- [ ] **Step 2: Write the failing API test**

Add to `tests/test_api_generate.py`, after
`test_a_hand_written_request_returns_the_captions_that_were_posted`:

```python
def test_a_model_written_request_may_leave_the_template_to_the_model(tmp_path):
    """"Let the LLM choose" posts no template. Accepted, and the rows come
    back naming none until the model has picked one."""
    client = _client(tmp_path)

    response = client.post(_url(), json={"mode": "llm", "count": 2})

    assert response.status_code == 202
    assert [row["template_id"] for row in response.json()] == [None, None]
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_generation.py tests/test_api_generate.py -k "choose or chose or names_no_template or leave_the_template" -v`

Expected: FAIL. The generation tests fail with a pydantic `ValidationError`
for `template_id` (on `LLMGeneration()` or on
`make_render_record(template_id=None)`). The API test gets `422` where it
expects `202`.

- [ ] **Step 4: Let `RenderRecord` carry no template**

In `zeitgeist/records.py`, replace the `RenderRecord` class with:

```python
class RenderRecord(BaseModel):
    """One rendered meme. The database is authoritative for whether it exists;
    the PNG and its thumbnail live at `output/<run_id>/renders/<id>.png`.

    While `status` is `"generating"`, `caption_slots` and `origin`'s
    `rationale` (on `AutoOrigin`) are not yet written — they hold
    placeholder values until the job finishes drawing this render — and
    must not be read as its real captions or the model's real reasoning.

    `template_id` is None where no template has been chosen: a `generating`
    row whose request left the choice to the model, and a `failed` row
    whose brief failed before the model chose. That is a real state rather
    than a placeholder — there is no template to name — so it is `| None`
    rather than an empty string standing in for one.
    """

    model_config = STRICT

    id: str
    run_id: str
    topic_id: str
    template_id: str | None
    caption_slots: dict[str, str]
    origin: Origin
    status: Literal["generating", "ready", "failed"]
    error: str | None
    created_at: datetime
```

- [ ] **Step 5: Make the column nullable and bump the schema**

In `zeitgeist/schema.py`, change `SCHEMA_VERSION = 4` to:

```python
SCHEMA_VERSION = 5
```

and replace the `renders` table's DDL with:

```sql
CREATE TABLE IF NOT EXISTS renders (
    id            TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL,
    topic_id      TEXT NOT NULL,
    -- NULL while the model has yet to choose a template for a render it
    -- was asked to choose one for, and on a render whose brief failed
    -- before it did. Every other row names the template it was drawn on.
    template_id   TEXT,
    caption_slots TEXT NOT NULL,
    origin        TEXT NOT NULL,
    status        TEXT NOT NULL,
    error         TEXT,
    created_at    TEXT NOT NULL
);
```

`store.py` needs no change: `_render` reads `row[3]` straight into the
model, and every write passes `record.template_id` through as a parameter,
so `None` round-trips as `NULL`.

- [ ] **Step 6: Let the request leave the template to the model**

In `zeitgeist/generation.py`, replace the `LLMGeneration` class with:

```python
class LLMGeneration(BaseModel):
    """Ask the model to write `count` briefs.

    `template_id` is a template the panel picked as an override. None — the
    panel's default, "Let the LLM choose" — offers the model the whole
    library and lets it pick per brief, exactly as the generate stage does.
    The below-the-cut `generate` link posts None too: a ranking row has no
    room to ask which template.
    """

    model_config = STRICT

    mode: Literal["llm"] = "llm"
    template_id: str | None = None
    count: Annotated[int, Field(ge=1, le=MAX_RENDERS)] = 1
```

In `_brief_for`, replace everything after the
`if job.provider is None:` guard with:

```python
    # A named template narrows the library to that one, so the model writes
    # captions rather than picking; None offers it the whole library, which
    # is "Let the LLM choose". Either way `generate_brief` validates the
    # answer against the library it was given, so a model that names
    # anything else is retried and then fails, rather than rendering onto a
    # template nobody offered it.
    # Bound to a local so the narrowing below is on a name, which every
    # type checker follows, rather than on an attribute access.
    template_id = request.template_id
    library = (
        job.templates
        if template_id is None
        else {template_id: job.templates[template_id]}
    )
    return generate_brief(job.topic, library, job.provider)
```

In `GenerationService.submit`, replace the unknown-template check with:

```python
        templates = load_templates(settings.templates_dir)
        # None is "let the model choose", which names nothing to check.
        if request.template_id is not None and request.template_id not in templates:
            raise GenerationRefused(
                f"template_id {request.template_id!r} is not in the library; "
                f"choose one of: {', '.join(sorted(templates))}"
            )
```

and in the `log.info("Queued ...")` call in the same method, replace the
last argument, `request.template_id,`, with:

```python
            request.template_id or "(the model's choice)",
```

In `_seed`'s docstring, add this paragraph after the one beginning "For an
`llm` request the brief does not exist yet":

```python
        `template_id` is the request's own, which is None when the model is
        choosing. `_draw` writes the one it chose. A brief that fails before
        the model chose leaves it None, which is the truth about that row.
```

`_seed`'s body already writes `template_id=request.template_id`, so it
needs no change.

- [ ] **Step 7: Let the Python factory build a render with no template**

In `tests/run_factory.py`, change `make_render_record`'s parameter:

```python
    template_id: str | None = "drake",
```

- [ ] **Step 8: Run the Python tests to verify they pass**

Run: `uv run pytest tests/test_generation.py tests/test_api_generate.py tests/test_store.py -v`

Expected: PASS, including every test that was already there. The
test that says "the model is only offered the template the panel named"
still passes: a named template still narrows the library.

- [ ] **Step 9: Regenerate the contract**

```bash
uv run python scripts/dump_openapi.py
```

```bash
npm --prefix web run generate:types
```

Run: `npm --prefix web run typecheck`

Expected: FAIL. `RenderGrid.tsx` passes `render.template_id`, now
`string | null`, to `MemeTile`'s `templateId?: string`. `RenderDetailPage`
passes it as a breadcrumb label, which must be a `string`. `factories.ts`
may also fail, depending on how the generator spells the field. The next
two steps fix all three.

- [ ] **Step 10: Let the web factory build a render with no template**

In `web/src/test/factories.ts`, in `makeRenderRecord`, change the option's
type and the field:

```ts
    templateId?: string | null;
```

```ts
    template_id: options.templateId === undefined ? "drake" : options.templateId,
```

`undefined` is "the test does not care", and `null` is "a render with no
template". `??` would turn the second into the first.

- [ ] **Step 11: Write the failing full-size view test**

Add to `web/src/features/renders/RenderDetailPage.test.tsx`, after the test
that chips the template and the provenance:

```tsx
  it("says no template was chosen for a render whose brief failed before choosing", async () => {
    // The model is asked to pick, fails before it does, and the row names
    // no template. Every place the page names the template still needs a
    // word, and "null" is not one: the chip, the breadcrumb's last entry,
    // the image's alt text and the download's file name. Each is checked,
    // because each is its own use site — the type checker is satisfied by
    // a template literal that prints "null".
    serve(makeRenderRecord({ templateId: null, status: "failed", error: "the model is down" }));

    renderPage();

    const chips = await screen.findByTestId("chips");
    expect(within(chips).getByText("no template chosen")).toBeInTheDocument();
    const crumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumb).getByText("no template chosen")).toBeInTheDocument();
    expect(screen.getByAltText("no template chosen meme")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Download PNG" }).getAttribute("download"),
    ).not.toMatch(/null/);
  });
```

Run: `npm --prefix web test -- RenderDetailPage`

Expected: FAIL. Typecheck is already red from Step 9, and the test itself
finds no `no template chosen`.

- [ ] **Step 12: Give a null template a label on both screens**

In `web/src/features/renders/RenderDetailPage.tsx`, inside the render
function, straight after `const topicLabel = ...`, add:

```tsx
        // None only on a render whose model never chose a template — a
        // brief that failed before it picked one. The breadcrumb, the chip
        // and the file name still need a word.
        const templateLabel = record.template_id ?? "no template chosen";
```

Then replace each of the four uses of `record.template_id` in that function:

```tsx
                { label: templateLabel },
```

```tsx
                <Chip tone="accent">{templateLabel}</Chip>
```

```tsx
                    alt={`${templateLabel} meme`}
```

```tsx
                      download={`${templateLabel}-${record.id}.png`}
```

In `web/src/features/topics/RenderGrid.tsx`, change the `MemeTile`
`templateId` prop to:

```tsx
              templateId={render.template_id ?? undefined}
```

The grid still draws ready renders only, and a ready render always names
its template. The `?? undefined` exists for the type and nothing else, and
Task 4 rewrites the grid anyway.

- [ ] **Step 13: Update the README**

In `README.md`, replace the sentence about the schema version in the
"Running" section with:

```markdown
per meme. A `data/zeitgeist.db` written before phase 7 is refused at startup
(schema version 4, where this build expects 5); there are no migrations, so
the fix is to delete it, which loses cross-run trend history and nothing else.
```

In the phase 4 list, replace the first bullet's opening with:

```markdown
- **Two ways to make a meme.** `POST /api/runs/{id}/topics/{topic_id}/renders`
  takes either `{"mode": "llm", "template_id": ..., "count": N}` — the model
  writes the captions, up to four at a time, for the template you name, or
  picks one itself when `template_id` is omitted or null — or
```

and leave the rest of that bullet as it is.

- [ ] **Step 14: Run the whole gate**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: all seven PASS. `tests/test_api_app.py` and `tests/test_serve.py`
compare against `SCHEMA_VERSION` rather than a literal, so the bump needs no
edit there.

- [ ] **Step 15: Commit**

```bash
git add zeitgeist/generation.py zeitgeist/records.py zeitgeist/schema.py tests/run_factory.py tests/test_generation.py tests/test_api_generate.py web/openapi.json web/src/api/schema.ts web/src/test/factories.ts web/src/features/topics/RenderGrid.tsx web/src/features/renders/RenderDetailPage.tsx web/src/features/renders/RenderDetailPage.test.tsx README.md
git commit -m "feat: let the model choose the template for an on-demand render"
```

---

### Task 2: generating, deleting, and watching a render finish

The client half of the two endpoints phase 4 built, plus the poll that keeps
topic detail current while renders generate. No screen changes yet. Every
later task consumes these hooks.

**Files:**
- Modify: `web/src/api/client.ts` (`apiDelete`)
- Modify: `web/src/api/types.ts` (three aliases)
- Modify: `web/src/api/queries.ts` (`GENERATION_POLL_MS`, `useTopicDetail`, `useGenerateRenders`, `GenerateMutation`, `useDeleteRender`)
- Test: `web/src/api/client.test.ts`, `web/src/api/queries.test.tsx`

**Interfaces:**
- Consumes: Task 1's regenerated `schema.ts` (`LLMGeneration.template_id` nullable) and `makeRenderRecord({ templateId: null })`.
- Produces:
  - `apiDelete(path: string): Promise<void>` — resolves on any 2xx and throws `ApiError` otherwise.
  - `type LLMGeneration`, `type ManualGeneration`, `type GenerationRequest = LLMGeneration | ManualGeneration` from `@/api/types`.
  - `GENERATION_POLL_MS = 1500`.
  - `useTopicDetail(runId, topicId)` — same signature. It now polls while any render is `generating`, and invalidates `["runs"]` and `["topics"]` when that count drops.
  - `useGenerateRenders(runId: string, topicId: string)` — `useMutation<RenderRecord[], ApiError, GenerationRequest>`. On success the reply's rows are appended to the cached topic detail.
  - `type GenerateMutation = ReturnType<typeof useGenerateRenders>`.
  - `useDeleteRender()` — `useMutation<void, ApiError, RenderRecord>`. A 404 counts as success. On success the row leaves the cached topic detail, and `["runs"]` and `["topics"]` are invalidated.

- [ ] **Step 1: Write the failing client tests**

Add to `web/src/api/client.test.ts`, and add `apiDelete` to its import from
`@/api/client`:

```ts
describe("apiDelete", () => {
  it("resolves on a 204, which carries no body to parse", async () => {
    // `DELETE /api/renders/{id}` answers 204 and nothing else. A client that
    // called `response.json()` on it would throw on the empty body and
    // report a deletion that worked as one that failed.
    let deleted = "";
    server.use(
      http.delete("/api/renders/:renderId", ({ params }) => {
        deleted = String(params.renderId);
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await expect(apiDelete("/api/renders/r1")).resolves.toBeUndefined();
    expect(deleted).toBe("r1");
  });

  it("raises an ApiError carrying the server's own detail", async () => {
    server.use(
      http.delete("/api/renders/:renderId", () =>
        HttpResponse.json({ detail: "Permission denied: r1.png" }, { status: 500 }),
      ),
    );

    await expect(apiDelete("/api/renders/r1")).rejects.toMatchObject({
      status: 500,
      detail: "Permission denied: r1.png",
    });
  });
});
```

- [ ] **Step 2: Write the failing hook tests**

In `web/src/api/queries.test.tsx`, add `GENERATION_POLL_MS`,
`useDeleteRender` and `useGenerateRenders` to the import from
`@/api/queries`. Then add:

```tsx
describe("useTopicDetail while renders generate", () => {
  it("polls while a render is generating, and stops once none is", async () => {
    // Asserted as a quiet window rather than a call count. The render
    // finishing triggers a refresh of its own — this detail is one of the
    // views that count renders — and how many requests that makes is the
    // implementation's business. What polling means is that requests keep
    // coming a poll interval apart, so the proof it stopped is a stretch
    // longer than one interval with no request at all.
    const requestedAt: number[] = [];
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () => {
        requestedAt.push(Date.now());
        // Generating on the first answer, ready on every one after.
        const status = requestedAt.length === 1 ? "generating" : "ready";
        return HttpResponse.json(
          makeTopicDetail({ renders: [makeRenderRecord({ id: "r1", status })] }),
        );
      }),
    );

    const { result } = renderHook(() => useTopicDetail("r1", "t1"), {
      wrapper: renderWithProviders.Wrapper,
    });

    // Reaching "ready" at all needs a poll: the first answer was generating.
    await waitFor(() => expect(result.current.data?.renders[0]?.status).toBe("ready"), {
      timeout: GENERATION_POLL_MS * 2,
    });
    await new Promise((resolve) => setTimeout(resolve, GENERATION_POLL_MS + 500));

    const quiet = Date.now() - (requestedAt.at(-1) ?? 0);
    expect(quiet).toBeGreaterThan(GENERATION_POLL_MS);
  }, 10_000);

  it("does not poll a topic with nothing generating", async () => {
    // A failed render is settled too: it will never become anything else,
    // so it is no reason to keep asking.
    let calls = 0;
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () => {
        calls += 1;
        return HttpResponse.json(
          makeTopicDetail({
            renders: [
              makeRenderRecord({ id: "r1", status: "ready" }),
              makeRenderRecord({ id: "r2", status: "failed", error: "overflow" }),
            ],
          }),
        );
      }),
    );

    const { result } = renderHook(() => useTopicDetail("r1", "t1"), {
      wrapper: renderWithProviders.Wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    await new Promise((resolve) => setTimeout(resolve, GENERATION_POLL_MS + 300));
    expect(calls).toBe(1);
  });

  it("refreshes the run's ranking when a render finishes", async () => {
    // `render_count` counts ready renders only, so a render finishing here
    // changes a number the ranking holds. Nothing else would tell it.
    let detailCalls = 0;
    let rankingCalls = 0;
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () => {
        detailCalls += 1;
        const status = detailCalls === 1 ? "generating" : "ready";
        return HttpResponse.json(
          makeTopicDetail({ renders: [makeRenderRecord({ id: "r1", status })] }),
        );
      }),
      http.get("/api/runs/:runId/topics", () => {
        rankingCalls += 1;
        return HttpResponse.json([makeRankedTopic()]);
      }),
    );

    const { result } = renderHook(
      () => ({ detail: useTopicDetail("r1", "t1"), ranking: useRanking("r1") }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.ranking.isSuccess).toBe(true));
    expect(rankingCalls).toBe(1);

    await waitFor(() => expect(rankingCalls).toBe(2), {
      timeout: GENERATION_POLL_MS * 3,
    });
  });
});

describe("useGenerateRenders", () => {
  it("posts to the topic's renders and puts the rows it returns straight into the cache", async () => {
    // The rows go into the cache from the reply itself. Waiting for a
    // refetch instead would leave a gap between the placeholders going and
    // the rows arriving. Every detail request after the first is held open,
    // so the only way "new" can reach the cache is the mutation's own write
    // — an implementation that invalidated rather than wrote never gets
    // there, deterministically rather than depending on which response
    // lands first.
    let detailCalls = 0;
    let posted: unknown = null;
    let postedTo = "";
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", async () => {
        detailCalls += 1;
        if (detailCalls > 1) await new Promise(() => undefined);
        return HttpResponse.json(
          makeTopicDetail({ renders: [makeRenderRecord({ id: "old" })] }),
        );
      }),
      http.post("/api/runs/:runId/topics/:topicId/renders", async ({ request, params }) => {
        posted = await request.json();
        postedTo = `${String(params.runId)}/${String(params.topicId)}`;
        return HttpResponse.json(
          [
            makeRenderRecord({
              id: "new",
              status: "generating",
              templateId: null,
              captionSlots: {},
            }),
          ],
          { status: 202 },
        );
      }),
    );

    const { result } = renderHook(
      () => ({ detail: useTopicDetail("r1", "t1"), generate: useGenerateRenders("r1", "t1") }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));

    await act(async () => {
      await result.current.generate.mutateAsync({ mode: "llm", template_id: null, count: 1 });
    });

    expect(postedTo).toBe("r1/t1");
    expect(posted).toEqual({ mode: "llm", template_id: null, count: 1 });
    expect(result.current.detail.data?.renders.map((render) => render.id)).toEqual([
      "old",
      "new",
    ]);
  });

  it("is not undone by a detail fetch that was sent before the rows existed", async () => {
    // The poll or a refocus can have a detail request on its way when the
    // reply lands. Answered from before the post, it lacks the new rows;
    // written over them, it would take the tiles away, and with nothing
    // left generating the poll that would find them again would stop.
    const created = makeRenderRecord({
      id: "new",
      status: "generating",
      templateId: null,
      captionSlots: {},
    });
    let renders = [makeRenderRecord({ id: "old" })];
    let detailCalls = 0;
    let staleAnswered = false;
    let releaseStale: () => void = () => undefined;
    const stale = new Promise<void>((resolve) => {
      releaseStale = resolve;
    });
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", async () => {
        detailCalls += 1;
        // Answered from the server's state at the moment it was asked.
        const answer = makeTopicDetail({ renders });
        if (detailCalls === 2) {
          await stale;
          staleAnswered = true;
        }
        return HttpResponse.json(answer);
      }),
      http.post("/api/runs/:runId/topics/:topicId/renders", () => {
        renders = [...renders, created];
        return HttpResponse.json([created], { status: 202 });
      }),
    );

    const { result } = renderHook(
      () => ({ detail: useTopicDetail("r1", "t1"), generate: useGenerateRenders("r1", "t1") }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));

    // A second fetch, sent and held before anything is posted.
    void result.current.detail.refetch();
    await waitFor(() => expect(detailCalls).toBe(2));

    await act(async () => {
      await result.current.generate.mutateAsync({ mode: "llm", template_id: null, count: 1 });
    });
    releaseStale();
    // Wait for the stale answer to have been sent and for the query to
    // settle, rather than for a fixed interval: a sleep that ran out before
    // the stale response was processed would let this test pass against
    // the very bug it names. Without the cancel, the query stays fetching
    // until that response lands and overwrites the cache; with it, the
    // query is already idle.
    await waitFor(() => expect(staleAnswered).toBe(true));
    await waitFor(() => expect(result.current.detail.isFetching).toBe(false));

    expect(result.current.detail.data?.renders.map((render) => render.id)).toEqual([
      "old",
      "new",
    ]);
  });
});

describe("useDeleteRender", () => {
  // `makeRenderRecord`'s own run and topic, which is what the hook keys the
  // cached detail by.
  const RUN = "20260829T090000Z";
  const TOPIC = "topic-1";

  /**
   * Answers the first detail request and holds every later one open, so the
   * only way a row can leave the cache in these tests is the mutation's own
   * write — not a refetch that happens to agree with it.
   */
  function serveDetailOnce(renders: RenderRecord[]) {
    let calls = 0;
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", async () => {
        calls += 1;
        if (calls > 1) await new Promise(() => undefined);
        return HttpResponse.json(makeTopicDetail({ renders }));
      }),
    );
  }

  it("takes the row out of the cached topic at once, not after a refetch", async () => {
    // "The tile disappearing is the confirmation", per the handoff.
    serveDetailOnce([makeRenderRecord({ id: "keep" }), makeRenderRecord({ id: "gone" })]);
    server.use(
      http.delete("/api/renders/:renderId", () => new HttpResponse(null, { status: 204 })),
    );

    const { result } = renderHook(
      () => ({ detail: useTopicDetail(RUN, TOPIC), remove: useDeleteRender() }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));

    await act(async () => {
      await result.current.remove.mutateAsync(makeRenderRecord({ id: "gone" }));
    });

    expect(result.current.detail.data?.renders.map((render) => render.id)).toEqual(["keep"]);
  });

  it("counts a render that is already gone as deleted", async () => {
    // Deleted in another tab. The end state asked for is the state the
    // server reports; a tile that stayed put with an error nobody can act
    // on would be the wrong answer to it.
    serveDetailOnce([makeRenderRecord({ id: "gone" })]);
    server.use(
      http.delete("/api/renders/:renderId", () =>
        HttpResponse.json({ detail: "No such render: gone" }, { status: 404 }),
      ),
    );

    const { result } = renderHook(
      () => ({ detail: useTopicDetail(RUN, TOPIC), remove: useDeleteRender() }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));

    await act(async () => {
      await result.current.remove.mutateAsync(makeRenderRecord({ id: "gone" }));
    });

    expect(result.current.detail.data?.renders).toEqual([]);
  });

  it("refreshes the ranking, which just lost a meme", async () => {
    let rankingCalls = 0;
    serveDetailOnce([makeRenderRecord({ id: "gone" })]);
    server.use(
      http.get("/api/runs/:runId/topics", () => {
        rankingCalls += 1;
        return HttpResponse.json([makeRankedTopic()]);
      }),
      http.delete("/api/renders/:renderId", () => new HttpResponse(null, { status: 204 })),
    );

    const { result } = renderHook(
      () => ({
        detail: useTopicDetail(RUN, TOPIC),
        ranking: useRanking(RUN),
        remove: useDeleteRender(),
      }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.ranking.isSuccess).toBe(true));

    await act(async () => {
      await result.current.remove.mutateAsync(makeRenderRecord({ id: "gone" }));
    });

    await waitFor(() => expect(rankingCalls).toBe(2));
  });

  it("refreshes the topics index, whose meme counts just lost one", async () => {
    // The index counts ready renders per topic, as the ranking does, but
    // lives under its own key rather than under the run's.
    let indexCalls = 0;
    serveDetailOnce([makeRenderRecord({ id: "gone" })]);
    server.use(
      http.get("/api/topics", () => {
        indexCalls += 1;
        return HttpResponse.json(makeTopicIndex());
      }),
      http.delete("/api/renders/:renderId", () => new HttpResponse(null, { status: 204 })),
    );

    const { result } = renderHook(
      () => ({
        detail: useTopicDetail(RUN, TOPIC),
        index: useTopicIndex(),
        remove: useDeleteRender(),
      }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.index.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));

    await act(async () => {
      await result.current.remove.mutateAsync(makeRenderRecord({ id: "gone" }));
    });

    await waitFor(() => expect(indexCalls).toBe(2));
  });

  it("leaves the row where it was when the server refuses", async () => {
    // A 500 is a render that still exists. Taking it out of the cache
    // anyway — TanStack's optimistic `onMutate` pattern with no rollback,
    // which "the tile disappearing is the confirmation" invites — would
    // show a deletion that did not happen, and unmount the tile that
    // carries the server's reason.
    serveDetailOnce([makeRenderRecord({ id: "keep" }), makeRenderRecord({ id: "stuck" })]);
    server.use(
      http.delete("/api/renders/:renderId", () =>
        HttpResponse.json({ detail: "Permission denied: renders/stuck.png" }, { status: 500 }),
      ),
    );

    const { result } = renderHook(
      () => ({ detail: useTopicDetail(RUN, TOPIC), remove: useDeleteRender() }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));

    act(() => {
      result.current.remove.mutate(makeRenderRecord({ id: "stuck" }));
    });
    await waitFor(() => expect(result.current.remove.isError).toBe(true));

    expect(result.current.detail.data?.renders.map((render) => render.id)).toEqual([
      "keep",
      "stuck",
    ]);
  });
});
```

Add `RenderRecord` to the test file's type imports:
`import type { RenderRecord } from "@/api/types";`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `npm --prefix web test -- client queries`

Expected: FAIL. `apiDelete`, `GENERATION_POLL_MS`, `useGenerateRenders` and
`useDeleteRender` do not exist yet.

- [ ] **Step 4: Add `apiDelete`**

In `web/src/api/client.ts`, after `apiSend`:

```ts
/**
 * A DELETE, whose success is a 204 with no body.
 *
 * Separate from `apiSend` rather than a third method on it: `apiSend`
 * returns the parsed reply, and a 204 has none — `response.json()` on an
 * empty body throws, so sharing the function would mean a special case
 * inside it for the one verb that answers with nothing.
 */
export async function apiDelete(path: string): Promise<void> {
  const response = await fetch(path, {
    method: "DELETE",
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(response.status, await detailOf(response));
  }
}
```

- [ ] **Step 5: Name the request types**

In `web/src/api/types.ts`, after `TemplateOption`:

```ts
export type LLMGeneration = Schemas["LLMGeneration"];
export type ManualGeneration = Schemas["ManualGeneration"];
/** What topic detail's two panels and the below-the-cut link post. */
export type GenerationRequest = LLMGeneration | ManualGeneration;
```

- [ ] **Step 6: The poll, the two mutations**

In `web/src/api/queries.ts`:

Change the client import to bring in `ApiError` as a value (the delete hook
tests `instanceof` against it) and `apiDelete`:

```ts
import { ApiError, apiDelete, apiGet, apiSend, openRunEvents, parseLogEvent } from "@/api/client";
```

and delete the separate `import type { ApiError } from "@/api/client";`
line. Add `GenerationRequest` to the `@/api/types` import, and `QueryClient`
to the TanStack import as a type:

```ts
import type { QueryClient } from "@tanstack/react-query";
```

The module docstring opens by counting its hooks ("all sixteen hooks — six
read, four mutations, …"), and the breakdown was already wrong before this
task: there are five mutations today. Replace that opening sentence — the
three lines after `/**`, ending "key cannot drift from the fetch that uses
it." — with one that cannot go stale:

```ts
 * The query-key factory and every hook the app fetches or mutates through,
 * in one module so a key cannot drift from the fetch that uses it.
```

Replace `useTopicDetail` with:

```ts
/** How often topic detail re-asks while one of its renders is generating. */
export const GENERATION_POLL_MS = 1500;

function generatingCount(detail: TopicDetail | undefined): number {
  return detail?.renders.filter((render) => render.status === "generating").length ?? 0;
}

/**
 * Everything that counts renders: the runs list's thumbnails, every run's
 * ranking, and the topics index's meme counts. Each counts ready renders
 * only, so each is stale the moment a render becomes ready or is deleted.
 *
 * `["runs"]` also covers the topic detail on screen, which refetches once
 * more. That is one request, and it is the page confirming what it drew.
 */
function invalidateRenderViews(client: QueryClient) {
  void client.invalidateQueries({ queryKey: ["runs"] });
  void client.invalidateQueries({ queryKey: ["topics"] });
}

/**
 * One topic's dossier and renders.
 *
 * Polls while any render is `generating`, and only then — a settled topic
 * makes one request, like every other read hook. A render finishing is the
 * only thing on this screen that changes on its own.
 *
 * When the number still generating drops, one of them became ready or
 * failed, so the counts other screens hold are refreshed. Watching the
 * count rather than each row keeps this to one comparison per render of
 * the hook.
 */
export function useTopicDetail(runId: string | undefined, topicId: string | undefined) {
  const client = useQueryClient();
  const query = useQuery<TopicDetail, ApiError>({
    queryKey: queryKeys.topicDetail(runId ?? "", topicId ?? ""),
    queryFn: () =>
      apiGet<TopicDetail>(
        `/api/runs/${encodeURIComponent(runId ?? "")}` +
          `/topics/${encodeURIComponent(topicId ?? "")}`,
      ),
    enabled: runId !== undefined && topicId !== undefined,
    refetchInterval: (current) =>
      generatingCount(current.state.data) > 0 ? GENERATION_POLL_MS : false,
  });

  const generating = generatingCount(query.data);
  const previous = useRef(generating);
  useEffect(() => {
    if (generating < previous.current) invalidateRenderViews(client);
    previous.current = generating;
  }, [generating, client]);

  return query;
}
```

Add the two mutations after `useSaveSettings`:

```ts
/**
 * Post one of topic detail's two panels, or the below-the-cut link.
 *
 * The reply's rows — already `generating`, with real ids — go straight into
 * the topic's cached detail rather than waiting for a refetch. TanStack
 * awaits `onSuccess` before the mutation stops being pending, and the
 * page draws placeholders from the pending request's `variables`, so the
 * placeholders give way to the real rows with nothing in between.
 *
 * An in-flight fetch of the detail is cancelled first. It was sent before
 * these rows existed; landing after the write, it would put back a detail
 * without them, and with nothing generating in it the poll that would
 * have found them again would stop.
 *
 * Nothing else is invalidated. A generating row is counted nowhere —
 * every count is ready renders only — so the counts change when a render
 * finishes, which `useTopicDetail` watches for.
 */
export function useGenerateRenders(runId: string, topicId: string) {
  const client = useQueryClient();
  return useMutation<RenderRecord[], ApiError, GenerationRequest>({
    mutationFn: (body) =>
      apiSend<RenderRecord[]>(
        "POST",
        `/api/runs/${encodeURIComponent(runId)}/topics/${encodeURIComponent(topicId)}/renders`,
        body,
      ),
    onSuccess: async (created) => {
      const key = queryKeys.topicDetail(runId, topicId);
      await client.cancelQueries({ queryKey: key, exact: true });
      client.setQueryData<TopicDetail>(key, (held) =>
        held === undefined ? held : { ...held, renders: [...held.renders, ...created] },
      );
    },
  });
}

/** What a panel is handed: one generate mutation, pending state and all. */
export type GenerateMutation = ReturnType<typeof useGenerateRenders>;

/**
 * Delete a render — the row, the PNG and the thumbnail, server-side.
 *
 * A 404 counts as done. The end state asked for is "no such render", which
 * is what the server reports, and a render deleted in another tab must
 * still leave this one rather than sit there with an error nobody can act
 * on.
 *
 * The row leaves the cached detail at once: "the tile disappearing is the
 * confirmation", per the handoff, and a round trip before it went would
 * read as the click not having worked. Then everything that counts renders
 * is refreshed, because each of them just lost one.
 */
export function useDeleteRender() {
  const client = useQueryClient();
  return useMutation<void, ApiError, RenderRecord>({
    mutationFn: async (render) => {
      try {
        await apiDelete(`/api/renders/${encodeURIComponent(render.id)}`);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return;
        throw error;
      }
    },
    onSuccess: async (_, render) => {
      const key = queryKeys.topicDetail(render.run_id, render.topic_id);
      await client.cancelQueries({ queryKey: key, exact: true });
      client.setQueryData<TopicDetail>(key, (held) =>
        held === undefined
          ? held
          : { ...held, renders: held.renders.filter((row) => row.id !== render.id) },
      );
      invalidateRenderViews(client);
    },
  });
}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `npm --prefix web test -- client queries`

Expected: PASS, including every test that was there before.

- [ ] **Step 8: Run the whole frontend gate**

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: PASS. No screen consumes the new hooks yet. `useTopicDetail`'s
new poll does not fire in any existing test, because their fixtures carry
ready renders only.

- [ ] **Step 9: Commit**

```bash
git add web/src/api/client.ts web/src/api/client.test.ts web/src/api/types.ts web/src/api/queries.ts web/src/api/queries.test.tsx
git commit -m "feat(web): generate and delete renders, and watch them finish"
```

---

### Task 3: `InlineConfirm` learns the tile footer

The render tile's confirm is the same behaviour as Abort's, with a different
shape. At rest it is a template line and a `✕`. When asking, the *whole
footer* becomes the question on contrast at 10%, with `yes` / `no` beside it
and no middle dot. The component already carries the behaviour, including
Escape, blur and the focus return a real run's walk found missing, so it
grows a variant rather than getting a sibling that would have to relearn
all of that.

**Files:**
- Modify: `web/src/components/InlineConfirm.tsx`
- Modify: `web/src/components/InlineConfirm.module.css`
- Test: `web/src/components/InlineConfirm.test.tsx`

**Interfaces:**
- Consumes: `InlineConfirm` as it stands.
- Produces: three optional props, each defaulting to today's behaviour:
  - `variant?: "pill" | "tile"` — `"pill"` by default, which is Abort's, Resume's and the full-size view's.
  - `ariaLabel?: string` — the trigger's accessible name, for a trigger whose visible label is a glyph.
  - `resting?: ReactNode` — tile only: what sits beside the trigger at rest, and gives way to the question.

- [ ] **Step 1: Write the failing tests**

Add to `web/src/components/InlineConfirm.test.tsx`:

```tsx
describe("InlineConfirm as a tile footer", () => {
  // Every test below finds the trigger by its `ariaLabel`, not by the "✕"
  // it shows. A button named "✕" tells a screen reader nothing about what
  // it deletes, so if `ariaLabel` stopped reaching the button, all of them
  // would fail — which is why there is no separate test for it.
  function setupTile(onConfirm = vi.fn()) {
    render(
      <InlineConfirm
        variant="tile"
        label="✕"
        ariaLabel="Delete render"
        question="Delete this render?"
        resting={<span>drake · auto</span>}
        onConfirm={onConfirm}
      />,
    );
    return { onConfirm, user: userEvent.setup() };
  }

  it("gives the whole footer to the question, resting line included", async () => {
    // The handoff's confirming tile has no template line: the question
    // takes the footer. Leaving the resting line beside it would put two
    // sentences in a quarter-width tile.
    const { user } = setupTile();

    await user.click(screen.getByRole("button", { name: "Delete render" }));

    expect(screen.getByText("Delete this render?")).toBeInTheDocument();
    expect(screen.queryByText("drake · auto")).not.toBeInTheDocument();
  });

  it("confirms on yes", async () => {
    const { onConfirm, user } = setupTile();

    await user.click(screen.getByRole("button", { name: "Delete render" }));
    await user.click(screen.getByRole("button", { name: "yes" }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("puts the resting line back on no, and deletes nothing", async () => {
    const { onConfirm, user } = setupTile();

    await user.click(screen.getByRole("button", { name: "Delete render" }));
    await user.click(screen.getByRole("button", { name: "no" }));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByText("drake · auto")).toBeInTheDocument();
  });

  it("reverts on Escape and hands focus back to its ✕", async () => {
    // What the variant exists to inherit. A tile branch whose `no` never
    // took focus would leave Escape nowhere to land.
    const { onConfirm, user } = setupTile();

    await user.click(screen.getByRole("button", { name: "Delete render" }));
    await user.keyboard("{Escape}");

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByText("drake · auto")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete render" })).toHaveFocus();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- InlineConfirm`

Expected: FAIL. Typecheck rejects the unknown props, and at runtime there is
no button named `Delete render` and the resting line is never drawn.

- [ ] **Step 3: Implement the variant**

In `web/src/components/InlineConfirm.tsx`, change the React type import to
include `ReactNode`:

```tsx
import type { FocusEvent, KeyboardEvent, ReactNode } from "react";
```

Add a paragraph to the component's docstring, after the one about focus:

```tsx
 *
 * Two shapes. `"pill"` is Abort's and Resume's: a pill button that becomes
 * a pill-shaped question. `"tile"` is the render tile's footer, per the
 * handoff's 2e: at rest a line of `resting` text and a `✕`; asking, the
 * whole footer becomes the question on contrast at 10%, with `yes` / `no`
 * beside it and no middle dot, because the tile draws none.
```

Add the three props to the destructured parameter list and its type:

```tsx
  variant = "pill",
  ariaLabel,
  resting,
```

```tsx
  /** Which shape — see above. */
  variant?: "pill" | "tile";
  /** The trigger's accessible name, when its visible label is a glyph. */
  ariaLabel?: string;
  /**
   * Tile only: what sits beside the trigger at rest — the tile's
   * `<template> · <provenance>` line — and gives way to the question.
   */
  resting?: ReactNode;
```

Replace the `if (!asking) { ... }` block with:

```tsx
  if (!asking) {
    const button = (
      <button
        ref={trigger}
        type="button"
        aria-label={ariaLabel}
        className={[
          variant === "tile"
            ? styles.tileTrigger
            : tone === "accent"
              ? styles.accentTrigger
              : styles.trigger,
          className,
        ]
          .filter(Boolean)
          .join(" ")}
        disabled={disabled}
        onClick={() => setAsking(true)}
      >
        {label}
      </button>
    );
    if (variant === "tile") {
      return (
        <div className={styles.tileRest}>
          {resting}
          {button}
        </div>
      );
    }
    return button;
  }
```

Replace the returned asking block with:

```tsx
  const tile = variant === "tile";
  return (
    <div
      className={tile ? styles.tileAsking : styles.asking}
      onKeyDown={onKeyDown}
      onBlur={onBlur}
    >
      <span className={tile ? styles.tileQuestion : styles.question}>{question}</span>
      <button
        type="button"
        className={tile ? styles.tileYes : styles.answer}
        onClick={() => {
          answer();
          onConfirm();
        }}
      >
        yes
      </button>
      {!tile && <span className={styles.dot}>·</span>}
      <button
        ref={cancel}
        type="button"
        className={tile ? styles.tileNo : styles.answer}
        onClick={answer}
      >
        no
      </button>
    </div>
  );
```

- [ ] **Step 4: Style the tile footer**

Append to `web/src/components/InlineConfirm.module.css`:

```css
/* The render tile's footer, per the handoff's 2e. At rest: the template
   line and a `✕` in text-35 that goes to text on hover. Asking: the whole
   footer on contrast at 10%, the question in contrast-light, `yes` in
   contrast-light at 700 and `no` in text-40 at 600, all mono 9.5. */
.tileRest,
.tileAsking {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
}

.tileAsking {
  background: var(--contrast-confirm);
  transition: background var(--transition);
}

.tileTrigger {
  padding: 0;
  border: none;
  background: none;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  color: var(--text-35);
  cursor: pointer;
  transition: color var(--transition);
}

.tileTrigger:hover:not(:disabled),
.tileTrigger:focus-visible {
  color: var(--text);
}

.tileTrigger:disabled {
  opacity: 0.5;
  cursor: default;
}

.tileQuestion {
  flex: 1;
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--contrast-light);
}

.tileYes,
.tileNo {
  padding: 0;
  border: none;
  background: none;
  font-family: var(--font-mono);
  font-size: 9.5px;
  line-height: 1;
  cursor: pointer;
}

.tileYes {
  font-weight: 700;
  color: var(--contrast-light);
}

.tileNo {
  font-weight: 600;
  color: var(--text-40);
}

.tileYes:hover,
.tileYes:focus-visible,
.tileNo:hover,
.tileNo:focus-visible {
  color: var(--text);
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npm --prefix web test -- InlineConfirm`

Expected: PASS, including every existing test. The pill path's markup is
unchanged, so Abort and Resume behave exactly as before.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/InlineConfirm.tsx web/src/components/InlineConfirm.module.css web/src/components/InlineConfirm.test.tsx
git commit -m "feat(web): the render tile's inline confirm"
```

---

### Task 4: the rendered grid, in every state a render can be in

Phase 5's grid drew ready renders only, and said phase 7 would draw the
rest. This task draws the rest: generating, failed, being deleted, the
placeholders a request in flight asks for, the counts above the grid, and
the dashed row that stands in for an empty grid. The panels that create
renders come in Tasks 5 and 6. Until then the page hands the grid an empty
`pending` list.

**Files:**
- Modify: `web/src/components/MemeTile.tsx` + `.module.css` (the `"grid"` size)
- Create: `web/src/features/topics/RenderTile.tsx` + `.module.css`
- Modify: `web/src/features/topics/RenderGrid.tsx` + `.module.css` (rewritten)
- Modify: `web/src/features/topics/TopicDetailPage.tsx` (the grid's new props)
- Create: `web/src/features/topics/RenderGrid.test.tsx`
- Test: `web/src/components/MemeTile.test.tsx`, `web/src/features/topics/TopicDetailPage.test.tsx`

**Interfaces:**
- Consumes: `useDeleteRender` (Task 2); `InlineConfirm`'s `variant="tile"`, `ariaLabel`, `resting` (Task 3); `GenerationRequest` (Task 2).
- Produces:
  - `MemeTile`'s `size` accepts `"grid"` as well as 34, 42 and 96: full width, 112px tall, full-size PNG.
  - `RenderTile({ render }: { render: RenderRecord })`.
  - `GeneratingTile({ label, doing, onCancel }: { label: string; doing: string; onCancel?: () => void })` — the placeholder form has no `onCancel`.
  - `RenderGrid({ renders, runId, pending }: { renders: RenderRecord[]; runId: string; pending: GenerationRequest[] })`.

- [ ] **Step 1: Write the failing MemeTile test**

Add to `web/src/components/MemeTile.test.tsx`:

```tsx
  it("fills a grid tile with the full-size PNG", () => {
    // Topic detail's tiles are a quarter of the page wide, far past the
    // 96px thumbnail — anything but the full image is a scaled-up blur.
    renderWithProviders(<MemeTile renderId="render-1" size="grid" />);

    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "/api/renders/render-1/image?size=full",
    );
  });
```

- [ ] **Step 2: Write the failing grid tests**

Create `web/src/features/topics/RenderGrid.test.tsx`:

```tsx
import userEvent from "@testing-library/user-event";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { GenerationRequest, RenderRecord } from "@/api/types";
import { RenderGrid } from "@/features/topics/RenderGrid";
import { makeRenderRecord } from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

// `makeRenderRecord`'s own run, so a tile's link and the grid's hint agree.
const RUN_ID = "20260829T090000Z";

function renderGrid(renders: RenderRecord[], pending: GenerationRequest[] = []) {
  return renderWithProviders(
    <RenderGrid renders={renders} runId={RUN_ID} pending={pending} />,
  );
}

/** Every render id the grid sends a DELETE for, in order. */
function recordDeletes(): string[] {
  const deleted: string[] = [];
  server.use(
    http.delete("/api/renders/:renderId", ({ params }) => {
      deleted.push(String(params.renderId));
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return deleted;
}

describe("RenderGrid", () => {
  it("draws a ready render as its image, linked to the full-size view", () => {
    // Hand-written rather than the factory's default `auto`, so a footer
    // that printed "auto" without reading the row's provenance would fail.
    renderGrid([makeRenderRecord({ id: "r1", templateId: "drake", rationale: null })]);

    expect(screen.getByAltText("drake meme").closest("a")).toHaveAttribute(
      "href",
      `/runs/${RUN_ID}/renders/r1`,
    );
    expect(screen.getByText("drake · manual")).toBeInTheDocument();
  });

  it("draws a generating model render as a brief being written, with no image yet", () => {
    renderGrid([makeRenderRecord({ id: "g1", status: "generating" })]);

    expect(screen.getByText("writing brief…")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("says a generating hand-written render is going straight to the renderer", () => {
    // The handoff draws "writing brief…" on a manual tile. A hand-written
    // render has no brief to write.
    renderGrid([makeRenderRecord({ id: "g1", status: "generating", rationale: null })]);

    expect(screen.getByText("rendering…")).toBeInTheDocument();
    expect(screen.queryByText("writing brief…")).not.toBeInTheDocument();
  });

  it("names no template on a render the model has not chosen one for yet", () => {
    renderGrid([
      makeRenderRecord({
        id: "g1",
        status: "generating",
        templateId: null,
        captionSlots: {},
      }),
    ]);

    expect(screen.getByText("choosing… · auto")).toBeInTheDocument();
  });

  it("keeps a failed render's tile, carrying the server's reason", () => {
    // Per the handoff: a failed render keeps its tile rather than vanishing.
    renderGrid([
      makeRenderRecord({
        id: "f1",
        status: "failed",
        error: "caption for rejected overflows its box",
      }),
    ]);

    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("caption for rejected overflows its box")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("names no template on a failed render whose brief failed before choosing one", () => {
    // Task 1's other template-less state. "null · auto" is not a label.
    renderGrid([
      makeRenderRecord({
        id: "f1",
        status: "failed",
        templateId: null,
        captionSlots: {},
        error: "the model is down",
      }),
    ]);

    expect(screen.getByText("no template · auto")).toBeInTheDocument();
  });

  it("counts what is ready, generating and failed above the grid", () => {
    // Three counts that differ — 3 ready; 1 generating row plus 1 meme a
    // request in flight asked for, so 2 generating; 1 failed — so no count
    // can be computed from the wrong status, and a placeholder total that
    // replaced the generating rows instead of adding to them reads 1.
    renderGrid(
      [
        makeRenderRecord({ id: "r1" }),
        makeRenderRecord({ id: "r2" }),
        makeRenderRecord({ id: "r3" }),
        makeRenderRecord({ id: "g1", status: "generating" }),
        makeRenderRecord({ id: "f1", status: "failed", error: "overflow" }),
      ],
      [{ mode: "llm", template_id: null, count: 1 }],
    );

    expect(
      screen.getByText("3 from …829T090000Z · 2 generating · 1 failed"),
    ).toBeInTheDocument();
  });

  it("draws a placeholder for every meme a request in flight asked for", () => {
    // "Both buttons immediately append placeholder tiles", per the handoff:
    // three asked for is three tiles, before the server has answered.
    renderGrid([], [{ mode: "llm", template_id: null, count: 3 }]);

    expect(screen.getAllByText("writing brief…")).toHaveLength(3);
    expect(screen.getByText("0 from …829T090000Z · 3 generating")).toBeInTheDocument();
  });

  it("offers no cancel on a placeholder, which has no row to cancel yet", () => {
    renderGrid(
      [],
      [
        {
          mode: "manual",
          template_id: "drake",
          caption_slots: { rejected: "a", preferred: "b" },
        },
      ],
    );

    expect(screen.getByText("drake · manual")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel render" })).not.toBeInTheDocument();
  });

  it("says nothing has rendered yet, in place of an empty grid", () => {
    renderGrid([]);

    expect(
      screen.getByText("Nothing rendered yet — use the panel above"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/ from …/)).not.toBeInTheDocument();
  });

  it("asks before deleting a ready render, and deletes only on yes", async () => {
    const deleted = recordDeletes();
    const user = userEvent.setup();
    renderGrid([makeRenderRecord({ id: "r1" })]);

    await user.click(screen.getByRole("button", { name: "Delete render" }));
    expect(screen.getByText("Delete this render?")).toBeInTheDocument();
    expect(deleted).toEqual([]);

    await user.click(screen.getByRole("button", { name: "yes" }));
    await waitFor(() => expect(deleted).toEqual(["r1"]));
  });

  it("cancels a generating render at once, without asking", async () => {
    // Nothing has been made yet, so there is nothing to lose but the wait.
    const deleted = recordDeletes();
    const user = userEvent.setup();
    renderGrid([makeRenderRecord({ id: "g1", status: "generating" })]);

    await user.click(screen.getByRole("button", { name: "Cancel render" }));

    await waitFor(() => expect(deleted).toEqual(["g1"]));
    expect(screen.queryByText("Delete this render?")).not.toBeInTheDocument();
  });

  it("dismisses a failed render at once, without asking", async () => {
    // No image to lose: the tile only carries a reason.
    const deleted = recordDeletes();
    const user = userEvent.setup();
    renderGrid([makeRenderRecord({ id: "f1", status: "failed", error: "overflow" })]);

    await user.click(screen.getByRole("button", { name: "Dismiss render" }));

    await waitFor(() => expect(deleted).toEqual(["f1"]));
  });

  it("dims a tile while its deletion is on its way", async () => {
    // One click must not become two DELETEs, and the tile must say it heard.
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.delete("/api/renders/:renderId", async () => {
        await held;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderGrid([makeRenderRecord({ id: "g1", status: "generating" })]);

    await user.click(screen.getByRole("button", { name: "Cancel render" }));

    expect(await screen.findByText("deleting…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel render" })).not.toBeInTheDocument();
    release();
  });

  it("keeps a tile the server would not delete, with the server's reason", async () => {
    server.use(
      http.delete("/api/renders/:renderId", () =>
        HttpResponse.json({ detail: "Permission denied: renders/r1.png" }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderGrid([makeRenderRecord({ id: "r1" })]);

    await user.click(screen.getByRole("button", { name: "Delete render" }));
    await user.click(screen.getByRole("button", { name: "yes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Permission denied: renders/r1.png",
    );
    expect(screen.getByAltText("drake meme")).toBeInTheDocument();
  });

  it.each([
    {
      state: "generating",
      render: makeRenderRecord({ id: "x1", status: "generating" }),
      cross: "Cancel render",
    },
    {
      state: "failed",
      render: makeRenderRecord({ id: "x1", status: "failed", error: "overflow" }),
      cross: "Dismiss render",
    },
  ])("says why a $state tile the server would not delete is still there", async ({ render, cross }) => {
    // Each branch of RenderTile draws the delete error itself — the
    // generating one outside GeneratingTile — so each can drop it alone.
    server.use(
      http.delete("/api/renders/:renderId", () =>
        HttpResponse.json({ detail: "Permission denied: renders/x1.png" }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderGrid([render]);

    await user.click(screen.getByRole("button", { name: cross }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Permission denied: renders/x1.png",
    );
  });
});
```

The grid is rendered without the page, so no topic detail is cached. The
delete hook's cache write is a no-op here, and nothing is refetched.
Whether the tile leaves the *page* is asserted in Step 3, where the cache
is real.

- [ ] **Step 3: Replace the phase 5 grid tests on the page**

In `web/src/features/topics/TopicDetailPage.test.tsx`:

Delete `shows only the renders that have an image behind them` and
`draws no render section at all when nothing has rendered yet`. Both pinned
phase 5's deliberate absence of this phase's states, and their comments say
so. `RenderGrid.test.tsx` now covers what replaces them.

Add `userEvent` to the imports
(`import userEvent from "@testing-library/user-event";`) and add:

```tsx
  it("takes a deleted render off the page, and leaves the others", async () => {
    // "The tile disappearing is the confirmation", per the handoff. The
    // server's list shrinks with the deletion, so the refetch that follows
    // agrees with what the page already drew.
    let renders = [
      makeRenderRecord({ id: "r1", templateId: "drake" }),
      makeRenderRecord({ id: "r2", templateId: "two_buttons" }),
    ];
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json(makeTopicDetail({ renders })),
      ),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
      http.delete("/api/renders/:renderId", ({ params }) => {
        renders = renders.filter((render) => render.id !== params.renderId);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    const tile = (await screen.findByAltText("drake meme")).closest("li");
    if (!(tile instanceof HTMLElement)) throw new Error("drake's tile is not a list item");
    await user.click(within(tile).getByRole("button", { name: "Delete render" }));
    await user.click(within(tile).getByRole("button", { name: "yes" }));

    await waitFor(() => expect(screen.queryByAltText("drake meme")).not.toBeInTheDocument());
    expect(screen.getByAltText("two_buttons meme")).toBeInTheDocument();
  });
```

Add `waitFor` to the `@testing-library/react` import.

- [ ] **Step 4: Run the tests to verify they fail**

Run: `npm --prefix web test -- MemeTile RenderGrid TopicDetailPage`

Expected: FAIL. `size="grid"` is not a valid size, `RenderGrid` takes no
`pending` prop, and there is no `writing brief…`, `Delete render` or
`Nothing rendered yet`.

- [ ] **Step 5: Give `MemeTile` a grid size**

In `web/src/components/MemeTile.tsx`, update the docstring's first sentence
and its closing line:

```tsx
 * One rendered meme, at one of the sizes the design draws: 34px in a
 * runs-list row, 42px in a ranking row, 96px square, and `"grid"` — the
 * full width of a topic-detail tile, 112px tall.
```

```tsx
 * The tile's other states — generating, failed as a row, confirming a
 * delete — belong to the card around it, `features/topics/RenderTile`,
 * because they live in its footer and its preview rather than in the image.
```

(The second replaces the line "Phase 7 adds the other two states,
`confirming` and `generating`.")

Change the size type and the body:

```tsx
  size: 34 | 42 | 96 | "grid";
```

```tsx
  const grid = size === "grid";
  // Anything drawn wider than the 96px thumbnail gets the full PNG.
  // `size === "grid"` is spelled out rather than reusing `grid`, so the
  // comparison on its right narrows `size` to a number without leaning on
  // aliased-condition narrowing.
  const source = size === "grid" || size >= 96 ? "full" : "thumb";
  const box = grid ? undefined : { "--tile": `${size}px` };

  if (failed) {
    return (
      <span
        className={grid ? `${styles.failed} ${styles.grid}` : styles.failed}
        style={box}
        title={`Render ${renderId} has no image on disk`}
      >
        failed
      </span>
    );
  }

  const image = (
    <img
      className={styles.image}
      src={imageUrl(renderId, source)}
      alt={templateId === undefined ? "meme" : `${templateId} meme`}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );

  return (
    <span className={grid ? `${styles.tile} ${styles.grid}` : styles.tile} style={box}>
      {to === undefined ? image : <Link to={to}>{image}</Link>}
    </span>
  );
```

Append to `web/src/components/MemeTile.module.css`:

```css
/* A linked tile's anchor fills the tile, so the image's 100% × 100% has a
   box to be a percentage of — at the grid size an unsized anchor left the
   image its natural 1180px wide. */
.tile > a {
  display: flex;
  width: 100%;
  height: 100%;
}

/* Topic detail's tile: the card's full width, 112px tall, per 2e. The card
   around it carries the border and the radius, so the image carries
   neither. Declared after `.tile` and `.failed` so it wins at equal
   specificity. */
.grid {
  width: 100%;
  height: 112px;
  border-radius: 0;
}

.tile.grid {
  border: none;
}
```

- [ ] **Step 6: Write the tile**

Create `web/src/features/topics/RenderTile.tsx`:

```tsx
import { useDeleteRender } from "@/api/queries";
import type { RenderRecord } from "@/api/types";
import { InlineConfirm } from "@/components/InlineConfirm";
import { MemeTile } from "@/components/MemeTile";

import styles from "./RenderTile.module.css";

/**
 * A tile still being made: the handoff's generating state, and — with no
 * `onCancel` — the placeholder the grid draws for a request in flight.
 *
 * The bar sweeps rather than standing at the mockup's 45%: nothing reports
 * how far along a brief is, so a fixed fraction would be a number made up
 * for the screen. See the plan's "Decisions", 4.
 */
export function GeneratingTile({
  label,
  doing,
  onCancel,
}: {
  label: string;
  doing: string;
  onCancel?: () => void;
}) {
  return (
    <div className={styles.generating}>
      <div className={styles.working}>
        <span className={styles.track} aria-hidden="true">
          <span className={styles.sweep} />
        </span>
        <span className={styles.doing}>{doing}</span>
      </div>
      <div className={styles.footer}>
        <span className={styles.line}>{label}</span>
        {onCancel !== undefined && (
          <button
            type="button"
            className={styles.cross}
            aria-label="Cancel render"
            onClick={onCancel}
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * One tile of "Rendered from this topic", in whichever state its row is.
 *
 * - **ready** — the image, linked to its full-size view, and a `✕` that
 *   asks first: a ready render is a PNG someone may want.
 * - **generating** — `GeneratingTile`, whose `✕` cancels at once: nothing
 *   has been made, so there is nothing to lose but the wait. The job keeps
 *   running server-side and its result is dropped, because a deleted row
 *   stays deleted (`generation._draw`).
 * - **failed** — kept rather than vanishing, per the handoff, with the
 *   server's own sentence in the footer. Its `✕` dismisses at once: there
 *   is no image to lose.
 * - **deleting** — dimmed until the row leaves the cache, so one click
 *   cannot become two DELETEs.
 *
 * See the plan's "Decisions", 5 and 6.
 */
export function RenderTile({ render }: { render: RenderRecord }) {
  const remove = useDeleteRender();
  const provenance = render.origin.provenance;
  const failure = remove.isError ? (
    <p role="alert" className={styles.deleteError}>
      {remove.error.detail}
    </p>
  ) : null;

  if (remove.isPending) {
    return (
      <div className={styles.deleting}>
        <div className={styles.preview} />
        <div className={styles.footer}>
          <span className={styles.line}>deleting…</span>
        </div>
      </div>
    );
  }

  if (render.status === "generating") {
    return (
      <>
        <GeneratingTile
          label={`${render.template_id ?? "choosing…"} · ${provenance}`}
          doing={provenance === "manual" ? "rendering…" : "writing brief…"}
          onCancel={() => remove.mutate(render)}
        />
        {failure}
      </>
    );
  }

  if (render.status === "failed") {
    return (
      <div className={styles.failed}>
        <div className={styles.failedPreview}>
          <span className={styles.failedWord}>failed</span>
          <span className={styles.failedLine}>
            {`${render.template_id ?? "no template"} · ${provenance}`}
          </span>
        </div>
        <div className={styles.footer}>
          <span className={styles.error} title={render.error ?? undefined}>
            {render.error ?? "No reason was recorded."}
          </span>
          <button
            type="button"
            className={styles.cross}
            aria-label="Dismiss render"
            onClick={() => remove.mutate(render)}
          >
            ✕
          </button>
        </div>
        {failure}
      </div>
    );
  }

  const to =
    `/runs/${encodeURIComponent(render.run_id)}` +
    `/renders/${encodeURIComponent(render.id)}`;
  return (
    <div className={styles.tile}>
      <MemeTile
        renderId={render.id}
        size="grid"
        to={to}
        templateId={render.template_id ?? undefined}
      />
      <InlineConfirm
        variant="tile"
        label="✕"
        ariaLabel="Delete render"
        question="Delete this render?"
        resting={
          <span className={styles.line}>
            {`${render.template_id ?? "no template"} · ${provenance}`}
          </span>
        }
        onConfirm={() => remove.mutate(render)}
      />
      {failure}
    </div>
  );
}
```

The generating branch's `failure` sits outside the tile's border, in a
fragment. That is the one state where the tile is drawn by
`GeneratingTile`, which the placeholders share, so the error line cannot go
inside it without giving placeholders a slot they never use.

Create `web/src/features/topics/RenderTile.module.css`:

```css
/* The handoff's 2e tile: radius 8, a 112px preview, and a footer of
   `<template> · auto|manual` and a `✕`. */
.tile,
.generating,
.failed,
.deleting {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: var(--radius-tile);
  overflow: hidden;
  background: var(--surface);
}

/* Accent at 40% in the mockup; accent-border-strong (35%) is the nearest
   token, and the spec adds none for the states it designs. */
.generating {
  border-color: var(--accent-border-strong);
  background: var(--accent-wash);
}

.failed {
  border: 1px dashed var(--contrast-border);
  background: none;
}

.deleting {
  opacity: 0.5;
}

.preview {
  height: 112px;
  background: var(--stripe);
}

.working,
.failedPreview {
  height: 112px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

/* White at 12% in the mockup; border-strong (14%) is the nearest token. */
.track {
  position: relative;
  width: 64%;
  height: 3px;
  border-radius: 2px;
  background: var(--border-strong);
  overflow: hidden;
}

.sweep {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 45%;
  border-radius: 2px;
  background: var(--accent);
  animation: sweep 1.4s ease-in-out infinite;
}

/* From fully off the left edge to fully off the right: the track is 100 /
   45 = 2.22 segment-widths wide. */
@keyframes sweep {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(222%);
  }
}

@media (prefers-reduced-motion: reduce) {
  .sweep {
    animation: none;
  }
}

.doing {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  line-height: 1;
  color: var(--accent);
}

.footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
}

.line {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: 9.5px;
  line-height: 1.4;
  color: var(--text-35);
}

.cross {
  padding: 0;
  border: none;
  background: none;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  color: var(--text-35);
  cursor: pointer;
  transition: color var(--transition);
}

.cross:hover,
.cross:focus-visible {
  color: var(--text);
}

.failedWord {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  line-height: 1;
  color: var(--contrast-light);
}

.failedLine {
  font-family: var(--font-mono);
  font-size: 9.5px;
  line-height: 1;
  color: var(--text-35);
}

/* Two lines of the server's sentence at most; the rest is in the title. */
.error {
  flex: 1;
  min-width: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-family: var(--font-mono);
  font-size: 9.5px;
  line-height: 1.4;
  color: var(--contrast-light);
}

.deleteError {
  padding: 0 10px 8px;
  font-family: var(--font-mono);
  font-size: 9.5px;
  line-height: 1.4;
  color: var(--contrast-light);
}
```

- [ ] **Step 7: Rewrite the grid**

Replace `web/src/features/topics/RenderGrid.tsx` with:

```tsx
import type { GenerationRequest, RenderRecord } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";
import { GeneratingTile, RenderTile } from "@/features/topics/RenderTile";
import { shortRunId } from "@/format";

import styles from "./RenderGrid.module.css";

/**
 * `2 from …829T090000Z · 1 generating · 1 failed`.
 *
 * "From" counts what there is to look at — ready renders — which is what
 * phase 5's hint counted. The other clauses appear only when there is
 * something to count, so a settled topic reads exactly as it did then.
 */
function hint(renders: RenderRecord[], placeholders: number, runId: string): string {
  const count = (status: RenderRecord["status"]) =>
    renders.filter((render) => render.status === status).length;
  const parts = [`${count("ready")} from ${shortRunId(runId)}`];
  const generating = count("generating") + placeholders;
  if (generating > 0) parts.push(`${generating} generating`);
  const failed = count("failed");
  if (failed > 0) parts.push(`${failed} failed`);
  return parts.join(" · ");
}

/** One placeholder per meme a request still in flight asked for. */
function placeholdersFor(request: GenerationRequest): { label: string; doing: string }[] {
  if (request.mode === "manual") {
    return [{ label: `${request.template_id} · manual`, doing: "rendering…" }];
  }
  return Array.from({ length: request.count }, () => ({
    label: `${request.template_id ?? "choosing…"} · auto`,
    doing: "writing brief…",
  }));
}

/**
 * "Rendered from this topic": every row the topic has, in whatever state
 * it is in, then a placeholder for each meme a request in flight asked for.
 *
 * The placeholders are the handoff's "both buttons immediately append
 * placeholder tiles". They are drawn from the requests themselves while
 * those are on their way, and give way to the server's own `generating`
 * rows the moment a reply lands in the cache — see the plan's
 * "Decisions", 8. They carry no `✕`: there is no row yet to cancel.
 *
 * With nothing at all, the grid's place is taken by the spec's dashed
 * row, which points at the panels right above it.
 */
export function RenderGrid({
  renders,
  runId,
  pending,
}: {
  renders: RenderRecord[];
  runId: string;
  pending: GenerationRequest[];
}) {
  const placeholders = pending.flatMap(placeholdersFor);
  const empty = renders.length === 0 && placeholders.length === 0;

  return (
    <section className={styles.section}>
      <SectionLabel hint={empty ? undefined : hint(renders, placeholders.length, runId)}>
        Rendered from this topic
      </SectionLabel>
      {empty ? (
        <p className={styles.nothing}>Nothing rendered yet — use the panel above</p>
      ) : (
        <ul className={styles.grid}>
          {renders.map((render) => (
            <li key={render.id}>
              <RenderTile render={render} />
            </li>
          ))}
          {placeholders.map((tile, index) => (
            // Index keys are right here: a placeholder has no identity of
            // its own, and all of a request's placeholders go at once.
            <li key={`pending-${index}`}>
              <GeneratingTile label={tile.label} doing={tile.doing} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

Replace `web/src/features/topics/RenderGrid.module.css` with:

```css
.section {
  margin-top: var(--gap-page);
}

/* 4-up, per 2e. Past four tiles it wraps to a second row. */
.grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--gap-card);
}

/* The spec's nothing-rendered-yet row: the grid's place, dashed, with the
   one instruction that matters. The mockup's dashed white 10% is the
   border token (9%). */
.nothing {
  padding: 22px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-tile);
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1;
  text-align: center;
  color: var(--text-35);
}
```

- [ ] **Step 8: Hand the grid its new props**

In `web/src/features/topics/TopicDetailPage.tsx`, change the grid's
mounting to:

```tsx
            <RenderGrid renders={data.renders} runId={topic.run_id} pending={[]} />
```

Task 5 replaces `[]` with what the panels have in flight.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `npm --prefix web test -- MemeTile RenderGrid TopicDetailPage`

Expected: PASS.

- [ ] **Step 10: Run the whole frontend gate**

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: PASS. `no-raw-colours.test.ts` confirms the two new stylesheets
name no colour, and that every `styles.x` in `RenderTile.tsx` and
`RenderGrid.tsx` exists.

- [ ] **Step 11: Commit**

```bash
git add web/src/components/MemeTile.tsx web/src/components/MemeTile.module.css web/src/components/MemeTile.test.tsx web/src/features/topics/RenderTile.tsx web/src/features/topics/RenderTile.module.css web/src/features/topics/RenderGrid.tsx web/src/features/topics/RenderGrid.module.css web/src/features/topics/RenderGrid.test.tsx web/src/features/topics/TopicDetailPage.tsx web/src/features/topics/TopicDetailPage.test.tsx
git commit -m "feat(web): every state a render can be in, and deleting one"
```

---

### Task 5: Ask the LLM

The primary way to make a meme: solid accent border, accent wash. The
template is optional, with **Let the LLM choose** as the default; then how
many, then generate. The page owns the mutation, so the grid can draw its
placeholders.

**Files:**
- Create: `web/src/features/topics/LlmPanel.tsx` + `.module.css`
- Create: `web/src/features/topics/GeneratePanels.tsx` + `.module.css`
- Modify: `web/src/features/topics/TopicDetailPage.tsx`
- Create: `web/src/features/topics/GeneratePanels.test.tsx`
- Modify: `web/src/features/topics/TopicDetailPage.test.tsx` (the options handler)

**Interfaces:**
- Consumes: `useGenerateRenders`, `GenerateMutation`, `useConfigOptions` (Task 2); `RenderGrid`'s `pending` (Task 4); `TemplateOption`, `TopicRow`.
- Produces:
  - `LlmPanel({ topic, templates, generation }: { topic: TopicRow; templates: TemplateOption[]; generation: GenerateMutation })`.
  - `GeneratePanels({ topic, templates, llm }: { topic: TopicRow; templates: TemplateOption[]; llm: GenerateMutation })` — Task 6 adds `manual`.
  - In `GeneratePanels.test.tsx`: `serveTopic(options)`, `renderPage()`, and `threeGenerating()`, which Task 6's tests reuse.

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/topics/GeneratePanels.test.tsx`:

```tsx
import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { RenderRecord, TemplateOption } from "@/api/types";
import { TopicDetailPage } from "@/features/topics/TopicDetailPage";
import {
  makeConfigOptions,
  makeRenderRecord,
  makeRunDetail,
  makeTopicDetail,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

const RUN_ID = "20260829T090000Z";
const TOPIC_ID = "topic-1";

interface Served {
  /** Every body the page posted, in order. */
  posted: unknown[];
  /** Let a held POST answer. */
  release: () => void;
}

/**
 * Topic detail, its run, the template library, and the renders endpoint,
 * with the topic's renders held as server state so the page's poll and the
 * panels' posts agree about what exists.
 *
 * A fixture that answered every GET with the same list would take back the
 * rows a post had just added the moment the page polled for them, and a
 * test asserting on those rows would be asserting on the fixture.
 */
function serveTopic(
  options: {
    topic?: Parameters<typeof makeTopicDetail>[0];
    templates?: TemplateOption[];
    /** The topic's renders before anything is posted. None by default. */
    initial?: RenderRecord[];
    /** The rows each accepted POST creates. */
    created?: RenderRecord[];
    /** Hold every POST until `release()` is called. */
    hold?: boolean;
    /** Refuse every POST with this 400 detail. */
    refuse?: string;
  } = {},
): Served {
  let renders: RenderRecord[] = options.initial ?? [];
  const posted: unknown[] = [];
  let release: () => void = () => undefined;
  const gate =
    options.hold === true
      ? new Promise<void>((resolve) => {
          release = resolve;
        })
      : Promise.resolve();

  server.use(
    http.get("/api/runs/:runId/topics/:topicId", () =>
      HttpResponse.json(makeTopicDetail({ ...options.topic, renders })),
    ),
    http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
    http.get("/api/config/options", () =>
      HttpResponse.json(makeConfigOptions({ templates: options.templates })),
    ),
    http.post("/api/runs/:runId/topics/:topicId/renders", async ({ request }) => {
      posted.push(await request.json());
      await gate;
      if (options.refuse !== undefined) {
        return HttpResponse.json({ detail: options.refuse }, { status: 400 });
      }
      const created = options.created ?? [];
      renders = [...renders, ...created];
      return HttpResponse.json(created, { status: 202 });
    }),
  );
  return { posted, release: () => release() };
}

function renderPage() {
  return renderWithProviders(<TopicDetailPage />, {
    route: `/topics/${RUN_ID}/${TOPIC_ID}`,
    path: "/topics/:runId/:topicId",
  });
}

/** What the server seeds for "Generate 3 memes" with the model choosing. */
function threeGenerating(): RenderRecord[] {
  return ["new-1", "new-2", "new-3"].map((id) =>
    makeRenderRecord({
      id,
      status: "generating",
      templateId: null,
      captionSlots: {},
      rationale: "",
    }),
  );
}

describe("Ask the LLM", () => {
  it("leaves the template to the model by default, and says what it will choose for", async () => {
    // Not the factory's funny / riffing, which is also the mockup's copy
    // word for word: a panel that printed the mockup's sentence would pass
    // with those.
    serveTopic({ topic: { sentiment: "cute", register: "delight" } });
    renderPage();

    expect(await screen.findByRole("radio", { name: /Let the LLM choose/ })).toBeChecked();
    expect(
      screen.getByText("picks the templates that suit cute / delight"),
    ).toBeInTheDocument();
  });

  it("says it will choose for the topic itself when no mood was recorded", async () => {
    // The dormant path writes no dossier, so no sentiment and no register.
    // "suit " followed by nothing would be a sentence with a hole in it.
    serveTopic({
      topic: { sentiment: null, register: null, dossier: null, scoreComponents: {} },
    });
    renderPage();

    expect(
      await screen.findByText("picks the templates that suit this topic"),
    ).toBeInTheDocument();
  });

  it("offers every template in the library as an override, with its slot count", async () => {
    // Driven by the loaded manifests, not by the four the handoff drew. One
    // slot reads "1 slot": phase 5's walk found a "1 memes".
    serveTopic({
      templates: [
        { id: "drake", slots: ["rejected", "preferred"] },
        { id: "single", slots: ["caption"] },
      ],
    });
    renderPage();

    const panel = within(await screen.findByRole("region", { name: "Ask the LLM" }));
    expect(panel.getByRole("radio", { name: /^drake/ })).not.toBeChecked();
    expect(panel.getByText("2 slots")).toBeInTheDocument();
    expect(panel.getByRole("radio", { name: /^single/ })).not.toBeChecked();
    expect(panel.getByText("1 slot")).toBeInTheDocument();
  });

  it("generates three by default, and the button says how many", async () => {
    serveTopic();
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("button", { name: "Generate 3 memes" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "1" }));
    expect(screen.getByRole("button", { name: "Generate 1 meme" })).toBeInTheDocument();
  });

  it("posts no template when the model is left to choose", async () => {
    const served = serveTopic({ created: threeGenerating() });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Generate 3 memes" }));

    await waitFor(() =>
      expect(served.posted).toEqual([{ mode: "llm", template_id: null, count: 3 }]),
    );
  });

  it("posts the template picked as an override", async () => {
    const served = serveTopic({
      created: [makeRenderRecord({ id: "new-1", status: "generating", captionSlots: {} })],
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("radio", { name: /^drake/ }));
    await user.click(screen.getByRole("button", { name: "1" }));
    await user.click(screen.getByRole("button", { name: "Generate 1 meme" }));

    await waitFor(() =>
      expect(served.posted).toEqual([{ mode: "llm", template_id: "drake", count: 1 }]),
    );
  });

  it("posts no template again once the choice is handed back to the model", async () => {
    // The default is also a choice someone can come back to. A "Let the
    // LLM choose" row that did not clear the tile picked before it would
    // keep posting that tile.
    const served = serveTopic({ created: threeGenerating() });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("radio", { name: /^drake/ }));
    await user.click(screen.getByRole("radio", { name: /Let the LLM choose/ }));
    await user.click(screen.getByRole("button", { name: "Generate 3 memes" }));

    await waitFor(() =>
      expect(served.posted).toEqual([{ mode: "llm", template_id: null, count: 3 }]),
    );
  });

  it("still draws what was rendered when the template library cannot be read", async () => {
    // The panels need the library; the grid does not. A failure loading one
    // must not take the other down with it — the renders are still there
    // to look at and delete.
    serveTopic({ initial: [makeRenderRecord({ id: "r1", templateId: "drake" })] });
    server.use(
      http.get("/api/config/options", () =>
        HttpResponse.json({ detail: "templates_dir does not exist" }, { status: 500 }),
      ),
    );
    renderPage();

    expect(await screen.findByText("templates_dir does not exist")).toBeInTheDocument();
    expect(screen.getByAltText("drake meme")).toBeInTheDocument();
  });

  it("draws a placeholder per meme the moment it is asked for, then the rows the server made", async () => {
    const served = serveTopic({ created: threeGenerating(), hold: true });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Generate 3 memes" }));

    // Before the server has answered: three placeholders, none of them
    // cancellable, because there is no row yet to cancel.
    expect(await screen.findAllByText("writing brief…")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: "Cancel render" })).not.toBeInTheDocument();

    served.release();

    // The server's own rows, which can be cancelled — and still three, not
    // three placeholders plus three rows.
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "Cancel render" })).toHaveLength(3),
    );
    expect(screen.getAllByText("writing brief…")).toHaveLength(3);
  });

  it("will not post a second request while the first is on its way", async () => {
    // Each meme is a model call. A button still armed while its request is
    // in flight turns a double-click into twice the calls and the tiles.
    const served = serveTopic({ created: threeGenerating(), hold: true });
    const user = userEvent.setup();
    renderPage();

    const generate = await screen.findByRole("button", { name: "Generate 3 memes" });
    await user.click(generate);
    await waitFor(() => expect(generate).toBeDisabled());
    await user.click(generate);

    served.release();
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "Cancel render" })).toHaveLength(3),
    );
    expect(served.posted).toHaveLength(1);
  });

  it("shows the server's reason when it will not generate, and leaves nothing drawn", async () => {
    serveTopic({ refuse: "ANTHROPIC_API_KEY is required for the anthropic provider" });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Generate 3 memes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "ANTHROPIC_API_KEY is required for the anthropic provider",
    );
    expect(screen.queryByText("writing brief…")).not.toBeInTheDocument();
    expect(
      screen.getByText("Nothing rendered yet — use the panel above"),
    ).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Serve the template library to the existing page tests**

The page now asks for `/api/config/options`, and MSW errors on anything a
test did not declare. In `web/src/features/topics/TopicDetailPage.test.tsx`,
add `makeConfigOptions` to the factories import, then add this line to
`serve()`'s `server.use(...)`, and to the `server.use(...)` of the
`takes a deleted render off the page` test Task 4 added:

```tsx
    http.get("/api/config/options", () => HttpResponse.json(makeConfigOptions())),
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `npm --prefix web test -- GeneratePanels`

Expected: FAIL. No `Ask the LLM` region, no radios, and no generate button.

- [ ] **Step 4: Write the panel**

Create `web/src/features/topics/LlmPanel.tsx`:

```tsx
import { useId, useState } from "react";

import type { GenerateMutation } from "@/api/queries";
import type { TemplateOption, TopicRow } from "@/api/types";

import styles from "./LlmPanel.module.css";

/** HOW MANY. The design's `5` is past `MAX_RENDERS` — "Decisions", 2. */
const COUNTS = [1, 3];
const DEFAULT_COUNT = 3;

/**
 * `picks the templates that suit funny / riffing` — the topic's event
 * sentiment and conversation register, which is what the model chooses
 * by. A topic with no dossier has neither, and the line says so rather
 * than ending on an empty "suit ".
 */
function suits(topic: TopicRow): string {
  const traits = [topic.event_sentiment, topic.conversation_register].filter(
    (trait): trait is string => typeof trait === "string" && trait !== "",
  );
  return traits.length === 0
    ? "picks the templates that suit this topic"
    : `picks the templates that suit ${traits.join(" / ")}`;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/**
 * Ask the LLM: the primary way to make a meme, so it reads solid.
 *
 * The template is optional. **Let the LLM choose** is the default and
 * posts `template_id: null`, which offers the model the whole library;
 * picking a tile narrows it to that one template. The tiles are the loaded
 * library, never the four templates the handoff drew.
 *
 * Real radio inputs, visually hidden, with the row and the tiles as their
 * labels: one choice from a set is what a radio group is, and it gives a
 * keyboard and a screen reader the arrow-key behaviour for free.
 */
export function LlmPanel({
  topic,
  templates,
  generation,
}: {
  topic: TopicRow;
  templates: TemplateOption[];
  generation: GenerateMutation;
}) {
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [count, setCount] = useState(DEFAULT_COUNT);
  const titleId = useId();
  const groupId = useId();
  const countId = useId();
  const radioName = useId();

  return (
    <section className={styles.panel} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.title}>
        Ask the LLM
      </h2>
      <p className={styles.subhead}>
        Writes fresh briefs from the dossier, then renders them. Costs a model call
        each.
      </p>

      <div className={styles.labelRow}>
        <span id={groupId} className={styles.fieldLabel}>
          Template
        </span>
        <span className={styles.optional}>optional</span>
      </div>
      <div role="radiogroup" aria-labelledby={groupId}>
        <label className={templateId === null ? styles.chooseOn : styles.choose}>
          <input
            type="radio"
            className={styles.srOnly}
            name={radioName}
            checked={templateId === null}
            onChange={() => setTemplateId(null)}
          />
          <span className={styles.dot} aria-hidden="true" />
          <span className={styles.chooseText}>
            <span className={styles.chooseTitle}>Let the LLM choose</span>
            <span className={styles.chooseHint}>{suits(topic)}</span>
          </span>
        </label>
        <div className={styles.tiles}>
          {templates.map((template) => (
            <label
              key={template.id}
              className={templateId === template.id ? styles.tileOn : styles.tile}
            >
              <input
                type="radio"
                className={styles.srOnly}
                name={radioName}
                checked={templateId === template.id}
                onChange={() => setTemplateId(template.id)}
              />
              <span className={styles.stripe} aria-hidden="true" />
              <span className={styles.tileText}>
                <span className={styles.tileId}>{template.id}</span>
                <span className={styles.slots}>
                  {plural(template.slots.length, "slot", "slots")}
                </span>
              </span>
            </label>
          ))}
        </div>
      </div>

      <div className={styles.bottom}>
        <div>
          <span id={countId} className={styles.fieldLabel}>
            How many
          </span>
          <div className={styles.pills} role="group" aria-labelledby={countId}>
            {COUNTS.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={count === option}
                className={count === option ? styles.pillOn : styles.pill}
                onClick={() => setCount(option)}
              >
                {option}
              </button>
            ))}
          </div>
        </div>
        <button
          type="button"
          className={styles.generate}
          disabled={generation.isPending}
          onClick={() => generation.mutate({ mode: "llm", template_id: templateId, count })}
        >
          {`Generate ${plural(count, "meme", "memes")}`}
        </button>
      </div>

      {generation.isError && (
        <p role="alert" className={styles.error}>
          {generation.error.detail}
        </p>
      )}
    </section>
  );
}
```

Create `web/src/features/topics/LlmPanel.module.css`:

```css
/* 2e's ASK THE LLM: solid accent border, accent wash, 18px 20px, radius
   12. The mockup's fill is accent at 5%; accent-wash (6%) is the token. */
.panel {
  display: flex;
  flex-direction: column;
  padding: 18px 20px;
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-panel);
  background: var(--accent-wash);
}

.title {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--accent);
}

/* text-45 in the mockup; text-40 is the nearest token. */
.subhead {
  margin: 4px 0 16px;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text-40);
}

.labelRow {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 9px;
}

.fieldLabel {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  text-transform: uppercase;
  color: var(--text-40);
}

.optional {
  font-family: var(--font-mono);
  font-size: 9.5px;
  line-height: 1;
  color: var(--text-30);
}

.choose,
.chooseOn {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 9px;
  padding: 11px 13px;
  border: 1px solid var(--border);
  border-radius: 9px;
  cursor: pointer;
  transition: border-color var(--transition), background var(--transition);
}

/* Accent at 10% in the mockup; accent-tint (14%) is the nearest token. */
.chooseOn {
  border-color: var(--accent);
  background: var(--accent-tint);
}

.dot {
  flex: none;
  width: 12px;
  height: 12px;
  border: 1px solid var(--border-strong);
  border-radius: 50%;
}

.chooseOn .dot {
  border: 4px solid var(--accent);
}

.chooseText {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.chooseTitle {
  font-size: 11.5px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--text-70);
}

.chooseOn .chooseTitle {
  color: var(--accent);
}

.chooseHint {
  font-family: var(--font-mono);
  font-size: 9.5px;
  line-height: 1.4;
  color: var(--text-40);
}

/* 4-up per 2e; a fifth template wraps to a second row. */
.tiles {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 9px;
}

/* The mockup draws the tiles at opacity .6: they are optional overrides
   to the default above them, and read as such until one is picked. */
.tile,
.tileOn {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 9px;
  overflow: hidden;
  cursor: pointer;
  opacity: 0.6;
  transition: opacity var(--transition), border-color var(--transition);
}

.tile:hover {
  opacity: 0.85;
  border-color: var(--border-hover);
}

.tileOn {
  opacity: 1;
  border-color: var(--accent);
}

.choose:has(:focus-visible),
.chooseOn:has(:focus-visible),
.tile:has(:focus-visible),
.tileOn:has(:focus-visible) {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* The template tile's stripe is tighter than a meme's — 6px bands, per
   the mockup — so it is written out here from the two stripe tokens
   rather than reusing --stripe. */
.stripe {
  height: 60px;
  background: repeating-linear-gradient(
    135deg,
    var(--stripe-a) 0 6px,
    var(--stripe-b) 6px 12px
  );
}

.tileText {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 9px;
}

.tileId {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
  color: var(--text-70);
}

.slots {
  font-family: var(--font-mono);
  font-size: 9px;
  line-height: 1.4;
  color: var(--text-35);
}

.bottom {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-top: 18px;
}

.pills {
  display: flex;
  gap: var(--gap-tight);
  margin-top: 8px;
}

.pill,
.pillOn {
  padding: 8px 13px;
  border-radius: var(--radius-pill);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
}

.pill {
  border: 1px solid var(--border-strong);
  background: none;
  color: var(--text-55);
}

.pillOn {
  border: 1px solid var(--accent);
  background: var(--accent);
  color: var(--on-accent);
}

.generate {
  padding: 13px 20px;
  border: none;
  border-radius: var(--radius-tile);
  background: var(--accent);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  color: var(--on-accent);
  cursor: pointer;
  transition: filter var(--transition);
}

.generate:hover:not(:disabled) {
  filter: brightness(0.94);
}

.generate:disabled {
  opacity: 0.5;
  cursor: default;
}

.error {
  margin-top: 10px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--contrast-light);
}

/* A radio a person never sees, but a keyboard and a screen reader do: the
   row and the tiles are its labels. */
.srOnly {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
```

- [ ] **Step 5: Write the pair**

Create `web/src/features/topics/GeneratePanels.tsx`:

```tsx
import type { GenerateMutation } from "@/api/queries";
import type { TemplateOption, TopicRow } from "@/api/types";
import { LlmPanel } from "@/features/topics/LlmPanel";

import styles from "./GeneratePanels.module.css";

/**
 * Topic detail's ways to make a meme, side by side at `1fr 340px`.
 *
 * The split is load-bearing, per the handoff: asking the model is the
 * primary action and reads solid; writing it yourself is the deliberate,
 * quieter alternative.
 */
export function GeneratePanels({
  topic,
  templates,
  llm,
}: {
  topic: TopicRow;
  templates: TemplateOption[];
  llm: GenerateMutation;
}) {
  return (
    <div className={styles.panels}>
      <LlmPanel topic={topic} templates={templates} generation={llm} />
    </div>
  );
}
```

Create `web/src/features/topics/GeneratePanels.module.css`:

```css
/* 1fr 340px, 14px gap, the two panels the same height. The page's own
   14px gap plus this 10px is the mockup's 24px above the pair. */
.panels {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: var(--gap-section);
  align-items: stretch;
  margin-top: 10px;
}
```

Until Task 6 the second column is empty. That is a checkpoint between two
commits, not a design, and nothing in this task's code mentions it. The
tests assert the LLM panel's behaviour, and none depends on the column's
width.

- [ ] **Step 6: Mount the panel, and hand the grid what is in flight**

In `web/src/features/topics/TopicDetailPage.tsx`, change the queries import
and add the panels import:

```tsx
import { useConfigOptions, useGenerateRenders, useRun, useTopicDetail } from "@/api/queries";
```

```tsx
import { GeneratePanels } from "@/features/topics/GeneratePanels";
```

After `const run = useRun(runId);`, add:

```tsx
  // The template library the panel offers: the loaded manifests, never the
  // four templates the handoff happened to draw.
  const options = useConfigOptions();
  // Owned here rather than by the panel: the grid draws a placeholder for
  // every meme a request in flight asked for, and the page is what the
  // panel and the grid share. See the plan's "Decisions", 8.
  const llm = useGenerateRenders(runId ?? "", topicId ?? "");
  const pending = llm.isPending && llm.variables !== undefined ? [llm.variables] : [];
```

Between the conversation block and the grid, add the panels, and give the
grid `pending`:

```tsx
            <QueryBoundary query={options} missing="No template library was found.">
              {(choices) => (
                <GeneratePanels topic={topic} templates={choices.templates} llm={llm} />
              )}
            </QueryBoundary>

            <RenderGrid renders={data.renders} runId={topic.run_id} pending={pending} />
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `npm --prefix web test -- GeneratePanels TopicDetailPage`

Expected: PASS.

- [ ] **Step 8: Run the whole frontend gate**

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add web/src/features/topics/LlmPanel.tsx web/src/features/topics/LlmPanel.module.css web/src/features/topics/GeneratePanels.tsx web/src/features/topics/GeneratePanels.module.css web/src/features/topics/GeneratePanels.test.tsx web/src/features/topics/TopicDetailPage.tsx web/src/features/topics/TopicDetailPage.test.tsx
git commit -m "feat(web): ask the model for memes from topic detail"
```

---

### Task 6: Write it yourself

The quieter alternative: a dashed border, muted labels, a ghost button. It
has one field per slot of the chosen template, named for the slot, and goes
straight to the renderer with no model call. The handoff says "Slot names in
the manual render panel must be read from the selected template's manifest,
not hardcoded."

**Files:**
- Create: `web/src/features/topics/ManualPanel.tsx` + `.module.css`
- Modify: `web/src/features/topics/GeneratePanels.tsx` (the second column)
- Modify: `web/src/features/topics/TopicDetailPage.tsx` (the second mutation)
- Test: `web/src/features/topics/GeneratePanels.test.tsx`

**Interfaces:**
- Consumes: `useGenerateRenders`, `GenerateMutation` (Task 2); `serveTopic`, `renderPage` (Task 5's test helpers).
- Produces:
  - `ManualPanel({ templates, generation }: { templates: TemplateOption[]; generation: GenerateMutation })`.
  - `GeneratePanels` gains `manual: GenerateMutation`.

- [ ] **Step 1: Write the failing tests**

Add to `web/src/features/topics/GeneratePanels.test.tsx`:

```tsx
describe("Write it yourself", () => {
  async function manualPanel() {
    return within(await screen.findByRole("region", { name: "Write it yourself" }));
  }

  it("writes one field per slot of the chosen template, named for the slot", async () => {
    serveTopic();
    renderPage();

    const panel = await manualPanel();
    expect(panel.getByRole("combobox", { name: "Template" })).toHaveValue("drake");
    expect(panel.getByRole("textbox", { name: "rejected" })).toBeInTheDocument();
    expect(panel.getByRole("textbox", { name: "preferred" })).toBeInTheDocument();
    expect(panel.getAllByRole("textbox")).toHaveLength(2);
  });

  it("swaps the fields when the template changes", async () => {
    serveTopic();
    const user = userEvent.setup();
    renderPage();

    const panel = await manualPanel();
    await user.selectOptions(panel.getByRole("combobox", { name: "Template" }), "two_buttons");

    expect(panel.getByRole("textbox", { name: "left" })).toBeInTheDocument();
    expect(panel.getByRole("textbox", { name: "sweating" })).toBeInTheDocument();
    expect(panel.queryByRole("textbox", { name: "rejected" })).not.toBeInTheDocument();
  });

  it("keeps what was typed for a template while another is looked at", async () => {
    serveTopic();
    const user = userEvent.setup();
    renderPage();

    const panel = await manualPanel();
    const picker = panel.getByRole("combobox", { name: "Template" });
    await user.type(panel.getByRole("textbox", { name: "rejected" }), "Filing an incident report");
    await user.selectOptions(picker, "two_buttons");
    await user.selectOptions(picker, "drake");

    expect(panel.getByRole("textbox", { name: "rejected" })).toHaveValue(
      "Filing an incident report",
    );
  });

  it("will not render until every slot has a caption", async () => {
    // The server refuses a blank slot with a 400; the button refusing first
    // saves the round trip. Whitespace is blank to both.
    serveTopic();
    const user = userEvent.setup();
    renderPage();

    const panel = await manualPanel();
    const render = panel.getByRole("button", { name: "Render" });
    expect(render).toBeDisabled();

    await user.type(panel.getByRole("textbox", { name: "rejected" }), "Filing an incident report");
    expect(render).toBeDisabled();

    await user.type(panel.getByRole("textbox", { name: "preferred" }), "   ");
    expect(render).toBeDisabled();

    await user.type(panel.getByRole("textbox", { name: "preferred" }), "Becoming the incident");
    expect(render).toBeEnabled();
  });

  it("posts the chosen template's captions, trimmed", async () => {
    const served = serveTopic({
      created: [
        makeRenderRecord({ id: "new-1", status: "generating", rationale: null }),
      ],
    });
    const user = userEvent.setup();
    renderPage();

    const panel = await manualPanel();
    await user.type(panel.getByRole("textbox", { name: "rejected" }), " Filing an incident report ");
    await user.type(panel.getByRole("textbox", { name: "preferred" }), "Becoming the incident");
    await user.click(panel.getByRole("button", { name: "Render" }));

    await waitFor(() =>
      expect(served.posted).toEqual([
        {
          mode: "manual",
          template_id: "drake",
          caption_slots: {
            rejected: "Filing an incident report",
            preferred: "Becoming the incident",
          },
        },
      ]),
    );
  });

  it("posts only the slots of the template it ends on", async () => {
    // Captions typed for one template are kept while another is looked at,
    // so switching back does not lose them — but they are not the new
    // template's slots, and the server refuses unknown ones.
    const served = serveTopic({
      created: [
        makeRenderRecord({ id: "new-1", status: "generating", rationale: null }),
      ],
    });
    const user = userEvent.setup();
    renderPage();

    const panel = await manualPanel();
    await user.type(panel.getByRole("textbox", { name: "rejected" }), "Filing an incident report");
    await user.selectOptions(panel.getByRole("combobox", { name: "Template" }), "two_buttons");
    await user.type(panel.getByRole("textbox", { name: "left" }), "Board the plane");
    await user.type(panel.getByRole("textbox", { name: "right" }), "Stay with the cat");
    await user.type(panel.getByRole("textbox", { name: "sweating" }), "Passenger 14C");
    await user.click(panel.getByRole("button", { name: "Render" }));

    await waitFor(() =>
      expect(served.posted).toEqual([
        {
          mode: "manual",
          template_id: "two_buttons",
          caption_slots: {
            left: "Board the plane",
            right: "Stay with the cat",
            sweating: "Passenger 14C",
          },
        },
      ]),
    );
  });

  it("draws a rendering placeholder while the request is in flight", async () => {
    serveTopic({
      created: [
        makeRenderRecord({ id: "new-1", status: "generating", rationale: null }),
      ],
      hold: true,
    });
    const user = userEvent.setup();
    renderPage();

    const panel = await manualPanel();
    await user.type(panel.getByRole("textbox", { name: "rejected" }), "Filing an incident report");
    await user.type(panel.getByRole("textbox", { name: "preferred" }), "Becoming the incident");
    await user.click(panel.getByRole("button", { name: "Render" }));

    expect(await screen.findByText("rendering…")).toBeInTheDocument();
    expect(screen.getByText("drake · manual")).toBeInTheDocument();
  });

  it("will not post the same captions twice while the first render is on its way", async () => {
    // `disabled` has two halves — every slot filled, and nothing in flight
    // — and a double-click tests the second: two identical renders.
    const served = serveTopic({
      created: [makeRenderRecord({ id: "new-1", status: "generating", rationale: null })],
      hold: true,
    });
    const user = userEvent.setup();
    renderPage();

    const panel = await manualPanel();
    await user.type(panel.getByRole("textbox", { name: "rejected" }), "Filing an incident report");
    await user.type(panel.getByRole("textbox", { name: "preferred" }), "Becoming the incident");
    const render = panel.getByRole("button", { name: "Render" });
    await user.click(render);
    await waitFor(() => expect(render).toBeDisabled());
    await user.click(render);

    served.release();
    expect(await screen.findByRole("button", { name: "Cancel render" })).toBeInTheDocument();
    expect(served.posted).toHaveLength(1);
  });

  it("shows the server's reason when it will not render", async () => {
    serveTopic({ refuse: "unknown slots for 'drake': extra" });
    const user = userEvent.setup();
    renderPage();

    const panel = await manualPanel();
    await user.type(panel.getByRole("textbox", { name: "rejected" }), "a");
    await user.type(panel.getByRole("textbox", { name: "preferred" }), "b");
    await user.click(panel.getByRole("button", { name: "Render" }));

    expect(await panel.findByRole("alert")).toHaveTextContent(
      "unknown slots for 'drake': extra",
    );
  });
});
```

`makeConfigOptions()`'s default library is `drake` (`rejected`,
`preferred`) and `two_buttons` (`left`, `right`, `sweating`), which is what
these tests pick from.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- GeneratePanels`

Expected: FAIL. There is no `Write it yourself` region.

- [ ] **Step 3: Write the panel**

Create `web/src/features/topics/ManualPanel.tsx`:

```tsx
import { useId, useState } from "react";

import type { GenerateMutation } from "@/api/queries";
import type { TemplateOption } from "@/api/types";

import styles from "./ManualPanel.module.css";

/**
 * Write it yourself: straight to the renderer, no model call. Quieter than
 * the LLM panel on purpose — dashed, muted, a ghost button — because it is
 * the deliberate alternative rather than the primary action.
 *
 * One field per slot of the chosen template, named for the slot, read from
 * the manifest rather than hardcoded. Captions are held by slot name across
 * template changes, so looking at another template and coming back loses
 * nothing; only the chosen template's slots are posted, because the server
 * refuses any others.
 *
 * Render stays disabled until every slot has a caption. The server refuses
 * a blank one with a 400 anyway; refusing here saves the round trip.
 * Captions are trimmed on the way out, since leading and trailing spaces
 * are nothing anyone meant to draw.
 */
export function ManualPanel({
  templates,
  generation,
}: {
  templates: TemplateOption[];
  generation: GenerateMutation;
}) {
  const [templateId, setTemplateId] = useState(() => templates[0]?.id ?? "");
  const [captions, setCaptions] = useState<Record<string, string>>({});
  const titleId = useId();

  const slots = templates.find((template) => template.id === templateId)?.slots ?? [];
  const complete =
    slots.length > 0 && slots.every((slot) => (captions[slot] ?? "").trim() !== "");

  function render() {
    generation.mutate({
      mode: "manual",
      template_id: templateId,
      caption_slots: Object.fromEntries(
        slots.map((slot) => [slot, (captions[slot] ?? "").trim()]),
      ),
    });
  }

  return (
    <section className={styles.panel} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.title}>
        Write it yourself
      </h2>
      <p className={styles.subhead}>Straight to the renderer. No model call.</p>

      {templates.length === 0 ? (
        <p className={styles.empty}>The template library is empty.</p>
      ) : (
        <>
          <label className={styles.picker}>
            <span className={styles.srOnly}>Template</span>
            <select
              className={styles.select}
              value={templateId}
              onChange={(event) => setTemplateId(event.target.value)}
            >
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.id}
                </option>
              ))}
            </select>
            <span className={styles.change} aria-hidden="true">
              change ▾
            </span>
          </label>

          <div className={styles.fields}>
            {slots.map((slot) => (
              <label key={slot} className={styles.field}>
                <span className={styles.slotName}>{slot}</span>
                <input
                  type="text"
                  className={styles.input}
                  placeholder="type a caption…"
                  value={captions[slot] ?? ""}
                  onChange={(event) =>
                    setCaptions((held) => ({ ...held, [slot]: event.target.value }))
                  }
                />
              </label>
            ))}
          </div>
        </>
      )}

      <button
        type="button"
        className={styles.render}
        disabled={!complete || generation.isPending}
        onClick={render}
      >
        Render
      </button>

      {generation.isError && (
        <p role="alert" className={styles.error}>
          {generation.error.detail}
        </p>
      )}
    </section>
  );
}
```

Create `web/src/features/topics/ManualPanel.module.css`:

```css
/* 2e's WRITE IT YOURSELF: dashed white 16% (border-hover), 18px 20px,
   radius 12. The mockup's near-transparent white 2% fill has no token and
   reads as none, so the panel has none. */
.panel {
  display: flex;
  flex-direction: column;
  padding: 18px 20px;
  border: 1px dashed var(--border-hover);
  border-radius: var(--radius-panel);
}

.title {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-55);
}

.subhead {
  margin: 4px 0 16px;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text-40);
}

/* The template selector as one row with a `change ▾` affordance. A real
   <select>, so the keyboard and a screen reader get a real listbox; its
   own arrow is hidden and the row draws the design's. White 12% in the
   mockup; border-strong (14%) is the nearest token. */
.picker {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  padding: 9px 11px;
  border: 1px solid var(--border-strong);
  border-radius: 7px;
}

.picker:has(:focus-visible) {
  border-color: var(--accent-border);
}

.select {
  flex: 1;
  appearance: none;
  padding: 0;
  border: none;
  background: none;
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 600;
  line-height: 1;
  color: var(--text-70);
  cursor: pointer;
}

.select:focus {
  outline: none;
}

.change {
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 1;
  color: var(--text-30);
  pointer-events: none;
}

.fields {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 9px 11px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface);
}

.field:has(:focus-visible) {
  border-color: var(--accent-border);
}

.slotName {
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 600;
  line-height: 1;
  text-transform: uppercase;
  color: var(--text-35);
}

.input {
  padding: 0;
  border: none;
  background: none;
  font-family: var(--font-ui);
  font-size: 12px;
  line-height: 1.4;
  color: var(--text);
}

.input::placeholder {
  color: var(--text-30);
}

.input:focus {
  outline: none;
}

/* The ghost button, pinned to the panel's foot so the two panels' buttons
   sit on one line. White 20% in the mockup; border-hover (16%) is the
   nearest token. */
.render {
  margin-top: auto;
  width: 100%;
  padding: 13px;
  border: 1px solid var(--border-hover);
  border-radius: var(--radius-tile);
  background: none;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  color: var(--text-70);
  cursor: pointer;
  transition: color var(--transition);
}

.render:hover:not(:disabled) {
  color: var(--text);
}

.render:disabled {
  opacity: 0.5;
  cursor: default;
}

.error {
  margin-top: 10px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--contrast-light);
}

.empty {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-35);
}

.srOnly {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
```

- [ ] **Step 4: Put it in the second column, and give it its own mutation**

In `web/src/features/topics/GeneratePanels.tsx`, import `ManualPanel`, add
`manual: GenerateMutation` to the props, and render it second:

```tsx
import { ManualPanel } from "@/features/topics/ManualPanel";
```

```tsx
export function GeneratePanels({
  topic,
  templates,
  llm,
  manual,
}: {
  topic: TopicRow;
  templates: TemplateOption[];
  llm: GenerateMutation;
  manual: GenerateMutation;
}) {
  return (
    <div className={styles.panels}>
      <LlmPanel topic={topic} templates={templates} generation={llm} />
      <ManualPanel templates={templates} generation={manual} />
    </div>
  );
}
```

In `web/src/features/topics/TopicDetailPage.tsx`, replace the `llm` and
`pending` lines with:

```tsx
  // One mutation per panel, so one panel's error or pending state is never
  // the other's.
  const llm = useGenerateRenders(runId ?? "", topicId ?? "");
  const manual = useGenerateRenders(runId ?? "", topicId ?? "");
  const pending = [llm, manual].flatMap((generation) =>
    generation.isPending && generation.variables !== undefined
      ? [generation.variables]
      : [],
  );
```

and pass `manual={manual}` to `GeneratePanels`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npm --prefix web test -- GeneratePanels TopicDetailPage`

Expected: PASS, the LLM panel's tests included. The error test in Task 5
finds exactly one `alert`, because only the LLM panel's mutation failed.

- [ ] **Step 6: Run the whole frontend gate**

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/topics/ManualPanel.tsx web/src/features/topics/ManualPanel.module.css web/src/features/topics/GeneratePanels.tsx web/src/features/topics/GeneratePanels.test.tsx web/src/features/topics/TopicDetailPage.tsx
git commit -m "feat(web): write a meme's captions by hand"
```

---

### Task 7: `generate ↗` generates

A dimmed ranking row below the cut was never briefed, and `generate ↗` is
"the escape hatch to brief them by hand". Phase 5 drew it as text inside the
row's own link. It becomes a button that briefs and renders that one topic
through the LLM panel's endpoint, then opens the topic. The row stops being a
single anchor, because a button inside an anchor is invalid HTML. The title's
link stretches over the whole row instead, so a click anywhere else on it
still opens the topic.

**Files:**
- Modify: `web/src/features/runs/RankRow.tsx` + `.module.css`
- Test: `web/src/features/runs/RunDetailPage.test.tsx`

**Interfaces:**
- Consumes: `useGenerateRenders` (Task 2).
- Produces: no new exports. `RankRow`'s props are unchanged.

- [ ] **Step 1: Write the failing tests**

In `web/src/features/runs/RunDetailPage.test.tsx`, add `Route`, `Routes`
and `useLocation` to a new import from `react-router-dom`, and
`makeRenderRecord` to the factories import. Add this helper above the
`describe`:

```tsx
/** Where a navigation ended up, for the tests that leave this page. */
function Landed() {
  const { pathname } = useLocation();
  return <p>{`landed on ${pathname}`}</p>;
}
```

Change the existing
`offers generate on a below-the-cut row instead of thumbnails` test's
assertion to find the control by role:

```tsx
    expect(await screen.findByRole("button", { name: "generate ↗" })).toBeInTheDocument();
```

Then add, after it:

```tsx
  it("generates one meme for a topic below the cut, the model choosing, then opens it", async () => {
    // The handoff: "briefs and renders that single topic without re-running
    // the pipeline — same backend path as the topic-detail LLM panel".
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "t1", finalRank: 1, aboveCut: true }),
      makeRankedTopic({ topicId: "t2", finalRank: 6, aboveCut: false, renderCount: 0 }),
    ]);
    let posted: unknown = null;
    let postedFor = "";
    server.use(
      http.post("/api/runs/:runId/topics/:topicId/renders", async ({ request, params }) => {
        posted = await request.json();
        postedFor = String(params.topicId);
        return HttpResponse.json(
          [
            makeRenderRecord({
              id: "new-1",
              topicId: "t2",
              status: "generating",
              templateId: null,
              captionSlots: {},
            }),
          ],
          { status: 202 },
        );
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route path="*" element={<Landed />} />
      </Routes>,
      { route: `/runs/${RUN_ID}` },
    );

    await user.click(await screen.findByRole("button", { name: "generate ↗" }));

    // The pathname, not just "some topic page": a destination built from
    // the wrong row, or with run and topic swapped, lands somewhere else.
    expect(await screen.findByText(`landed on /topics/${RUN_ID}/t2`)).toBeInTheDocument();
    expect(postedFor).toBe("t2");
    expect(posted).toEqual({ mode: "llm", template_id: null, count: 1 });
  });

  it("says why on the row when the server will not generate", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "t2", finalRank: 6, aboveCut: false, renderCount: 0 }),
    ]);
    server.use(
      http.post("/api/runs/:runId/topics/:topicId/renders", () =>
        HttpResponse.json(
          { detail: "ANTHROPIC_API_KEY is required for the anthropic provider" },
          { status: 400 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "generate ↗" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "ANTHROPIC_API_KEY is required for the anthropic provider",
    );
  });

  it("does not brief the topic twice while the first request is on its way", async () => {
    // Each click is a model call. Refused at the end, so the row stays on
    // this page to be counted from rather than navigating away.
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "t2", finalRank: 6, aboveCut: false, renderCount: 0 }),
    ]);
    let posts = 0;
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post("/api/runs/:runId/topics/:topicId/renders", async () => {
        posts += 1;
        await held;
        return HttpResponse.json(
          { detail: "ANTHROPIC_API_KEY is required for the anthropic provider" },
          { status: 400 },
        );
      }),
    );
    const user = userEvent.setup();
    renderPage();

    const generate = await screen.findByRole("button", { name: "generate ↗" });
    await user.click(generate);
    await waitFor(() => expect(generate).toBeDisabled());
    await user.click(generate);
    release();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(posts).toBe(1);
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- RunDetailPage`

Expected: FAIL. There is no button named `generate ↗`, only text.

- [ ] **Step 3: Make it a button, and the row a stretched link**

Replace `web/src/features/runs/RankRow.tsx` with:

```tsx
import { Link, useNavigate } from "react-router-dom";

import { useGenerateRenders } from "@/api/queries";
import type { RankedTopic } from "@/api/types";
import { Chip } from "@/components/Chip";
import { formatScore } from "@/format";

import styles from "./RankRow.module.css";

/**
 * `trending · 412 posts · “absolute unit” 31 authors`.
 *
 * The phrase clause is dropped rather than emptied when the dossier found
 * nothing above `phrase_min_authors`: an empty quote reads as a phrase that
 * is literally nothing.
 */
function subline(topic: RankedTopic["topic"]): string {
  const parts = [topic.trend_status, `${topic.post_count} posts`];
  if (topic.top_phrase !== null && topic.top_phrase !== undefined) {
    parts.push(`“${topic.top_phrase}” ${topic.top_phrase_authors ?? 0} authors`);
  }
  return parts.join(" · ");
}

/**
 * `generate ↗` — briefs and renders this one topic without re-running the
 * pipeline, through the endpoint topic detail's LLM panel posts to. One
 * meme, with the model choosing the template: the row has no room to ask,
 * and letting the model choose is that panel's own default.
 *
 * On a 202 it opens the topic, where the new tile is already generating.
 * Staying here would show nothing, because the ranking counts ready
 * renders only. A refusal stays on the row, in the server's own words.
 */
function GenerateButton({
  runId,
  topicId,
  to,
}: {
  runId: string;
  topicId: string;
  to: string;
}) {
  const navigate = useNavigate();
  const generation = useGenerateRenders(runId, topicId);

  if (generation.isError) {
    return (
      <span role="alert" className={styles.generateError} title={generation.error.detail}>
        {generation.error.detail}
      </span>
    );
  }
  return (
    <button
      type="button"
      className={styles.generate}
      disabled={generation.isPending}
      onClick={() =>
        generation.mutate(
          { mode: "llm", template_id: null, count: 1 },
          { onSuccess: () => void navigate(to) },
        )
      }
    >
      {generation.isPending ? "generating…" : "generate ↗"}
    </button>
  );
}

export function RankRow({
  entry,
  highlighted,
  offerGenerate,
}: {
  entry: RankedTopic;
  highlighted: boolean;
  /**
   * Draw `generate ↗` where the meme count would be. True below the cut —
   * those topics were never briefed — and true for every row when the
   * generate stage rendered nothing at all.
   */
  offerGenerate: boolean;
}) {
  const { topic, render_count, above_cut } = entry;
  const to = `/topics/${encodeURIComponent(topic.run_id)}/${encodeURIComponent(topic.topic_id)}`;

  // Not one anchor any more: `generate ↗` is a button, and a button inside
  // an anchor is invalid HTML the browser silently reshapes. The title's
  // link stretches over the row instead (see `.label::after`), so the row
  // still opens the topic wherever it is clicked, and the button sits above
  // the stretch.
  return (
    <div
      className={[
        styles.row,
        highlighted ? styles.highlighted : "",
        above_cut ? "" : styles.belowCut,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span className={styles.rank}>{topic.final_rank}</span>

      <span className={styles.identity}>
        <Link to={to} className={styles.label}>
          {topic.label}
        </Link>
        <span className={styles.subline}>{subline(topic)}</span>
      </span>

      <span className={styles.chips}>
        {topic.event_sentiment !== null && topic.event_sentiment !== undefined && (
          <Chip tone="accent">{topic.event_sentiment}</Chip>
        )}
        {topic.conversation_register !== null &&
          topic.conversation_register !== undefined && (
            <Chip>{topic.conversation_register}</Chip>
          )}
      </span>

      <span className={styles.scores}>
        <span className={styles.components}>
          trend {formatScore(topic.trend_score)} · meme {formatScore(topic.meme_potential)}
        </span>
        <span className={styles.final}>final {formatScore(topic.final_score, 3)}</span>
      </span>

      <span className={styles.memes}>
        {offerGenerate ? (
          <GenerateButton runId={topic.run_id} topicId={topic.topic_id} to={to} />
        ) : (
          // A count, not thumbnails. `RankedTopic` carries `render_count`
          // from `Store.render_counts` and no render ids, and addressing an
          // image needs an id — only topic detail's `renders` list has
          // those. The design draws 42px tiles here; showing them would mean
          // one extra request per row to render something topic detail
          // shows one click away. So the row states the count and topic
          // detail draws the memes.
          <span className={styles.count}>
            {render_count} {render_count === 1 ? "meme" : "memes"}
          </span>
        )}
      </span>
    </div>
  );
}
```

In `web/src/features/runs/RankRow.module.css`, add `position: relative;` to
`.row`, and replace `.label` and `.generate` with the following. `.generate`
stays in the grouped mono rule near the top of the file, so it keeps its
font. Only its own rule below changes.

```css
.label {
  font-size: 14.5px;
  font-weight: 700;
  line-height: 1.25;
  color: inherit;
}

/* The whole row opens the topic, as it did when the row was one anchor:
   the title's link stretches over it. `generate ↗` sits above this, at
   `z-index: 1`. */
.label::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
}

.generate {
  position: relative;
  z-index: 1;
  padding: 0;
  border: none;
  background: none;
  color: var(--contrast-light);
  cursor: pointer;
}

.generate:hover:not(:disabled),
.generate:focus-visible {
  color: var(--text);
}

.generate:disabled {
  cursor: default;
}

/* A refusal, on the row, in the server's words — one line, the rest in the
   title. Above the stretched link, so it can be hovered for that title. */
.generateError {
  position: relative;
  z-index: 1;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--contrast-light);
}
```

The row is now `position: relative`, so the label's `::after` stretches to
the row. The `.memes` cell's `min-width: 0` comes from `.generateError`
itself. The grid column is a fixed 128px, so the ellipsis has a width to
work against.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- RunDetailPage`

Expected: PASS, the existing ranking tests included. `links each ranking
row to its topic` still finds the title's link. `says so when the generate
stage produced nothing at all` still finds two `generate ↗`, now as buttons.

- [ ] **Step 5: Run the whole frontend gate**

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/runs/RankRow.tsx web/src/features/runs/RankRow.module.css web/src/features/runs/RunDetailPage.test.tsx
git commit -m "feat(web): generate a meme for a topic below the cut"
```

---

### Task 8: Delete from the full-size view

The spec's full-size view has "a ghost **Delete** carrying the same inline
confirm as the tile". Phase 5 built the view read-only. Delete sits beside
**Download PNG**. It asks in place, and on `yes` it returns to the topic the
render came from, where the tile is already gone.

**Files:**
- Modify: `web/src/features/renders/RenderDetailPage.tsx` + `.module.css`
- Test: `web/src/features/renders/RenderDetailPage.test.tsx`

**Interfaces:**
- Consumes: `useDeleteRender` (Task 2); `InlineConfirm` (pill variant, as Abort uses it).
- Produces: no new exports.

- [ ] **Step 1: Write the failing tests**

In `web/src/features/renders/RenderDetailPage.test.tsx`, add
`import userEvent from "@testing-library/user-event";`, add `fireEvent` to
the `@testing-library/react` import if it is not there, and add `Route`,
`Routes` and `useLocation` from `react-router-dom`. Add this helper above
the `describe`:

```tsx
/** Where a navigation ended up, for the tests that leave this page. */
function Landed() {
  const { pathname } = useLocation();
  return <p>{`landed on ${pathname}`}</p>;
}
```

Then add:

```tsx
  it("asks before deleting, then returns to the topic the render came from", async () => {
    // A topic id no route here carries, so the page must navigate by the
    // record's own run and topic, in that order — a landing route that
    // matched any two segments would pass for either swapped.
    serve(makeRenderRecord({ id: RENDER_ID, runId: RUN_ID, topicId: "airport-cat" }));
    let deleted = "";
    server.use(
      http.delete("/api/renders/:renderId", ({ params }) => {
        deleted = String(params.renderId);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/runs/:runId/renders/:renderId" element={<RenderDetailPage />} />
        <Route path="*" element={<Landed />} />
      </Routes>,
      { route: `/runs/${RUN_ID}/renders/${RENDER_ID}` },
    );

    await user.click(await screen.findByRole("button", { name: "Delete" }));
    expect(screen.getByText("Delete this render?")).toBeInTheDocument();
    expect(deleted).toBe("");

    await user.click(screen.getByRole("button", { name: "yes" }));

    expect(
      await screen.findByText(`landed on /topics/${RUN_ID}/airport-cat`),
    ).toBeInTheDocument();
    expect(deleted).toBe(RENDER_ID);
  });

  it("stays, and says why, when the server will not delete", async () => {
    serve();
    server.use(
      http.delete("/api/renders/:renderId", () =>
        HttpResponse.json({ detail: "Permission denied: renders/r1.png" }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "yes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Permission denied: renders/r1.png",
    );
  });

  it("still offers Delete when the image is missing", async () => {
    // A render whose PNG is gone is the likeliest one to want deleting.
    // Download goes with the image — phase 5's own test already says so —
    // and Delete, which now shares its footer, must not go with it.
    serve();
    renderPage();

    fireEvent.error(await screen.findByRole("img"));

    expect(
      await screen.findByText(`Render ${RENDER_ID} has no image on disk`),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });
```

`RENDER_ID` and `RUN_ID` are the file's existing constants. The delete
test's record carries `airport-cat` as its topic, which is not the
factory's default. The topic detail `serve()` answers for the breadcrumb
is matched by any topic id, so that fixture is unaffected.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- RenderDetailPage`

Expected: FAIL. There is no `Delete` button.

- [ ] **Step 3: Add Delete**

In `web/src/features/renders/RenderDetailPage.tsx`, import `useNavigate`,
`useDeleteRender` and `InlineConfirm`:

```tsx
import { useNavigate, useParams } from "react-router-dom";
```

```tsx
import { useDeleteRender, useRender, useTopicDetail } from "@/api/queries";
```

```tsx
import { InlineConfirm } from "@/components/InlineConfirm";
```

At the top of the component, after the existing hooks:

```tsx
  const navigate = useNavigate();
  const remove = useDeleteRender();
```

Replace the footer block, `{!failed && (<div className={styles.footer}>...</div>)}`,
with:

```tsx
                <div className={styles.footer}>
                  {!failed && (
                    <a
                      className={styles.download}
                      href={imageUrl(record.id, "full")}
                      download={`${templateLabel}-${record.id}.png`}
                    >
                      Download PNG
                    </a>
                  )}
                  {/* Offered whether or not the image loaded: a render whose
                      PNG is gone is the likeliest to want deleting. On yes,
                      back to the topic it came from, where its tile has
                      already left the cache. */}
                  <InlineConfirm
                    label="Delete"
                    question="Delete this render?"
                    disabled={remove.isPending}
                    onConfirm={() =>
                      remove.mutate(record, {
                        onSuccess: () =>
                          void navigate(
                            `/topics/${encodeURIComponent(record.run_id)}` +
                              `/${encodeURIComponent(record.topic_id)}`,
                          ),
                      })
                    }
                  />
                </div>
                {remove.isError && (
                  <p role="alert" className={styles.deleteError}>
                    {remove.error.detail}
                  </p>
                )}
```

In `web/src/features/renders/RenderDetailPage.module.css`, replace `.footer`
with the following and add `.deleteError`:

```css
.footer {
  display: flex;
  align-items: center;
  gap: var(--gap-tight);
  margin-top: 16px;
}

.deleteError {
  margin-top: 10px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--contrast-light);
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- RenderDetailPage`

Expected: PASS, every existing test included.

- [ ] **Step 5: Run the whole frontend gate**

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/renders/RenderDetailPage.tsx web/src/features/renders/RenderDetailPage.module.css web/src/features/renders/RenderDetailPage.test.tsx
git commit -m "feat(web): delete a render from its full-size view"
```

---

### Task 9: run it against a real run, then write down what changed

Phase 5's walk and both of phase 6's found defects that MSW fixtures
structurally could not catch: an image that never resolves, a connection
that races itself, a log numbering that collides on resume. This phase adds
real surface of the same kind: a real executor thread, real model calls,
real Pillow failures, and a real poll racing a real POST. Run it, and fix
what the walk finds, each with a test that would have caught it.

**Files:**
- Modify: whatever the walk finds
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-09-02-web-ui-design.md`

**Interfaces:**
- Consumes: everything Tasks 1–8 built.
- Produces: no new names. A green gate, a README that describes the app as
  it now is, and the spec's phase 7 entry.

- [ ] **Step 1: Start both processes on a fresh database**

Task 1 moved the schema to version 5, so an existing `data/zeitgeist.db`
refuses to open. That refusal is the migration strategy working.

```bash
rm -f data/zeitgeist.db
```

```bash
uv run zeitgeist
```

```bash
npm --prefix web run dev
```

- [ ] **Step 2: Point it at the local model**

In `.env`, or the shell that runs `zeitgeist`:

```bash
LLM_PROVIDER=ollama
LLM_MODEL=qwen3.5:latest
OLLAMA_HOST=http://127.0.0.1:11434
DISTIL_CONCURRENCY=2
```

On-demand generation reads the provider from settings, not from New run,
because it has no form of its own. Then start a run from `/runs/new` with
**Memes to generate** at 3, and let it finish.

- [ ] **Step 3: Walk the LLM panel**

Open a kept topic from the finished run.

- [ ] **Let the LLM choose** is selected, and its line names the topic's
      sentiment and register.
- [ ] Click **Generate 1 meme**. A placeholder appears at once, then
      becomes a tile reading `choosing… · auto`, then an image whose footer
      names the template the model chose.
- [ ] Reload the page mid-generation. The generating tile is still there —
      the row exists before the model has answered.
- [ ] Pick a template tile and **Generate 3 memes**. Three tiles appear and
      resolve one by one, each naming that template.
- [ ] The grid's header counts `generating` down and `from` up as they
      finish. On run detail, the topic's meme count has moved without a
      reload.

- [ ] **Step 4: Walk the manual panel**

- [ ] Change the template. The fields become that template's slots.
- [ ] **Render** is disabled until every field has text.
- [ ] Render something short. The tile says `rendering…`, not
      `writing brief…`, then shows the image. Its full-size view says
      `written by hand`.
- [ ] Render a caption far too long for its box. The tile stays, marked
      `failed`, with the renderer's reason in its footer.

- [ ] **Step 5: Walk deletion and cancel**

- [ ] `✕` on a ready tile: the footer becomes `Delete this render?`.
      Escape reverts it. `yes` removes the tile at once.
- [ ] Run detail and the Runs list no longer count or show it.
- [ ] Start a generation and `✕` its tile while it is still generating. It
      goes at once and does not come back, including after a reload once
      the job would have finished.
- [ ] `✕` on a failed tile: gone, no question asked.
- [ ] Open a ready render's full-size view, **Delete**, `yes`. You land on
      the topic, and its tile is gone.

- [ ] **Step 6: Walk the below-the-cut link**

- [ ] On run detail, click `generate ↗` on a dimmed row. You land on that
      topic with one tile generating.
- [ ] Clicking anywhere else on any row still opens its topic.

- [ ] **Step 7: Walk a refusal**

Stop `zeitgeist`, set `LLM_PROVIDER=anthropic` with no `ANTHROPIC_API_KEY`,
and start it again.

- [ ] **Generate** shows the server's sentence about the missing key, and
      no placeholder is left behind.
- [ ] `generate ↗` shows the same sentence on its row.

Put the provider back afterwards.

- [ ] **Step 8: Generate while a run is in flight**

- [ ] Start a run, and while it is in flight generate a meme on a topic of
      an earlier run. Both finish. On Ollama they contend for one GPU and
      are slower, which the spec documents rather than solves.

- [ ] **Step 9: Fix what the walk found**

For each defect: write the test that would have caught it, watch it fail,
fix it, watch it pass. A fix with no test is a defect that comes back.

- [ ] **Step 10: Update the README**

In `README.md`, replace "Generating a meme from the browser is phase 7."
with a short section, `### Making memes from the browser`, that covers:

- Topic detail's two panels, and the difference between them. **Ask the
  LLM** writes captions with a model call per meme, and lets the model pick
  the template unless you pick one. **Write it yourself** takes a caption
  per slot and makes no model call.
- A request makes one or three memes, and never more than four, because
  every one is a model call.
- The tile states: generating (whose `✕` cancels), failed (kept, with the
  reason; `✕` dismisses), and ready (`✕` asks first).
- `generate ↗` below the cut on run detail, which briefs that one topic
  and opens it.
- **Delete** on the full-size view.
- On-demand generation uses the provider and model from settings and
  `.env`, not a per-run choice. It runs on its own executor, so it works
  while a run is in flight.

- [ ] **Step 11: Write the phase 7 entry in the spec**

In `docs/superpowers/specs/2026-09-02-web-ui-design.md`:

Under "Decisions taken against the handoff", add one paragraph each for
this plan's "Decisions" 1, 2, 4, 5, 6 and 7. Keep each to the decision and
its reason, in the spec's own voice, as the existing paragraphs there are:

- **The model can choose, so a render may not have a template yet.**
- **HOW MANY is 1 / 3.**
- **The generating bar sweeps.**
- **Only a ready tile asks before its `✕` acts.**
- **`writing brief…` is for model renders only.**
- **The Track tile is not drawn.**

In the "API surface" table, change the phase 4 `POST .../renders` row's
body to `{mode: "llm", template_id?, count}`, and add a sentence under the
table saying that an omitted or null `template_id` lets the model choose.
In "Models", change `RenderRecord`'s `template_id: str` to
`template_id: str | None`, with a comment that it is None until the model
has chosen.

Extend the phase 7 entry under "Phases" the way phases 5 and 6 record their
walks: what the real-run walk found, and that each finding was fixed with a
test that fails without the fix — or, if it found nothing, say so.

- [ ] **Step 12: Run the whole gate one last time**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: all seven PASS.

- [ ] **Step 13: Commit**

```bash
git add -A
git commit -m "docs: making memes from the browser, and what a real run found"
```

---

## Tests

What this phase's suite covers, and why each is worth its line.

**Backend**

| Area | Assertion |
| --- | --- |
| Letting the model choose | A request that names no template offers the model the whole library. The finished row names the template the model chose, not one the code picked. |
| Seeded rows | A request that names no template seeds rows with none, read back through the nullable column. |
| The endpoint | `{mode: "llm"}` with no template is 202, with `template_id: null` on every row. |
| Unchanged | Everything phase 4 asserted, including that a named template still narrows the library to one. |

**Frontend**

| Area | Assertion |
| --- | --- |
| `apiDelete` | Resolves on a bodiless 204. Raises `ApiError` with the server's detail. |
| `useTopicDetail` | Polls while a render is generating, and goes quiet for longer than a poll interval once none is. Does not poll a settled topic, failed renders included. Refreshes the ranking when a render finishes. |
| `useGenerateRenders` | Posts to the topic's renders with the body given. Writes the reply's rows into the cache itself, with every later fetch held open. Is not undone by a detail fetch sent before the rows existed. |
| `useDeleteRender` | Removes the row from the cache before any refetch returns. Counts a 404 as done. Leaves the row in place on a 500. Refreshes the ranking and the topics index. |
| `InlineConfirm` tile | Found by its `ariaLabel` throughout, never by its glyph. Gives the whole footer to the question. Confirms on yes. Restores the resting line on no. Reverts on Escape and returns focus to the `✕`. |
| `MemeTile` | The grid size asks for the full PNG. |
| `RenderGrid` | Ready links to the full view and names its own provenance. Generating says `writing brief…` or `rendering…` by provenance, and `choosing…` with no template. Failed keeps the tile and the reason, and says `no template` when none was chosen. The header counts ready, generating (rows plus placeholders) and failed, from counts that all differ. One placeholder per requested meme, none cancellable. The nothing-rendered-yet row. Ready asks before deleting; generating and failed do not. A deletion in flight dims the tile. A refused deletion keeps the tile and shows the reason, in all three states. |
| Topic detail | A deleted render leaves the page and the others stay. |
| Ask the LLM | Defaults to letting the model choose, with the topic's mood, or "this topic" without one. Offers every template in the library with its slot count, singular at one. Three by default, with the count on the button. Posts `template_id: null` when choosing, the picked id when not, and null again once the choice is handed back. The grid survives the library failing to load. Placeholders before the reply, rows after, never both. No second post while one is pending. The server's sentence on a refusal, with nothing left drawn. |
| Write it yourself | One field per slot of the chosen template. Fields swap with the template, and captions survive a look at another. Render is disabled until every slot has non-blank text, and while a render is pending. Posts the chosen template's captions trimmed, and only its slots. A rendering placeholder while the request is in flight. The server's sentence on a refusal. |
| `generate ↗` | Posts one meme with the model choosing, for that topic, then opens exactly that topic. No second post while one is pending. The server's sentence on the row when refused. |
| Full-size view | Asks, deletes, and returns to exactly the render's own topic. Stays and says why on a refusal. Offers Delete without the image. A render with no template says so in every place it would be named. |

**Not tested, deliberately**

- The design itself. High-fidelity CSS is not meaningfully unit-testable,
  and fidelity is a human review against the mockups, which Task 9 is.
- The sweep animation and its reduced-motion fallback: neither is
  observable in jsdom.
- The stretched link's hit area on a ranking row, which is layout. Task 9
  walks it.
- The one-frame overlap between a request's placeholders going and its
  rows arriving. TanStack awaits `onSuccess` before a mutation stops being
  pending, so the rows are in the cache first. The Ask the LLM test asserts
  three tiles rather than six after the reply, which is the observable half.

---

## Self-review

Run against the spec after writing, before handing over.

**1. Spec coverage.** Phase 7's entry names:
- the two generation panels on topic detail (Tasks 5 and 6);
- the rendered grid with its three tile states (Task 4);
- the inline delete confirm (Tasks 3 and 4, and Task 8 for the full-size
  view, whose Delete the spec specifies under "Full-size meme view");
- the below-the-cut `generate ↗` link (Task 7);
- the nothing-rendered-yet state (Task 4).

"Ends with the design built" is Task 9's walk. The spec's testing section
names "optimistic render tiles, the inline delete confirm … the
below-the-cut generate link" for this phase, and each has a test above. The
handoff's `Track — not built yet` tile has no task. It is recorded as a
decision ("Decisions", 7) and in the spec by Task 9.

**2. Placeholder scan.** No step says "add error handling" or "similar to
Task N" without the code. Task 9's Steps 9–11 are the one place content
depends on what the walk finds, which is the nature of a walk. Their
structure, and every heading the spec entry needs, are given.

**3. Type consistency.**
- `GenerationRequest` is defined in Task 2's `types.ts`, and consumed by
  `useGenerateRenders` (Task 2), `RenderGrid`'s `pending` (Task 4), and
  `TopicDetailPage`'s `pending` (Tasks 5 and 6).
- `GenerateMutation` is `ReturnType<typeof useGenerateRenders>`, and is
  the type of `LlmPanel.generation`, `ManualPanel.generation`, and
  `GeneratePanels`' `llm` and `manual`.
- `RenderRecord.template_id` is `str | None` in Python and
  `string | null` in TypeScript after regeneration. Every reader handles
  null with a named fallback: `choosing…` while generating, `no template`
  on a failed or ready tile, and `no template chosen` on the full-size
  view.
- `useDeleteRender` takes a whole `RenderRecord`, because it keys the
  cache by the record's own `run_id` and `topic_id`. `RenderTile` and
  `RenderDetailPage` both pass the record they hold.
- `InlineConfirm`'s new props are `variant`, `ariaLabel` and `resting` in
  Task 3, and `RenderTile` passes exactly those in Task 4.

---

## Test audit

`CLAUDE.md`'s second gate, the `reviewing-plan-tests` skill, **has been
run** over Tasks 1–9 by a fresh reviewer against `writing-good-tests.md`.
It audited 55 tests and reported thirteen findings, all applied. One was
adjusted, as noted. They are recorded here so the gate's effect stays
legible, and so a later reader can tell an amended test from an original
one.

**Rewritten (3)**

1. `says no template was chosen for a render whose brief failed before
   choosing` (Task 1). It asserted only the chip, while Step 12 changes four
   use sites. A breadcrumb given `?? ""`, or an alt and a file name that
   print `null` through a template literal, all passed. It now checks the
   chip, the breadcrumb, the alt text, and that the download name carries
   no `null`.
2. `leaves the template to the model by default, and says what it will
   choose for` (Task 5). The fixture's `funny / riffing` is also the
   mockup's copy word for word, so a panel that printed the mockup's
   sentence passed. It now uses `cute / delight`. The reviewer proposed
   `deadpan`, which is not a register the pipeline produces, so it was
   swapped for one that is.
3. `asks before deleting, then returns to the topic the render came from`
   (Task 8). It landed on a route that matched any two segments, so a
   destination with run and topic swapped passed. It now carries a topic id
   of its own and asserts the pathname through a `Landed` helper. The same
   weakness was fixed in Task 7's navigation test while applying it, which
   the reviewer had not flagged.

**Added (10)**

4. `is not undone by a detail fetch that was sent before the rows existed`
   (Task 2). This is the only test that fails without `useGenerateRenders`'
   `cancelQueries`, whose absence drops the new tiles in a real browser.
5. `leaves the row where it was when the server refuses` (Task 2). This
   guards against moving the cache removal into an optimistic `onMutate`
   with no rollback. The handoff's wording invites that move, and the grid's
   own 500 test could not see it without a cached detail.
6. `refreshes the topics index, whose meme counts just lost one` (Task 2).
   Only the ranking half of `invalidateRenderViews` was watched.
7. `reverts on Escape and hands focus back to its ✕` (Task 3). This is what
   the tile variant exists to inherit, and no tile test pressed Escape.
8. `names no template on a failed render whose brief failed before choosing
   one` (Task 4). Decision 1's second template-less state had no test.
9. `says why a $state tile the server would not delete is still there`
   (Task 4), for generating and failed. Each branch draws its own delete
   error, and only the ready branch was tested.
10. `will not post a second request while the first is on its way` (Task 5).
11. `keeps what was typed for a template while another is looked at`
    (Task 6). A comment promised this behaviour and nothing asserted it.
12. `will not post the same captions twice while the first render is on
    its way` (Task 6).
13. `does not brief the topic twice while the first request is on its way`
    (Task 7). Findings 10, 12 and 13 are the three `isPending` guards, each
    of which stands between a double-click and twice the model calls.

**The change-detector pass.** The skill records that this gate reliably
misses one category, tests only an intentional decision could break, and
asks the planner to walk the tests again for it. That walk is done.

Three tests assert copy the plan itself chose:
- the grid header's `· N generating · N failed` join;
- `rendering…` for a manual tile;
- the default count of 3.

Each rides with a real assertion in the same test: the counts behind the
header, the branch on provenance, and the button label tracking the count
with its pluralisation. The copy is also the design's or the spec's, which
the Global Constraints declare final. So each can fail for a bug, not only
for a change of mind, and they stay. `offers no cancel on a placeholder`
looks like an absence check, but a `✕` on a row that does not exist could
only issue a DELETE for nothing, so it guards a real defect.

### A second pass, against the rubric directly

A second review read every test against `writing-good-tests.md`
directly. It found eight more issues, all applied. Rubric sections are in
brackets.

**Rewritten (5)**

14. **`polls while a render is generating, and stops once none is`**
    (Task 2). [Mutation check; no change detectors] It waited a fixed
    150ms for the refetch that a finishing render triggers, and only then
    started counting. On a loaded CI box that refetch lands late and the
    test fails against correct code. The refetch count is also the
    implementation's own business. The test now asserts what polling
    means: after the render is ready, more than one poll interval passes
    with no request at all. It carries an explicit 10s timeout, because it
    runs on real timers past vitest's 5s default.
15. **`posts to the topic's renders and puts the rows it returns straight
    into the cache`** (Task 2). [No change detectors; make doubles
    specific] `expect(detailCalls).toBe(1)` could only fail on a decision:
    an extra refetch is harmless against a real server. Its fixture's GET
    also never returned the posted rows, so a write-then-invalidate
    implementation made the test pass or fail by response order. Every
    later detail request is now held open, so only the cache write can put
    the row there, and the call-count assertion is gone.
16. **`is not undone by a detail fetch that was sent before the rows
    existed`** (Task 2). [The test can pass against the bug it names] It
    slept 100ms after releasing the stale response. If that response had
    not been processed by then, the test passed with the `cancelQueries`
    line deleted. It now waits for the stale answer to be sent and for the
    query to go idle. Without the cancel, the query is fetching until the
    overwrite lands.
17. **`counts what is ready, generating and failed above the grid`**
    (Task 4). [Derive expectations from fixtures that can tell
    implementations apart] Generating and failed were both 1, so counts
    computed from each other's status passed. No pending request was in
    the mix, so a placeholder total that replaced the generating rows
    rather than adding to them also passed. The counts are now 3, 2 (one
    row plus one placeholder) and 1.
18. **`draws a ready render as its image, linked to the full-size view`**
    (Task 4). [Same] The fixture's provenance was the factory default,
    `auto`, so a ready tile that printed "auto" without reading the row
    passed. It is now a hand-written render.

**Deleted (1)**

19. **`names its glyph trigger for a screen reader`** (Task 3). [Tests ship
    with the behaviour and only those] Every other tile test finds the
    trigger by that same accessible name, so dropping `ariaLabel` already
    fails all four. This test added no failure mode of its own. Its reason
    moved to a comment on the helper.

**Added (2)**

20. **`posts no template again once the choice is handed back to the
    model`** (Task 5). [Mutation check: missing state change] A "Let the
    LLM choose" row whose `onChange` did not clear a picked tile would keep
    posting that tile, and nothing tested the way back.
21. **`still draws what was rendered when the template library cannot be
    read`** (Task 5). [Mutation check: wrong branch] The grid was a sibling
    of the options boundary only by the plan's say-so. Nested inside it,
    the grid would vanish with the library. `serveTopic` gains an `initial`
    option for this test.

**Trimmed (1)**

- **`still offers Delete when the image is missing`** (Task 8). Its
  Download-is-withdrawn assertion repeated phase 5's own test word for
  word. It now waits for the missing-image state and asserts Delete, which
  is what this task adds.

**Judged and left alone.** Several generating-row fixtures carry the
factory's filled captions and rationale, where the server would send `{}`
and `""`. That is unrealistic, but no test would change outcome with it.
Nothing on a generating tile reads either field, and a test asserting that
nothing does would assert an absence. Tests that pin copy the design fixes,
such as `rendering…` and the grid header's join, each ride with a branch
or a count, as the first pass recorded.

---

## Execution Handoff

Nine tasks. Task 1 is Python and lands first: its regenerated contract is
what every later task types against. Task 2 is the hook layer that Tasks 4–8
consume. Task 3 is independent of Task 2, and Task 4 needs both. Tasks 5 and
6 build on Task 4's grid. Tasks 7 and 8 need only Task 2, and Task 8 needs
Task 3's unchanged pill variant. Task 9 is the walk.

One branch off `main` and one pull request, per the spec's "Landing the
work". Every commit above leaves all seven gate commands green, so the
branch has a checkpoint at each one.
