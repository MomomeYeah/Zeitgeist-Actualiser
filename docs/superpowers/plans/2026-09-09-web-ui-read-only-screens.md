# Design System and Read-Only Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up `web/` — the Vite scaffold, the token table, the generated client, the primitives and the router — and build every screen that only reads: Topics, Runs, Run detail (completed and failed), Topic detail, and the full-size meme view.

**Architecture:** A React SPA in `web/`, served by Vite in development and proxying `/api` to uvicorn, so there is no CORS and one contract. TypeScript types are generated from the backend's own OpenAPI schema and checked in; two gates keep the three layers honest — a pytest test asserts `web/openapi.json` still matches the live app, and an npm script asserts `src/api/schema.ts` still matches `web/openapi.json`. Styling is CSS custom properties in one `tokens.css` transcribed verbatim from the handoff, plus CSS Modules beside each component. Data comes through TanStack Query over a thin typed fetch client; nothing on these screens mutates.

**Tech Stack:** React 19, TypeScript 5, Vite 7, React Router 7, TanStack Query 5, CSS Modules, `@fontsource` (Outfit, IBM Plex Mono), Vitest, Testing Library, MSW 2, ESLint 9, `openapi-typescript`.

## Global Constraints

Copied from `docs/superpowers/specs/2026-09-02-web-ui-design.md` and `design_handoff_zeitgeist_ui/README.md`. Every task's requirements implicitly include this section.

- **The Definition of Done grows from four commands to seven in this phase, and Task 1 is what grows it.** After Task 1, every task must end with all seven passing:

  ```bash
  uv run ruff check .
  uv run ruff format --check .
  uv run ty check
  uv run pytest
  npm --prefix web run lint
  npm --prefix web run typecheck
  npm --prefix web test
  ```

  **There is no red window — the tree is green at the start of every task and must be green at the end.**
- **The backend contract is frozen.** Phase 4 closed it. No endpoint, response model, query parameter or status code changes in this phase. Where a screen wants a number the API does not return, the screen changes — see "Decisions this phase is required to make". If you find yourself editing `zeitgeist/api/`, stop: that is a spec deviation, not a task step.
- **The design is high-fidelity. Colours, typography, spacing and copy are final.** Transcribe them; do not improve them.
- **No new tokens.** Anything needing a colour the handoff's table does not have is a sign the screen is fighting the design rather than extending it. Every colour in every `.module.css` is a `var(--…)` from `tokens.css`. Where the handoff writes a value inline rather than as a table row — the failure borders at `rgba(61,99,230,.35)`, the chip fills at white 8% and 15%, the mood bar's tail colours — Task 3 gives it a name in `tokens.css` and the stylesheets use the name; that is not a new colour, it is the same colour written once. The single literal outside `tokens.css` is the trailing stop of `StageBar`'s hard-edged gradient, which the handoff specifies as part of the gradient itself.
- **No modals.** The design confirms destructive actions by swapping a footer in place. Nothing in this phase is destructive, so nothing in this phase opens a dialog.
- **Mono versus Outfit is semantic, not decorative.** Anything the machine produced or names — ids, filenames, scores, stage names, counts, template ids, log output, section labels, chips — is IBM Plex Mono. Anything written for a human to read is Outfit. Never smaller than 9px, and 9–10px is mono-only: Outfit is never used below 11px.
- **Fonts are local.** `@fontsource`, never a Google Fonts `<link>`. A local tool should not need the network to render correctly.
- **This phase is read-only.** No `POST`, `PUT` or `DELETE` is issued from any screen. The affordances that would mutate — **New run**, **Resume from**, **Re-run config**, **Generate**, **Delete** — are phase 6 and 7 work and are handled as named in "Decisions this phase is required to make".
- **No snapshot tests of the design.** High-fidelity CSS is not meaningfully unit-testable and fidelity is a human review against the mockups. Tests target behaviour: what renders for which data, what links where, what is absent when it should be absent.
- **MSW mocks at the network layer, with handlers typed from the generated OpenAPI types**, so a backend contract change breaks frontend tests rather than surfacing in the browser. No test stubs `fetch` directly and no test stubs a query hook.
- **Fixtures are built through typed factories**, never hand-written object literals cast with `as`. `web/src/test/factories.ts` is the frontend analogue of `tests/run_factory.py`, and the same rule applies: a factory returns a fully typed value that the contract's own types accept.
- **`tests/conftest.py`'s autouse fixture stays authoritative for Python tests** — hermetic, no network, `Settings` environment stripped.
- ruff: line length 88, rules `E, F, I, UP, B, SIM`. `docs/` is excluded. Python 3.14: PEP 695 generics, never `typing.TypeVar`.
- ty: fix type errors at the root cause. No blanket `# type: ignore`.
- TypeScript: `strict: true`, and **no `any`, no non-null `!`, no `as` casts of API data.** The generated types are the contract; a cast is a place the contract was ignored. The single exemption is `src/api/client.ts`, scoped in the ESLint config: `Response.json()` is `Promise<any>`, so untyped JSON becomes a typed contract in exactly one place and every other module gets it already typed.
- **`web/src/api/schema.ts` and `web/openapi.json` are generated artifacts and are checked in.** Never hand-edit either. Both are regenerated by the commands Task 2 documents.

## Decisions this phase is required to make

The spec and the handoff leave seven questions open at the phase 5 boundary. All seven answers are load-bearing below.

### 1. The phase-6 and phase-7 affordances are omitted, not stubbed

Phase 5's stated end is "any run the harness has produced browsable end to end". A run is produced by `scripts/run_pipeline.py` or by `POST /api/runs`, not by a screen, so no screen in this phase needs a button that starts one.

So: the **New run** pill in the Topics and Runs headers is **absent** in this phase, and `EmptyState` takes its action as an *optional* prop that no phase-5 caller passes. Phase 6 adds `/runs/new`, then adds the pill and fills that slot. This is deliberately not a disabled button or a link to a route that 404s — a control that visibly does nothing is worse than a control that is not there yet, and an optional prop is a real seam rather than a placeholder.

The same rule covers **Resume from &lt;stage&gt;** and **Re-run config** on run detail (phase 6), and the generation panels, the generating and confirming tile states, and the meme view's **Delete** (phase 7). Each is absent. `MemeTile` renders one state in this phase — normal — and phase 7 adds the other two.

### 2. `generate ↗` links to topic detail in this phase

The below-the-cut ranking rows and the every-brief-failed rows draw `generate ↗` where their thumbnails would be. The spec assigns "the below-the-cut `generate ↗` link" to phase 7, which is the *action*: brief and render that one topic without re-running the pipeline.

Drawing the row without it would leave a visibly incomplete ranking on the screen this phase is meant to finish, and drawing it inert would be a control that does nothing. So in this phase it is a `<Link>` to that topic's detail page — which is where phase 7 puts the generation panels, making "go and generate one" exactly what the link means. Phase 7 replaces the `to` with an `onClick` that posts.

This is the one place in this phase where an affordance's *destination* changes in a later phase. It is called out here so phase 7 changes it deliberately rather than finding it and wondering.

### 3. Presentation ordering is the client's job

The contract is frozen and `GET /api/topics` returns its topics in `topics_for_runs` order — newest run first, deduplicated on `label_slug` — which is recency, not rank. Three things on the Topics screen need rank order: the hero ("TOP RIGHT NOW"), the highlighted first trending card, and the trending grid itself.

The client sorts. `final_score` descending, with `topic_id` ascending as the tiebreak so the order is total and the tests are not flaky. This is presentation, not a second ranking: `final_score` is already `rank_score`'s output, computed once in `projection.flatten`, and sorting by it cannot disagree with the backend the way re-deriving the blend would.

### 4. The mood line reports sentiment only

The handoff's mood bar carries one line beneath it covering "register skew and average meme potential versus the previous run". `TopicIndex` returns `sentiment_totals` and `previous_sentiment_totals` and nothing else aggregate: there are no register totals, and no previous-window topic rows to average `meme_potential` over.

Both would be new response fields, and the contract is frozen. So the line reports what the contract actually carries: the dominant sentiment, its share of the window, and its change against the previous run — `funny leads at 38% of the window · up 6 points on the previous run`. When `previous_sentiment_totals` is empty the delta clause is dropped rather than rendered as zero, because "no previous run" and "no change" are different facts.

### 5. The Runs metadata line counts the page, not the archive

The handoff's line reads `27 total · 24 ok · 3 failed · bluesky only`. `GET /api/runs` is cursor-paginated and returns no archive totals; a total would be a new field on `RunPage`.

The line reports the page it is looking at and says so: `25 shown · 22 ok · 2 failed · 1 aborted · bluesky`. Each status present is named with its own count rather than forced into the handoff's `ok · failed` pair — `RunStatus` has five members, and both ways of collapsing them are wrong here: grouping everything-not-ok under "failed" calls an aborted run a failure, and counting only the two named statuses prints a total the parts do not add up to. The sources clause is the distinct `config.sources` across the page, joined by `·`, so a page that mixes sources says so rather than claiming one.

### 6. A failed run's "what survived" is derived from the failed stage

The Runs list draws, for a failed row, what the run managed to write — the handoff's "ranked.json intact". `RunSummary` carries the run record and nothing about stages, and the spec has already dropped the file extensions (`ranked checkpoint intact`).

It is derivable from `run.error.stage` alone, because the stages run in order and a stage fails only after its predecessors wrote: `ingest` → `nothing written`; `analyse` → `evidence checkpoint intact`; `evaluate` → `topics checkpoint intact`; `generate` → `ranked checkpoint intact`. That is the same fact `resume_stage` encodes on run detail, reached without a second request, and the `ingest` case is exactly the source outage the spec describes — nothing written, so nothing to resume, so column four shows `re-run ↗` rather than a resume affordance.

### 7. Partial failure is shown where the contract carries it, and the Runs pill drops the `3 of 5` form

The handoff's partial-failure pill reads `OK · 3 of 5`, the `3 of 5` in `contrast-light`. That needs the ready count and the attempted count for a run.

`RunSummary` carries neither. `render_ids` comes from `Store.renders_for_run`, which filters on nothing, so it counts `ready`, `generating` and `failed` rows alike — and the field name alone does not say so. `Store.render_counts`, the ready-only accessor, is reached through `GET /api/runs/{id}/topics`, one request per run. Computing the pill on a 25-row list would mean 25 extra requests, and adding the count to `RunPage` would reopen a contract phase 4 closed.

So the pill on the Runs list reads `OK · <n>` where `n` is `render_ids.length` — renders that exist — and never the `3 of 5` form. The partial fact is drawn in the two places the contract does carry it, and drawn fully:

- **Run detail's generate stage card** renders `StageRecord.summary`, which the pipeline already writes as `"3 of 5 rendered"` (`pipeline.py:250`). That is the pipeline's own words for exactly this fact, and it needs no second request and no client-side arithmetic. The spec's `· 2 failed` suffix is dropped: "of 5" already carries it, and the failed count is not separately in the contract.
- **A thumbnail whose PNG is not on disk** — which is what a `failed` render is — renders as the design's dashed `--contrast-border` tile with `failed` in mono 9.5 `--contrast-light`, driven by the `<img>`'s own `onError`. This is not a workaround: the spec already requires that "a PNG deleted out from under it renders as a failed tile, not a crash", so the tile needs that state regardless, and having it means the partial signal reaches the Runs list visually without a contract change.

Topic detail carries `RenderRecord.status` and `error` per render and needs none of this.

## What phases 1–4 left you

**Do not reimplement any of this, and do not change any of it.**

**Endpoints** — all fifteen exist and are tested. The nine this phase reads:

| Method | Path | Response model |
| --- | --- | --- |
| GET | `/api/runs?limit&cursor` | `RunPage` |
| GET | `/api/runs/{run_id}` | `RunDetail` |
| GET | `/api/runs/{run_id}/topics` | `RankedTopic[]` |
| GET | `/api/runs/{run_id}/topics/{topic_id}` | `TopicDetail` |
| GET | `/api/runs/{run_id}/log?verbose` | `LogLine[]` |
| GET | `/api/topics?window&status` | `TopicIndex` |
| GET | `/api/renders/{render_id}` | `RenderRecord` |
| GET | `/api/renders/{render_id}/image?size=full\|thumb` | `image/png` |
| GET | `/api/settings` | `SettingField[]` |

The six this phase does not touch: `POST /api/runs`, `POST /api/runs/{id}/resume`, `/stop`, `/abort`, `GET /api/runs/{id}/events`, `GET /api/runs/active`, `GET /api/config/options`, `PUT /api/settings`, `POST /api/runs/{id}/topics/{id}/renders`, `DELETE /api/renders/{id}`.

**Response models** (`zeitgeist/api/schemas.py`) — `SettingField`, `SettingsUpdate`, `StartRunBody`, `RunActionAck`, `ResumeBody`, `RunSummary(run, topic_labels, render_ids)`, `RunPage(runs, next_cursor)`, `RunDetail(run, stages, resume_stage)`, `RankedTopic(topic, render_count, above_cut)`, `ReplyOut(text, like_count, created_at)`, `TopicRecurrence(run_count, first_seen_run_id)`, `TopicDetail(topic, dossier, score_components, replies, renders, recurrence)`, `IndexedTopic(topic, run_count, render_count)`, `TopicIndex(topics, status_totals, sentiment_totals, previous_sentiment_totals)`, `PlatformOption`, `TemplateOption`, `ConfigOptions`.

**Records** (`zeitgeist/records.py`) — `Stage` (`ingest|analyse|evaluate|generate`), `ORDER`, `RunStatus` (`running|ok|failed|aborted|interrupted`), `StageStatus` (`queued|running|ok|failed|skipped`), `RunConfig(sources, trend_limit, posts_per_trend, top_count, meme_potential_weight, phrase_min_authors, distil_char_budget, distil_concurrency, llm_provider, llm_model, template_ids)`, `RunError(kind, message, stage)`, `RunRecordRow(run_id, status, started_at, finished_at, config, error, item_count, trends_found, topics_kept, phrases_found)`, `StageRecord(stage, status, started_at, finished_at, payload_bytes, summary)`, `AutoOrigin(provenance="auto", rationale)`, `ManualOrigin(provenance="manual")`, `RenderRecord(id, run_id, topic_id, template_id, caption_slots, origin, status, error, created_at)`, `LogLine(seq, logged_at, level, logger, message)`.

**Projection** (`zeitgeist/projection.py`) — `TopicRow(run_id, topic_id, label, label_slug, trend_status, event_sentiment, conversation_register, meme_potential, trend_score, final_score, final_rank, post_count, top_phrase, top_phrase_authors)`.

**Domain** (`zeitgeist/models.py`) — `TrendStatus = Literal["trending","saturating","cooling","stale"]`; `Sentiment` (cute, heartwarming, funny, awe, schadenfreude, outrage, sad, scary, gross, cringe, mundane); `Register` (tribute, mourning, delight, outrage, dunking, gallows, riffing, awe, alarm, debate, resignation); `Dossier(what_happened, key_entities, conversation_summary, conversation_register, secondary_registers, event_sentiment, meme_potential, recurring_phrases)`; `Phrase(text, occurrences, distinct_authors)`.

**App** (`zeitgeist/api/app.py`) — `create_app(settings, *, execute=None, generate=None) -> FastAPI`. Router imports live inside `create_app`'s body to break the import cycle. **A new module that needs the app must call this factory, never import a module-level app.**

**Entry point** (`zeitgeist/serve.py`) — `uv run zeitgeist`, `--host`/`--port`/`--reload`, serving `127.0.0.1:8000`. `_app()` is the reload factory.

**Python test helpers** — `tests/api_factory.py`: `SeededRun`, `seed_run`, `api_settings(tmp_path)`, `seeded_client(tmp_path, *, runs=(), execute=None, generate=None, templates_dir=None)`. `tests/run_factory.py`: `make_run_config`, `make_stage_record`, `make_render_record`, `make_dossier`, `make_topic`, `make_scored_topic`, `make_evidence`, `FIXED_TIME`.

**Gates as they stand** — `.claude/settings.json` holds one Stop hook running `uv sync --locked` then the four Python commands. `.github/workflows/ci.yml` runs the same five steps. `CLAUDE.md`'s "Definition of Done" lists the four.

## File Structure

**Created — repository root:**

| File | Responsibility |
| --- | --- |
| `scripts/dump_openapi.py` | Writes the live app's OpenAPI document to `web/openapi.json`. The one command that moves the contract across the language boundary. |
| `tests/test_openapi_schema.py` | Asserts `web/openapi.json` still matches `create_app(...).openapi()`. This is the gate that turns a backend contract change into a red `uv run pytest` rather than a runtime surprise in the browser. |

**Created — `web/`:**

| File | Responsibility |
| --- | --- |
| `package.json`, `package-lock.json` | Dependencies and the three gate scripts (`lint`, `typecheck`, `test`). |
| `vite.config.ts` | Dev server, the `/api` proxy to `127.0.0.1:8000`, and the Vitest configuration. There is one config file, not two: the test environment is a property of this app, and splitting it invites the two to disagree about aliases. |
| `tsconfig.json`, `tsconfig.node.json` | `strict: true`, bundler resolution, the `@/` alias. |
| `eslint.config.js` | Flat config: TypeScript, React Hooks, and the import ordering the Python side gets from ruff's `I`. |
| `index.html`, `src/main.tsx` | The mount point and the provider tree. |
| `src/vite-env.d.ts` | `/// <reference types="vite/client" />`, which is what gives `*.module.css` imports a type. |
| `src/css-properties.d.ts` | The three custom properties components set through `style` (`--fill`, `--tile`, `--share`), declared on `CSSProperties` so no `as` cast is needed. |
| `scripts/check-types.mjs` | Regenerates `src/api/schema.ts` into a temp file and fails if it differs from the checked-in one. Folded into `typecheck`, which is where the spec puts contract drift. |
| `openapi.json` | Generated. The backend contract, checked in so the frontend gate needs no running server. |
| `src/api/schema.ts` | Generated by `openapi-typescript`. Never hand-edited. |
| `src/api/types.ts` | Named aliases over `schema.ts`'s deep `components["schemas"][...]` paths, so no other module reaches into the generated tree. |
| `src/api/client.ts` | `apiGet`, the typed fetch wrapper, and `ApiError`. Query-string building and error mapping live here and nowhere else. |
| `src/api/queries.ts` | The TanStack Query hooks and the query-key factory. One module so keys cannot drift from the fetches that use them. |
| `src/styles/tokens.css` | The handoff's colour, typography and geometry tables as custom properties. |
| `src/styles/reset.css` | Box sizing, margin reset, the body's ground, and the font stacks. |
| `src/styles/fonts.ts` | The `@fontsource` imports, in one place so the weights used are auditable. |
| `src/components/*` | `Chip`, `StatusPill`, `SectionLabel`, `StageBar`, `MemeTile`, `EmptyState`, `MetaLine`, `Breadcrumb`, `QueryBoundary` — each with its `.module.css`. |
| `src/format.ts` | `formatBytes`, `formatDuration`, `formatRelative`, `formatScore`, `shortRunId`, `formatClock`. Pure, and tested as pure functions rather than through six screens. |
| `src/app/*` | `App.tsx` (routes), `AppLayout.tsx` + `Sidebar.tsx`, `providers.tsx`. |
| `src/features/topics/*` | `TopicsPage`, `HeroTopic`, `MoodBar`, `TopicCard`, `RecentTable`, `StatusFilters`, `TopicDetailPage`, `DossierCards`, `ReplyList`, `PhraseCard`, `RenderGrid`. |
| `src/features/runs/*` | `RunsPage`, `RunRow`, `RunDetailPage`, `StageCards`, `RankingList`, `RankRow`. |
| `src/features/renders/*` | `RenderDetailPage`. |
| `src/test/*` | `setup.ts` (MSW lifecycle, `matchMedia`), `server.ts` (the MSW server), `factories.ts` (typed fixtures), `render.tsx` (the router + query-client wrapper every screen test uses). |

**Modified:**

| File | Change |
| --- | --- |
| `CLAUDE.md` | The Definition of Done grows to seven commands, with a line on what the three new ones cover. |
| `.claude/settings.json` | The Stop hook runs all seven. |
| `.github/workflows/ci.yml` | A Node setup step and the three npm steps. |
| `.gitignore` | `web/node_modules`, `web/dist`, `web/coverage`. |
| `README.md` | A "The web UI, in a browser" section: the two dev processes, and the two commands that regenerate the contract. |

---

### Task 1: the `web/` scaffold, and the Definition of Done grows to seven

This task exists on its own because it is the one that changes the gate. Everything after it runs seven commands; nothing before it could. It ends with a scaffold that renders one element and a suite that proves the three new commands actually run something.

**Files:**
- Create: `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, `web/tsconfig.node.json`, `web/eslint.config.js`, `web/index.html`, `web/src/main.tsx`, `web/src/App.tsx`, `web/src/styles/fonts.ts`, `web/src/test/setup.ts`
- Test: `web/src/App.test.tsx`
- Modify: `CLAUDE.md`, `.claude/settings.json`, `.github/workflows/ci.yml`, `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: the three gate commands `npm --prefix web run lint`, `npm --prefix web run typecheck`, `npm --prefix web test`; the `@/` alias resolving to `web/src/`; `web/src/test/setup.ts` as Vitest's `setupFiles` entry, which Task 4 extends with the MSW lifecycle.

- [ ] **Step 1: Create the package manifest and install**

Create `web/package.json`:

```json
{
  "name": "zeitgeist-web",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "lint": "eslint .",
    "typecheck": "node scripts/check-types.mjs && tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest",
    "generate:types": "openapi-typescript openapi.json -o src/api/schema.ts"
  },
  "dependencies": {
    "@fontsource-variable/outfit": "^5.2.5",
    "@fontsource/ibm-plex-mono": "^5.2.5",
    "@tanstack/react-query": "^5.62.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-router-dom": "^7.1.0"
  },
  "devDependencies": {
    "@eslint/js": "^9.17.0",
    "@testing-library/dom": "^10.4.0",
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.4",
    "eslint": "^9.17.0",
    "eslint-plugin-react-hooks": "^5.1.0",
    "eslint-plugin-react-refresh": "^0.4.16",
    "jsdom": "^25.0.1",
    "msw": "^2.7.0",
    "openapi-typescript": "^7.5.0",
    "typescript": "^5.7.2",
    "typescript-eslint": "^8.18.0",
    "vite": "^7.0.0",
    "vitest": "^2.1.8"
  }
}
```

`typecheck` references `scripts/check-types.mjs`, which Task 2 writes. Until then it does not exist, so **create a one-line placeholder now that Task 2 replaces** — this is the one exception to the no-placeholders rule in this plan, and it exists so that Task 1 can leave the gate green:

Create `web/scripts/check-types.mjs`:

```js
// Task 2 replaces this with the real drift check once `openapi.json` and
// `src/api/schema.ts` exist. It cannot check for drift in the types before
// there are types, and `npm run typecheck` has to pass at the end of this
// task.
process.exit(0);
```

Install:

```bash
npm --prefix web install
```

- [ ] **Step 2: Write the TypeScript, Vite and ESLint configuration**

Create `web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "types": ["vitest/globals", "@testing-library/jest-dom"],
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedIndexedAccess": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "resolveJsonModule": true,
    "skipLibCheck": true,
    "noEmit": true,
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  },
  "include": ["src", "vite.config.ts", "eslint.config.js"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

`noUncheckedIndexedAccess` is on deliberately. Several screens index into arrays whose emptiness is a real state — `topics[0]` as the hero, `render_ids[0]` as the latest meme — and this is the flag that makes the compiler insist those are handled rather than assumed.

Create `web/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2023"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "types": ["node"],
    "strict": true,
    "noEmit": true,
    "isolatedModules": true,
    "skipLibCheck": true
  },
  "include": ["scripts"]
}
```

Create `web/vite.config.ts`:

```ts
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Before anything reads a date. Several screens render a wall clock —
// reply timestamps, "as of 14:02" — and `Intl` resolves the zone from the
// process. Without this, those assertions pass in London and fail in
// Sydney, which is the worst kind of test.
process.env.TZ = "UTC";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    // Dev is two processes: Vite here, uvicorn on 8000. Proxying rather
    // than enabling CORS keeps the app same-origin in development and
    // identical to the deployment where the built SPA is served by
    // uvicorn itself — so no request path is exercised only in one mode.
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    restoreMocks: true,
  },
});
```

`css: false` is deliberate. CSS Modules resolve to a proxy in tests, so class names stay stable and cheap; nothing in this phase asserts on a class name, and parsing every stylesheet per test file would buy nothing.

Create `web/eslint.config.js`:

```js
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage", "src/api/schema.ts"] },
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // The three rules that enforce the Global Constraints' TypeScript
      // rule. Without them "no any, no !, no as" is a request rather than
      // a gate.
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-non-null-assertion": "error",
      "@typescript-eslint/consistent-type-assertions": [
        "error",
        { assertionStyle: "never" },
      ],
      "@typescript-eslint/consistent-type-imports": "error",
    },
  },
  {
    // The one file allowed to assert a type: `Response.json()` is
    // `Promise<any>` by definition, so the boundary between untyped JSON
    // and the generated contract types has to be asserted exactly once,
    // and `src/api/client.ts` is where. Scoping the exemption to the file
    // rather than sprinkling `eslint-disable` lines is what makes "the app
    // has one cast" a fact you can check by reading this config.
    files: ["src/api/client.ts"],
    rules: { "@typescript-eslint/consistent-type-assertions": "off" },
  },
  {
    // The generated schema and the node scripts are not part of the app's
    // type-checked project, and the drift checker is plain JS.
    files: ["scripts/**/*.mjs"],
    ...tseslint.configs.disableTypeChecked,
  },
);
```

`assertionStyle: "never"` bans `as` outright, including `as const`. Nothing in this phase needs `as const`: the two places that would reach for it — `STAGES` and `STATUS_ORDER` — are declared `readonly T[]` with an explicit element type instead, which is what they actually want.

- [ ] **Step 3: Write the entry point and the smoke test**

Create `web/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Zeitgeist</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `web/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />
```

Without this, `import styles from "./Chip.module.css"` has no type and
`tsc --noEmit` fails on the first component. It is one line and it is easy
to lose an hour to.

Create `web/src/styles/fonts.ts`:

```ts
// Bundled rather than fetched: a local tool should not need the network to
// render correctly. The weights are exactly those the handoff's typography
// table uses — Outfit 400/500/600/700/800 (covered by the variable face)
// and IBM Plex Mono 400/500/600/700, which ships as static weights.
import "@fontsource-variable/outfit";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import "@fontsource/ibm-plex-mono/700.css";
```

Create `web/src/App.tsx`:

```tsx
export function App() {
  return <div>Zeitgeist</div>;
}
```

Create `web/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/App";
import "@/styles/fonts";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("index.html is missing #root");
}
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

Create `web/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

Create `web/src/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "@/App";

describe("App", () => {
  it("mounts", () => {
    render(<App />);
    expect(screen.getByText("Zeitgeist")).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run the three new commands and confirm they pass**

```bash
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web test
```

Expected: three clean exits, with `vitest` reporting `1 passed`.

If `typecheck` reports that `vitest/globals` is not found, the `types` array in `tsconfig.json` is not being picked up — confirm `web/tsconfig.json` is the file being read and not a stray generated one from `npm create vite`.

- [ ] **Step 5: Grow the Definition of Done to seven commands**

In `CLAUDE.md`, replace the fenced block under "## Definition of Done" with all seven commands, and replace the paragraph beneath it:

````markdown
## Definition of Done

A task is not complete until all seven of these pass:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web test
```

Do not report a task as finished, and do not open a pull request, until you
have run them and seen them pass. A Stop hook enforces this, and CI runs the
same seven commands on pushes to `main` and on every pull request. Both the
Stop hook and CI run `uv sync --locked` and `npm --prefix web ci` before the
seven commands, so a stale lockfile on either side fails fast.

`npm --prefix web run typecheck` also regenerates `web/src/api/schema.ts`
from `web/openapi.json` and fails if the checked-in file differs, and
`uv run pytest` asserts `web/openapi.json` still matches the FastAPI app.
Between them, a backend contract change that has not been carried across to
the client turns the gate red rather than surfacing in the browser.
````

- [ ] **Step 6: Grow the Stop hook and CI**

Replace the `command` string in `.claude/settings.json`'s Stop hook. It is one line; the seven commands chain after the two installs:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "shell": "bash",
            "timeout": 600,
            "statusMessage": "Checking lint, format, types, tests, web",
            "command": "out=$( { uv sync --locked && npm --prefix web ci && uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest && npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test ; } 2>&1 ) || { printf '%s\\n' \"$out\" >&2; echo 'Definition of Done failed. Fix the failures above before completing this task.' >&2; exit 2; }"
          }
        ]
      }
    ]
  }
}
```

The timeout doubles to 600 because it now installs two dependency trees and runs two suites.

In `.github/workflows/ci.yml`, add the Node setup after the uv sync step and the three npm steps after `uv run pytest`:

```yaml
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run ty check
      - run: uv run pytest

      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: web/package-lock.json

      # `ci` rather than `install`: it installs exactly what the lockfile
      # says and fails when package.json has drifted from it, which is the
      # same guarantee `uv sync --locked` gives on the Python side.
      - run: npm --prefix web ci

      - run: npm --prefix web run lint
      - run: npm --prefix web run typecheck
      - run: npm --prefix web test
```

Add to `.gitignore`:

```
web/node_modules/
web/dist/
web/coverage/
```

- [ ] **Step 7: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest && npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: all seven pass. `package-lock.json` must be committed — CI's `npm ci` fails without it.

- [ ] **Step 8: Commit**

```bash
git add web CLAUDE.md .claude/settings.json .github/workflows/ci.yml .gitignore
git commit -m "Scaffold web/ and grow the Definition of Done to seven commands"
```

---

### Task 2: the contract crosses the language boundary, and two gates keep it there

**Files:**
- Create: `scripts/dump_openapi.py`, `tests/test_openapi_schema.py`, `web/openapi.json` (generated), `web/src/api/schema.ts` (generated), `web/src/api/types.ts`
- Modify: `web/scripts/check-types.mjs` (replacing Task 1's placeholder)

**Interfaces:**
- Consumes: Task 1's `web/package.json` scripts and `@/` alias.
- Produces: `web/src/api/types.ts` exporting `RunPage`, `RunSummary`, `RunRecordRow`, `RunConfig`, `RunError`, `RunDetail`, `StageRecord`, `Stage`, `RunStatus`, `StageStatus`, `RankedTopic`, `TopicRow`, `TrendStatus`, `TopicDetail`, `ReplyOut`, `TopicRecurrence`, `Dossier`, `Phrase`, `IndexedTopic`, `TopicIndex`, `RenderRecord`, `Origin`, `LogLine`, `SettingField`, plus `STAGES` and `ARTIFACT_NAMES`. Every later task imports its types from here and from nowhere else.

- [ ] **Step 1: Write the failing test**

Create `tests/test_openapi_schema.py`:

```python
"""The checked-in OpenAPI document must still be the app's own.

`web/openapi.json` is what `openapi-typescript` generates the client types
from, and the frontend gate reads it from disk rather than from a running
server. That makes it a copy, and a copy of a contract is only useful while
something proves it is current. This is that proof: change a response model
without re-running `scripts/dump_openapi.py` and `uv run pytest` goes red
here, before the drift can reach a screen.
"""

import json
from pathlib import Path

from zeitgeist.api import create_app
from zeitgeist.config import Settings

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "web" / "openapi.json"


def test_checked_in_openapi_matches_the_app(tmp_path):
    app = create_app(Settings(db_path=tmp_path / "z.db", output_dir=tmp_path / "out"))

    assert SCHEMA_PATH.is_file(), (
        f"{SCHEMA_PATH} is missing. Run: uv run python scripts/dump_openapi.py"
    )
    assert json.loads(SCHEMA_PATH.read_text(encoding="utf-8")) == app.openapi(), (
        "web/openapi.json is stale. Regenerate it with "
        "`uv run python scripts/dump_openapi.py`, then regenerate the client "
        "types with `npm --prefix web run generate:types`."
    )


def test_every_endpoint_this_phase_reads_is_present():
    """The nine read endpoints phase 5 builds against.

    A guard against the schema being regenerated from an app that failed to
    mount a router: `create_app` imports its routers inside its own body, so
    a broken import would produce a smaller but perfectly valid document,
    and the equality test above would happily accept it.
    """
    paths = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["paths"]

    for path in (
        "/api/runs",
        "/api/runs/{run_id}",
        "/api/runs/{run_id}/topics",
        "/api/runs/{run_id}/topics/{topic_id}",
        "/api/runs/{run_id}/log",
        "/api/topics",
        "/api/renders/{render_id}",
        "/api/renders/{render_id}/image",
        "/api/settings",
    ):
        assert path in paths, f"{path} is missing from the schema"
        assert "get" in paths[path], f"{path} has no GET operation"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_openapi_schema.py -v`

Expected: both FAIL — the first on the `is_file()` assertion naming the missing path, the second with `FileNotFoundError` reading it.

- [ ] **Step 3: Write the dump script**

Create `scripts/dump_openapi.py`:

```python
"""Write the app's OpenAPI document to `web/openapi.json`.

The one command that carries the contract across the language boundary.
The frontend generates its TypeScript from the file rather than from a
running server, so `npm --prefix web run typecheck` needs nothing listening
on port 8000 — a gate that needs a server running is a gate that fails for
the wrong reason.

Run it after any change to a response model, then regenerate the client
types:

    uv run python scripts/dump_openapi.py
    npm --prefix web run generate:types
"""

import json
import sys
import tempfile
from pathlib import Path

from zeitgeist.api import create_app
from zeitgeist.config import Settings

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "web" / "openapi.json"


def main() -> int:
    # A throwaway database: building the app opens a store and initialises a
    # schema, and dumping a schema must not touch the real one — nor create
    # it as a side effect on a machine that has never run the tool.
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        app = create_app(
            Settings(db_path=scratch / "openapi.db", output_dir=scratch / "out")
        )
        document = app.openapi()

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    # indent=2 and a trailing newline so a regeneration produces a reviewable
    # diff rather than one very long changed line.
    TARGET.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {TARGET.relative_to(ROOT)} ({len(document['paths'])} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Generate the document and the types**

```bash
uv run python scripts/dump_openapi.py
```

```bash
npm --prefix web run generate:types
```

Expected: `Wrote web\openapi.json (15 paths)`, then `openapi-typescript` reporting it wrote `src/api/schema.ts`.

Read the head of the generated file and confirm it carries `components["schemas"]["RunPage"]`, `["RunDetail"]`, `["TopicIndex"]` and `["RenderRecord"]`. **Do not edit it.**

- [ ] **Step 5: Run the Python tests to verify they pass**

Run: `uv run pytest tests/test_openapi_schema.py -v`

Expected: both PASS.

- [ ] **Step 6: Write the real drift checker**

Replace `web/scripts/check-types.mjs` in full:

```js
// Fails when `src/api/schema.ts` no longer matches what `openapi.json`
// generates. Folded into `npm run typecheck` because the spec puts contract
// drift there, and because a generated file that nothing regenerates is a
// contract nobody is holding to.
//
// It regenerates into a temp file rather than in place: a checker that
// rewrites the working tree turns a failing gate into a passing one on the
// second run, which is the one behaviour a drift gate must not have.

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const scratch = mkdtempSync(join(tmpdir(), "zeitgeist-types-"));
const candidate = join(scratch, "schema.ts");

try {
  execFileSync(
    process.execPath,
    ["node_modules/openapi-typescript/bin/cli.js", "openapi.json", "-o", candidate],
    { stdio: ["ignore", "ignore", "inherit"] },
  );

  if (readFileSync(candidate, "utf8") !== readFileSync("src/api/schema.ts", "utf8")) {
    console.error(
      [
        "src/api/schema.ts is stale.",
        "",
        "If you changed a backend response model, regenerate both:",
        "  uv run python scripts/dump_openapi.py",
        "  npm --prefix web run generate:types",
        "",
        "If you did not, someone hand-edited a generated file. Regenerate it.",
      ].join("\n"),
    );
    process.exit(1);
  }
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
```

- [ ] **Step 7: Write the named type aliases**

Create `web/src/api/types.ts`:

```ts
/**
 * Named aliases over the generated schema.
 *
 * `schema.ts` addresses every model as `components["schemas"]["RunPage"]`.
 * Letting screens reach into that shape would spread the generator's own
 * layout through the app, so a future switch of generator — or a `$ref` that
 * resolves differently — would touch every file that names a type. This
 * module is the only one that knows the shape.
 */
import type { components } from "@/api/schema";

type Schemas = components["schemas"];

export type RunConfig = Schemas["RunConfig"];
export type RunError = Schemas["RunError"];
export type RunRecordRow = Schemas["RunRecordRow"];
export type RunStatus = RunRecordRow["status"];
export type RunSummary = Schemas["RunSummary"];
export type RunPage = Schemas["RunPage"];
export type RunDetail = Schemas["RunDetail"];
export type StageRecord = Schemas["StageRecord"];
export type Stage = StageRecord["stage"];
export type StageStatus = StageRecord["status"];

export type TopicRow = Schemas["TopicRow"];
export type TrendStatus = TopicRow["trend_status"];
export type RankedTopic = Schemas["RankedTopic"];
export type TopicDetail = Schemas["TopicDetail"];
export type ReplyOut = Schemas["ReplyOut"];
export type TopicRecurrence = Schemas["TopicRecurrence"];
export type Dossier = Schemas["Dossier"];
export type Phrase = Schemas["Phrase"];
export type IndexedTopic = Schemas["IndexedTopic"];
export type TopicIndex = Schemas["TopicIndex"];

export type RenderRecord = Schemas["RenderRecord"];
export type Origin = RenderRecord["origin"];
export type RenderStatus = RenderRecord["status"];
export type LogLine = Schemas["LogLine"];
export type SettingField = Schemas["SettingField"];

/** The four stages in the order they run — the order the stage cards draw. */
export const STAGES: readonly Stage[] = ["ingest", "analyse", "evaluate", "generate"];

/**
 * What each stage's checkpoint is called on screen.
 *
 * The spec drops the extensions the design drew (`evidence.json`) because
 * these are database rows now, and a filename for a row is a small lie on a
 * screen whose whole job is telling you what a run actually did. The names
 * themselves are the pipeline's own vocabulary and stay.
 */
export const ARTIFACT_NAMES: Readonly<Record<Stage, string>> = {
  ingest: "evidence",
  analyse: "topics",
  evaluate: "ranked",
  generate: "briefs",
};
```

- [ ] **Step 8: Run the frontend gates to verify they pass**

Run: `npm --prefix web run typecheck` then `npm --prefix web run lint`

Expected: both clean.

Then prove the drift gate is real: change one character inside a string in `web/src/api/schema.ts`, re-run `npm --prefix web run typecheck`, and confirm it fails with the "src/api/schema.ts is stale." message. Restore it with `npm --prefix web run generate:types`.

- [ ] **Step 9: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest && npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: all seven pass.

- [ ] **Step 10: Commit**

```bash
git add scripts/dump_openapi.py tests/test_openapi_schema.py web/openapi.json web/src/api web/scripts/check-types.mjs
git commit -m "Generate the client's types from the API's own OpenAPI schema"
```

---

### Task 3: `tokens.css` — the handoff's tables, transcribed

**Files:**
- Create: `web/src/styles/tokens.css`, `web/src/styles/reset.css`
- Modify: `web/src/main.tsx`

**Interfaces:**
- Consumes: nothing.
- Produces: every custom property listed in Step 1. Every `.module.css` written after this task references these and defines no colour of its own.

**This task ships no test, deliberately.** A token table is a design artifact, not behaviour: every assertion available over it is a grep of its own source text, which proves only that the source is the source, and the values themselves fail only when a designer changes their mind. Colour, type and spacing fidelity is a human review against the mockups — the spec says so, and a machine assertion would duplicate that review and freeze a table the designer is entitled to change.

The one mechanically checkable invariant here spans files rather than living in this one: *no stylesheet in the app defines a colour of its own*. That is a lint over every `.module.css`, it can be violated accidentally by anyone adding a component, and nobody catches it by eye across twenty files. It lands in Task 5, with the first stylesheets that could break it.

- [ ] **Step 1: Write the stylesheets**

Create `web/src/styles/tokens.css`:

```css
/*
 * The handoff's colour, typography and geometry tables, verbatim.
 * Source: design_handoff_zeitgeist_ui/README.md, "Design Tokens".
 *
 * Several tokens below are not rows in that table. They are here because
 * the handoff names their values inline, in more than one place, and a
 * value repeated across four stylesheets is a value that drifts:
 *
 *   --on-accent        #17140e — text on an accent fill. The same hex as
 *                      --bg, named for its role: the hero card inverts the
 *                      palette, and "the page colour" and "the colour text
 *                      takes on an accent fill" are different ideas that
 *                      happen to agree.
 *   --contrast-border  rgba(61,99,230,.35) — the failed run row's border,
 *                      the failed render tile, the queue notice.
 *   --contrast-fill    rgba(61,99,230,.2) — the FAILED status pill's fill.
 *   --chip-fill        white 8% — the secondary chip, per "Chip".
 *   --mood-tail /      white 16% / 8% — the mood bar's third segment and
 *   --mood-rest        its tail.
 *   --border-hover     white 16% — the handoff's suggested hover.
 *
 * Ranged tokens in the handoff (radius-panel 11-12px, gap-page 20-22px)
 * take the value the mockups use most; a range describes the design and is
 * not something CSS can hold.
 */
:root {
  --bg: #17140e;
  --bg-sidebar: #141109;
  --surface: #1d1a12;
  --surface-log: #100e09;

  --accent: #ffd93d;
  --accent-wash: rgba(255, 217, 61, 0.06);
  --accent-tint: rgba(255, 217, 61, 0.14);
  --accent-border: rgba(255, 217, 61, 0.3);
  --accent-border-strong: rgba(255, 217, 61, 0.35);
  --accent-half: rgba(255, 217, 61, 0.5);
  --on-accent: #17140e;

  --contrast: #3d63e6;
  --contrast-light: #8aa4ff;
  --contrast-border: rgba(61, 99, 230, 0.35);
  --contrast-wash: rgba(61, 99, 230, 0.08);
  --contrast-fill: rgba(61, 99, 230, 0.2);

  --text: #f5f1e6;
  --text-70: rgba(245, 241, 230, 0.7);
  --text-55: rgba(245, 241, 230, 0.55);
  --text-50: rgba(245, 241, 230, 0.5);
  --text-40: rgba(245, 241, 230, 0.4);
  --text-35: rgba(245, 241, 230, 0.35);
  --text-30: rgba(245, 241, 230, 0.3);

  --border: rgba(255, 255, 255, 0.09);
  --border-strong: rgba(255, 255, 255, 0.14);
  --border-hover: rgba(255, 255, 255, 0.16);
  --divider: rgba(255, 255, 255, 0.07);
  --chip-fill: rgba(255, 255, 255, 0.08);
  --chip-fill-strong: rgba(255, 255, 255, 0.15);
  --mood-tail: rgba(255, 255, 255, 0.16);
  --mood-rest: rgba(255, 255, 255, 0.08);

  --stripe-a: #211d14;
  --stripe-b: #272216;
  --stripe: repeating-linear-gradient(
    135deg,
    var(--stripe-a) 0 8px,
    var(--stripe-b) 8px 16px
  );

  --font-ui: "Outfit Variable", "Outfit", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", monospace;

  --radius-pill: 20px;
  --radius-card: 14px;
  --radius-panel: 12px;
  --radius-tile: 8px;
  --radius-sm: 6px;

  --gap-page: 20px;
  --gap-section: 14px;
  --gap-card: 12px;
  --gap-tight: 6px;

  --sidebar-width: 180px;
  --content-width: 1000px;
  --app-width: 1180px;

  /* 120-150ms ease-out, per the handoff's hover note. One duration, so the
     whole app agrees about how fast it moves. */
  --transition: 140ms ease-out;
}
```

Create `web/src/styles/reset.css`:

```css
*,
*::before,
*::after {
  box-sizing: border-box;
}

body,
h1,
h2,
h3,
p,
figure,
ul,
ol {
  margin: 0;
}

ul,
ol {
  padding: 0;
  list-style: none;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 13px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}

/* The design underlines no link anywhere; colour and weight carry it. */
a {
  color: inherit;
  text-decoration: none;
}

button {
  font: inherit;
  color: inherit;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
}

img {
  max-width: 100%;
  display: block;
}

/* Dossier prose and card titles. `pretty` is what stops the two-word widow
   on a title that the mockups never show. */
p,
h1,
h2,
h3 {
  text-wrap: pretty;
}
```

- [ ] **Step 2: Import the stylesheets at the entry point**

In `web/src/main.tsx`, add two imports above the fonts import — tokens first, because `reset.css` reads them:

```tsx
import "@/styles/tokens.css";
import "@/styles/reset.css";
import "@/styles/fonts";
```

- [ ] **Step 3: Confirm the tokens resolve in a browser, not in a test**

```bash
npm --prefix web run dev
```

Open the URL Vite prints and, in the devtools console, evaluate:

```js
getComputedStyle(document.documentElement).getPropertyValue("--accent")
```

Expected: `#ffd93d`. An empty string means the stylesheet is not reaching the document — almost always an import missing from `main.tsx`, or `tokens.css` imported after something that reads it. This is the check that a grep of the file cannot make, which is why it is done here and once, by eye.

- [ ] **Step 4: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest && npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

- [ ] **Step 5: Commit**

```bash
git add web/src/styles web/src/main.tsx
git commit -m "Transcribe the handoff's token table into tokens.css"
```

---

### Task 4: the typed client, the query hooks, and the test harness every later task uses

**Files:**
- Create: `web/src/api/client.ts`, `web/src/api/queries.ts`, `web/src/format.ts`, `web/src/test/server.ts`, `web/src/test/factories.ts`, `web/src/test/render.tsx`
- Test: `web/src/api/client.test.ts`, `web/src/api/queries.test.tsx`, `web/src/format.test.ts`
- Modify: `web/src/test/setup.ts`

**Interfaces:**
- Consumes: `@/api/types` (Task 2).
- Produces:
  - `apiGet<T>(path: string, params?: QueryParams): Promise<T>`, `ApiError { status: number; detail: string }`, `imageUrl(renderId: string, size: "full" | "thumb"): string`.
  - `queryKeys` and the hooks `useRuns(limit?)`, `useRun(runId)`, `useRanking(runId)`, `useTopicDetail(runId, topicId)`, `useTopicIndex(options?)`, `useRender(renderId)`. Each returns TanStack Query's `UseQueryResult<T, ApiError>`.
  - `formatBytes`, `formatDuration`, `formatRelative`, `formatClock`, `formatScore`, `shortRunId`.
  - `server` (the MSW server), the factories `makeRunConfig`, `makeRunRecord`, `makeRunSummary`, `makeRunPage`, `makeStageRecord`, `makeRunDetail`, `makeTopicRow`, `makeRankedTopic`, `makeDossier`, `makeTopicDetail`, `makeIndexedTopic`, `makeTopicIndex`, `makeRenderRecord`, and `renderWithProviders(ui, { route, path })` plus `renderWithProviders.Wrapper`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/format.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
  formatBytes,
  formatClock,
  formatDuration,
  formatRelative,
  formatScore,
  shortRunId,
} from "@/format";

describe("formatBytes", () => {
  it("renders a stage payload the way the stage card does", () => {
    // 1_363_148 / 1_000_000 = 1.363148, which toFixed(1) rounds to 1.4.
    expect(formatBytes(1_363_148)).toBe("1.4 MB");
  });

  it("keeps small payloads in kB rather than showing 0.0 MB", () => {
    expect(formatBytes(4096)).toBe("4.1 kB");
  });

  it("renders bytes without a decimal point", () => {
    expect(formatBytes(812)).toBe("812 B");
  });

  it("says nothing for a stage that wrote no checkpoint", () => {
    // A queued, failed or skipped stage has payload_bytes = null. "0 B" would
    // claim it wrote an empty checkpoint, which is a different fact.
    expect(formatBytes(null)).toBe("—");
  });
});

describe("formatDuration", () => {
  it("renders minutes and seconds", () => {
    expect(formatDuration("2026-08-29T09:00:00Z", "2026-08-29T09:06:41Z")).toBe("6m 41s");
  });

  it("renders a sub-minute stage in seconds alone", () => {
    expect(formatDuration("2026-08-29T09:00:00Z", "2026-08-29T09:00:09Z")).toBe("9s");
  });

  it("renders hours when a run took them", () => {
    expect(formatDuration("2026-08-29T09:00:00Z", "2026-08-29T11:04:00Z")).toBe(
      "2h 4m",
    );
  });

  it("says nothing when the run has not finished", () => {
    expect(formatDuration("2026-08-29T09:00:00Z", null)).toBe("—");
  });
});

describe("formatRelative", () => {
  const now = new Date("2026-08-29T12:00:00Z");

  it("renders minutes for something within the hour", () => {
    expect(formatRelative("2026-08-29T11:38:00Z", now)).toBe("22m ago");
  });

  it("renders hours within the day", () => {
    expect(formatRelative("2026-08-29T04:00:00Z", now)).toBe("8h ago");
  });

  it("renders days beyond that", () => {
    expect(formatRelative("2026-08-26T12:00:00Z", now)).toBe("3d ago");
  });

  it("renders the most recent minute as just now rather than 0m ago", () => {
    expect(formatRelative("2026-08-29T11:59:31Z", now)).toBe("just now");
  });
});

describe("formatScore", () => {
  it("renders two decimals, which is what the ranking columns show", () => {
    expect(formatScore(0.9)).toBe("0.90");
  });

  it("renders three where the design does, for the final score", () => {
    expect(formatScore(0.8954, 3)).toBe("0.895");
  });

  it("renders an em dash for a topic the model gave no meme potential", () => {
    // Dossier.meme_potential is null when the model returned no usable
    // number. "0.00" would read as "this is a terrible meme", which is a
    // claim the pipeline never made.
    expect(formatScore(null)).toBe("—");
  });
});

describe("shortRunId", () => {
  it("truncates to the tail the runs list shows", () => {
    expect(shortRunId("20260829T090000Z")).toBe("…829T090000Z");
  });

  it("leaves an id that is already short alone", () => {
    expect(shortRunId("090000Z")).toBe("090000Z");
  });
});

describe("formatClock", () => {
  it("renders the wall clock the Topics header ends with", () => {
    expect(formatClock("2026-08-29T14:02:00Z", "UTC")).toBe("14:02");
  });
});
```

Create `web/src/api/client.test.ts`:

```ts
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { ApiError, apiGet, imageUrl } from "@/api/client";
import { server } from "@/test/server";

describe("apiGet", () => {
  it("returns the decoded body", async () => {
    server.use(
      http.get("/api/runs/:runId", () => HttpResponse.json({ hello: "world" })),
    );

    await expect(apiGet<{ hello: string }>("/api/runs/abc")).resolves.toEqual({
      hello: "world",
    });
  });

  it("appends the parameters it was given", async () => {
    let seen = "";
    server.use(
      http.get("/api/topics", ({ request }) => {
        seen = new URL(request.url).search;
        return HttpResponse.json({ topics: [] });
      }),
    );

    await apiGet("/api/topics", { window: 6, status: "trending" });

    expect(seen).toBe("?window=6&status=trending");
  });

  it("omits a parameter that is undefined rather than sending the string", async () => {
    // `status` is the filter chip's "no filter" state. Sending
    // `status=undefined` would filter on a status no topic has, and the
    // screen would silently render empty.
    let seen = "";
    server.use(
      http.get("/api/topics", ({ request }) => {
        seen = new URL(request.url).search;
        return HttpResponse.json({ topics: [] });
      }),
    );

    await apiGet("/api/topics", { window: 6, status: undefined });

    expect(seen).toBe("?window=6");
  });

  it("raises ApiError carrying the status and FastAPI's own detail", async () => {
    server.use(
      http.get("/api/runs/:runId", () =>
        HttpResponse.json({ detail: "No such run: nope" }, { status: 404 }),
      ),
    );

    await expect(apiGet("/api/runs/nope")).rejects.toThrowError(
      expect.objectContaining({ status: 404, detail: "No such run: nope" }),
    );
  });

  it("raises ApiError with a readable detail when the body is not JSON", async () => {
    // uvicorn's own 502/503 pages are HTML. A client that assumed JSON here
    // would throw a SyntaxError, and the screen would report a parse failure
    // instead of the server being down.
    server.use(
      http.get("/api/runs", () =>
        HttpResponse.text("<html>Bad Gateway</html>", { status: 502 }),
      ),
    );

    await expect(apiGet("/api/runs")).rejects.toThrowError(
      expect.objectContaining({ status: 502, detail: "Request failed (502)" }),
    );
  });

  it("is an Error, so an untyped boundary still reports something useful", () => {
    expect(new ApiError(404, "gone")).toBeInstanceOf(Error);
    expect(new ApiError(404, "gone").message).toBe("gone");
  });
});

describe("imageUrl", () => {
  it("addresses the full-size PNG", () => {
    expect(imageUrl("r1", "full")).toBe("/api/renders/r1/image?size=full");
  });

  it("addresses the 96px thumbnail", () => {
    expect(imageUrl("r1", "thumb")).toBe("/api/renders/r1/image?size=thumb");
  });
});
```

Create `web/src/api/queries.test.tsx`:

```tsx
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import {
  queryKeys,
  useRanking,
  useRender,
  useRun,
  useRuns,
  useTopicDetail,
  useTopicIndex,
} from "@/api/queries";
import {
  makeRankedTopic,
  makeRenderRecord,
  makeRunDetail,
  makeRunPage,
  makeTopicDetail,
  makeTopicIndex,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

describe("queryKeys", () => {
  it("scopes a ranking under its run, so one run's cache cannot serve another", () => {
    expect(queryKeys.ranking("a")).not.toEqual(queryKeys.ranking("b"));
  });

  it("varies with the topics window and status, which the filter chips change", () => {
    expect(queryKeys.topicIndex({ window: 6 })).not.toEqual(
      queryKeys.topicIndex({ window: 6, status: "trending" }),
    );
  });
});

describe("useRun", () => {
  it("resolves the run detail for the id it was given", async () => {
    server.use(
      http.get("/api/runs/:runId", ({ params }) =>
        HttpResponse.json(makeRunDetail({ runId: String(params.runId) })),
      ),
    );

    const { result } = renderHook(() => useRun("20260829T090000Z"), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.run.run_id).toBe("20260829T090000Z");
  });

  it("surfaces a 404 as an ApiError rather than retrying it", async () => {
    // The default retry would turn every mistyped run id into three requests
    // and a several-second wait before the screen could say "no such run".
    server.use(
      http.get("/api/runs/:runId", () =>
        HttpResponse.json({ detail: "No such run: nope" }, { status: 404 }),
      ),
    );

    const { result } = renderHook(() => useRun("nope"), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.status).toBe(404);
    expect(result.current.failureCount).toBe(1);
  });

  it("does not fire until it has a run id", () => {
    const { result } = renderHook(() => useRun(undefined), {
      wrapper: renderWithProviders.Wrapper,
    });

    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useRanking", () => {
  it("returns the rows in the order the API sent them", async () => {
    server.use(
      http.get("/api/runs/:runId/topics", () =>
        HttpResponse.json([
          makeRankedTopic({ topicId: "t1", finalRank: 1 }),
          makeRankedTopic({ topicId: "t2", finalRank: 2 }),
        ]),
      ),
    );

    const { result } = renderHook(() => useRanking("r1"), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.map((row) => row.topic.topic_id)).toEqual(["t1", "t2"]);
  });
});

describe("useRuns", () => {
  it("sends the limit it was given", async () => {
    let seen = "";
    server.use(
      http.get("/api/runs", ({ request }) => {
        seen = new URL(request.url).search;
        return HttpResponse.json(makeRunPage());
      }),
    );

    const { result } = renderHook(() => useRuns(10), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(seen).toBe("?limit=10");
  });
});

describe("useTopicDetail", () => {
  it("does not fire until it has both a run id and a topic id", () => {
    // Two ids, so the guard is an `&&`. Mutated to `||`, this would request
    // `/api/runs/undefined/topics/t1` — a 404 the screen would report as a
    // missing topic, sending someone looking for a data problem that is
    // really a routing one.
    const { result: onlyRun } = renderHook(() => useTopicDetail("r1", undefined), {
      wrapper: renderWithProviders.Wrapper,
    });
    expect(onlyRun.current.fetchStatus).toBe("idle");

    const { result: onlyTopic } = renderHook(() => useTopicDetail(undefined, "t1"), {
      wrapper: renderWithProviders.Wrapper,
    });
    expect(onlyTopic.current.fetchStatus).toBe("idle");
  });

  it("addresses the topic under its run once both ids are present", async () => {
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", ({ params }) =>
        HttpResponse.json(
          makeTopicDetail({
            runId: String(params.runId),
            topicId: String(params.topicId),
          }),
        ),
      ),
    );

    const { result } = renderHook(() => useTopicDetail("r1", "t1"), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.topic.topic_id).toBe("t1");
  });
});

describe("useRender", () => {
  it("resolves the render for the id it was given", async () => {
    server.use(
      http.get("/api/renders/:renderId", ({ params }) =>
        HttpResponse.json(makeRenderRecord({ id: String(params.renderId) })),
      ),
    );

    const { result } = renderHook(() => useRender("render-9"), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe("render-9");
  });

  it("does not fire until it has a render id", () => {
    const { result } = renderHook(() => useRender(undefined), {
      wrapper: renderWithProviders.Wrapper,
    });

    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useTopicIndex", () => {
  it("sends the window and the status filter", async () => {
    let seen = "";
    server.use(
      http.get("/api/topics", ({ request }) => {
        seen = new URL(request.url).search;
        return HttpResponse.json(makeTopicIndex());
      }),
    );

    const { result } = renderHook(() => useTopicIndex({ window: 6, status: "cooling" }), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(seen).toBe("?window=6&status=cooling");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test`

Expected: FAIL — every new file reports an unresolved import for `@/format`, `@/api/client`, `@/api/queries` or `@/test/*`.

- [ ] **Step 3: Write the formatters**

Create `web/src/format.ts`:

```ts
/**
 * Every number and date the screens render, in one place.
 *
 * Pure, and tested as pure functions rather than through six screens. The
 * em dash is the shared convention for "there genuinely is no value here":
 * a stage that wrote no checkpoint, a run that has not finished, a topic the
 * model gave no meme potential. Rendering a zero for any of those would be a
 * claim the pipeline never made.
 */

const NONE = "—";

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return NONE;
  if (bytes < 1000) return `${bytes} B`;
  if (bytes < 1_000_000) return `${(bytes / 1000).toFixed(1)} kB`;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

export function formatDuration(
  startedAt: string,
  finishedAt: string | null | undefined,
): string {
  if (!finishedAt) return NONE;
  const seconds = Math.max(
    0,
    Math.round(
      (new Date(finishedAt).getTime() - new Date(startedAt).getTime()) / 1000,
    ),
  );
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function formatRelative(at: string, now: Date = new Date()): string {
  const seconds = Math.max(0, (now.getTime() - new Date(at).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** The wall clock, `14:02`, that the Topics header's metadata line ends with. */
export function formatClock(at: string, timeZone?: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone,
  }).format(new Date(at));
}

export function formatScore(score: number | null | undefined, digits = 2): string {
  if (score === null || score === undefined) return NONE;
  return score.toFixed(digits);
}

/**
 * `…829T090000Z` — the truncation the runs list draws.
 *
 * A run id is a timestamp, so its leading characters are the part that
 * repeats. Dropping them is what makes a column of twenty-five ids readable.
 */
export function shortRunId(runId: string): string {
  return runId.length > 12 ? `…${runId.slice(-11)}` : runId;
}
```

- [ ] **Step 4: Write the client**

Create `web/src/api/client.ts`:

```ts
/**
 * The one place that talks to the API.
 *
 * Same-origin `/api/...` paths throughout: Vite proxies them to uvicorn in
 * development, and the built SPA is served by uvicorn itself. No base URL,
 * no environment variable, no CORS.
 */

export type QueryParams = Record<string, string | number | boolean | undefined>;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

function withParams(path: string, params?: QueryParams): string {
  if (!params) return path;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    // Undefined is "this filter is off", not "filter on the string
    // 'undefined'" — which is what URLSearchParams would otherwise send,
    // and which the server would answer with an empty list.
    if (value !== undefined) search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

async function detailOf(response: Response): Promise<string> {
  // FastAPI's errors are `{"detail": "..."}`. uvicorn's own 502/503 pages
  // are HTML, so a client that assumed JSON would throw a SyntaxError and
  // the screen would report a parse failure rather than the server being
  // down.
  try {
    const body: unknown = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "string"
    ) {
      return body.detail;
    }
  } catch {
    /* fall through to the generic message */
  }
  return `Request failed (${response.status})`;
}

export async function apiGet<T>(path: string, params?: QueryParams): Promise<T> {
  const response = await fetch(withParams(path, params), {
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(response.status, await detailOf(response));
  }
  // The one type assertion in the app, and the reason nothing else needs
  // one: `Response.json()` is `Promise<any>`, so untyped JSON becomes a
  // typed contract exactly here. Callers name `T` from `@/api/types`, and
  // `eslint.config.js` scopes the assertion exemption to this file so that
  // "the app has one cast" stays a fact you can check.
  return (await response.json()) as T;
}

/**
 * A render's PNG.
 *
 * Returned as a URL rather than fetched, because it is an `<img src>`: the
 * browser's own cache and decoding are better at images than anything this
 * layer could add.
 */
export function imageUrl(renderId: string, size: "full" | "thumb"): string {
  return `/api/renders/${encodeURIComponent(renderId)}/image?size=${size}`;
}
```

- [ ] **Step 5: Write the query hooks**

Create `web/src/api/queries.ts`:

```ts
/**
 * The query-key factory and the six read hooks, in one module so a key
 * cannot drift from the fetch that uses it.
 *
 * Nothing here polls. `useActiveRun` and `useRunEvents` — the two hooks that
 * carry live behaviour — are phase 6's, and an idle app on these screens
 * makes no requests after the ones its route needed.
 */
import { useQuery } from "@tanstack/react-query";

import { ApiError, apiGet } from "@/api/client";
import type {
  RankedTopic,
  RenderRecord,
  RunDetail,
  RunPage,
  TopicDetail,
  TopicIndex,
  TrendStatus,
} from "@/api/types";

export interface TopicIndexOptions {
  window?: number;
  status?: TrendStatus;
}

export const queryKeys = {
  runs: (limit?: number) => ["runs", { limit }],
  run: (runId: string) => ["runs", runId],
  ranking: (runId: string) => ["runs", runId, "topics"],
  topicDetail: (runId: string, topicId: string) => ["runs", runId, "topics", topicId],
  topicIndex: (options: TopicIndexOptions) => ["topics", options],
  render: (renderId: string) => ["renders", renderId],
};

/** The three rows the design's run strip shows, and the runs list's page. */
export const DEFAULT_RUN_LIMIT = 25;
/** "across the last 6 runs", per the Topics header. */
export const DEFAULT_WINDOW = 6;

export function useRuns(limit: number = DEFAULT_RUN_LIMIT) {
  return useQuery<RunPage, ApiError>({
    queryKey: queryKeys.runs(limit),
    queryFn: () => apiGet<RunPage>("/api/runs", { limit }),
  });
}

export function useRun(runId: string | undefined) {
  return useQuery<RunDetail, ApiError>({
    queryKey: queryKeys.run(runId ?? ""),
    queryFn: () => apiGet<RunDetail>(`/api/runs/${encodeURIComponent(runId ?? "")}`),
    enabled: runId !== undefined,
  });
}

export function useRanking(runId: string | undefined) {
  return useQuery<RankedTopic[], ApiError>({
    queryKey: queryKeys.ranking(runId ?? ""),
    queryFn: () =>
      apiGet<RankedTopic[]>(`/api/runs/${encodeURIComponent(runId ?? "")}/topics`),
    enabled: runId !== undefined,
  });
}

export function useTopicDetail(runId: string | undefined, topicId: string | undefined) {
  return useQuery<TopicDetail, ApiError>({
    queryKey: queryKeys.topicDetail(runId ?? "", topicId ?? ""),
    queryFn: () =>
      apiGet<TopicDetail>(
        `/api/runs/${encodeURIComponent(runId ?? "")}` +
          `/topics/${encodeURIComponent(topicId ?? "")}`,
      ),
    enabled: runId !== undefined && topicId !== undefined,
  });
}

export function useTopicIndex(options: TopicIndexOptions = {}) {
  const window = options.window ?? DEFAULT_WINDOW;
  return useQuery<TopicIndex, ApiError>({
    queryKey: queryKeys.topicIndex({ window, status: options.status }),
    queryFn: () =>
      apiGet<TopicIndex>("/api/topics", { window, status: options.status }),
  });
}

export function useRender(renderId: string | undefined) {
  return useQuery<RenderRecord, ApiError>({
    queryKey: queryKeys.render(renderId ?? ""),
    queryFn: () =>
      apiGet<RenderRecord>(`/api/renders/${encodeURIComponent(renderId ?? "")}`),
    enabled: renderId !== undefined,
  });
}
```

- [ ] **Step 6: Write the test harness**

Create `web/src/test/server.ts`:

```ts
import { setupServer } from "msw/node";

/**
 * No default handlers.
 *
 * Every test declares the responses its screen needs with `server.use`, so
 * a test that forgot one fails loudly on an unhandled request rather than
 * quietly passing against a fixture it did not choose.
 */
export const server = setupServer();
```

Replace `web/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";

import { afterAll, afterEach, beforeAll } from "vitest";

import { server } from "@/test/server";

// `error` rather than `warn`: an unhandled request means a screen asked for
// something the test did not describe, and the assertion that follows would
// fail for a reason that has nothing to do with what is being tested.
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
```

Create `web/src/test/factories.ts`:

```ts
/**
 * Typed fixtures — the frontend's `tests/run_factory.py`.
 *
 * Every factory returns a value the generated contract types accept in full,
 * so a response model that gains a required field breaks these rather than
 * the twenty tests that use them. Options are named for what a test wants to
 * vary, never for the wire field, so a rename on the wire touches this file
 * alone.
 */
import type {
  Dossier,
  IndexedTopic,
  RankedTopic,
  RenderRecord,
  RunConfig,
  RunDetail,
  RunError,
  RunPage,
  RunRecordRow,
  RunStatus,
  RunSummary,
  Stage,
  StageRecord,
  StageStatus,
  TopicDetail,
  TopicIndex,
  TopicRow,
  TrendStatus,
} from "@/api/types";

/** Frozen, like `run_factory.FIXED_TIME`: relative dates make flaky tests. */
export const FIXED_START = "2026-08-29T09:00:00Z";
export const FIXED_END = "2026-08-29T09:06:41Z";

export function makeRunConfig(overrides: Partial<RunConfig> = {}): RunConfig {
  return {
    sources: ["bluesky"],
    trend_limit: 25,
    posts_per_trend: 30,
    top_count: 5,
    meme_potential_weight: 0.3,
    phrase_min_authors: 3,
    distil_char_budget: 6000,
    distil_concurrency: 4,
    llm_provider: "anthropic",
    llm_model: "claude-opus-5",
    template_ids: null,
    ...overrides,
  };
}

export function makeRunRecord(
  options: {
    runId?: string;
    status?: RunStatus;
    finishedAt?: string | null;
    error?: RunError | null;
    trendsFound?: number | null;
    topicsKept?: number | null;
    phrasesFound?: number | null;
    config?: Partial<RunConfig>;
  } = {},
): RunRecordRow {
  return {
    run_id: options.runId ?? "20260829T090000Z",
    status: options.status ?? "ok",
    started_at: FIXED_START,
    finished_at: options.finishedAt === undefined ? FIXED_END : options.finishedAt,
    config: makeRunConfig(options.config),
    error: options.error ?? null,
    item_count: 750,
    trends_found: options.trendsFound === undefined ? 25 : options.trendsFound,
    topics_kept: options.topicsKept === undefined ? 5 : options.topicsKept,
    phrases_found: options.phrasesFound === undefined ? 18 : options.phrasesFound,
  };
}

export function makeRunSummary(
  options: {
    runId?: string;
    status?: RunStatus;
    error?: RunError | null;
    labels?: string[];
    renderIds?: string[];
    finishedAt?: string | null;
    trendsFound?: number | null;
    topicsKept?: number | null;
    config?: Partial<RunConfig>;
  } = {},
): RunSummary {
  return {
    run: makeRunRecord(options),
    topic_labels: options.labels ?? ["Airport cat", "Stadium rat"],
    render_ids: options.renderIds ?? ["render-1", "render-2"],
  };
}

export function makeRunPage(
  runs: RunSummary[] = [makeRunSummary()],
  nextCursor: string | null = null,
): RunPage {
  return { runs, next_cursor: nextCursor };
}

export function makeStageRecord(
  options: {
    stage?: Stage;
    status?: StageStatus;
    startedAt?: string | null;
    finishedAt?: string | null;
    payloadBytes?: number | null;
    summary?: string;
  } = {},
): StageRecord {
  return {
    stage: options.stage ?? "ingest",
    status: options.status ?? "ok",
    started_at: options.startedAt === undefined ? FIXED_START : options.startedAt,
    finished_at:
      options.finishedAt === undefined ? "2026-08-29T09:01:12Z" : options.finishedAt,
    payload_bytes:
      options.payloadBytes === undefined ? 1_363_148 : options.payloadBytes,
    summary: options.summary ?? "25 trends, 750 posts",
  };
}

export function makeRunDetail(
  options: {
    runId?: string;
    status?: RunStatus;
    error?: RunError | null;
    stages?: StageRecord[];
    resumeStage?: Stage | null;
    config?: Partial<RunConfig>;
  } = {},
): RunDetail {
  return {
    run: makeRunRecord(options),
    stages: options.stages ?? [
      makeStageRecord({ stage: "ingest" }),
      makeStageRecord({ stage: "analyse", summary: "25 distilled" }),
      makeStageRecord({ stage: "evaluate", summary: "5 kept of 25" }),
      makeStageRecord({ stage: "generate", summary: "5 of 5 rendered" }),
    ],
    resume_stage: options.resumeStage === undefined ? "generate" : options.resumeStage,
  };
}

export function makeTopicRow(
  options: {
    runId?: string;
    topicId?: string;
    label?: string;
    trendStatus?: TrendStatus;
    sentiment?: string | null;
    register?: string | null;
    memePotential?: number | null;
    trendScore?: number;
    finalScore?: number;
    finalRank?: number;
    postCount?: number;
    topPhrase?: string | null;
    topPhraseAuthors?: number | null;
  } = {},
): TopicRow {
  const label = options.label ?? "Airport cat";
  return {
    run_id: options.runId ?? "20260829T090000Z",
    topic_id: options.topicId ?? "topic-1",
    label,
    label_slug: label.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
    trend_status: options.trendStatus ?? "trending",
    event_sentiment: options.sentiment === undefined ? "funny" : options.sentiment,
    conversation_register: options.register === undefined ? "riffing" : options.register,
    meme_potential: options.memePotential === undefined ? 0.86 : options.memePotential,
    trend_score: options.trendScore ?? 0.91,
    final_score: options.finalScore ?? 0.895,
    final_rank: options.finalRank ?? 1,
    post_count: options.postCount ?? 412,
    top_phrase: options.topPhrase === undefined ? "absolute unit" : options.topPhrase,
    top_phrase_authors:
      options.topPhraseAuthors === undefined ? 31 : options.topPhraseAuthors,
  };
}

export function makeRankedTopic(
  options: Parameters<typeof makeTopicRow>[0] & {
    renderCount?: number;
    aboveCut?: boolean;
  } = {},
): RankedTopic {
  return {
    topic: makeTopicRow(options),
    render_count: options.renderCount ?? 1,
    above_cut: options.aboveCut ?? true,
  };
}

export function makeDossier(overrides: Partial<Dossier> = {}): Dossier {
  return {
    what_happened: "A cat got loose in an airport terminal and stopped boarding.",
    key_entities: ["the cat", "the terminal", "ground staff"],
    conversation_summary: "Everyone is writing the cat's incident report for it.",
    conversation_register: "riffing",
    secondary_registers: ["delight"],
    event_sentiment: "funny",
    meme_potential: 0.86,
    recurring_phrases: [
      { text: "absolute unit", occurrences: 48, distinct_authors: 31 },
      { text: "ground control", occurrences: 22, distinct_authors: 14 },
    ],
    ...overrides,
  };
}

export function makeRenderRecord(
  options: {
    id?: string;
    runId?: string;
    topicId?: string;
    templateId?: string;
    rationale?: string | null;
    status?: RenderRecord["status"];
    error?: string | null;
    captionSlots?: Record<string, string>;
    createdAt?: string;
  } = {},
): RenderRecord {
  const rationale = options.rationale;
  return {
    id: options.id ?? "render-1",
    run_id: options.runId ?? "20260829T090000Z",
    topic_id: options.topicId ?? "topic-1",
    template_id: options.templateId ?? "drake",
    caption_slots: options.captionSlots ?? {
      rejected: "Filing an incident report",
      preferred: "Becoming the incident",
    },
    origin:
      rationale === null
        ? { provenance: "manual" }
        : { provenance: "auto", rationale: rationale ?? "Two panels, one reversal." },
    status: options.status ?? "ready",
    error: options.error ?? null,
    created_at: options.createdAt ?? FIXED_END,
  };
}

export function makeTopicDetail(
  options: Parameters<typeof makeTopicRow>[0] & {
    dossier?: Dossier | null;
    scoreComponents?: Record<string, number>;
    replies?: TopicDetail["replies"];
    renders?: RenderRecord[];
    runCount?: number;
    firstSeenRunId?: string | null;
  } = {},
): TopicDetail {
  return {
    topic: makeTopicRow(options),
    dossier: options.dossier === undefined ? makeDossier() : options.dossier,
    score_components: options.scoreComponents ?? { bluesky: 0.91, corroboration: 1.0 },
    replies: options.replies ?? [
      { text: "ground control to major tom", like_count: 1412, created_at: FIXED_END },
      { text: "he has a boarding pass and everything", like_count: 903, created_at: FIXED_END },
    ],
    renders: options.renders ?? [makeRenderRecord()],
    recurrence: {
      run_count: options.runCount ?? 3,
      first_seen_run_id:
        options.firstSeenRunId === undefined ? "20260826T090000Z" : options.firstSeenRunId,
    },
  };
}

export function makeIndexedTopic(
  options: Parameters<typeof makeTopicRow>[0] & {
    runCount?: number;
    renderCount?: number;
  } = {},
): IndexedTopic {
  return {
    topic: makeTopicRow(options),
    run_count: options.runCount ?? 3,
    render_count: options.renderCount ?? 2,
  };
}

export function makeTopicIndex(
  options: {
    topics?: IndexedTopic[];
    statusTotals?: Record<string, number>;
    sentimentTotals?: Record<string, number>;
    previousSentimentTotals?: Record<string, number>;
  } = {},
): TopicIndex {
  return {
    topics: options.topics ?? [makeIndexedTopic()],
    status_totals: options.statusTotals ?? {
      trending: 9,
      saturating: 6,
      cooling: 4,
      stale: 31,
    },
    sentiment_totals: options.sentimentTotals ?? {
      funny: 9,
      cute: 5,
      schadenfreude: 3,
      mundane: 2,
    },
    previous_sentiment_totals: options.previousSentimentTotals ?? {
      funny: 7,
      cute: 6,
      schadenfreude: 3,
      mundane: 3,
    },
  };
}
```

Create `web/src/test/render.tsx`:

```tsx
/**
 * The wrapper every screen test renders through.
 *
 * `retry: false` and `gcTime: 0` because a test that retries a deliberate
 * 404 three times spends seconds proving nothing, and a cache that outlives
 * a test leaks one test's fixtures into the next.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

function newClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
}

interface Options {
  /** The URL to start at. Defaults to "/". */
  route?: string;
  /** The route pattern `ui` is mounted at, when it reads path params. */
  path?: string;
}

export function renderWithProviders(ui: ReactElement, options: Options = {}) {
  const { route = "/", path } = options;
  return render(
    <QueryClientProvider client={newClient()}>
      <MemoryRouter initialEntries={[route]}>
        {path === undefined ? ui : <Routes>{<Route path={path} element={ui} />}</Routes>}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The `wrapper` form, for `renderHook`. */
renderWithProviders.Wrapper = function Wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={newClient()}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
};
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `npm --prefix web test`

Expected: PASS — `format.test.ts`, `client.test.ts`, `queries.test.tsx` and `App.test.tsx` all green.

- [ ] **Step 8: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest && npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

- [ ] **Step 9: Commit**

```bash
git add web/src/api web/src/format.ts web/src/format.test.ts web/src/test
git commit -m "Add the typed API client, the read hooks and the MSW test harness"
```

---

### Task 5: the shared primitives

Six components and their stylesheets. They exist as primitives because each appears on three or more screens; a seventh that appeared once would belong to its screen.

**Files:**
- Create: `web/src/components/Chip.tsx` + `Chip.module.css`, `StatusPill.tsx` + `.module.css`, `SectionLabel.tsx` + `.module.css`, `StageBar.tsx` + `.module.css`, `MemeTile.tsx` + `.module.css`, `EmptyState.tsx` + `.module.css`, `MetaLine.tsx` + `.module.css`, `QueryBoundary.tsx` + `.module.css`
- Test: `web/src/components/StatusPill.test.tsx`, `MemeTile.test.tsx`, `EmptyState.test.tsx`, `StageBar.test.tsx`, `QueryBoundary.test.tsx`, `web/src/styles/no-raw-colours.test.ts`

**Interfaces:**
- Consumes: `@/api/types`, `@/api/client`'s `imageUrl`, `@/format`, `@/styles/tokens.css`.
- Produces:
  - `<Chip tone="accent" | "muted" | "contrast" | "inverted">{children}</Chip>`
  - `<StatusPill status={RunStatus} count={number | undefined} />`
  - `<SectionLabel hint={ReactNode}>{children}</SectionLabel>`
  - `<StageBar fill={number} tone="accent" | "muted" />` — `fill` is 0–1.
  - `<MemeTile renderId={string} size={34 | 42 | 96} to={string | undefined} templateId={string | undefined} />`
  - `<EmptyState headline={string} body={string} action={ReactNode | undefined} />`
  - `<MetaLine>{children}</MetaLine>`
  - `<QueryBoundary query={UseQueryResult<T, ApiError>} missing={string}>{(data) => ReactNode}</QueryBoundary>`

- [ ] **Step 1: Write the failing tests**

Create `web/src/components/StatusPill.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RunStatus } from "@/api/types";
import { StatusPill } from "@/components/StatusPill";
import { renderWithProviders } from "@/test/render";

describe("StatusPill", () => {
  it("renders a completed run with its render count", () => {
    renderWithProviders(<StatusPill status="ok" count={5} />);
    expect(screen.getByText("OK · 5")).toBeInTheDocument();
  });

  it("renders a completed run that rendered nothing without a dangling separator", () => {
    // A run whose every brief failed still completed. "OK · " with nothing
    // after it reads as a truncation bug.
    renderWithProviders(<StatusPill status="ok" count={0} />);
    expect(screen.getByText("OK")).toBeInTheDocument();
  });

  it("renders a failure without a count", () => {
    // The count is meaningless on a run that never reached generate, and
    // the design's failed pill carries the word alone.
    renderWithProviders(<StatusPill status="failed" count={0} />);
    expect(screen.getByText("FAILED")).toBeInTheDocument();
  });

  // RunStatus is a five-member literal. A status with no label renders an
  // empty pill, which is the failure mode this catches. Typed rather than
  // `as const`, which the lint rules ban.
  const LABELS: [RunStatus, string][] = [
    ["running", "RUNNING"],
    ["ok", "OK"],
    ["failed", "FAILED"],
    ["aborted", "ABORTED"],
    ["interrupted", "INTERRUPTED"],
  ];

  it.each(LABELS)("labels the %s status as %s", (status, label) => {
    renderWithProviders(<StatusPill status={status} />);
    expect(screen.getByText(new RegExp(`^${label}`))).toBeInTheDocument();
  });
});
```

Create `web/src/components/MemeTile.test.tsx`:

```tsx
import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MemeTile } from "@/components/MemeTile";
import { renderWithProviders } from "@/test/render";

describe("MemeTile", () => {
  it("points at the render's own image endpoint", () => {
    renderWithProviders(<MemeTile renderId="render-1" size={42} />);
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "/api/renders/render-1/image?size=thumb",
    );
  });

  it("asks for the full-size PNG at the largest size", () => {
    // 96px is the thumbnail's own width, so anything larger would be a
    // scaled-up 96px image.
    renderWithProviders(<MemeTile renderId="render-1" size={96} />);
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "/api/renders/render-1/image?size=full",
    );
  });

  it("links to the full-size view when given a destination", () => {
    renderWithProviders(
      <MemeTile renderId="render-1" size={42} to="/runs/r1/renders/render-1" />,
    );
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/runs/r1/renders/render-1",
    );
  });

  it("renders no link when it has no destination", () => {
    // A tile inside a runs-list row is already inside that row's own link,
    // and nesting one anchor in another is invalid HTML the browser
    // silently reshapes. So the tile must not invent a destination it was
    // not given.
    renderWithProviders(<MemeTile renderId="render-1" size={42} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders a failed tile when the PNG is not on disk", () => {
    // The database is authoritative for whether a render exists, so a row
    // whose image 404s is a failed render, not a crash. This is also how a
    // partially failed run shows itself on the runs list.
    renderWithProviders(<MemeTile renderId="render-1" size={42} />);

    fireEvent.error(screen.getByRole("img"));

    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("stops being a link once its image has failed", () => {
    // Nothing to open at full size, so the affordance goes with it.
    renderWithProviders(
      <MemeTile renderId="render-1" size={42} to="/runs/r1/renders/render-1" />,
    );

    fireEvent.error(screen.getByRole("img"));

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("names the template in its alt text", () => {
    // The only description of a meme this app has. "meme" alone would tell
    // a screen reader nothing the surrounding row does not already say.
    renderWithProviders(
      <MemeTile renderId="render-1" size={42} templateId="drake" />,
    );
    expect(screen.getByAltText("drake meme")).toBeInTheDocument();
  });
});
```

Create `web/src/components/EmptyState.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyState } from "@/components/EmptyState";
import { renderWithProviders } from "@/test/render";

describe("EmptyState", () => {
  it("renders the headline and body", () => {
    renderWithProviders(
      <EmptyState
        headline="Nothing has run yet"
        body="A run reads Bluesky, works out what is trending, and generates memes about it. The first one takes a few minutes."
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Nothing has run yet" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/reads Bluesky/)).toBeInTheDocument();
  });

  it("renders no action when it was given none", () => {
    // Phase 5 has no New run screen to send anyone to, so every caller in
    // this phase omits it. A disabled button would be worse than no button.
    renderWithProviders(<EmptyState headline="Nothing has run yet" body="…" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders the action it was given, which is what phase 6 fills", () => {
    renderWithProviders(
      <EmptyState headline="h" body="b" action={<button>New run</button>} />,
    );
    expect(screen.getByRole("button", { name: "New run" })).toBeInTheDocument();
  });
});
```

`SectionLabel` gets no test file. It renders a string and, when given one, a second string; it validates nothing, derives nothing and causes no side effect, which is the rubric's line for when trivial rendering earns a test. Its hint is exercised through the screens that pass one — the ranking's `top 5 of 25`, the render grid's `2 from …829T090000Z` — and both are asserted there, on the value that made the hint worth rendering.

`EmptyState` is the near neighbour that *does* get the absent-branch test, and the difference is worth naming: its `action` slot renders a wrapper with its own 18px margin, so an unconditional render leaves a visible gap under every empty state in the app, and phase 6 fills that slot for real. `SectionLabel`'s hint has neither property.

Create `web/src/styles/no-raw-colours.test.ts`:

```ts
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = fileURLToPath(new URL("..", import.meta.url));

function stylesheets(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return stylesheets(path);
    return entry.name.endsWith(".module.css") ? [path] : [];
  });
}

/**
 * The one invariant over the stylesheets that a person cannot hold.
 *
 * Not a check that `tokens.css` says what it says — that would grep its own
 * source and prove only that the source is the source. This is a cross-file
 * rule with a real failure mode: a component that hardcodes `#ffd93d`
 * instead of `var(--accent)` looks correct on the day it is written and
 * stops tracking the palette forever after, and nobody catches it by eye
 * across twenty stylesheets.
 *
 * `tokens.css` itself is excluded because it is where the colours are
 * defined; it is not a `.module.css`, so the walk never reaches it.
 */
describe("component stylesheets", () => {
  it("name no colour of their own", () => {
    const offenders = stylesheets(SRC)
      .map((path) => ({ path, text: readFileSync(path, "utf8") }))
      .filter(({ text }) => /#[0-9a-f]{3,8}\b/i.test(text) || /\brgba?\(/i.test(text))
      // StageBar's gradient carries its own trailing stop, which the
      // handoff writes inline as part of the gradient rather than as a
      // token. It is the one documented exception.
      .filter(({ path }) => !path.endsWith("StageBar.module.css"))
      .map(({ path }) => path.slice(SRC.length));

    expect(offenders).toEqual([]);
  });
});
```

At this task it passes over the eight stylesheets Task 5 writes; it gains teeth with every screen after. It is placed here rather than in Task 3 because Task 3 has nothing for it to scan.

Create `web/src/components/StageBar.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StageBar } from "@/components/StageBar";
import { renderWithProviders } from "@/test/render";

describe("StageBar", () => {
  it("reports its fill to assistive technology as a progress bar", () => {
    renderWithProviders(<StageBar fill={0.68} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "68");
  });

  it("clamps a fill outside 0-1 rather than drawing past its track", () => {
    // Phase 6 drives this from `17 / 25` counters, and a stage that
    // overshoots its estimate would otherwise paint outside the card.
    const { rerender } = renderWithProviders(<StageBar fill={1.4} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");

    rerender(<StageBar fill={-2} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });
});
```

Create `web/src/components/QueryBoundary.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { useRun } from "@/api/queries";
import { QueryBoundary } from "@/components/QueryBoundary";
import { makeRunDetail } from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

function Subject({ runId }: { runId: string }) {
  return (
    <QueryBoundary query={useRun(runId)} missing="No such run.">
      {(detail) => <p>{detail.run.run_id}</p>}
    </QueryBoundary>
  );
}

describe("QueryBoundary", () => {
  it("renders its children once the data arrives", async () => {
    server.use(http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())));

    renderWithProviders(<Subject runId="20260829T090000Z" />);

    expect(await screen.findByText("20260829T090000Z")).toBeInTheDocument();
  });

  it("says what is missing on a 404 rather than showing a generic failure", async () => {
    // A mistyped run id and a server that is down are different problems,
    // and the fix for each is different too.
    server.use(
      http.get("/api/runs/:runId", () =>
        HttpResponse.json({ detail: "No such run: nope" }, { status: 404 }),
      ),
    );

    renderWithProviders(<Subject runId="nope" />);

    expect(await screen.findByText("No such run.")).toBeInTheDocument();
  });

  it("surfaces the server's own detail on any other failure", async () => {
    server.use(
      http.get("/api/runs/:runId", () =>
        HttpResponse.json({ detail: "database is locked" }, { status: 500 }),
      ),
    );

    renderWithProviders(<Subject runId="r1" />);

    expect(await screen.findByText(/database is locked/)).toBeInTheDocument();
  });

  it("says it is loading while the request is in flight", async () => {
    server.use(http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())));

    renderWithProviders(<Subject runId="20260829T090000Z" />);

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText("Loading…")).not.toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test`

Expected: FAIL — four component test files, each on an unresolved import from `@/components/…`. `no-raw-colours.test.ts` passes from the start: it walks a directory that holds no `.module.css` yet, so it has nothing to object to, and it is written now so that the first stylesheet in Step 3 is the first thing it checks.

- [ ] **Step 3: Write `Chip`, `SectionLabel` and `MetaLine`**

Create `web/src/components/Chip.tsx`:

```tsx
import type { ReactNode } from "react";

import styles from "./Chip.module.css";

/**
 * The four chip treatments the handoff uses.
 *
 * `inverted` is the hero card's: on an accent fill the palette inverts, so a
 * chip there is a dark fill with accent text rather than the other way
 * round.
 */
export type ChipTone = "accent" | "muted" | "contrast" | "inverted";

export function Chip({
  tone = "muted",
  children,
}: {
  tone?: ChipTone;
  children: ReactNode;
}) {
  return <span className={`${styles.chip} ${styles[tone]}`}>{children}</span>;
}
```

Create `web/src/components/Chip.module.css`:

```css
.chip {
  display: inline-flex;
  align-items: center;
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: 0.04em;
  padding: 5px 8px;
  border-radius: var(--radius-pill);
  white-space: nowrap;
}

.accent {
  background: var(--accent-tint);
  color: var(--accent);
}

.muted {
  background: var(--chip-fill);
  color: var(--text-70);
}

.contrast {
  background: var(--contrast-fill);
  color: var(--contrast-light);
}

.inverted {
  background: var(--on-accent);
  color: var(--accent);
}
```

Create `web/src/components/SectionLabel.tsx`:

```tsx
import type { ReactNode } from "react";

import styles from "./SectionLabel.module.css";

/**
 * The mono 700/9.5/.12em uppercase label above every block, with the
 * right-aligned hint several of them carry ("optional", "exactly one",
 * "2 rendered · 3 to go").
 */
export function SectionLabel({
  children,
  hint,
}: {
  children: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className={styles.row}>
      <span className={styles.label}>{children}</span>
      {hint !== undefined && <span className={styles.hint}>{hint}</span>}
    </div>
  );
}
```

Create `web/src/components/SectionLabel.module.css`:

```css
.row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--gap-section);
  margin-bottom: 10px;
}

.label {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-40);
}

.hint {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 500;
  color: var(--text-30);
}
```

Create `web/src/components/MetaLine.tsx`:

```tsx
import type { ReactNode } from "react";

import styles from "./MetaLine.module.css";

/** The mono 400/10.5 line under a page title, a run id, or a card header. */
export function MetaLine({ children }: { children: ReactNode }) {
  return <p className={styles.meta}>{children}</p>;
}
```

Create `web/src/components/MetaLine.module.css`:

```css
.meta {
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 400;
  line-height: 1.55;
  color: var(--text-35);
}
```

- [ ] **Step 4: Write `StatusPill` and `StageBar`**

Create `web/src/components/StatusPill.tsx`:

```tsx
import type { RunStatus } from "@/api/types";

import styles from "./StatusPill.module.css";

const LABELS: Readonly<Record<RunStatus, string>> = {
  running: "RUNNING",
  ok: "OK",
  failed: "FAILED",
  aborted: "ABORTED",
  interrupted: "INTERRUPTED",
};

/**
 * `OK · 5` in accent tint, `FAILED` in contrast.
 *
 * The count is only drawn beside a completed run, and only when there is
 * one: a failure that never reached generate has no meaningful number, and
 * `OK · ` with nothing after it reads as a truncation bug.
 *
 * The handoff's partial form, `OK · 3 of 5`, is deliberately absent — see
 * "Decisions this phase is required to make", 7. The count here is how many
 * render rows the run has, from `RunSummary.render_ids`, which does not
 * distinguish ready from failed.
 */
export function StatusPill({
  status,
  count,
}: {
  status: RunStatus;
  count?: number;
}) {
  const tone = status === "ok" ? styles.ok : status === "running" ? styles.running : styles.bad;
  const suffix = status === "ok" && count !== undefined && count > 0 ? ` · ${count}` : "";
  return <span className={`${styles.pill} ${tone}`}>{`${LABELS[status]}${suffix}`}</span>;
}
```

Create `web/src/components/StatusPill.module.css`:

```css
.pill {
  display: inline-flex;
  align-items: center;
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: 0.08em;
  padding: 6px 10px;
  border-radius: var(--radius-pill);
  white-space: nowrap;
}

.ok {
  background: var(--accent-tint);
  color: var(--accent);
}

.running {
  background: var(--accent);
  color: var(--on-accent);
}

/* failed, aborted and interrupted share one treatment: all three are a run
   that did not produce what it set out to, and the design draws one. */
.bad {
  background: var(--contrast-fill);
  color: var(--contrast-light);
}
```

Create `web/src/components/StageBar.tsx`:

```tsx
import styles from "./StageBar.module.css";

/**
 * The 3-4px bar across a stage card and the four-segment run progress bar.
 *
 * A partial fill is a hard-edged gradient rather than a nested element,
 * because that is what the handoff specifies:
 * `linear-gradient(90deg, accent 68%, rgba(255,255,255,.12) 68%)`.
 *
 * `fill` is 0-1 and is clamped. Phase 6 drives it from stage-relative
 * counters (`17 / 25`), and a stage that overshoots its own estimate must
 * not paint outside the card.
 */
export function StageBar({
  fill,
  tone = "accent",
}: {
  fill: number;
  tone?: "accent" | "muted";
}) {
  const percent = Math.round(Math.min(1, Math.max(0, fill)) * 100);
  return (
    <div
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      className={`${styles.bar} ${tone === "muted" ? styles.muted : styles.accent}`}
      style={{ "--fill": `${percent}%` }}
    />
  );
}
```

`style` carries a custom property, which React types as `CSSProperties`, and `CSSProperties` does not admit `--fill`. `as` is banned by the lint rules, so the property is declared instead. Create `web/src/css-properties.d.ts` — one file for all three of them, so they are declared once rather than in each component that sets one:

```ts
import "react";

declare module "react" {
  interface CSSProperties {
    /** StageBar's hard-edged gradient stop. */
    "--fill"?: string;
    /** MemeTile's square edge length. */
    "--tile"?: string;
    /** MoodBar's segment share. */
    "--share"?: string;
  }
}
```

Create `web/src/components/StageBar.module.css`:

```css
.bar {
  height: 3px;
  border-radius: 2px;
  width: 100%;
}

.accent {
  background: linear-gradient(
    90deg,
    var(--accent) var(--fill, 100%),
    rgba(255, 255, 255, 0.12) var(--fill, 100%)
  );
}

.muted {
  background: var(--border);
}
```

The one `rgba()` outside `tokens.css` in the whole app is the gradient's own trailing colour, which the handoff writes inline as part of the gradient rather than as a token. `no-raw-colours.test.ts` excludes this file by name for exactly that reason — the exception is written down in the test rather than left to whoever next reads the stylesheet.

- [ ] **Step 5: Write `MemeTile`**

Create `web/src/components/MemeTile.tsx`:

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";

import { imageUrl } from "@/api/client";

import styles from "./MemeTile.module.css";

/**
 * One rendered meme, at one of the three sizes the design draws: 34px in a
 * runs-list row, 42px in a ranking row, 96px in a topic-detail grid.
 *
 * The database is authoritative for whether a render exists, so a row whose
 * PNG is missing is a failed tile rather than a broken image or a crash.
 * That state is reached through the image's own `onError`, which is also how
 * a partially failed run shows itself on the runs list — see "Decisions this
 * phase is required to make", 7.
 *
 * Phase 7 adds the other two states, `confirming` and `generating`.
 */
export function MemeTile({
  renderId,
  size,
  to,
  templateId,
}: {
  renderId: string;
  size: 34 | 42 | 96;
  to?: string;
  templateId?: string;
}) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <span
        className={styles.failed}
        style={{ "--tile": `${size}px` }}
        title={`Render ${renderId} has no image on disk`}
      >
        failed
      </span>
    );
  }

  const image = (
    <img
      className={styles.image}
      src={imageUrl(renderId, size >= 96 ? "full" : "thumb")}
      alt={templateId === undefined ? "meme" : `${templateId} meme`}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );

  return (
    <span className={styles.tile} style={{ "--tile": `${size}px` }}>
      {to === undefined ? image : <Link to={to}>{image}</Link>}
    </span>
  );
}
```

`--tile` is already declared in `web/src/css-properties.d.ts` from Step 4, so this needs no declaration of its own.

Create `web/src/components/MemeTile.module.css`:

```css
.tile,
.failed {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--tile);
  height: var(--tile);
  border-radius: var(--radius-sm);
  overflow: hidden;
  flex: none;
}

.tile {
  background: var(--stripe);
  border: 1px solid var(--border);
}

.image {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.failed {
  border: 1px dashed var(--contrast-border);
  color: var(--contrast-light);
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 500;
}
```

- [ ] **Step 6: Write `EmptyState` and `QueryBoundary`**

Create `web/src/components/EmptyState.tsx`:

```tsx
import type { ReactNode } from "react";

import styles from "./EmptyState.module.css";

/**
 * The centred block for an emptiness that is the app's condition rather than
 * the user's own doing. The lighter treatment — a filter that matched
 * nothing — is a single line, not a card, and belongs to the screen that
 * owns the filter.
 *
 * `action` is optional and no phase-5 caller passes it: the only sensible
 * next step is "New run", and there is no New run screen until phase 6.
 */
export function EmptyState({
  headline,
  body,
  action,
}: {
  headline: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className={styles.block}>
      <h2 className={styles.headline}>{headline}</h2>
      <p className={styles.body}>{body}</p>
      {action !== undefined && <div className={styles.action}>{action}</div>}
    </div>
  );
}
```

Create `web/src/components/EmptyState.module.css`:

```css
.block {
  margin: 48px auto;
  max-width: 420px;
  padding: 40px;
  text-align: center;
  background: var(--surface);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-card);
}

.headline {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
}

.body {
  margin-top: 8px;
  font-size: 12.5px;
  font-weight: 400;
  line-height: 1.5;
  color: var(--text-70);
}

.action {
  margin-top: 18px;
}
```

Create `web/src/components/QueryBoundary.tsx`:

```tsx
import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";

import type { ApiError } from "@/api/client";

import styles from "./QueryBoundary.module.css";

/**
 * Loading, missing and broken — the three states every screen in this phase
 * shares, in one place.
 *
 * A 404 is separated from every other failure because they are different
 * problems with different fixes: a mistyped run id is the user's, and a 500
 * is the server's. Collapsing them into "something went wrong" would send
 * someone looking in the wrong place.
 *
 * This is deliberately not an error boundary. TanStack Query already holds
 * the failure as data; throwing it so a boundary could catch it would lose
 * the status code that makes the distinction above possible.
 */
export function QueryBoundary<T>({
  query,
  missing,
  children,
}: {
  query: UseQueryResult<T, ApiError>;
  missing: string;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) {
    return <p className={styles.state}>Loading…</p>;
  }
  if (query.isError) {
    return (
      <p className={styles.error}>
        {query.error.status === 404 ? missing : query.error.detail}
      </p>
    );
  }
  return <>{children(query.data)}</>;
}
```

Create `web/src/components/QueryBoundary.module.css`:

```css
.state,
.error {
  padding: 24px 0;
  text-align: center;
  font-family: var(--font-mono);
  font-size: 10.5px;
}

.state {
  color: var(--text-35);
}

.error {
  color: var(--contrast-light);
}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `npm --prefix web test`

Expected: every component test green.

- [ ] **Step 8: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest && npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

- [ ] **Step 9: Commit**

```bash
git add web/src/components web/src/css-properties.d.ts web/src/styles/no-raw-colours.test.ts
git commit -m "Add the shared primitives the six screens are built from"
```

---

### Task 6: the router, the layout and the sidebar

**Files:**
- Create: `web/src/app/providers.tsx`, `web/src/app/AppLayout.tsx` + `AppLayout.module.css`, `web/src/app/Sidebar.tsx` + `Sidebar.module.css`, `web/src/app/routes.tsx`
- Test: `web/src/app/routes.test.tsx`
- Modify: `web/src/App.tsx`, `web/src/App.test.tsx`, `web/src/main.tsx`

**Interfaces:**
- Consumes: `@/components/*`.
- Produces: `<App />` mounting the full route table; `<AppLayout />` as the layout route; the route paths `/`, `/runs`, `/runs/:runId`, `/runs/:runId/renders/:renderId`, `/topics/:runId/:topicId`. Tasks 7–11 replace each route's placeholder element with a real page, and **each of those tasks owns exactly one replacement**.

- [ ] **Step 1: Write the failing test**

Create `web/src/app/routes.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AppLayout } from "@/app/AppLayout";
import { renderWithProviders } from "@/test/render";

describe("Sidebar", () => {
  it("names the app and its two destinations, in the handoff's order", () => {
    renderWithProviders(<AppLayout />, { route: "/" });

    expect(screen.getByText("Zeitgeist")).toBeInTheDocument();
    const nav = screen.getAllByRole("link").map((link) => link.textContent);
    expect(nav).toEqual(["Topics", "Runs"]);
  });

  it("marks the destination matching the current route as current", () => {
    renderWithProviders(<AppLayout />, { route: "/runs" });

    expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Topics" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("does not mark Topics current on a run's own page", () => {
    // "/" would match every route under a prefix match, so Topics needs an
    // exact one. Without it both nav items highlight on /runs.
    renderWithProviders(<AppLayout />, { route: "/runs/20260829T090000Z" });

    expect(screen.getByRole("link", { name: "Topics" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("keeps Runs current on a run's detail page", () => {
    renderWithProviders(<AppLayout />, { route: "/runs/20260829T090000Z" });

    expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("navigates without a page load", async () => {
    renderWithProviders(<AppLayout />, { route: "/" });

    await userEvent.click(screen.getByRole("link", { name: "Runs" }));

    expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm --prefix web test -- routes`

Expected: FAIL — unresolved import for `@/app/AppLayout`.

- [ ] **Step 3: Write the sidebar and the layout**

Create `web/src/app/Sidebar.tsx`:

```tsx
import { NavLink } from "react-router-dom";

import styles from "./Sidebar.module.css";

/**
 * 180px, one step darker than the page, two destinations.
 *
 * Topics and Runs, in that order, per the handoff. The spec merges the
 * landing dashboard and the topics index into `/`, so those two are the
 * whole nav in this phase; phase 6 adds Settings beneath them, and the
 * in-flight card that pins to the bottom via `margin-top: auto`.
 */
export function Sidebar() {
  return (
    <nav className={styles.rail}>
      <span className={styles.wordmark}>Zeitgeist</span>
      <ul className={styles.nav}>
        <li>
          {/* `end` because "/" prefix-matches every route in the app. */}
          <NavLink to="/" end className={navClass}>
            Topics
          </NavLink>
        </li>
        <li>
          <NavLink to="/runs" className={navClass}>
            Runs
          </NavLink>
        </li>
      </ul>
    </nav>
  );
}

function navClass({ isActive }: { isActive: boolean }): string | undefined {
  return isActive ? `${styles.item} ${styles.active}` : styles.item;
}
```

`NavLink` sets `aria-current="page"` itself when active, which is what the tests assert on and what a screen reader needs; the class is the visual half of the same fact.

Create `web/src/app/Sidebar.module.css`:

```css
.rail {
  width: var(--sidebar-width);
  flex: none;
  display: flex;
  flex-direction: column;
  padding: var(--gap-page) 12px;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
}

.wordmark {
  padding: 0 8px;
  font-size: 18px;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--text);
}

.nav {
  margin-top: 26px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.item {
  display: block;
  padding: 10px 11px;
  border-radius: var(--radius-tile);
  font-size: 12.5px;
  font-weight: 500;
  line-height: 1;
  color: var(--text-55);
  transition: background var(--transition), color var(--transition);
}

.item:hover {
  color: var(--text);
}

.active,
.active:hover {
  background: var(--accent);
  color: var(--on-accent);
  font-weight: 700;
}
```

Create `web/src/app/AppLayout.tsx`:

```tsx
import { Outlet } from "react-router-dom";

import { Sidebar } from "@/app/Sidebar";

import styles from "./AppLayout.module.css";

/**
 * The rail plus the content column.
 *
 * `app-width` (1180px) is the shell's own cap, per the handoff's geometry
 * table; the detail screens narrow themselves to `content-width` (1000px)
 * inside it rather than the shell knowing which routes are detail screens.
 */
export function AppLayout() {
  return (
    <div className={styles.shell}>
      <Sidebar />
      <main className={styles.content}>
        <Outlet />
      </main>
    </div>
  );
}
```

Create `web/src/app/AppLayout.module.css`:

```css
.shell {
  display: flex;
  min-height: 100vh;
  max-width: var(--app-width);
  margin: 0 auto;
}

.content {
  flex: 1;
  min-width: 0;
  padding: var(--gap-page) 22px;
}
```

`min-width: 0` is load-bearing: without it a flex child refuses to shrink below its content, and the runs list's ellipsised title column would push the rail off screen instead of truncating.

- [ ] **Step 4: Write the route table and the providers**

Create `web/src/app/providers.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { BrowserRouter } from "react-router-dom";

/**
 * `retry: false` for the same reason the test harness sets it: every failure
 * these screens can produce is either a 404 (retrying cannot help) or a
 * server that is down (the user can see that faster than three backoffs
 * can). `refetchOnWindowFocus` stays on — coming back to a tab after a run
 * finished elsewhere should show the run that finished.
 */
const client = new QueryClient({
  defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
});

export function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={client}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
}
```

Create `web/src/app/routes.tsx`:

```tsx
import { Route, Routes } from "react-router-dom";

import { AppLayout } from "@/app/AppLayout";
import { RenderDetailPage } from "@/features/renders/RenderDetailPage";
import { RunDetailPage } from "@/features/runs/RunDetailPage";
import { RunsPage } from "@/features/runs/RunsPage";
import { TopicDetailPage } from "@/features/topics/TopicDetailPage";
import { TopicsPage } from "@/features/topics/TopicsPage";

/**
 * Five routes in this phase. Phase 6 adds `/runs/new` and `/settings`.
 *
 * Topic detail is run-scoped because the dossier, the replies and the
 * renders all belong to one run, and because generating a meme needs an
 * unambiguous run to attach to.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<TopicsPage />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route path="/runs/:runId/renders/:renderId" element={<RenderDetailPage />} />
        <Route path="/topics/:runId/:topicId" element={<TopicDetailPage />} />
      </Route>
    </Routes>
  );
}
```

This imports five pages that do not exist yet. Tasks 7–11 create them, and each of those tasks owns exactly one. To keep the tree green *now*, create each of the five as a one-line component that the task naming it replaces in full:

```tsx
// web/src/features/runs/RunsPage.tsx — replaced in full by Task 7.
export function RunsPage() {
  return null;
}
```

Do the same for `RunDetailPage` (Task 8), `TopicsPage` (Task 9), `TopicDetailPage` (Task 10) and `RenderDetailPage` (Task 11). This is the second and last exception to the no-placeholders rule in this plan, and it exists for the same reason as Task 1's: the route table is one unit and the gate is green at every task boundary.

Replace `web/src/App.tsx`:

```tsx
import { AppRoutes } from "@/app/routes";
import { Providers } from "@/app/providers";

export function App() {
  return (
    <Providers>
      <AppRoutes />
    </Providers>
  );
}
```

Delete `web/src/App.test.tsx`.

It existed for one task, to prove `npm --prefix web test` actually ran something rather than passing an empty suite. `routes.test.tsx` now renders the same tree and asserts what is in it, so the smoke test can only fail by crashing — the rubric's "the test can fail only through a panic, crash, or missing selector" — and it would be asserting on the framework mounting rather than on anything this app does.

```bash
git rm web/src/App.test.tsx
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npm --prefix web test`

Expected: all green, including `routes.test.tsx`.

- [ ] **Step 6: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest && npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

- [ ] **Step 7: Commit**

```bash
git add web/src/app web/src/App.tsx web/src/App.test.tsx web/src/features
git commit -m "Add the router, the app shell and the sidebar"
```

---

### Task 7: the Runs list, including the failed row and the source outage

**Files:**
- Create: `web/src/features/runs/RunRow.tsx` + `RunRow.module.css`, `web/src/features/runs/survived.ts`
- Test: `web/src/features/runs/RunsPage.test.tsx`
- Modify: `web/src/features/runs/RunsPage.tsx` (replacing Task 6's placeholder), and add `RunsPage.module.css`

**Interfaces:**
- Consumes: `useRuns` (Task 4), `StatusPill`, `MemeTile`, `MetaLine`, `EmptyState`, `QueryBoundary` (Task 5), `formatRelative`, `formatDuration`, `shortRunId` (Task 4).
- Produces: `survivedFor(stage: Stage): string` and `resumeStageFor(error: RunError | null): Stage | null`, both pure and both reused by Task 8's run detail.

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/runs/RunsPage.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { RunsPage } from "@/features/runs/RunsPage";
import { makeRunPage, makeRunSummary } from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

function servePage(page = makeRunPage()) {
  server.use(http.get("/api/runs", () => HttpResponse.json(page)));
}

describe("RunsPage", () => {
  it("draws a row per run, truncating the id the way the design does", async () => {
    servePage(
      makeRunPage([
        makeRunSummary({ runId: "20260829T090000Z" }),
        makeRunSummary({ runId: "20260828T090000Z" }),
      ]),
    );

    renderWithProviders(<RunsPage />);

    expect(await screen.findByText("…829T090000Z")).toBeInTheDocument();
    expect(screen.getByText("…828T090000Z")).toBeInTheDocument();
  });

  it("joins the topic titles with the design's separator", async () => {
    servePage(
      makeRunPage([makeRunSummary({ labels: ["Airport cat", "Stadium rat"] })]),
    );

    renderWithProviders(<RunsPage />);

    expect(await screen.findByText("Airport cat · Stadium rat")).toBeInTheDocument();
  });

  it("reports the fan-out and what survived it", async () => {
    servePage(makeRunPage([makeRunSummary({ trendsFound: 25, topicsKept: 5 })]));

    renderWithProviders(<RunsPage />);

    expect(await screen.findByText("25 trends → 5 kept")).toBeInTheDocument();
    expect(screen.getByText("18 phrases")).toBeInTheDocument();
  });

  it("links each row to that run's detail page", async () => {
    servePage(makeRunPage([makeRunSummary({ runId: "20260829T090000Z" })]));

    renderWithProviders(<RunsPage />);

    expect(await screen.findByRole("link")).toHaveAttribute(
      "href",
      "/runs/20260829T090000Z",
    );
  });

  it("draws at most three thumbnails and counts the rest", async () => {
    servePage(
      makeRunPage([makeRunSummary({ renderIds: ["a", "b", "c", "d", "e"] })]),
    );

    renderWithProviders(<RunsPage />);

    expect(await screen.findAllByRole("img")).toHaveLength(3);
    expect(screen.getByText("+2")).toBeInTheDocument();
  });

  it("draws no overflow tile when three renders fit exactly", async () => {
    servePage(makeRunPage([makeRunSummary({ renderIds: ["a", "b", "c"] })]));

    renderWithProviders(<RunsPage />);

    expect(await screen.findAllByRole("img")).toHaveLength(3);
    expect(screen.queryByText(/^\+/)).not.toBeInTheDocument();
  });

  it("shows the error, what survived and the resume affordance on a failure", async () => {
    servePage(
      makeRunPage([
        makeRunSummary({
          status: "failed",
          finishedAt: null,
          error: {
            kind: "RenderError",
            message: "3 of 5 briefs written",
            stage: "generate",
          },
        }),
      ]),
    );

    renderWithProviders(<RunsPage />);

    expect(
      await screen.findByText("RenderError in generate — 3 of 5 briefs written"),
    ).toBeInTheDocument();
    expect(screen.getByText("ranked checkpoint intact")).toBeInTheDocument();
    expect(screen.getByText("resume from generate ↗")).toBeInTheDocument();
  });

  it("offers a re-run rather than a resume when ingest returned nothing", async () => {
    // A source outage writes no checkpoint, so `resume_stage` is None and
    // the UI must not offer a resume it cannot honour.
    servePage(
      makeRunPage([
        makeRunSummary({
          status: "failed",
          finishedAt: null,
          error: {
            kind: "SourceError",
            message: "no trends returned",
            stage: "ingest",
          },
        }),
      ]),
    );

    renderWithProviders(<RunsPage />);

    expect(
      await screen.findByText("SourceError in ingest — no trends returned"),
    ).toBeInTheDocument();
    expect(screen.getByText("nothing written")).toBeInTheDocument();
    expect(screen.getByText("re-run ↗")).toBeInTheDocument();
    expect(screen.queryByText(/resume from/)).not.toBeInTheDocument();
  });

  it("counts the page it is showing, not an archive total it was not sent", async () => {
    // The aborted run is what makes this test bite. `RunStatus` has five
    // members and the line names whichever are present, so a counter that
    // grouped everything-not-ok under "failed" would call an aborted run a
    // failure, and one that only counted "ok" and "failed" would print
    // four runs adding up to three.
    servePage(
      makeRunPage([
        makeRunSummary({ runId: "a" }),
        makeRunSummary({ runId: "b" }),
        makeRunSummary({
          runId: "c",
          status: "failed",
          error: { kind: "RenderError", message: "boom", stage: "generate" },
        }),
        makeRunSummary({ runId: "d", status: "aborted", finishedAt: null }),
      ]),
    );

    renderWithProviders(<RunsPage />);

    expect(
      await screen.findByText("4 shown · 2 ok · 1 failed · 1 aborted · bluesky"),
    ).toBeInTheDocument();
  });

  it("names every source when a page mixes them", async () => {
    servePage(
      makeRunPage([
        makeRunSummary({ runId: "a", config: { sources: ["bluesky"] } }),
        makeRunSummary({ runId: "b", config: { sources: ["lemmy"] } }),
      ]),
    );

    renderWithProviders(<RunsPage />);

    expect(await screen.findByText(/bluesky · lemmy$/)).toBeInTheDocument();
  });

  it("explains the app when nothing has ever run", async () => {
    servePage(makeRunPage([]));

    renderWithProviders(<RunsPage />);

    expect(
      await screen.findByRole("heading", { name: "Nothing has run yet" }),
    ).toBeInTheDocument();
  });

  it("reports a server failure rather than an empty list", async () => {
    // An empty list and a broken server look identical without this, and
    // "nothing has run yet" would be a lie about a database that is fine.
    server.use(
      http.get("/api/runs", () =>
        HttpResponse.json({ detail: "database is locked" }, { status: 500 }),
      ),
    );

    renderWithProviders(<RunsPage />);

    expect(await screen.findByText(/database is locked/)).toBeInTheDocument();
    expect(screen.queryByText("Nothing has run yet")).not.toBeInTheDocument();
  });

  it("marks a failed row so the whole row reads as failed, not just its pill", async () => {
    // The design gives a failed row its own `contrast` border. Asserting
    // the pill's text would pass with that border removed, because the
    // pill draws itself from `run.status` and knows nothing about the row.
    servePage(
      makeRunPage([
        makeRunSummary({
          runId: "20260829T090000Z",
          status: "failed",
          error: { kind: "RenderError", message: "boom", stage: "generate" },
        }),
        makeRunSummary({ runId: "20260828T090000Z", status: "ok" }),
      ]),
    );

    renderWithProviders(<RunsPage />);

    const rows = await screen.findAllByRole("link");
    const failedRow = rows.find((row) => row.textContent?.includes("boom"));
    const okRow = rows.find((row) => row !== failedRow);

    expect(failedRow?.className).toContain("failed");
    expect(okRow?.className).not.toContain("failed");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- RunsPage`

Expected: FAIL — the page renders `null`, so every query fails to find its text.

- [ ] **Step 3: Write the two derivations**

Create `web/src/features/runs/survived.ts`:

```ts
import type { RunError, Stage } from "@/api/types";

/**
 * What a failed run managed to write, from the stage it died in.
 *
 * The stages run in order and a stage only fails after its predecessors
 * wrote, so the failed stage names the last checkpoint that exists. That is
 * the same fact `RunDetail.resume_stage` encodes, reached without a second
 * request — `RunSummary` carries no stage records.
 *
 * The extensions are gone (`ranked`, not `ranked.json`): these are database
 * rows now, and a filename for a row would be a small lie on a screen whose
 * whole job is telling you what a run actually did.
 */
const SURVIVED: Readonly<Record<Stage, string>> = {
  ingest: "nothing written",
  analyse: "evidence checkpoint intact",
  evaluate: "topics checkpoint intact",
  generate: "ranked checkpoint intact",
};

export function survivedFor(stage: Stage): string {
  return SURVIVED[stage];
}

/**
 * Where a resume would start, or null when there is nothing to resume from.
 *
 * Null is the source outage: ingest wrote no checkpoint, so the run has to
 * start over. The UI must not offer a resume it cannot honour.
 */
export function resumeStageFor(error: RunError | null | undefined): Stage | null {
  if (!error) return null;
  return error.stage === "ingest" ? null : error.stage;
}
```

- [ ] **Step 4: Write the row**

Create `web/src/features/runs/RunRow.tsx`:

```tsx
import { Link } from "react-router-dom";

import type { RunSummary } from "@/api/types";
import { MemeTile } from "@/components/MemeTile";
import { StatusPill } from "@/components/StatusPill";
import { formatDuration, formatRelative, shortRunId } from "@/format";
import { resumeStageFor, survivedFor } from "@/features/runs/survived";

import styles from "./RunRow.module.css";

/** Three, then a dashed `+n` tile. Column four is 128px wide. */
const MAX_THUMBNAILS = 3;

export function RunRow({ summary }: { summary: RunSummary }) {
  const { run, topic_labels, render_ids } = summary;
  const failed = run.error !== null;
  const shown = render_ids.slice(0, MAX_THUMBNAILS);
  const overflow = render_ids.length - shown.length;

  return (
    <Link
      to={`/runs/${encodeURIComponent(run.run_id)}`}
      className={`${styles.row} ${failed ? styles.failed : ""}`}
    >
      <span className={styles.identity}>
        <span className={styles.runId}>{shortRunId(run.run_id)}</span>
        <span className={styles.when}>
          {formatRelative(run.started_at)} · {formatDuration(run.started_at, run.finished_at)}
        </span>
      </span>

      {run.error ? (
        <span className={styles.error}>
          {run.error.kind} in {run.error.stage} — {run.error.message}
        </span>
      ) : (
        <span className={styles.labels}>{topic_labels.join(" · ")}</span>
      )}

      {run.error ? (
        <span className={styles.survived}>{survivedFor(run.error.stage)}</span>
      ) : (
        <span className={styles.counts}>
          <span>
            {run.trends_found ?? 0} trends → {run.topics_kept ?? 0} kept
          </span>
          <span className={styles.phrases}>{run.phrases_found ?? 0} phrases</span>
        </span>
      )}

      {run.error ? (
        <span className={styles.action}>
          {resumeStageFor(run.error) === null
            ? "re-run ↗"
            : `resume from ${resumeStageFor(run.error) ?? ""} ↗`}
        </span>
      ) : (
        <span className={styles.thumbnails}>
          {shown.map((id) => (
            <MemeTile key={id} renderId={id} size={34} />
          ))}
          {overflow > 0 && <span className={styles.overflow}>+{overflow}</span>}
        </span>
      )}

      <span className={styles.status}>
        <StatusPill status={run.status} count={render_ids.length} />
      </span>
    </Link>
  );
}
```

The resume label repeats `resumeStageFor(run.error)` rather than binding it once because the ternary above already narrowed it; a `const` above the JSX would read more cleanly and is the better shape if the linter is happy with it — either is fine, and neither changes behaviour.

Create `web/src/features/runs/RunRow.module.css`:

```css
.row {
  display: grid;
  grid-template-columns: 150px 1fr 150px 128px 84px;
  gap: var(--gap-section);
  align-items: center;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--surface);
  transition: border-color var(--transition);
}

.row:hover {
  border-color: var(--border-hover);
}

.failed {
  border-color: var(--contrast-border);
}

.identity {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.runId {
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text);
}

.when,
.phrases {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-35);
}

.labels {
  font-size: 13px;
  color: var(--text-70);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.error {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--contrast-light);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.counts {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-55);
}

.survived,
.action {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--contrast-light);
}

.thumbnails {
  display: flex;
  gap: var(--gap-tight);
}

.overflow {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-35);
}

.status {
  justify-self: end;
}
```

- [ ] **Step 5: Write the page**

Replace `web/src/features/runs/RunsPage.tsx` in full:

```tsx
import type { RunStatus, RunSummary } from "@/api/types";
import { useRuns } from "@/api/queries";
import { EmptyState } from "@/components/EmptyState";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { RunRow } from "@/features/runs/RunRow";

import styles from "./RunsPage.module.css";

/** Every status, in the order the line names them. */
const STATUS_ORDER: readonly RunStatus[] = [
  "ok",
  "failed",
  "aborted",
  "interrupted",
  "running",
];

/**
 * The page it is looking at, not an archive total.
 *
 * `GET /api/runs` is cursor-paginated and returns no totals; the handoff's
 * `27 total` would be a new field on a contract phase 4 closed. So the line
 * says "shown", which is both true and visibly about this page.
 *
 * Each status present is named with its own count rather than grouped into
 * the handoff's `ok · failed` pair. `RunStatus` has five members, and both
 * ways of forcing them into two are wrong on this line: grouping
 * everything-not-ok under "failed" calls an aborted run a failure, and
 * counting only the two named statuses prints a total the parts do not add
 * up to. The sources clause names every distinct source across the page
 * rather than claiming one, because a page can mix them.
 */
function summarise(runs: RunSummary[]): string {
  const counts = new Map<RunStatus, number>();
  for (const entry of runs) {
    counts.set(entry.run.status, (counts.get(entry.run.status) ?? 0) + 1);
  }
  const statuses = STATUS_ORDER.filter((status) => counts.has(status)).map(
    (status) => `${counts.get(status) ?? 0} ${status}`,
  );
  const sources = [...new Set(runs.flatMap((entry) => entry.run.config.sources))];
  return [`${runs.length} shown`, ...statuses, ...sources].join(" · ");
}

export function RunsPage() {
  const query = useRuns();

  return (
    <QueryBoundary query={query} missing="No runs.">
      {(page) => (
        <>
          <header className={styles.header}>
            <h1 className={styles.title}>Runs</h1>
            {page.runs.length > 0 && <MetaLine>{summarise(page.runs)}</MetaLine>}
          </header>

          {page.runs.length === 0 ? (
            <EmptyState
              headline="Nothing has run yet"
              body="A run reads Bluesky, works out what is trending, and generates memes about it. The first one takes a few minutes."
            />
          ) : (
            <ul className={styles.rows}>
              {page.runs.map((summary) => (
                <li key={summary.run.run_id}>
                  <RunRow summary={summary} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </QueryBoundary>
  );
}
```

Create `web/src/features/runs/RunsPage.module.css`:

```css
.header {
  margin-bottom: var(--gap-page);
}

.title {
  font-size: 22px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: -0.03em;
}

.rows {
  display: flex;
  flex-direction: column;
  gap: var(--gap-tight);
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npm --prefix web test -- RunsPage`

Expected: every case green. If "3 shown · 2 ok · 1 failed · bluesky" fails on the source clause, the factory's runs all share one `sources`, and `new Set` is collapsing them correctly — check the assertion, not the code.

- [ ] **Step 7: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest && npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

- [ ] **Step 8: Commit**

```bash
git add web/src/features/runs
git commit -m "Build the Runs list, with the failed row and the source outage"
```

---

### Task 8: Run detail — stage cards, the ranking, and the cut line

**Files:**
- Create: `web/src/components/Breadcrumb.tsx` + `Breadcrumb.module.css`, `web/src/features/runs/StageCards.tsx` + `.module.css`, `web/src/features/runs/RankingList.tsx` + `.module.css`, `web/src/features/runs/RankRow.tsx` + `.module.css`
- Test: `web/src/features/runs/RunDetailPage.test.tsx`
- Modify: `web/src/features/runs/RunDetailPage.tsx` (replacing Task 6's placeholder), and add `RunDetailPage.module.css`

**Interfaces:**
- Consumes: `useRun`, `useRanking`, `survivedFor`, `resumeStageFor`, every Task 5 primitive.
- Produces: `<Breadcrumb trail={{ label: string; to?: string }[]} />`; `<RankRow topic={RankedTopic} rank={number} highlighted={boolean} />`, which Task 9 does **not** reuse — the topics index draws cards, not rows.

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/runs/RunDetailPage.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { RankedTopic, RunDetail } from "@/api/types";
import { RunDetailPage } from "@/features/runs/RunDetailPage";
import {
  makeRankedTopic,
  makeRunDetail,
  makeStageRecord,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

const RUN_ID = "20260829T090000Z";

function serve(detail: RunDetail, ranking: RankedTopic[]) {
  server.use(
    http.get("/api/runs/:runId", () => HttpResponse.json(detail)),
    http.get("/api/runs/:runId/topics", () => HttpResponse.json(ranking)),
  );
}

function renderPage() {
  return renderWithProviders(<RunDetailPage />, {
    route: `/runs/${RUN_ID}`,
    path: "/runs/:runId",
  });
}

describe("RunDetailPage", () => {
  it("shows the run id and the config it froze", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [makeRankedTopic()]);

    renderPage();

    expect(await screen.findByText(RUN_ID)).toBeInTheDocument();
    expect(
      screen.getByText(
        "bluesky · trend_limit 25 · posts_per_trend 30 · top_count 5 · claude-opus-5 · 6m 41s",
      ),
    ).toBeInTheDocument();
  });

  it("draws a card per stage with its artifact and size", async () => {
    serve(
      makeRunDetail({
        runId: RUN_ID,
        stages: [
          makeStageRecord({ stage: "ingest", payloadBytes: 1_363_148 }),
          makeStageRecord({ stage: "analyse", payloadBytes: 88_000 }),
          makeStageRecord({ stage: "evaluate", payloadBytes: 9_100 }),
          makeStageRecord({
            stage: "generate",
            payloadBytes: 4_100,
            summary: "3 of 5 rendered",
          }),
        ],
      }),
      [makeRankedTopic()],
    );

    renderPage();

    expect(await screen.findByText("evidence · 1.4 MB")).toBeInTheDocument();
    expect(screen.getByText("ranked · 9.1 kB")).toBeInTheDocument();
    // The pipeline's own words for a partially failed generate stage. This
    // is where partial failure is shown — see the plan's decision 7.
    expect(screen.getByText("3 of 5 rendered")).toBeInTheDocument();
  });

  it("draws a stage that never ran without a size it does not have", async () => {
    serve(
      makeRunDetail({
        runId: RUN_ID,
        stages: [
          makeStageRecord({ stage: "ingest" }),
          makeStageRecord({
            stage: "analyse",
            status: "failed",
            finishedAt: null,
            payloadBytes: null,
            summary: "DistilError",
          }),
        ],
      }),
      [],
    );

    renderPage();

    expect(await screen.findByText("topics · —")).toBeInTheDocument();
  });

  it("draws a card for a stage the run never reached at all", async () => {
    // `stages_for_run` returns only the stages that were recorded. A run
    // that died in analyse has no evaluate row, and the design draws four
    // cards regardless — the last two queued.
    serve(
      makeRunDetail({ runId: RUN_ID, stages: [makeStageRecord({ stage: "ingest" })] }),
      [],
    );

    renderPage();

    expect(await screen.findByText("generate")).toBeInTheDocument();
    expect(screen.getAllByText("queued")).toHaveLength(3);
  });

  it("ranks the topics and shows each one's scores", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({
        topicId: "t1",
        label: "Airport cat",
        finalRank: 1,
        trendScore: 0.91,
        memePotential: 0.86,
        finalScore: 0.895,
      }),
    ]);

    renderPage();

    expect(await screen.findByText("Airport cat")).toBeInTheDocument();
    expect(screen.getByText("trend 0.91 · meme 0.86")).toBeInTheDocument();
    expect(screen.getByText("final 0.895")).toBeInTheDocument();
  });

  it("shows the topic's own subline: status, posts and its top phrase", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({
        trendStatus: "saturating",
        postCount: 412,
        topPhrase: "absolute unit",
        topPhraseAuthors: 31,
      }),
    ]);

    renderPage();

    expect(
      await screen.findByText("saturating · 412 posts · “absolute unit” 31 authors"),
    ).toBeInTheDocument();
  });

  it("drops the phrase clause for a topic that had no recurring phrase", async () => {
    // `top_phrase` is null when the dossier found nothing above
    // phrase_min_authors. An empty quote would read as a phrase that is
    // literally nothing.
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ trendStatus: "cooling", postCount: 90, topPhrase: null }),
    ]);

    renderPage();

    expect(await screen.findByText("cooling · 90 posts")).toBeInTheDocument();
  });

  it("links each ranking row to that topic's detail page", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "topic-9" }),
    ]);

    renderPage();

    const rows = await screen.findAllByRole("link");
    expect(rows.some((link) => link.getAttribute("href") === `/topics/${RUN_ID}/topic-9`)).toBe(
      true,
    );
  });

  it("offers generate on a below-the-cut row instead of thumbnails", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "t1", finalRank: 1, aboveCut: true }),
      makeRankedTopic({
        topicId: "t2",
        finalRank: 6,
        aboveCut: false,
        renderCount: 0,
      }),
    ]);

    renderPage();

    expect(await screen.findByText("generate ↗")).toBeInTheDocument();
  });

  it("counts the rows below the cut", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "t1", finalRank: 1, aboveCut: true }),
      makeRankedTopic({ topicId: "t2", finalRank: 2, aboveCut: false }),
      makeRankedTopic({ topicId: "t3", finalRank: 3, aboveCut: false }),
    ]);

    renderPage();

    expect(await screen.findByText("2 more below the cut")).toBeInTheDocument();
  });

  it("says nothing about a cut when every topic is above it", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "t1", finalRank: 1, aboveCut: true }),
    ]);

    renderPage();

    expect(await screen.findByText("Airport cat")).toBeInTheDocument();
    expect(screen.queryByText(/below the cut/)).not.toBeInTheDocument();
  });

  it("says so when the generate stage produced nothing at all", async () => {
    // Not an empty screen: the ranking is still there, and every row shows
    // generate rather than a thumbnail.
    serve(
      makeRunDetail({
        runId: RUN_ID,
        stages: [makeStageRecord({ stage: "generate", summary: "0 of 5 rendered" })],
      }),
      [
        makeRankedTopic({ topicId: "t1", finalRank: 1, renderCount: 0 }),
        makeRankedTopic({ topicId: "t2", finalRank: 2, renderCount: 0 }),
      ],
    );

    renderPage();

    expect(
      await screen.findByText("No memes were rendered — every brief failed"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("generate ↗")).toHaveLength(2);
  });

  it("does not claim every brief failed on a run that never reached generate", async () => {
    // The ranking has to be non-empty for this to test anything: an empty
    // one takes a different branch and never consults the generate stage
    // at all. Here evaluate wrote a ranking and generate never ran, so
    // every render_count is 0 because nothing tried — not because every
    // brief failed. Without the stage guard the screen reads the first as
    // the second and sends someone hunting a renderer bug.
    serve(
      makeRunDetail({
        runId: RUN_ID,
        status: "failed",
        error: { kind: "DistilError", message: "model returned nothing", stage: "analyse" },
        stages: [makeStageRecord({ stage: "ingest" })],
      }),
      [makeRankedTopic({ topicId: "t1", finalRank: 1, renderCount: 0 })],
    );

    renderPage();

    expect(await screen.findByText(/DistilError in analyse/)).toBeInTheDocument();
    expect(screen.queryByText(/every brief failed/)).not.toBeInTheDocument();
  });

  it("shows the failure and what survived it", async () => {
    serve(
      makeRunDetail({
        runId: RUN_ID,
        status: "failed",
        error: {
          kind: "RenderError",
          message: "3 of 5 briefs written",
          stage: "generate",
        },
        resumeStage: "generate",
      }),
      [makeRankedTopic()],
    );

    renderPage();

    expect(
      await screen.findByText(
        "RenderError in generate — 3 of 5 briefs written · ranked checkpoint intact",
      ),
    ).toBeInTheDocument();
  });

  it("says which run is missing rather than showing an empty page", async () => {
    server.use(
      http.get("/api/runs/:runId", () =>
        HttpResponse.json({ detail: "No such run" }, { status: 404 }),
      ),
      http.get("/api/runs/:runId/topics", () =>
        HttpResponse.json({ detail: "No such run" }, { status: 404 }),
      ),
    );

    renderPage();

    expect(await screen.findByText("No such run.")).toBeInTheDocument();
  });

  it("breadcrumbs back to the runs list", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [makeRankedTopic()]);

    renderPage();

    const crumb = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumb).getByRole("link", { name: "Runs" })).toHaveAttribute(
      "href",
      "/runs",
    );
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- RunDetailPage`

Expected: FAIL — the page renders `null`.

- [ ] **Step 3: Write `Breadcrumb`**

Create `web/src/components/Breadcrumb.tsx`:

```tsx
import { Link } from "react-router-dom";

import styles from "./Breadcrumb.module.css";

export interface Crumb {
  label: string;
  /** Omitted for the final crumb, which is where you already are. */
  to?: string;
}

export function Breadcrumb({ trail }: { trail: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className={styles.trail}>
      {trail.map((crumb, index) => (
        <span key={`${crumb.label}-${index}`} className={styles.crumb}>
          {index > 0 && <span className={styles.separator}>/</span>}
          {crumb.to === undefined ? (
            <span className={styles.current}>{crumb.label}</span>
          ) : (
            <Link to={crumb.to}>{crumb.label}</Link>
          )}
        </span>
      ))}
    </nav>
  );
}
```

Create `web/src/components/Breadcrumb.module.css`:

```css
.trail {
  display: flex;
  align-items: center;
  gap: var(--gap-tight);
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-35);
  margin-bottom: 10px;
}

.crumb {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-tight);
}

.crumb a:hover {
  color: var(--text-70);
}

.separator {
  color: var(--text-30);
}

.current {
  color: var(--text-55);
}
```

- [ ] **Step 4: Write the stage cards**

Create `web/src/features/runs/StageCards.tsx`:

```tsx
import type { StageRecord } from "@/api/types";
import { ARTIFACT_NAMES, STAGES } from "@/api/types";
import { StageBar } from "@/components/StageBar";
import { formatBytes, formatDuration } from "@/format";

import styles from "./StageCards.module.css";

/**
 * Four cards, always.
 *
 * `stages_for_run` returns only the stages that were recorded, so a run that
 * died in analyse has no evaluate or generate row at all. The design draws
 * four regardless — the ones that never ran are `queued` in `text-30` with
 * no accent bar — because "this stage has not happened" is information, and
 * a three-card row would just look like a different screen.
 */
export function StageCards({ stages }: { stages: StageRecord[] }) {
  const recorded = new Map(stages.map((stage) => [stage.stage, stage]));

  return (
    <ul className={styles.grid}>
      {STAGES.map((name) => {
        // The accent bar means "this stage completed". A failed, skipped or
        // absent stage gets the muted treatment, which is what the design's
        // "incomplete stages use `border` and `text-30` throughout with no
        // accent bar" asks for. Phase 6 adds the partial fill for a stage
        // that is running.
        const record = recorded.get(name);
        const complete = record?.status === "ok";
        return (
          <li key={name} className={`${styles.card} ${complete ? "" : styles.idle}`}>
            {complete ? <StageBar fill={1} /> : <StageBar fill={0} tone="muted" />}
            <div className={styles.head}>
              <span className={styles.name}>{name}</span>
              <span className={styles.duration}>
                {record === undefined || record.started_at === null
                  ? "—"
                  : formatDuration(record.started_at, record.finished_at)}
              </span>
            </div>
            <p className={styles.summary}>{record?.summary ?? "queued"}</p>
            <span className={styles.artifact}>
              {ARTIFACT_NAMES[name]} · {formatBytes(record?.payload_bytes)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
```

Create `web/src/features/runs/StageCards.module.css`:

```css
.grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 13px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
}

.idle {
  color: var(--text-30);
}

.head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--gap-tight);
}

.name {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  color: inherit;
}

.duration {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-35);
}

.summary {
  font-size: 11.5px;
  font-weight: 400;
  color: var(--text-70);
}

.idle .summary {
  color: var(--text-30);
}

.artifact {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-30);
}
```

- [ ] **Step 5: Write the ranking**

Create `web/src/features/runs/RankRow.tsx`:

```tsx
import { Link } from "react-router-dom";

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

export function RankRow({
  entry,
  highlighted,
  offerGenerate,
}: {
  entry: RankedTopic;
  highlighted: boolean;
  /**
   * Draw `generate ↗` where the thumbnails would be. True below the cut —
   * those topics were never briefed — and true for every row when the
   * generate stage rendered nothing at all.
   */
  offerGenerate: boolean;
}) {
  const { topic, render_count, above_cut } = entry;
  const to = `/topics/${encodeURIComponent(topic.run_id)}/${encodeURIComponent(topic.topic_id)}`;

  return (
    <Link
      to={to}
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
        <span className={styles.label}>{topic.label}</span>
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
          // Phase 7 replaces this with the action itself. Here it is text
          // inside the row's own link, which already goes to topic detail —
          // where that action's panels will live.
          <span className={styles.generate}>generate ↗</span>
        ) : (
          // A count, not thumbnails. `RankedTopic` carries `render_count`
          // from `Store.render_counts` and no render ids, and addressing an
          // image needs an id — only topic detail's `renders` list has
          // those. The design draws 42px tiles here; showing them would mean
          // one extra request per row, on a frozen contract, to render
          // something topic detail shows one click away. So the row states
          // the count and topic detail draws the memes.
          <span className={styles.count}>
            {render_count} {render_count === 1 ? "meme" : "memes"}
          </span>
        )}
      </span>
    </Link>
  );
}
```

This is the one deliberate departure from the mockup's ranking row, and it is forced: the frozen contract does not carry render ids on this endpoint. It is recorded in "Decisions taken against the handoff" in Task 12's spec update, alongside the six the spec already lists.

Create `web/src/features/runs/RankRow.module.css`:

```css
.row {
  display: grid;
  grid-template-columns: 30px 1fr 132px 150px 128px;
  gap: var(--gap-tight);
  align-items: center;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--surface);
  transition: border-color var(--transition);
}

.row:hover {
  border-color: var(--border-hover);
}

.highlighted {
  border-color: var(--accent-border);
  background: var(--accent-wash);
}

.belowCut {
  border-style: dashed;
  background: none;
  opacity: 0.62;
}

.rank {
  font-size: 17px;
  font-weight: 800;
  line-height: 1;
  color: var(--text-50);
}

.highlighted .rank {
  color: var(--accent);
}

.identity {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.label {
  font-size: 14.5px;
  font-weight: 700;
  line-height: 1.25;
}

.subline,
.components,
.final,
.count,
.generate {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-35);
}

.chips {
  display: flex;
  gap: var(--gap-tight);
  flex-wrap: wrap;
}

.scores {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.final {
  color: var(--text-55);
}

.highlighted .final {
  color: var(--accent);
}

.generate {
  color: var(--contrast-light);
}
```

Create `web/src/features/runs/RankingList.tsx`:

```tsx
import type { RankedTopic } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";
import { RankRow } from "@/features/runs/RankRow";

import styles from "./RankingList.module.css";

export function RankingList({
  ranking,
  topCount,
  everyBriefFailed,
}: {
  ranking: RankedTopic[];
  topCount: number;
  everyBriefFailed: boolean;
}) {
  const below = ranking.filter((entry) => !entry.above_cut).length;

  return (
    <section className={styles.section}>
      <SectionLabel hint={`top ${topCount} of ${ranking.length}`}>Ranking</SectionLabel>

      {everyBriefFailed && (
        <p className={styles.noMemes}>No memes were rendered — every brief failed</p>
      )}

      <ul className={styles.rows}>
        {ranking.map((entry, index) => (
          <li key={entry.topic.topic_id}>
            <RankRow
              entry={entry}
              highlighted={index === 0 && entry.above_cut}
              offerGenerate={everyBriefFailed || !entry.above_cut}
            />
          </li>
        ))}
      </ul>

      {below > 0 && <p className={styles.cut}>{below} more below the cut</p>}
    </section>
  );
}
```

Create `web/src/features/runs/RankingList.module.css`:

```css
.section {
  margin-top: var(--gap-page);
}

.rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.noMemes {
  margin-bottom: 10px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--contrast-light);
}

.cut {
  margin-top: 12px;
  text-align: center;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-30);
}
```

- [ ] **Step 6: Write the page**

Replace `web/src/features/runs/RunDetailPage.tsx` in full:

```tsx
import { useParams } from "react-router-dom";

import type { RankedTopic, RunDetail, StageRecord } from "@/api/types";
import { useRanking, useRun } from "@/api/queries";
import { Breadcrumb } from "@/components/Breadcrumb";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { StatusPill } from "@/components/StatusPill";
import { RankingList } from "@/features/runs/RankingList";
import { StageCards } from "@/features/runs/StageCards";
import { survivedFor } from "@/features/runs/survived";
import { formatDuration, shortRunId } from "@/format";

import styles from "./RunDetailPage.module.css";

/** Sources, the three fan-out numbers, the model, the duration. */
function configLine(detail: RunDetail): string {
  const { run } = detail;
  const config = run.config;
  return [
    config.sources.join(" · "),
    `trend_limit ${config.trend_limit}`,
    `posts_per_trend ${config.posts_per_trend}`,
    `top_count ${config.top_count}`,
    config.llm_model,
    formatDuration(run.started_at, run.finished_at),
  ].join(" · ");
}

/**
 * The generate stage ran and produced nothing.
 *
 * Both halves are needed: a run that died in analyse also has zero renders,
 * and telling that user every brief failed would send them looking for a
 * renderer problem that does not exist.
 */
function everyBriefFailed(stages: StageRecord[], ranking: RankedTopic[]): boolean {
  const generate = stages.find((stage) => stage.stage === "generate");
  if (generate === undefined || generate.status === "queued") return false;
  return (
    ranking.length > 0 &&
    ranking.every((entry) => entry.render_count === 0)
  );
}

export function RunDetailPage() {
  const { runId } = useParams();
  const run = useRun(runId);
  const ranking = useRanking(runId);

  return (
    <QueryBoundary query={run} missing="No such run.">
      {(detail) => (
        <div className={styles.page}>
          <Breadcrumb
            trail={[
              { label: "Runs", to: "/runs" },
              // Shortened rather than the mockup's full id: the header two
              // lines down already shows it in full, and `findByText` (and
              // a reader's eye) needs the run id to appear once, not twice,
              // in identical text.
              { label: shortRunId(detail.run.run_id) },
            ]}
          />

          <header className={styles.header}>
            <div className={styles.identity}>
              <StatusPill status={detail.run.status} />
              <span className={styles.runId}>{detail.run.run_id}</span>
            </div>
            <MetaLine>{configLine(detail)}</MetaLine>
            {detail.run.error !== null && (
              <p className={styles.error}>
                {detail.run.error.kind} in {detail.run.error.stage} —{" "}
                {detail.run.error.message} · {survivedFor(detail.run.error.stage)}
              </p>
            )}
          </header>

          <StageCards stages={detail.stages} />

          <QueryBoundary query={ranking} missing="No such run.">
            {(rows) =>
              rows.length === 0 ? (
                <p className={styles.noRanking}>
                  This run wrote no ranking — it did not reach evaluate.
                </p>
              ) : (
                <RankingList
                  ranking={rows}
                  topCount={detail.run.config.top_count}
                  everyBriefFailed={everyBriefFailed(detail.stages, rows)}
                />
              )
            }
          </QueryBoundary>
        </div>
      )}
    </QueryBoundary>
  );
}
```

Create `web/src/features/runs/RunDetailPage.module.css`:

```css
.page {
  max-width: var(--content-width);
}

.header {
  margin-bottom: var(--gap-page);
}

.identity {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.runId {
  font-family: var(--font-mono);
  font-size: 19px;
  font-weight: 700;
  line-height: 1;
}

.error {
  margin-top: 8px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--contrast-light);
}

.noRanking {
  margin-top: var(--gap-page);
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-35);
}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `npm --prefix web test -- RunDetailPage`

Expected: every case green. The "4 cards regardless" test is the one most likely to fail first — check `StageCards` iterates `STAGES` and not the `stages` prop.

- [ ] **Step 8: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest && npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

- [ ] **Step 9: Commit**

```bash
git add web/src/features/runs web/src/components/Breadcrumb.tsx web/src/components/Breadcrumb.module.css
git commit -m "Build run detail: stage cards, the ranking and the cut line"
```

---

### Task 9: the Topics screen — hero, mood bar, filters and the two lists

The spec merges the handoff's landing dashboard (`2b`) and topics index (`2d`) into one `/` screen: `2b`'s hero and mood bar above `2d`'s two lists.

Two things the handoff draws here are not in this phase. The **run strip** in `2b`'s bottom-right belongs to phase 6 (its running row carries the in-flight treatment), so the mood bar spans the content width in this phase and phase 6 restores the `1fr 320px` split beside it. The **New run** button is phase 6, per decision 1.

**Files:**
- Create: `web/src/features/topics/HeroTopic.tsx` + `.module.css`, `MoodBar.tsx` + `.module.css`, `StatusFilters.tsx` + `.module.css`, `TopicCard.tsx` + `.module.css`, `RecentTable.tsx` + `.module.css`, `web/src/features/topics/ordering.ts`
- Test: `web/src/features/topics/TopicsPage.test.tsx`, `web/src/features/topics/ordering.test.ts`
- Modify: `web/src/features/topics/TopicsPage.tsx` (replacing Task 6's placeholder), and add `TopicsPage.module.css`

**Interfaces:**
- Consumes: `useTopicIndex`, `useRuns`, `useTopicDetail`, `Chip`, `SectionLabel`, `MetaLine`, `EmptyState`, `MemeTile`, `QueryBoundary`, `formatScore`, `formatClock`.
- Produces: `byRank(topics: IndexedTopic[]): IndexedTopic[]` and `moodSegments(totals, previous): { sentiment, count, share, tone }[]`, both pure.

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/topics/ordering.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { byRank, moodLine, moodSegments } from "@/features/topics/ordering";
import { makeIndexedTopic } from "@/test/factories";

describe("byRank", () => {
  it("orders by final score, highest first", () => {
    // The API returns recency order — newest run first, deduplicated on
    // label_slug — because that is what `topics_for_runs` produces. The
    // hero says "TOP RIGHT NOW", so the client sorts.
    const ordered = byRank([
      makeIndexedTopic({ topicId: "b", finalScore: 0.4 }),
      makeIndexedTopic({ topicId: "a", finalScore: 0.9 }),
      makeIndexedTopic({ topicId: "c", finalScore: 0.6 }),
    ]);

    expect(ordered.map((entry) => entry.topic.topic_id)).toEqual(["a", "c", "b"]);
  });

  it("breaks a tie on topic id so the order is total", () => {
    // Two topics can genuinely share a score. Without a tiebreak the order
    // depends on the input's order, and a test asserting on the first card
    // would pass or fail on nothing.
    const ordered = byRank([
      makeIndexedTopic({ topicId: "z", finalScore: 0.5 }),
      makeIndexedTopic({ topicId: "a", finalScore: 0.5 }),
    ]);

    expect(ordered.map((entry) => entry.topic.topic_id)).toEqual(["a", "z"]);
  });

  it("does not mutate what it was given", () => {
    const input = [
      makeIndexedTopic({ topicId: "b", finalScore: 0.4 }),
      makeIndexedTopic({ topicId: "a", finalScore: 0.9 }),
    ];

    byRank(input);

    expect(input.map((entry) => entry.topic.topic_id)).toEqual(["b", "a"]);
  });
});

describe("moodSegments", () => {
  it("sizes each segment by its share of the window", () => {
    const segments = moodSegments({ funny: 6, cute: 2, mundane: 2 });

    expect(segments.map((segment) => segment.sentiment)).toEqual([
      "funny",
      "cute",
      "mundane",
    ]);
    expect(segments[0]?.share).toBeCloseTo(0.6);
  });

  it("gives the top sentiment the accent and the second half of it", () => {
    const segments = moodSegments({ funny: 6, cute: 3 });

    expect(segments[0]?.tone).toBe("top");
    expect(segments[1]?.tone).toBe("second");
  });

  it("always draws schadenfreude in contrast, wherever it ranks", () => {
    // The handoff singles it out by name rather than by position.
    const segments = moodSegments({ funny: 9, cute: 5, schadenfreude: 1 });

    expect(segments.find((s) => s.sentiment === "schadenfreude")?.tone).toBe(
      "schadenfreude",
    );
  });

  it("returns nothing for a window with no distilled topics", () => {
    // Every topic on the dormant path has a null sentiment, so the totals
    // can legitimately be empty. Dividing by zero would give NaN widths.
    expect(moodSegments({})).toEqual([]);
  });
});

describe("moodLine", () => {
  it("names the leader, its share and its change on the previous run", () => {
    // 9/16 = 56%; the previous run's funny share was 7/13 = 54%. Both
    // denominators are that window's own total, which is the whole point:
    // comparing raw counts across windows of different sizes would report
    // a move that is only a change in how many topics were distilled.
    expect(moodLine({ funny: 9, cute: 5, mundane: 2 }, { funny: 7, cute: 6 })).toBe(
      "funny leads at 56% of the window · up 2 points on the previous run",
    );
  });

  it("says down when the leader lost ground", () => {
    expect(moodLine({ funny: 5, cute: 5 }, { funny: 8, cute: 2 })).toBe(
      "funny leads at 50% of the window · down 30 points on the previous run",
    );
  });

  it("drops the comparison when there is no previous run", () => {
    // "no previous run" and "no change" are different facts, and rendering
    // the second for the first would be a claim nothing supports.
    expect(moodLine({ funny: 9, cute: 5 }, {})).toBe(
      "funny leads at 64% of the window",
    );
  });

  it("says nothing at all for an empty window", () => {
    expect(moodLine({}, {})).toBe("");
  });
});
```

Create `web/src/features/topics/TopicsPage.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { TopicsPage } from "@/features/topics/TopicsPage";
import {
  makeIndexedTopic,
  makeRunPage,
  makeRunSummary,
  makeTopicDetail,
  makeTopicIndex,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

function serve(
  index = makeTopicIndex(),
  runs = makeRunPage([makeRunSummary()]),
  detail = makeTopicDetail(),
) {
  server.use(
    http.get("/api/topics", () => HttpResponse.json(index)),
    http.get("/api/runs", () => HttpResponse.json(runs)),
    http.get("/api/runs/:runId/topics/:topicId", () => HttpResponse.json(detail)),
  );
}

describe("TopicsPage", () => {
  it("titles the page and counts each status in the window", async () => {
    serve();

    renderWithProviders(<TopicsPage />);

    expect(await screen.findByRole("heading", { name: "Right now" })).toBeInTheDocument();
    expect(screen.getByText(/9 trending · 6 saturating · 4 cooling/)).toBeInTheDocument();
  });

  it("heroes the highest-scoring topic, not the most recent one", async () => {
    serve(
      makeTopicIndex({
        topics: [
          makeIndexedTopic({ topicId: "recent", label: "Stadium rat", finalScore: 0.4 }),
          makeIndexedTopic({ topicId: "best", label: "Airport cat", finalScore: 0.95 }),
        ],
      }),
    );

    renderWithProviders(<TopicsPage />);

    const hero = await screen.findByTestId("hero");
    expect(within(hero).getByText("Airport cat")).toBeInTheDocument();
  });

  it("writes the hero's kicker from the topic's own status and score", async () => {
    serve(
      makeTopicIndex({
        topics: [
          makeIndexedTopic({ trendStatus: "saturating", memePotential: 0.86 }),
        ],
      }),
    );

    renderWithProviders(<TopicsPage />);

    expect(
      await screen.findByText("TOP RIGHT NOW · SATURATING · MEME 0.86"),
    ).toBeInTheDocument();
  });

  it("fills the hero's summary from that topic's dossier", async () => {
    // TopicIndex carries no prose — TopicRow has no summary field — so the
    // hero fetches the one topic it is showing. One request, real words.
    serve(
      makeTopicIndex({ topics: [makeIndexedTopic({ topicId: "t1" })] }),
      makeRunPage([makeRunSummary()]),
      makeTopicDetail({
        dossier: {
          what_happened: "A cat got loose in an airport terminal.",
          key_entities: [],
          conversation_summary: "",
          conversation_register: "riffing",
          secondary_registers: [],
          event_sentiment: "funny",
          meme_potential: 0.86,
          recurring_phrases: [],
        },
      }),
    );

    renderWithProviders(<TopicsPage />);

    expect(
      await screen.findByText("A cat got loose in an airport terminal."),
    ).toBeInTheDocument();
  });

  it("draws the mood bar with a segment per sentiment", async () => {
    serve(
      makeTopicIndex({
        sentimentTotals: { funny: 9, cute: 5 },
        previousSentimentTotals: { funny: 7, cute: 6 },
      }),
    );

    renderWithProviders(<TopicsPage />);

    const mood = await screen.findByTestId("mood");
    expect(within(mood).getByText("funny 9")).toBeInTheDocument();
    expect(within(mood).getByText("cute 5")).toBeInTheDocument();
  });

  it("says how the leading sentiment moved against the previous run", async () => {
    serve(
      makeTopicIndex({
        sentimentTotals: { funny: 9, cute: 5, mundane: 2 },
        previousSentimentTotals: { funny: 7, cute: 6 },
      }),
    );

    renderWithProviders(<TopicsPage />);

    expect(
      await screen.findByText(
        "funny leads at 56% of the window · up 2 points on the previous run",
      ),
    ).toBeInTheDocument();
  });

  it("labels a recurring topic with how many runs carried it", async () => {
    serve(makeTopicIndex({ topics: [makeIndexedTopic({ runCount: 3 })] }));

    renderWithProviders(<TopicsPage />);

    expect(await screen.findByText("▲ SEEN IN 3 RUNS")).toBeInTheDocument();
  });

  it("labels a topic seen once as new, not as seen in 1 run", async () => {
    serve(makeTopicIndex({ topics: [makeIndexedTopic({ runCount: 1 })] }));

    renderWithProviders(<TopicsPage />);

    expect(await screen.findByText("NEW THIS RUN")).toBeInTheDocument();
  });

  it("says a topic has no memes yet, which is the cue to go generate some", async () => {
    serve(makeTopicIndex({ topics: [makeIndexedTopic({ renderCount: 0 })] }));

    renderWithProviders(<TopicsPage />);

    expect(await screen.findByText("no memes yet")).toBeInTheDocument();
  });

  it("links each card to that topic in the run it was last seen in", async () => {
    serve(
      makeTopicIndex({
        topics: [makeIndexedTopic({ runId: "20260829T090000Z", topicId: "topic-7" })],
      }),
    );

    renderWithProviders(<TopicsPage />);

    const links = await screen.findAllByRole("link");
    expect(
      links.some(
        (link) => link.getAttribute("href") === "/topics/20260829T090000Z/topic-7",
      ),
    ).toBe(true);
  });

  it("draws at most three trending cards even when more exist", async () => {
    // The grid is 3-up. Without the cap a busy window renders a fourth card
    // that wraps onto its own row, which is the layout breaking rather than
    // extending.
    serve(
      makeTopicIndex({
        topics: [
          makeIndexedTopic({ topicId: "a", label: "Card A", finalScore: 0.9 }),
          makeIndexedTopic({ topicId: "b", label: "Card B", finalScore: 0.8 }),
          makeIndexedTopic({ topicId: "c", label: "Card C", finalScore: 0.7 }),
          makeIndexedTopic({ topicId: "d", label: "Card D", finalScore: 0.6 }),
        ],
      }),
    );

    renderWithProviders(<TopicsPage />);

    const trending = await screen.findByTestId("trending-now");
    expect(within(trending).getAllByRole("heading", { level: 3 })).toHaveLength(3);
    expect(within(trending).queryByText("Card D")).not.toBeInTheDocument();
  });

  it("puts saturating and cooling topics in the second list, not the first", async () => {
    serve(
      makeTopicIndex({
        topics: [
          makeIndexedTopic({ topicId: "a", label: "Trending one", trendStatus: "trending" }),
          makeIndexedTopic({ topicId: "b", label: "Cooling one", trendStatus: "cooling" }),
        ],
      }),
    );

    renderWithProviders(<TopicsPage />);

    const trending = await screen.findByTestId("trending-now");
    const recent = screen.getByTestId("recently-trending");
    expect(within(trending).getByText("Trending one")).toBeInTheDocument();
    expect(within(recent).getByText("Cooling one")).toBeInTheDocument();
  });

  it("refetches with the status the filter chip names", async () => {
    let lastQuery = "";
    server.use(
      http.get("/api/topics", ({ request }) => {
        lastQuery = new URL(request.url).search;
        return HttpResponse.json(makeTopicIndex());
      }),
      http.get("/api/runs", () => HttpResponse.json(makeRunPage([makeRunSummary()]))),
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json(makeTopicDetail()),
      ),
    );

    renderWithProviders(<TopicsPage />);
    await screen.findByRole("heading", { name: "Right now" });

    await userEvent.click(screen.getByRole("button", { name: /cooling 4/ }));

    expect(lastQuery).toContain("status=cooling");
  });

  it("drops the filter when the active chip is clicked again", async () => {
    let lastQuery = "";
    server.use(
      http.get("/api/topics", ({ request }) => {
        lastQuery = new URL(request.url).search;
        return HttpResponse.json(makeTopicIndex());
      }),
      http.get("/api/runs", () => HttpResponse.json(makeRunPage([makeRunSummary()]))),
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json(makeTopicDetail()),
      ),
    );

    renderWithProviders(<TopicsPage />);
    await screen.findByRole("heading", { name: "Right now" });

    await userEvent.click(screen.getByRole("button", { name: /cooling 4/ }));
    await userEvent.click(screen.getByRole("button", { name: /cooling 4/ }));

    expect(lastQuery).not.toContain("status=");
  });

  it("says so lightly when a filter matched nothing", async () => {
    // The user did this to themselves and the remedy is one click away, so
    // it is a line rather than the empty-state card.
    serve(makeTopicIndex({ topics: [] }));

    renderWithProviders(<TopicsPage />);
    await screen.findByRole("heading", { name: "Right now" });

    await userEvent.click(screen.getByRole("button", { name: /stale 31/ }));

    expect(await screen.findByText("No topics with this status.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Nothing has run yet/ })).toBeNull();
  });

  it("explains the app when nothing has ever run", async () => {
    serve(makeTopicIndex({ topics: [] }), makeRunPage([]));

    renderWithProviders(<TopicsPage />);

    expect(
      await screen.findByRole("heading", { name: "Nothing has run yet" }),
    ).toBeInTheDocument();
  });

  it("says everything has gone stale when runs exist but nothing is current", async () => {
    serve(
      makeTopicIndex({ topics: [], statusTotals: { stale: 31 } }),
      makeRunPage([makeRunSummary()]),
    );

    renderWithProviders(<TopicsPage />);

    expect(
      await screen.findByRole("heading", { name: "No topics in the last 6 runs" }),
    ).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- topics`

Expected: FAIL on unresolved imports for `@/features/topics/ordering`, and on `TopicsPage` rendering `null`.

- [ ] **Step 3: Write the ordering and mood derivations**

Create `web/src/features/topics/ordering.ts`:

```ts
import type { IndexedTopic } from "@/api/types";

/**
 * Rank order, which the API does not return.
 *
 * `GET /api/topics` deduplicates on `label_slug` over `topics_for_runs`,
 * which is newest-run-first — recency, not rank. The hero says "TOP RIGHT
 * NOW", so the client sorts.
 *
 * This is presentation, not a second ranking: `final_score` is already
 * `rank_score`'s output, computed once in `projection.flatten`. Sorting by
 * it cannot disagree with the backend the way re-deriving the blend would.
 *
 * The `topic_id` tiebreak makes the order total. Two topics can genuinely
 * share a score, and without it the first card would depend on input order.
 */
export function byRank(topics: IndexedTopic[]): IndexedTopic[] {
  return [...topics].sort((left, right) => {
    const delta = right.topic.final_score - left.topic.final_score;
    return delta !== 0 ? delta : left.topic.topic_id.localeCompare(right.topic.topic_id);
  });
}

export type MoodTone = "top" | "second" | "schadenfreude" | "tail" | "rest";

export interface MoodSegment {
  sentiment: string;
  count: number;
  /** 0-1. The segment's flex-basis. */
  share: number;
  tone: MoodTone;
}

/**
 * One segment per sentiment, largest first.
 *
 * Accent for the leader, accent at 50% for the second, `contrast` for
 * schadenfreude wherever it ranks — the handoff singles it out by name, not
 * by position — then white at 16% and 8% for the rest.
 */
export function moodSegments(totals: Record<string, number>): MoodSegment[] {
  const entries = Object.entries(totals).filter(([, count]) => count > 0);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  if (total === 0) return [];

  return entries
    .sort((left, right) => right[1] - left[1])
    .map(([sentiment, count], index) => ({
      sentiment,
      count,
      share: count / total,
      tone: toneFor(sentiment, index),
    }));
}

function toneFor(sentiment: string, index: number): MoodTone {
  if (sentiment === "schadenfreude") return "schadenfreude";
  if (index === 0) return "top";
  if (index === 1) return "second";
  return index === 2 ? "tail" : "rest";
}

/**
 * The line beneath the bar.
 *
 * The handoff has it cover register skew and average meme potential versus
 * the previous run. `TopicIndex` carries neither — no register totals, and
 * no previous-window rows to average over — and the contract is frozen, so
 * this reports what the contract does carry: the leader, its share, and its
 * change against the previous run.
 *
 * The comparison is dropped rather than shown as zero when there is no
 * previous run: "no previous run" and "no change" are different facts.
 */
export function moodLine(
  totals: Record<string, number>,
  previous: Record<string, number>,
): string {
  const segments = moodSegments(totals);
  const leader = segments[0];
  if (leader === undefined) return "";

  const share = Math.round(leader.share * 100);
  const head = `${leader.sentiment} leads at ${share}% of the window`;

  const previousTotal = Object.values(previous).reduce((sum, count) => sum + count, 0);
  if (previousTotal === 0) return head;

  const before = Math.round(((previous[leader.sentiment] ?? 0) / previousTotal) * 100);
  const delta = share - before;
  if (delta === 0) return `${head} · unchanged on the previous run`;
  const direction = delta > 0 ? "up" : "down";
  return `${head} · ${direction} ${Math.abs(delta)} points on the previous run`;
}
```

- [ ] **Step 4: Write the hero, the mood bar and the filters**

Create `web/src/features/topics/HeroTopic.tsx`:

```tsx
import { Link } from "react-router-dom";

import type { IndexedTopic } from "@/api/types";
import { useTopicDetail } from "@/api/queries";
import { Chip } from "@/components/Chip";
import { formatScore } from "@/format";

import styles from "./HeroTopic.module.css";

/**
 * The accent-filled card, where the palette inverts.
 *
 * The summary comes from a second request. `TopicIndex` carries no prose —
 * `TopicRow` has no summary field, and adding one would reopen a contract
 * phase 4 closed — so the hero fetches the one topic it is showing. The
 * card renders fully without it; the paragraph appears when it arrives.
 */
export function HeroTopic({ entry }: { entry: IndexedTopic }) {
  const { topic } = entry;
  const detail = useTopicDetail(topic.run_id, topic.topic_id);
  const to = `/topics/${encodeURIComponent(topic.run_id)}/${encodeURIComponent(topic.topic_id)}`;

  return (
    <Link to={to} className={styles.hero} data-testid="hero">
      <span className={styles.kicker}>
        {`TOP RIGHT NOW · ${topic.trend_status.toUpperCase()} · MEME ${formatScore(topic.meme_potential)}`}
      </span>
      <h2 className={styles.title}>{topic.label}</h2>
      {detail.data?.dossier != null && (
        <p className={styles.summary}>{detail.data.dossier.what_happened}</p>
      )}
      <span className={styles.chips}>
        {topic.event_sentiment != null && (
          <Chip tone="inverted">{topic.event_sentiment}</Chip>
        )}
        {topic.conversation_register != null && (
          <Chip tone="inverted">{topic.conversation_register}</Chip>
        )}
        <Chip tone="inverted">
          {`${entry.render_count} ${entry.render_count === 1 ? "meme" : "memes"}`}
        </Chip>
      </span>
    </Link>
  );
}
```

Create `web/src/features/topics/HeroTopic.module.css`:

```css
.hero {
  display: flex;
  flex-direction: column;
  min-height: 168px;
  padding: 20px 22px;
  border-radius: var(--radius-card);
  background: var(--accent);
  color: var(--on-accent);
}

.kicker {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.title {
  margin-top: 8px;
  font-size: 29px;
  font-weight: 800;
  line-height: 1.1;
  letter-spacing: -0.03em;
}

.summary {
  margin-top: 8px;
  max-width: 500px;
  font-size: 13px;
  line-height: 1.55;
  opacity: 0.72;
}

.chips {
  margin-top: auto;
  padding-top: 14px;
  display: flex;
  gap: var(--gap-tight);
  flex-wrap: wrap;
}
```

Create `web/src/features/topics/MoodBar.tsx`:

```tsx
import { moodLine, moodSegments } from "@/features/topics/ordering";

import styles from "./MoodBar.module.css";

/** A 28px segmented bar, one segment per sentiment, sized by share. */
export function MoodBar({
  totals,
  previous,
}: {
  totals: Record<string, number>;
  previous: Record<string, number>;
}) {
  const segments = moodSegments(totals);
  if (segments.length === 0) return null;

  return (
    <section data-testid="mood">
      <div className={styles.bar}>
        {segments.map((segment) => (
          <span
            key={segment.sentiment}
            className={`${styles.segment} ${styles[segment.tone]}`}
            style={{ "--share": `${segment.share * 100}%` }}
          >
            {segment.sentiment} {segment.count}
          </span>
        ))}
      </div>
      <p className={styles.line}>{moodLine(totals, previous)}</p>
    </section>
  );
}
```

Create `web/src/features/topics/MoodBar.module.css`:

```css
.bar {
  display: flex;
  gap: 3px;
  height: 28px;
}

.segment {
  flex: 0 0 var(--share);
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
}

.top {
  background: var(--accent);
  color: var(--on-accent);
}

.second {
  background: var(--accent-half);
  color: var(--on-accent);
}

.schadenfreude {
  background: var(--contrast);
  color: var(--text);
}

.tail {
  background: var(--mood-tail);
  color: var(--text-70);
}

.rest {
  background: var(--mood-rest);
  color: var(--text-55);
}

.line {
  margin-top: 10px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-35);
}
```

Create `web/src/features/topics/StatusFilters.tsx`:

```tsx
import type { TrendStatus } from "@/api/types";

import styles from "./StatusFilters.module.css";

const ORDER: readonly TrendStatus[] = ["trending", "saturating", "cooling", "stale"];

/**
 * The chip row. Clicking the active chip clears the filter — the design
 * draws no "all" chip, so the active one has to be the way back.
 *
 * `status_totals` counts the whole window rather than the filtered list, so
 * every chip keeps its number while one of them is active.
 */
export function StatusFilters({
  totals,
  active,
  onChange,
}: {
  totals: Record<string, number>;
  active: TrendStatus | undefined;
  onChange: (status: TrendStatus | undefined) => void;
}) {
  return (
    <div className={styles.row}>
      {ORDER.map((status) => (
        <button
          key={status}
          type="button"
          aria-pressed={active === status}
          className={[
            styles.chip,
            active === status ? styles.active : "",
            status === "stale" ? styles.stale : "",
          ]
            .filter(Boolean)
            .join(" ")}
          onClick={() => onChange(active === status ? undefined : status)}
        >
          {status} {totals[status] ?? 0}
        </button>
      ))}
    </div>
  );
}
```

Create `web/src/features/topics/StatusFilters.module.css`:

```css
.row {
  display: flex;
  gap: var(--gap-tight);
}

.chip {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: 0.04em;
  padding: 6px 10px;
  border-radius: var(--radius-pill);
  background: var(--chip-fill);
  color: var(--text-70);
  transition: background var(--transition), color var(--transition);
}

.stale {
  color: var(--text-35);
}

.active,
.active.stale {
  background: var(--accent);
  color: var(--on-accent);
}
```

- [ ] **Step 5: Write the two lists**

Create `web/src/features/topics/TopicCard.tsx`:

```tsx
import { Link } from "react-router-dom";

import type { IndexedTopic } from "@/api/types";
import { Chip } from "@/components/Chip";
import { formatScore } from "@/format";

import styles from "./TopicCard.module.css";

/**
 * `▲ SEEN IN 3 RUNS` or `NEW THIS RUN`.
 *
 * A floor rather than a count: the slug fixes case and punctuation drift
 * across runs but not wording drift, so a relabelled topic reads as new.
 * "Seen in" is the honest verb for that; "appeared in exactly 3 runs" is not.
 */
function recurrence(runCount: number): string {
  return runCount > 1 ? `▲ SEEN IN ${runCount} RUNS` : "NEW THIS RUN";
}

export function TopicCard({
  entry,
  highlighted,
}: {
  entry: IndexedTopic;
  highlighted: boolean;
}) {
  const { topic, run_count, render_count } = entry;
  const to = `/topics/${encodeURIComponent(topic.run_id)}/${encodeURIComponent(topic.topic_id)}`;

  return (
    <Link to={to} className={`${styles.card} ${highlighted ? styles.highlighted : ""}`}>
      <span className={styles.head}>
        <span className={styles.recurrence}>{recurrence(run_count)}</span>
        <span className={styles.score}>{formatScore(topic.meme_potential)}</span>
      </span>

      <h3 className={styles.title}>{topic.label}</h3>

      <span className={styles.chips}>
        {topic.event_sentiment != null && <Chip tone="accent">{topic.event_sentiment}</Chip>}
        {topic.conversation_register != null && <Chip>{topic.conversation_register}</Chip>}
      </span>

      <span className={styles.counts}>
        {topic.post_count} posts ·{" "}
        {render_count === 0 ? (
          <span className={styles.noMemes}>no memes yet</span>
        ) : (
          `${render_count} ${render_count === 1 ? "meme" : "memes"}`
        )}
      </span>
    </Link>
  );
}
```

Create `web/src/features/topics/TopicCard.module.css`:

```css
.card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--surface);
  transition: border-color var(--transition);
}

.card:hover {
  border-color: var(--border-hover);
}

.highlighted {
  border-color: var(--accent-border);
  background: var(--accent-wash);
}

.head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--gap-tight);
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--text-40);
}

.score {
  color: var(--accent);
}

.title {
  font-size: 16px;
  font-weight: 700;
  line-height: 1.22;
}

.chips {
  display: flex;
  gap: var(--gap-tight);
  flex-wrap: wrap;
}

.counts {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-35);
}

.noMemes {
  color: var(--accent);
}
```

Create `web/src/features/topics/RecentTable.tsx`:

```tsx
import { Link } from "react-router-dom";

import type { IndexedTopic } from "@/api/types";
import { Chip } from "@/components/Chip";
import { formatScore } from "@/format";

import styles from "./RecentTable.module.css";

/**
 * Saturating and cooling, as rows.
 *
 * 1px gaps over a `divider` background, so the hairlines read as borders
 * without every row carrying one — which is what the handoff specifies and
 * what keeps a long list from looking striped.
 */
export function RecentTable({ topics }: { topics: IndexedTopic[] }) {
  return (
    <div className={styles.table} data-testid="recently-trending">
      {topics.map(({ topic }) => (
        <Link
          key={`${topic.run_id}-${topic.topic_id}`}
          to={`/topics/${encodeURIComponent(topic.run_id)}/${encodeURIComponent(topic.topic_id)}`}
          className={styles.row}
        >
          <span className={styles.title}>{topic.label}</span>
          <span>
            {topic.event_sentiment != null && <Chip>{topic.event_sentiment}</Chip>}
          </span>
          <span className={styles.meta}>{topic.trend_status}</span>
          <span className={styles.meta}>{topic.post_count} posts</span>
          <span className={styles.score}>{formatScore(topic.meme_potential)}</span>
        </Link>
      ))}
    </div>
  );
}
```

Create `web/src/features/topics/RecentTable.module.css`:

```css
.table {
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: var(--divider);
  border-radius: 11px;
  overflow: hidden;
}

.row {
  display: grid;
  grid-template-columns: 1fr 122px 108px 92px 78px;
  gap: var(--gap-tight);
  align-items: center;
  padding: 11px 14px;
  background: var(--surface);
  transition: background var(--transition);
}

.row:hover {
  background: var(--bg);
}

.title {
  font-size: 13px;
  font-weight: 700;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-35);
}

.score {
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 600;
  color: var(--accent);
  text-align: right;
}
```

- [ ] **Step 6: Write the page**

Replace `web/src/features/topics/TopicsPage.tsx` in full:

```tsx
import { useState } from "react";

import type { TrendStatus } from "@/api/types";
import { useRuns, useTopicIndex } from "@/api/queries";
import { EmptyState } from "@/components/EmptyState";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { SectionLabel } from "@/components/SectionLabel";
import { HeroTopic } from "@/features/topics/HeroTopic";
import { MoodBar } from "@/features/topics/MoodBar";
import { RecentTable } from "@/features/topics/RecentTable";
import { StatusFilters } from "@/features/topics/StatusFilters";
import { TopicCard } from "@/features/topics/TopicCard";
import { byRank } from "@/features/topics/ordering";
import { formatClock } from "@/format";

import styles from "./TopicsPage.module.css";

/** Three, matching the run strip phase 6 puts beside the mood bar. */
const RUN_STRIP = 3;
const TRENDING_CARDS = 3;

export function TopicsPage() {
  const [status, setStatus] = useState<TrendStatus | undefined>(undefined);
  const index = useTopicIndex({ status });
  const runs = useRuns(RUN_STRIP);

  return (
    <QueryBoundary query={index} missing="No topics.">
      {(data) => {
        const ordered = byRank(data.topics);
        const hero = ordered[0];
        const trending = ordered.filter(
          (entry) => entry.topic.trend_status === "trending",
        );
        const recent = ordered.filter((entry) =>
          ["saturating", "cooling"].includes(entry.topic.trend_status),
        );
        const latestRun = runs.data?.runs[0];
        const noRunsAtAll = runs.isSuccess && runs.data.runs.length === 0;

        return (
          <div className={styles.page}>
            <header className={styles.header}>
              <h1 className={styles.title}>Right now</h1>
              <MetaLine>
                {[
                  `${data.status_totals.trending ?? 0} trending`,
                  `${data.status_totals.saturating ?? 0} saturating`,
                  `${data.status_totals.cooling ?? 0} cooling`,
                  latestRun === undefined
                    ? "no runs yet"
                    : `as of ${formatClock(latestRun.run.finished_at ?? latestRun.run.started_at)}`,
                ].join(" · ")}
              </MetaLine>
            </header>

            {noRunsAtAll ? (
              <EmptyState
                headline="Nothing has run yet"
                body="A run reads Bluesky, works out what is trending, and generates memes about it. The first one takes a few minutes."
              />
            ) : (
              <>
                {hero !== undefined && (
                  <div className={styles.heroRow}>
                    <HeroTopic entry={hero} />
                  </div>
                )}

                <div className={styles.mood}>
                  <SectionLabel>The mood today</SectionLabel>
                  <MoodBar
                    totals={data.sentiment_totals}
                    previous={data.previous_sentiment_totals}
                  />
                </div>

                <div className={styles.filters}>
                  <StatusFilters
                    totals={data.status_totals}
                    active={status}
                    onChange={setStatus}
                  />
                </div>

                {data.topics.length === 0 ? (
                  status === undefined ? (
                    <EmptyState
                      headline="No topics in the last 6 runs"
                      body="Everything has gone stale. Start a run to see what is trending now."
                    />
                  ) : (
                    <p className={styles.filtered}>No topics with this status.</p>
                  )
                ) : (
                  <>
                    {trending.length > 0 && (
                      <section className={styles.block} data-testid="trending-now">
                        <SectionLabel>Trending now</SectionLabel>
                        <div className={styles.cards}>
                          {trending.slice(0, TRENDING_CARDS).map((entry, position) => (
                            <TopicCard
                              key={`${entry.topic.run_id}-${entry.topic.topic_id}`}
                              entry={entry}
                              highlighted={position === 0}
                            />
                          ))}
                        </div>
                      </section>
                    )}

                    {recent.length > 0 && (
                      <section className={styles.block}>
                        <SectionLabel>Recently trending — saturating &amp; cooling</SectionLabel>
                        <RecentTable topics={recent} />
                      </section>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        );
      }}
    </QueryBoundary>
  );
}
```

Create `web/src/features/topics/TopicsPage.module.css`:

```css
.page {
  display: flex;
  flex-direction: column;
  gap: var(--gap-section);
}

.header {
  margin-bottom: 6px;
}

.title {
  font-size: 22px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: -0.03em;
}

/* `1.55fr 1fr` in the handoff, where the second column is the latest meme
   tile. That tile needs a render id, which `TopicIndex` does not carry;
   phase 6's run strip lands in the same bottom row and phase 7 owns the
   meme grid, so the hero spans the width here rather than sitting beside an
   empty column. */
.heroRow {
  display: grid;
  grid-template-columns: 1fr;
}

.mood,
.block {
  margin-top: 6px;
}

.cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 11px;
}

.filtered {
  padding: 24px 0;
  text-align: center;
  font-size: 12.5px;
  color: var(--text-35);
}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `npm --prefix web test -- topics`

Expected: every case green.

- [ ] **Step 8: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest && npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

- [ ] **Step 9: Commit**

```bash
git add web/src/features/topics
git commit -m "Build the merged Topics screen: hero, mood bar, filters and both lists"
```

---

### Task 10: Topic detail — the dossier, the replies, the phrases and the grid

Everything on `2e` except the two generation panels and the tile states that go with them, which are phase 7's.

**Files:**
- Create: `web/src/features/topics/DossierCards.tsx` + `.module.css`, `ReplyList.tsx` + `.module.css`, `PhraseCard.tsx` + `.module.css`, `RenderGrid.tsx` + `.module.css`
- Test: `web/src/features/topics/TopicDetailPage.test.tsx`
- Modify: `web/src/features/topics/TopicDetailPage.tsx` (replacing Task 6's placeholder), and add `TopicDetailPage.module.css`

**Interfaces:**
- Consumes: `useTopicDetail`, `useRun`, `Breadcrumb`, `Chip`, `SectionLabel`, `MemeTile`, `QueryBoundary`, `formatScore`, `formatClock`, `shortRunId`.
- Produces: `<RenderGrid renders={RenderRecord[]} runId={string} />`, which phase 7 extends with the generating and confirming tile states.

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/topics/TopicDetailPage.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { TopicDetail } from "@/api/types";
import { TopicDetailPage } from "@/features/topics/TopicDetailPage";
import {
  makeDossier,
  makeRenderRecord,
  makeRunDetail,
  makeTopicDetail,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

const RUN_ID = "20260829T090000Z";
const TOPIC_ID = "topic-1";

function serve(detail: TopicDetail = makeTopicDetail()) {
  server.use(
    http.get("/api/runs/:runId/topics/:topicId", () => HttpResponse.json(detail)),
    http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
  );
}

function renderPage() {
  return renderWithProviders(<TopicDetailPage />, {
    route: `/topics/${RUN_ID}/${TOPIC_ID}`,
    path: "/topics/:runId/:topicId",
  });
}

describe("TopicDetailPage", () => {
  it("titles the page with the topic's label", async () => {
    serve(makeTopicDetail({ label: "Airport cat" }));

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Airport cat", level: 1 }),
    ).toBeInTheDocument();
  });

  it("breadcrumbs with the topic id and the run it was first seen in", async () => {
    serve(makeTopicDetail({ firstSeenRunId: "20260826T090000Z" }));

    renderPage();

    const crumb = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumb).getByRole("link", { name: "Topics" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(
      within(crumb).getByText("topic-1 · first seen 20260826T090000Z"),
    ).toBeInTheDocument();
  });

  it("says a topic is new when no earlier run carried it", async () => {
    // `first_seen_run_id` is null when the slug matched nothing earlier.
    // "first seen null" would be a bug on screen.
    serve(makeTopicDetail({ firstSeenRunId: null, runCount: 1 }));

    renderPage();

    const crumb = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumb).getByText("topic-1 · new this run")).toBeInTheDocument();
  });

  it("shows the three header stats", async () => {
    serve(
      makeTopicDetail({ trendScore: 0.91, memePotential: 0.86, finalRank: 2 }),
    );

    renderPage();

    const stats = await screen.findByTestId("stats");
    expect(within(stats).getByText("0.91")).toBeInTheDocument();
    expect(within(stats).getByText("0.86")).toBeInTheDocument();
    expect(within(stats).getByText("2")).toBeInTheDocument();
  });

  it("draws the dossier prose and its entity chips", async () => {
    serve(
      makeTopicDetail({
        dossier: makeDossier({
          what_happened: "A cat got loose in an airport terminal.",
          conversation_summary: "Everyone is writing its incident report.",
          key_entities: ["the cat", "ground staff"],
        }),
      }),
    );

    renderPage();

    expect(
      await screen.findByText("A cat got loose in an airport terminal."),
    ).toBeInTheDocument();
    expect(screen.getByText("Everyone is writing its incident report.")).toBeInTheDocument();
    expect(screen.getByText("the cat")).toBeInTheDocument();
    expect(screen.getByText("ground staff")).toBeInTheDocument();
  });

  it("lists the score components under the conversation card", async () => {
    serve(
      makeTopicDetail({ scoreComponents: { bluesky: 0.91, corroboration: 1.0 } }),
    );

    renderPage();

    expect(
      await screen.findByText("score_components · bluesky 0.91 · corroboration 1.00"),
    ).toBeInTheDocument();
  });

  it("still renders when the topic has no dossier", async () => {
    // The dormant path and a stale checkpoint both give dossier=null. The
    // topic was still ranked, so the row still exists and the page must not
    // blank out.
    serve(makeTopicDetail({ dossier: null, scoreComponents: {} }));

    renderPage();

    expect(await screen.findByRole("heading", { name: "Airport cat" })).toBeInTheDocument();
    expect(screen.getByText("No dossier was written for this topic.")).toBeInTheDocument();
  });

  it("shows the replies with their likes, and says no handles are stored", async () => {
    serve(
      makeTopicDetail({
        replies: [
          {
            text: "ground control to major tom",
            like_count: 1412,
            created_at: "2026-08-29T14:31:00Z",
          },
        ],
      }),
    );

    renderPage();

    expect(await screen.findByText("ground control to major tom")).toBeInTheDocument();
    expect(screen.getByText("1,412 likes · 14:31")).toBeInTheDocument();
    expect(screen.getByText(/no handles stored/i)).toBeInTheDocument();
  });

  it("ranks the recurring phrases and reports the threshold that filtered them", async () => {
    serve(
      makeTopicDetail({
        dossier: makeDossier({
          recurring_phrases: [
            { text: "absolute unit", occurrences: 48, distinct_authors: 31 },
            { text: "ground control", occurrences: 22, distinct_authors: 14 },
          ],
        }),
      }),
    );

    renderPage();

    expect(await screen.findByText("absolute unit")).toBeInTheDocument();
    expect(screen.getByText("48× · 31 authors")).toBeInTheDocument();
    // The run's own frozen threshold, from RunDetail — TopicDetail does not
    // carry the config, and the count of phrases *below* it is nowhere in
    // the contract, so the line names the threshold rather than a total.
    expect(screen.getByText("filtered at phrase_min_authors=3")).toBeInTheDocument();
  });

  it("draws a tile per render, linked to its full-size view", async () => {
    serve(
      makeTopicDetail({
        renders: [
          makeRenderRecord({ id: "r1", templateId: "drake" }),
          makeRenderRecord({ id: "r2", templateId: "two_buttons" }),
        ],
      }),
    );

    renderPage();

    expect(await screen.findByAltText("drake meme")).toBeInTheDocument();
    const links = screen.getAllByRole("link");
    expect(
      links.some((link) => link.getAttribute("href") === `/runs/${RUN_ID}/renders/r1`),
    ).toBe(true);
  });

  it("says how many memes came from which run", async () => {
    serve(
      makeTopicDetail({
        renders: [makeRenderRecord({ id: "r1" }), makeRenderRecord({ id: "r2" })],
      }),
    );

    renderPage();

    expect(await screen.findByText("2 from …829T090000Z")).toBeInTheDocument();
  });

  it("shows only the renders that have an image behind them", async () => {
    // A `generating` row has no PNG yet and a `failed` one never will.
    // Phase 7 draws both states; this phase draws neither, so a tile with
    // nothing behind it must not appear.
    serve(
      makeTopicDetail({
        renders: [
          makeRenderRecord({ id: "r1", status: "ready" }),
          makeRenderRecord({ id: "r2", status: "generating" }),
          makeRenderRecord({ id: "r3", status: "failed", error: "caption too long" }),
        ],
      }),
    );

    renderPage();

    expect(await screen.findByText("1 from …829T090000Z")).toBeInTheDocument();
    expect(screen.getAllByRole("img")).toHaveLength(1);
  });

  it("draws no render section at all when nothing has rendered yet", async () => {
    // Not the same as hiding the tiles: an empty section would show the
    // label and a "0 from …" hint under it, which is a worse answer than
    // saying nothing. Phase 7 replaces this with the designed dashed row.
    serve(makeTopicDetail({ renders: [] }));

    renderPage();

    await screen.findByRole("heading", { name: "Airport cat" });
    expect(screen.queryByText("Rendered from this topic")).not.toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("says which topic is missing rather than showing an empty page", async () => {
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json({ detail: "No such topic" }, { status: 404 }),
      ),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
    );

    renderPage();

    expect(await screen.findByText("No such topic in this run.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- TopicDetailPage`

Expected: FAIL — the page renders `null`.

- [ ] **Step 3: Write the dossier cards**

Create `web/src/features/topics/DossierCards.tsx`:

```tsx
import type { Dossier } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";
import { formatScore } from "@/format";

import styles from "./DossierCards.module.css";

export function DossierCards({
  dossier,
  scoreComponents,
}: {
  dossier: Dossier | null;
  scoreComponents: Record<string, number>;
}) {
  if (dossier === null) {
    // The dormant path and a stale checkpoint. The topic was still ranked,
    // so the page keeps its header and its ranking context and says what is
    // missing rather than blanking out.
    return <p className={styles.absent}>No dossier was written for this topic.</p>;
  }

  const components = Object.entries(scoreComponents)
    .map(([name, value]) => `${name} ${formatScore(value)}`)
    .join(" · ");

  return (
    <div className={styles.grid}>
      <section className={styles.card}>
        <SectionLabel>What happened</SectionLabel>
        <p className={styles.prose}>{dossier.what_happened}</p>
        {(dossier.key_entities ?? []).length > 0 && (
          <ul className={styles.entities}>
            {(dossier.key_entities ?? []).map((entity) => (
              <li key={entity} className={styles.entity}>
                {entity}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.card}>
        <SectionLabel>How the conversation is going</SectionLabel>
        <p className={styles.prose}>{dossier.conversation_summary}</p>
        {components !== "" && (
          <>
            <hr className={styles.rule} />
            <p className={styles.components}>score_components · {components}</p>
          </>
        )}
      </section>
    </div>
  );
}
```

Create `web/src/features/topics/DossierCards.module.css`:

```css
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--gap-section);
}

.card {
  padding: 15px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface);
}

.prose {
  font-size: 13px;
  line-height: 1.55;
  color: var(--text-70);
}

.entities {
  margin-top: 10px;
  display: flex;
  gap: var(--gap-tight);
  flex-wrap: wrap;
}

.entity {
  padding: 5px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-55);
}

.rule {
  margin: 12px 0;
  border: none;
  border-top: 1px solid var(--divider);
}

.components {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-35);
}

.absent {
  padding: 24px 0;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-35);
}
```

- [ ] **Step 4: Write the replies, the phrases and the grid**

Create `web/src/features/topics/ReplyList.tsx`:

```tsx
import type { ReplyOut } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";
import { formatClock } from "@/format";

import styles from "./ReplyList.module.css";

/**
 * Every reply gets the accent left border.
 *
 * The design draws accent when a reply matches the dominant sentiment and
 * white 15% when it does not, and says that border is the only signal on
 * these cards. Nothing computes per-reply sentiment, and doing it properly
 * is a model call per reply. Fabricating the signal on a screen whose whole
 * purpose is showing what people actually said would be worse than not
 * having it — so it is absent, and the spec has flagged it back to the
 * designer as needing either a real source or removal.
 *
 * No author, handle or avatar: `ReplyOut` carries none, and an API that
 * returned them would undo the project's own no-personal-data position.
 */
export function ReplyList({ replies }: { replies: ReplyOut[] }) {
  return (
    <section>
      <SectionLabel hint="no handles stored">Replies</SectionLabel>
      <ul className={styles.list}>
        {replies.map((reply, index) => (
          <li key={`${reply.created_at}-${index}`} className={styles.reply}>
            <p className={styles.text}>{reply.text}</p>
            <span className={styles.meta}>
              {reply.like_count.toLocaleString("en-GB")} likes ·{" "}
              {formatClock(reply.created_at)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

Create `web/src/features/topics/ReplyList.module.css`:

```css
.list {
  display: flex;
  flex-direction: column;
  gap: var(--gap-tight);
}

.reply {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-left: 2px solid var(--accent);
  border-radius: 0 7px 7px 0;
  background: var(--surface);
}

.text {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-70);
}

.meta {
  display: block;
  margin-top: 6px;
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-35);
}
```

Create `web/src/features/topics/PhraseCard.tsx`:

```tsx
import type { Phrase } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";

import styles from "./PhraseCard.module.css";

/**
 * 15px, 13px, then 12px for everything after — the design's three steps.
 *
 * No explicit return type: under `noUncheckedIndexedAccess`, a CSS module's
 * properties type as `string | undefined`, same as `StatusPill`'s `tone`.
 */
function sizeClass(index: number) {
  if (index === 0) return styles.first;
  if (index === 1) return styles.second;
  return styles.rest;
}

export function PhraseCard({
  phrases,
  minAuthors,
}: {
  phrases: Phrase[];
  /**
   * The run's own frozen `phrase_min_authors`, from `RunDetail`.
   * `TopicDetail` does not carry the config, and the number of phrases that
   * fell *below* the threshold is nowhere in the contract — so the footer
   * names the threshold rather than claiming a count of what it removed.
   */
  minAuthors: number | undefined;
}) {
  return (
    <section className={styles.card}>
      <SectionLabel>Recurring phrases</SectionLabel>
      <ul className={styles.list}>
        {phrases.map((phrase, index) => (
          <li key={phrase.text}>
            <span className={`${styles.phrase} ${sizeClass(index)}`}>{phrase.text}</span>
            <span className={styles.meta}>
              {phrase.occurrences}× · {phrase.distinct_authors} authors
            </span>
          </li>
        ))}
      </ul>
      {minAuthors !== undefined && (
        <p className={styles.footer}>filtered at phrase_min_authors={minAuthors}</p>
      )}
    </section>
  );
}
```

Create `web/src/features/topics/PhraseCard.module.css`:

```css
.card {
  padding: 15px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface);
}

.list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.phrase {
  display: block;
  font-weight: 700;
  line-height: 1.25;
}

.first {
  font-size: 15px;
  color: var(--accent);
}

.second {
  font-size: 13px;
  color: var(--text);
}

.rest {
  font-size: 12px;
  color: var(--text-70);
}

.meta {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-35);
}

.footer {
  margin-top: 12px;
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-30);
}
```

Create `web/src/features/topics/RenderGrid.tsx`:

```tsx
import { Link } from "react-router-dom";

import type { RenderRecord } from "@/api/types";
import { MemeTile } from "@/components/MemeTile";
import { SectionLabel } from "@/components/SectionLabel";
import { shortRunId } from "@/format";

import styles from "./RenderGrid.module.css";

/**
 * The 4-up grid of what was rendered from this topic.
 *
 * Only `ready` renders are drawn. A `generating` row has no PNG yet and a
 * `failed` one never will; both states are designed and both belong to
 * phase 7, along with the two tile states that go with them and the
 * nothing-rendered-yet row.
 */
export function RenderGrid({
  renders,
  runId,
}: {
  renders: RenderRecord[];
  runId: string;
}) {
  const ready = renders.filter((render) => render.status === "ready");
  if (ready.length === 0) return null;

  return (
    <section className={styles.section}>
      <SectionLabel hint={`${ready.length} from ${shortRunId(runId)}`}>
        Rendered from this topic
      </SectionLabel>
      <ul className={styles.grid}>
        {ready.map((render) => (
          <li key={render.id} className={styles.cell}>
            <MemeTile
              renderId={render.id}
              size={96}
              templateId={render.template_id}
              to={`/runs/${encodeURIComponent(runId)}/renders/${encodeURIComponent(render.id)}`}
            />
            <Link
              to={`/runs/${encodeURIComponent(runId)}/renders/${encodeURIComponent(render.id)}`}
              className={styles.footer}
            >
              {render.template_id} · {render.origin.provenance}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

Create `web/src/features/topics/RenderGrid.module.css`:

```css
.section {
  margin-top: var(--gap-page);
}

.grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--gap-card);
}

.cell {
  display: flex;
  flex-direction: column;
  gap: var(--gap-tight);
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-tile);
  background: var(--surface);
}

.footer {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-35);
}

.footer:hover {
  color: var(--text-70);
}
```

- [ ] **Step 5: Write the page**

Replace `web/src/features/topics/TopicDetailPage.tsx` in full:

```tsx
import { useParams } from "react-router-dom";

import { useRun, useTopicDetail } from "@/api/queries";
import { Breadcrumb } from "@/components/Breadcrumb";
import { Chip } from "@/components/Chip";
import { QueryBoundary } from "@/components/QueryBoundary";
import { DossierCards } from "@/features/topics/DossierCards";
import { PhraseCard } from "@/features/topics/PhraseCard";
import { RenderGrid } from "@/features/topics/RenderGrid";
import { ReplyList } from "@/features/topics/ReplyList";
import { formatScore } from "@/format";

import styles from "./TopicDetailPage.module.css";

export function TopicDetailPage() {
  const { runId, topicId } = useParams();
  const detail = useTopicDetail(runId, topicId);
  // Only for `phrase_min_authors`: TopicDetail carries no config, and the
  // phrases footer names the run's own frozen threshold.
  const run = useRun(runId);

  return (
    <QueryBoundary query={detail} missing="No such topic in this run.">
      {(data) => {
        const { topic, dossier, recurrence } = data;
        const seen =
          recurrence.first_seen_run_id === null
            ? "new this run"
            : `first seen ${recurrence.first_seen_run_id}`;

        return (
          <div className={styles.page}>
            <Breadcrumb
              trail={[{ label: "Topics", to: "/" }, { label: `${topic.topic_id} · ${seen}` }]}
            />

            <header className={styles.header}>
              <div>
                <h1 className={styles.title}>{topic.label}</h1>
                <div className={styles.chips}>
                  {topic.event_sentiment != null && (
                    <Chip tone="accent">{topic.event_sentiment}</Chip>
                  )}
                  {topic.conversation_register != null && (
                    <Chip>{topic.conversation_register}</Chip>
                  )}
                  {(dossier?.secondary_registers ?? []).length > 0 && (
                    <Chip>{`2nd: ${(dossier?.secondary_registers ?? []).join(", ")}`}</Chip>
                  )}
                  <Chip tone="contrast">{topic.trend_status}</Chip>
                </div>
              </div>

              <dl className={styles.stats} data-testid="stats">
                <div>
                  <dt>TREND</dt>
                  <dd>{formatScore(topic.trend_score)}</dd>
                </div>
                <div>
                  <dt>MEME</dt>
                  <dd className={styles.meme}>{formatScore(topic.meme_potential)}</dd>
                </div>
                <div>
                  <dt>RANK</dt>
                  <dd>{topic.final_rank}</dd>
                </div>
              </dl>
            </header>

            <DossierCards dossier={dossier} scoreComponents={data.score_components} />

            <div className={styles.conversation}>
              <ReplyList replies={data.replies} />
              <PhraseCard
                phrases={dossier?.recurring_phrases ?? []}
                minAuthors={run.data?.run.config.phrase_min_authors}
              />
            </div>

            <RenderGrid renders={data.renders} runId={topic.run_id} />
          </div>
        );
      }}
    </QueryBoundary>
  );
}
```

The header renders `2nd: delight, awe` from `secondary_registers`. The handoff labels that chip as secondary *sentiments*; `Dossier` has no such field and does have `secondary_registers`, so the chip shows what the pipeline actually records. Task 12 records this alongside the other decisions taken against the handoff.

Create `web/src/features/topics/TopicDetailPage.module.css`:

```css
.page {
  max-width: var(--content-width);
  display: flex;
  flex-direction: column;
  gap: var(--gap-section);
}

.header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gap-page);
}

.title {
  font-size: 28px;
  font-weight: 800;
  line-height: 1.12;
  letter-spacing: -0.03em;
}

.chips {
  margin-top: 10px;
  display: flex;
  gap: var(--gap-tight);
  flex-wrap: wrap;
}

.stats {
  display: flex;
  gap: 22px;
  text-align: right;
  flex: none;
}

.stats dt {
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--text-40);
}

.stats dd {
  margin: 4px 0 0;
  font-size: 22px;
  font-weight: 700;
  line-height: 1;
}

.meme {
  color: var(--accent);
}

.conversation {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: var(--gap-section);
  align-items: start;
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npm --prefix web test -- TopicDetailPage`

Expected: every case green.

- [ ] **Step 7: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest && npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

- [ ] **Step 8: Commit**

```bash
git add web/src/features/topics
git commit -m "Build topic detail: the dossier, the replies, the phrases and the grid"
```

---

### Task 11: the full-size meme view

The largest gap the handoff flagged, designed in the spec and built here. Deep-linkable, which is why `GET /api/renders/{id}` exists rather than renders arriving only embedded in topic detail.

**Files:**
- Test: `web/src/features/renders/RenderDetailPage.test.tsx`
- Modify: `web/src/features/renders/RenderDetailPage.tsx` (replacing Task 6's placeholder), and add `RenderDetailPage.module.css`

**Interfaces:**
- Consumes: `useRender`, `useTopicDetail`, `imageUrl`, `Breadcrumb`, `Chip`, `SectionLabel`, `MetaLine`, `QueryBoundary`.
- Produces: nothing other tasks consume. Phase 7 adds the **Delete** ghost button and its inline confirm to this page's footer.

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/renders/RenderDetailPage.test.tsx`:

```tsx
import { fireEvent, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { RenderRecord } from "@/api/types";
import { RenderDetailPage } from "@/features/renders/RenderDetailPage";
import { makeRenderRecord, makeTopicDetail } from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

const RUN_ID = "20260829T090000Z";
const RENDER_ID = "render-1";

function serve(record: RenderRecord = makeRenderRecord()) {
  server.use(
    http.get("/api/renders/:renderId", () => HttpResponse.json(record)),
    http.get("/api/runs/:runId/topics/:topicId", () =>
      HttpResponse.json(makeTopicDetail({ label: "Airport cat" })),
    ),
  );
}

function renderPage() {
  return renderWithProviders(<RenderDetailPage />, {
    route: `/runs/${RUN_ID}/renders/${RENDER_ID}`,
    path: "/runs/:runId/renders/:renderId",
  });
}

describe("RenderDetailPage", () => {
  it("shows the PNG at full size, not the thumbnail", async () => {
    serve();

    renderPage();

    expect(await screen.findByRole("img")).toHaveAttribute(
      "src",
      `/api/renders/${RENDER_ID}/image?size=full`,
    );
  });

  it("breadcrumbs through the topic to the template", async () => {
    serve(makeRenderRecord({ templateId: "drake" }));

    renderPage();

    const crumb = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumb).getByRole("link", { name: "Topics" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(
      await within(crumb).findByRole("link", { name: "Airport cat" }),
    ).toHaveAttribute("href", `/topics/${RUN_ID}/topic-1`);
    expect(within(crumb).getByText("drake")).toBeInTheDocument();
  });

  it("chips the template and the provenance", async () => {
    serve(makeRenderRecord({ templateId: "drake" }));

    renderPage();

    const chips = await screen.findByTestId("chips");
    expect(within(chips).getByText("drake")).toBeInTheDocument();
    expect(within(chips).getByText("auto")).toBeInTheDocument();
  });

  it("lays out one block per caption slot, with the slot's real name", async () => {
    serve(
      makeRenderRecord({
        captionSlots: {
          rejected: "Filing an incident report",
          preferred: "Becoming the incident",
        },
      }),
    );

    renderPage();

    expect(await screen.findByText("rejected")).toBeInTheDocument();
    expect(screen.getByText("Filing an incident report")).toBeInTheDocument();
    expect(screen.getByText("preferred")).toBeInTheDocument();
    expect(screen.getByText("Becoming the incident")).toBeInTheDocument();
  });

  it("explains the model's choice on an auto render", async () => {
    serve(makeRenderRecord({ rationale: "Two panels, one reversal." }));

    renderPage();

    expect(await screen.findByText("Why this template")).toBeInTheDocument();
    expect(screen.getByText("Two panels, one reversal.")).toBeInTheDocument();
  });

  it("says a hand-written render was hand-written, and explains nothing", async () => {
    // The AutoOrigin/ManualOrigin split is what makes this a presence check
    // rather than an empty-string check: a manual render has no rationale
    // field at all.
    serve(makeRenderRecord({ rationale: null }));

    renderPage();

    expect(await screen.findByText("written by hand")).toBeInTheDocument();
    expect(screen.queryByText("Why this template")).not.toBeInTheDocument();
    expect(screen.getByText("manual")).toBeInTheDocument();
  });

  it("offers the PNG for download", async () => {
    serve();

    renderPage();

    const download = await screen.findByRole("link", { name: "Download PNG" });
    expect(download).toHaveAttribute("href", `/api/renders/${RENDER_ID}/image?size=full`);
    expect(download).toHaveAttribute("download");
  });

  it("reports the image's real dimensions once it has loaded", async () => {
    // The contract carries no width, height or byte size for a render, so
    // the page reads what the browser decoded rather than claiming numbers
    // nothing sent it.
    serve();

    renderPage();

    const image = await screen.findByRole("img");
    Object.defineProperty(image, "naturalWidth", { value: 1180, configurable: true });
    Object.defineProperty(image, "naturalHeight", { value: 1180, configurable: true });
    fireEvent.load(image);

    expect(await screen.findByText(/1180×1180/)).toBeInTheDocument();
  });

  it("carries the run id and created time in its metadata line", async () => {
    // Both parts, on the same element. Asserting only that the run id
    // appears somewhere would pass with the timestamp dropped from the
    // joined line entirely.
    serve(makeRenderRecord({ createdAt: "2026-08-29T14:31:00Z" }));

    renderPage();

    const line = await screen.findByText(new RegExp(RUN_ID));
    expect(line).toHaveTextContent("14:31");
  });

  it("says which render is missing rather than showing an empty frame", async () => {
    server.use(
      http.get("/api/renders/:renderId", () =>
        HttpResponse.json({ detail: "No such render" }, { status: 404 }),
      ),
    );

    renderPage();

    expect(await screen.findByText("No such render.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- RenderDetailPage`

Expected: FAIL — the page renders `null`.

- [ ] **Step 3: Write the page**

Replace `web/src/features/renders/RenderDetailPage.tsx` in full:

```tsx
import { useState } from "react";
import { useParams } from "react-router-dom";

import { imageUrl } from "@/api/client";
import { useRender, useTopicDetail } from "@/api/queries";
import { Breadcrumb } from "@/components/Breadcrumb";
import { Chip } from "@/components/Chip";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { SectionLabel } from "@/components/SectionLabel";
import { formatClock } from "@/format";

import styles from "./RenderDetailPage.module.css";

export function RenderDetailPage() {
  const { renderId } = useParams();
  const render = useRender(renderId);
  // The breadcrumb wants the topic's title, which `RenderRecord` does not
  // carry — it carries the ids that address it.
  const topic = useTopicDetail(render.data?.run_id, render.data?.topic_id);
  const [size, setSize] = useState<string>("");

  return (
    <QueryBoundary query={render} missing="No such render.">
      {(record) => (
        <div className={styles.page}>
          <Breadcrumb
            trail={[
              { label: "Topics", to: "/" },
              {
                label: topic.data?.topic.label ?? record.topic_id,
                to: `/topics/${encodeURIComponent(record.run_id)}/${encodeURIComponent(record.topic_id)}`,
              },
              { label: record.template_id },
            ]}
          />

          <header className={styles.header}>
            <h1 className={styles.title}>
              {topic.data?.topic.label ?? record.topic_id}
            </h1>
            <div className={styles.chips} data-testid="chips">
              <Chip tone="accent">{record.template_id}</Chip>
              <Chip>{record.origin.provenance}</Chip>
            </div>
            <MetaLine>
              {[record.run_id, formatClock(record.created_at), size]
                .filter((part) => part !== "")
                .join(" · ")}
            </MetaLine>
          </header>

          <div className={styles.body}>
            <figure className={styles.frame}>
              <img
                className={styles.image}
                src={imageUrl(record.id, "full")}
                alt={`${record.template_id} meme`}
                // The contract carries no dimensions or byte size for a
                // render, so this reports what the browser decoded rather
                // than numbers nothing sent it.
                onLoad={(event) =>
                  setSize(
                    `${event.currentTarget.naturalWidth}×${event.currentTarget.naturalHeight}`,
                  )
                }
              />
            </figure>

            <aside className={styles.brief}>
              <SectionLabel>The brief</SectionLabel>
              <dl className={styles.slots}>
                {Object.entries(record.caption_slots).map(([slot, caption]) => (
                  <div key={slot} className={styles.slot}>
                    <dt className={styles.slotName}>{slot}</dt>
                    <dd className={styles.caption}>{caption}</dd>
                  </div>
                ))}
              </dl>

              {record.origin.provenance === "auto" ? (
                <>
                  <SectionLabel>Why this template</SectionLabel>
                  <p className={styles.rationale}>{record.origin.rationale}</p>
                </>
              ) : (
                <p className={styles.byHand}>written by hand</p>
              )}

              <div className={styles.footer}>
                <a
                  className={styles.download}
                  href={imageUrl(record.id, "full")}
                  download={`${record.template_id}-${record.id}.png`}
                >
                  Download PNG
                </a>
              </div>
            </aside>
          </div>
        </div>
      )}
    </QueryBoundary>
  );
}
```

`record.origin.provenance === "auto"` narrows the discriminated union, so `record.origin.rationale` type-checks without a cast — which is exactly why phase 1 made `Origin` discriminated, and why a manual render with a rationale is unrepresentable rather than merely discouraged.

Create `web/src/features/renders/RenderDetailPage.module.css`:

```css
.page {
  max-width: var(--content-width);
}

.header {
  margin-bottom: var(--gap-section);
}

.title {
  font-size: 28px;
  font-weight: 800;
  line-height: 1.12;
  letter-spacing: -0.03em;
}

.chips {
  margin: 10px 0 6px;
  display: flex;
  gap: var(--gap-tight);
}

.body {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: var(--gap-section);
  align-items: start;
}

.frame {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px;
  background: var(--surface-log);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
}

/* Never upscaled past its natural size: these are 1180px templates, and a
   stretched meme looks broken. */
.image {
  max-width: 100%;
  max-height: 70vh;
  width: auto;
  height: auto;
  object-fit: contain;
}

.brief {
  padding: 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 9px;
}

.slots {
  margin: 0 0 14px;
}

.slot + .slot {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--divider);
}

.slotName {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-40);
}

.caption {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.55;
}

.rationale {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-70);
}

.byHand {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-35);
}

.footer {
  margin-top: 16px;
}

.download {
  display: inline-flex;
  align-items: center;
  padding: 9px 14px;
  border-radius: var(--radius-pill);
  background: var(--accent);
  color: var(--on-accent);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- RenderDetailPage`

Expected: every case green.

- [ ] **Step 5: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest && npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

- [ ] **Step 6: Commit**

```bash
git add web/src/features/renders
git commit -m "Build the full-size meme view"
```

---

### Task 12: run it against a real run, then write down what changed

The phase's stated end is "any run the harness has produced browsable end to end, including one that failed and one that half-succeeded". Nothing so far has proved that against a real database — every test has run against MSW. This task does, and then records the phase.

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-09-02-web-ui-design.md`

- [ ] **Step 1: Browse a real run end to end**

In one terminal:

```bash
uv run zeitgeist
```

In another:

```bash
npm --prefix web run dev
```

Open the Vite URL and walk every screen against whatever `data/zeitgeist.db` holds:

- `/` — the hero, the mood bar, both lists, and each filter chip including `stale`.
- `/runs` — a completed row and, if one exists, a failed row.
- `/runs/<id>` — four stage cards, the config line, the ranking, the cut line.
- `/topics/<run>/<topic>` — the dossier, the replies, the phrases, the grid.
- `/runs/<run>/renders/<id>` — reached by clicking a tile, and again by pasting the URL into a new tab. The second is what "deep-linkable" means and the first does not prove it.

If the database has no failed run and no partially failed one, make them rather than skipping the check — this phase's failure presentations are otherwise unverified against real data:

```bash
uv run python - <<'PY'
from datetime import UTC, datetime
from zeitgeist.config import Settings
from zeitgeist.records import RunConfig, RunError, Stage
from zeitgeist.store import Store

settings = Settings()
store = Store(settings.db_path)
store.init_schema()

run_id = "20260101T000000Z"
store.start_run(run_id, RunConfig.freeze(settings, None))
store.fail_run(
    run_id,
    RunError(kind="SourceError", message="no trends returned", stage=Stage.INGEST),
)
store.close()
print(f"Seeded a source-outage run: {run_id}")
PY
```

Confirm on `/runs` that it reads `SourceError in ingest — no trends returned`, `nothing written` and `re-run ↗`, and on its detail page that the four stage cards all read `queued` except none. Then delete the row, or leave it — the data is disposable.

Check the two failure paths the browser is the only place to see: stop uvicorn and reload a screen (every page should show the server's failure, not a blank frame), and rename one PNG under `output/<run>/renders/` (its tile should read `failed`, and the rest of the page should be untouched).

- [ ] **Step 2: Fix anything that walk turned up, then re-run the gates**

Any fix belongs in the task that owns the file, with a test that would have caught it. A fix with no test is a fix that comes back.

- [ ] **Step 3: Document the web UI in the README**

Add after the phase 4 paragraphs in "## The web UI":

````markdown
Phase 5 adds the browser half. Development is two processes:

```bash
uv run zeitgeist
```

```bash
npm --prefix web run dev
```

Vite serves the SPA and proxies `/api` to uvicorn on 8000, so the app is
same-origin in development and there is no CORS anywhere in the project.
Open the URL Vite prints.

Five screens, all read-only in this phase: Topics (`/`), Runs (`/runs`), run
detail (`/runs/<id>`), topic detail (`/topics/<run>/<topic>`) and the
full-size meme view (`/runs/<run>/renders/<id>`). Starting a run, the live
log and the settings screen are phase 6; generating a meme from the browser
is phase 7. Until then a run is started with `scripts/run_pipeline.py` or
`POST /api/runs`, and the UI shows what it produced.

The client's TypeScript types are generated from the API's own OpenAPI
schema and checked in. After changing any response model, regenerate both:

```bash
uv run python scripts/dump_openapi.py
```

```bash
npm --prefix web run generate:types
```

`uv run pytest` fails if `web/openapi.json` no longer matches the app, and
`npm --prefix web run typecheck` fails if `web/src/api/schema.ts` no longer
matches `web/openapi.json`. Between them there is no way to change the
contract on one side and not the other without the gate saying so.
````

Also update the "## Tests" section, which currently describes the Python suite alone:

````markdown
## Tests

```bash
uv run pytest
```

```bash
npm --prefix web test
```

No test touches the network. Every LLM call goes through `FakeLLMProvider`,
and the frontend's requests are intercepted by MSW with handlers typed from
the generated OpenAPI types — so a backend contract change breaks frontend
tests rather than surfacing in the browser.
````

- [ ] **Step 4: Record the phase's decisions in the spec**

The spec's "Decisions taken against the handoff" lists the calls made before any screen existed. Building them surfaced five more, each forced by the contract phase 4 froze. Add them to that section:

````markdown
**The ranking row shows a meme count, not thumbnails.** The design draws
42px tiles in the ranking's fifth column. `GET /api/runs/{id}/topics`
returns `render_count` — `Store.render_counts`, ready renders only — and no
render ids, and addressing an image needs an id. Drawing the tiles would
mean one extra request per row to show what topic detail shows one click
away, so the row states the count.

**The Runs pill drops the `3 of 5` partial form.** `RunSummary.render_ids`
comes from `Store.renders_for_run`, which filters on nothing and so counts
`ready`, `generating` and `failed` alike. Partial failure is shown where the
contract carries it: run detail's generate stage card renders
`StageRecord.summary`, which the pipeline already writes as `3 of 5
rendered`, and a thumbnail whose PNG is missing renders as the designed
failed tile.

**The mood line reports sentiment only.** The handoff has it cover register
skew and average meme potential against the previous run. `TopicIndex`
carries neither, so the line names the leading sentiment, its share of the
window, and its change against the previous run. The comparison is dropped
rather than shown as zero when there is no previous run.

**The Runs metadata line counts the page, and names every status.** `GET
/api/runs` is cursor-paginated and returns no archive totals, so `27 total ·
24 ok · 3 failed` becomes `25 shown · 22 ok · 2 failed · 1 aborted`. The
handoff's `ok · failed` pair does not fit a `RunStatus` with five members:
grouping everything-not-ok under "failed" calls an aborted run a failure,
and counting only those two prints a total the parts do not add up to.
Every distinct source across the page is named rather than one claimed.

**The secondary chip shows secondary registers.** The design's `2nd:
delight, awe` is labelled as secondary sentiments. `Dossier` has no such
field and does have `secondary_registers`, so the chip shows what the
pipeline actually records.
````

Also mark phase 5 done in the "Phases" section by prefixing its paragraph with `**Landed.**`, matching however phases 1–4 were marked when they landed. If they were not marked, do not invent a convention — leave the section alone.

- [ ] **Step 5: Run the full Definition of Done**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest && npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

- [ ] **Step 6: Commit and open the pull request**

```bash
git add README.md docs/superpowers/specs/2026-09-02-web-ui-design.md
git commit -m "Document the web UI and record phase 5's decisions"
```

The pull request covers the whole phase: the scaffold, the gate growing to seven commands, the generated client, the design system, and the five read-only screens.

---

## Self-review

Run before handing the plan off, and again after any task is added.

**Spec coverage.** Walk phase 5's sentence in the spec — "Vite scaffold, `tokens.css`, the shared primitives, the TypeScript types generated from the now-complete OpenAPI schema, the typed client, router, layout and sidebar; then the merged Topics screen, Runs list, Run detail (completed and failed) and Topic detail; the full-size meme view; the empty states and the filter-matched-nothing line; the partial-failure and source-outage presentations" — and point at the task for each: scaffold (1), tokens (3), primitives (5), types (2), client (4), router/layout/sidebar (6), Topics (9), Runs (7), Run detail (8), Topic detail (10), meme view (11), empty states (7 and 9), filter-matched-nothing (9), partial failure (8, and decision 7), source outage (7 and 8). Plus the Definition of Done growing to seven commands (1), which the spec assigns to this phase explicitly.

**Nothing from phase 6 or 7 has leaked in.** No `POST`, `PUT` or `DELETE` anywhere; no `useActiveRun`, no `EventSource`, no `/runs/new`, no `/settings`, no generation panel, no delete confirm, no run strip, no sidebar in-flight card.

**Type consistency.** `RankedTopic` is `{ topic, render_count, above_cut }` everywhere; `IndexedTopic` is `{ topic, run_count, render_count }`; `RunSummary` is `{ run, topic_labels, render_ids }`. `MemeTile` takes `renderId`, never `id`. `formatScore(value, digits?)` — the three-decimal call is `formatScore(x, 3)`. `survivedFor(stage)` takes a `Stage`, `resumeStageFor(error)` takes a `RunError | null`.

**Placeholders.** Two, both deliberate and both named where they appear: Task 1's `check-types.mjs` stub, replaced in full by Task 2, and Task 6's five one-line page components, each replaced in full by the task that owns it. Both exist so the gate is green at every task boundary. There are no others.

## Test audit

Run by two fresh reviewers over Tasks 1–6 and 7–12 under the
`reviewing-plan-tests` skill, against `writing-good-tests.md`. 183 tests
audited, 13 findings, all applied. Two of them were arithmetic errors that
would have made the suite red on transcription, which is exactly what this
gate is for:

- `formatBytes(1_363_148)` is `"1.4 MB"`, not `"1.3 MB"` — `1.363148`
  rounds up. Fixed in `format.test.ts` and in Task 8's stage-card assertion,
  which shared the fixture.
- `moodLine` with `{funny: 9, …}` over `{funny: 7, …}` moves **2** points,
  not 3: `round(9/16×100) = 56` against `round(7/13×100) = 54`. Fixed in
  `ordering.test.ts` and in `TopicsPage.test.tsx`.

Three tests were rewritten because their names promised coverage their
assertions did not have — the failed run row (which asserted the pill's
text, not the row's own treatment), the every-brief-failed guard (which
served an empty ranking and so never reached the branch), and the meme
view's metadata line (which checked the run id and not the timestamp beside
it). Six tests were added for behaviour nothing covered: `MemeTile`'s
no-destination branch, `SectionLabel`'s optional hint, `useTopicDetail`'s
two-id guard, `useRuns` and `useRender` at all, the trending grid's 3-card
cap, and `RenderGrid`'s empty case.

One finding was applied in modified form. The reviewer asked for the stripe
gradient's exact declaration, whitespace collapsed; the assertion here names
the two stop widths instead, which catches the same mistranscription without
pinning how the property is wrapped across lines.

**Second pass, against the rubric directly.** The skill records that this
gate reliably misses tests only an intentional decision could break, so a
further pass was run by hand against `writing-good-tests.md`. It removed
nine tests and one whole file, on three of the rubric's Warning Signs:

*The test greps source text.* `tokens.test.ts` is gone entirely, and Task 3
now ships no test at all. Every assertion available over a token table is a
grep of its own source, which proves only that the source is the source, and
the values fail only when a designer changes their mind — while colour
fidelity is already the human review against the mockups that the spec
assigns. What replaces it is narrower and lives where it can bite:
`no-raw-colours.test.ts` in Task 5 walks every `.module.css` in the app and
fails on a hardcoded colour. That is a cross-file invariant with a real
accidental failure mode, not a restatement of one file's contents. Task 3
keeps one check, done once and by eye: read `--accent` back out of
`getComputedStyle` in a browser, which is the thing no grep can confirm.

*Asserts a removed symbol stays removed.* Five tests asserted the absence of
phase 6 and phase 7 work — no in-flight card, no Resume button, no
generation panel, no Delete control, no New run link. Each would fail in the
phase that legitimately adds the thing, which is a change detector by
definition. The phase boundary is documented in "Decisions this phase is
required to make"; it does not also need tests that a later phase must
delete. `EmptyState`'s absent-action test stays, because that one is the
component's own optional-prop contract rather than a marker for work
elsewhere.

*Trivial forwarding earns no test.* `SectionLabel.test.tsx` — added on the
subagents' Finding 4 — is reversed and deleted. The component validates
nothing, derives nothing and causes no side effect; its hint is asserted
through the screens that pass one. `App.test.tsx` is deleted in Task 6 for
the neighbouring sign, "can fail only through a panic, crash, or missing
selector": once `routes.test.tsx` renders the same tree and asserts what is
in it, the smoke test only proves the framework mounts. It still earns its
place in Task 1, where its job is to prove `npm test` runs something at all.

Also deleted: topic detail's "names no author on any reply". `ReplyOut` has
no author field, so the type makes the break unrepresentable, and the
assertion — no `@` anywhere on the page — would fail on any reply text that
happened to contain one.

The same pass found the Runs summary line counting `status !== "ok"` as
"failed", which would have labelled an aborted run a failure. The line now
names each status present with its own count, and the test carries an
aborted run so the distinction bites.

**Seven defects found in the plan's own code during execution.** `navClass`
and `sizeClass` claimed a `string` return type that `noUncheckedIndexedAccess`
does not allow a CSS-module lookup to have. The run detail breadcrumb and the
hero and card chips each duplicated text an unscoped query or a reader's eye
would meet twice. `makeTopicDetail`'s `first_seen_run_id` used `??`, which
cannot tell "not supplied" from an explicit `null` and so silently ignored
what a test asked for. And two `RenderDetailPage` tests queried
`findByText("drake")` and a breadcrumb link without scoping or awaiting,
against a screen that renders the template id twice and resolves the topic
title one commit after the render itself. All seven are corrected above,
against the shipped files.

They share one root cause: the plan's code was written against a strict
toolchain the plan itself introduces in Task 1, and was never compiled or
linted against it. Instances included `as const` under
`consistent-type-assertions: never`, `console` under `no-undef`, a value
import used only as a type under `consistent-type-imports`, CSS-module
access under `noUncheckedIndexedAccess`, and four unscoped `findByText`
queries against identifiers the high-fidelity design deliberately renders
twice. The `reviewing-plan-tests` audit above checks falsifiability and
dependency discipline; it does not compile. For a plan that stands up its
own toolchain mid-flight, a pre-flight pass that type-checks and lints the
plan's code blocks against the config its own Task 1 writes would have
caught five of the seven before any dispatch.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-09-web-ui-read-only-screens.md`.

Before executing: this plan contains test code, so the `reviewing-plan-tests` skill's audit is the gate that has to pass first — per `CLAUDE.md`, "a plan containing test code is not finished until those tests have been audited."
