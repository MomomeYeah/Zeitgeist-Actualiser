# Handoff: Zeitgeist Actualiser — Web UI

## Overview

A web frontend for [Zeitgeist Actualiser](https://github.com/MomomeYeah/Zeitgeist-Actualiser), a pipeline that reads Bluesky, distils trending topics and the conversation around them, ranks them, and generates memes.

The UI covers six screens:

1. **Topics (home)** — what is trending right now, plus the mood of the whole window and a small run strip.
2. **Topics index** — trending now, and recently trending.
3. **Runs** — the run list, with the in-flight run pinned at the top.
4. **Run detail** — the four pipeline stages, their checkpoint artifacts, and the full topic ranking with the `top_count` cut drawn explicitly. Two variants: completed, and in flight with a live log.
5. **Topic detail** — the dossier (event summary, conversation register, replies, recurring phrases), the memes rendered from it, and on-demand generation.
6. **New run** — run configuration.

## About the Design Files

The files in this bundle are **design references created in HTML**. They are prototypes showing intended look, structure and behaviour — not production code to copy. The task is to **recreate these designs in the target codebase's environment** using its established patterns and libraries. The Zeitgeist Actualiser repo is currently a Python CLI with no frontend, so the framework choice is open; pick whatever suits the backend you put in front of it (a small React or Svelte SPA over a thin FastAPI layer reading the same JSON artifacts is the obvious fit).

The HTML uses inline styles throughout because of how it was authored. Do **not** carry that over — extract the token table below into whatever the target uses (CSS variables, Tailwind config, theme object).

## Fidelity

**High-fidelity.** Colours, typography, spacing and copy are final. Recreate the UI faithfully.

Two things are deliberately not final:

- **Meme images** are diagonal-stripe placeholders. Real renders come from `output/`.
- **Sample content** (airport cat, stadium rat, sneeze) is invented. Every field maps to a real model field — see Data Mapping.

## Source of Truth

The design file is `Zeitgeist Mockups.dc.html`. It contains five turns of exploration stacked newest-first, each option labelled with its id in the top-left corner. **Turns 2, 4 and 5 are canonical. Turns 1 and 3 are rejected exploration — ignore them** (turn 1 predates the codebase read; turn 3 was a colour study, and the yellow-on-brown palette of turn 2 was kept).

Build these:

| Option id | Screen | Notes |
| --- | --- | --- |
| `2b` | Topics / home | The landing screen. |
| `2d` | Topics index | Reached from the sidebar. |
| `2a` | Runs list | Was also a home candidate; not chosen as home, but is the Runs view. |
| `2c` | Run detail — completed / failed | |
| `5a` | Run detail — in flight, mid-analyse | Same screen as `2c` in a running state. |
| `5b` | Run detail — in flight, mid-generate | Same screen, later state. |
| `2e` | Topic detail | |
| `4a` | New run | Reached from the **New run** button. |

Note `2b` and `2d` overlap: `2b` is the landing dashboard (hero topic + four cards + mood bar + run strip), `2d` is the fuller topics index reached from the sidebar. Treat `2b` as home and `2d` as `/topics`. If you want to collapse them into one view, `2b`'s hero and mood bar sitting above `2d`'s two lists is the natural merge — flag it rather than deciding silently.

## Design Tokens

### Colour

| Token | Hex | Use |
| --- | --- | --- |
| `bg` | `#17140e` | Page and main content background |
| `bg-sidebar` | `#141109` | Left rail, one step darker than page |
| `surface` | `#1d1a12` | Cards, rows, panels |
| `surface-log` | `#100e09` | Log blocks, inset areas |
| `accent` | `#ffd93d` | Active nav, primary buttons, hero card fill, running state, meme scores |
| `accent-wash` | `rgba(255,217,61,.06)` | Tinted background on the active/highlighted row |
| `accent-tint` | `rgba(255,217,61,.14)` | Chip background for the accent chip on dark surfaces |
| `accent-border` | `rgba(255,217,61,.3)` | Border of highlighted cards and the LLM panel |
| `contrast` | `#3d63e6` | Failure state fills, schadenfreude chip background at 20% |
| `contrast-light` | `#8aa4ff` | Failure text and links on dark |
| `text` | `#f5f1e6` | Primary text |
| `text-70` | `rgba(245,241,230,.7)` | Secondary body |
| `text-55` | `rgba(245,241,230,.55)` | Inactive nav |
| `text-40` | `rgba(245,241,230,.4)` | Section labels |
| `text-35` | `rgba(245,241,230,.35)` | Metadata |
| `text-30` | `rgba(245,241,230,.3)` | Disabled, below-the-cut rows |
| `border` | `rgba(255,255,255,.09)` | Standard card and row border |
| `border-strong` | `rgba(255,255,255,.14)` | Ghost button border |
| `divider` | `rgba(255,255,255,.07)` | Hairlines inside cards |
| `stripe-a` / `stripe-b` | `#211d14` / `#272216` | Meme placeholder stripes (`repeating-linear-gradient(135deg, a 0 8px, b 8px 16px)`) |

On the accent-filled hero card the palette inverts: text is `#17140e`, chips are `#17140e` fill with `#ffd93d` text, and secondary chips are `rgba(23,20,14,.14)`.

### Typography

Two families, loaded from Google Fonts:

- **Outfit** (300–800) — all UI text, headings, body, buttons.
- **IBM Plex Mono** (400–700) — run ids, scores, metadata, section labels, log output, chips, template names.

The split is semantic, not decorative: anything the machine produced or names (ids, filenames, scores, stage names, counts, template ids) is mono; anything written for a human to read is Outfit.

| Role | Spec |
| --- | --- |
| Page title (`Right now`, `Runs`, `Topics`) | Outfit 800 / 22px / 1 / `-.03em` |
| Hero topic title | Outfit 800 / 29px / 1.1 / `-.03em` |
| Topic detail title | Outfit 800 / 28px / 1.12 / `-.03em` |
| Card topic title | Outfit 700 / 15–16px / 1.22–1.25 |
| Ranking row title | Outfit 700 / 14.5px / 1.25 |
| Body / dossier prose | Outfit 400 / 13px / 1.55, `text-wrap: pretty` |
| Small body | Outfit 400 / 11.5–12.5px / 1.45–1.5 |
| Button label | Outfit 700 / 12px / 1 |
| Nav item | Outfit 700 (active) or 500 / 12.5px / 1 |
| Section label | IBM Plex Mono 700 / 9.5px / 1, `letter-spacing: .12em`, uppercase |
| Run id, large | IBM Plex Mono 700 / 19–20px / 1 |
| Run id, inline | IBM Plex Mono 500–600 / 11–12px / 1 |
| Metadata line | IBM Plex Mono 400 / 10–10.5px / 1.5–1.6 |
| Chip | IBM Plex Mono 600–700 / 9.5–10px / 1 |
| Log line | IBM Plex Mono 400 / 11px / 1.9 |
| Rank numeral | Outfit 800 / 17px / 1 |
| Stat numeral (trend / meme / rank) | Outfit 700 / 22px / 1 |

Never smaller than 9px, and 9–10px is mono-only — Outfit is not used below 11px.

### Geometry

| Token | Value | Use |
| --- | --- | --- |
| radius-pill | `20–24px` | Chips, status badges, primary buttons in headers |
| radius-card | `14px` | Hero card, in-flight run card |
| radius-panel | `11–12px` | Ranking rows, topic cards, generate panels |
| radius-tile | `8–9px` | Meme tiles, template tiles, small inputs |
| radius-sm | `6–7px` | Nav items, log block, slot fields |
| gap-page | `20–22px` | Page padding, top-level column gap |
| gap-section | `14–16px` | Between major blocks |
| gap-card | `9–12px` | Between cards in a grid |
| gap-tight | `5–8px` | Chip rows, inline meta |
| stage-bar | `3–4px` tall, `2px` radius | Stage progress bars |
| sidebar-width | `180px` | Left rail |
| content-width | `1000px` | Detail screens (`2c`, `2d`, `2e`) |
| app-width | `1180px` | Screens with the rail (`2a`, `2b`) |

Section labels sit `9–12px` above their content. Cards use `13–18px` internal padding; the hero card uses `20px 22px`.

## Screens

### 1. Sidebar (persistent, on `2a` and `2b`)

180px, `bg-sidebar`, `1px` right border in `border`. Contents top to bottom:

- Wordmark "Zeitgeist", Outfit 800 / 18px / `-.03em`, `0 8px` padding.
- 26px gap, then nav: **Topics**, **Runs** — in that order. 3px gap between items, each `10px 11px`, radius 8px. Active: `accent` fill, `#17140e` text, weight 700. Inactive: `text-55`, weight 500.
- `margin-top: auto`, then the in-flight card: `11px` padding, radius 9px, `accent-wash` fill, `accent-border` at 20%. Label "IN FLIGHT" in mono 600/9.5 accent; below it the current stage and elapsed, mono 500/10 in `text-50`, line-height 1.5.

The in-flight card is only rendered when a run is active.

### 2. Topics / home (`2b`)

Header row: title "Right now" with a mono metadata line beneath (`9 trending · 6 saturating · 4 cooling · as of 14:02`), and a pill **New run** button (accent fill) right-aligned.

**Hero + latest meme**, `1.55fr 1fr` grid, 14px gap, min-height 168px:

- Hero: accent fill, `#17140e` text, radius 14. Kicker line in mono 700/10 `.12em` reading `TOP RIGHT NOW · <TREND_STATUS> · MEME <score>`. Title Outfit 800/29. Summary at 72% opacity, max-width 500px. Chip row pinned to the bottom: sentiment (inverted dark chip), register, meme count.
- Meme tile: bordered, radius 14, stripe placeholder filling the top, footer bar in `surface` with template id (mono, `text-50`) and an "open ↗" affordance in accent.

**Four topic cards**, 4-up grid, 12px gap. Each: status label + meme score on one line (mono 700/9.5, score in accent), title Outfit 700/15, chip row, then `<n> posts · <n> memes` in mono. A topic with no memes shows "no memes yet" in accent — that is the cue to go generate some.

**Bottom row**, `1fr 320px`:

- *The mood today* — a 28px segmented bar, 3px gaps, radius 6, one segment per sentiment sized by share, label centred inside each (`funny 9`, `cute 5`, …). Accent for the top sentiment, accent at 50% for the second, `contrast` for schadenfreude, white at 16% and 8% for mundane and the tail. Below it one mono line covering register skew and average meme potential versus the previous run.
- *Runs* — three rows max, 7px gap, each a bordered pill-ish row with a 6px status dot, run id, and state. Running row gets the accent border and wash.

### 3. Runs (`2a`)

Header: "Runs", metadata line (`27 total · 24 ok · 3 failed · bluesky only`), **New run** button.

**In-flight card** (only when a run is active): accent border and wash, radius 14, 16px/18px padding. Status badge, run id, elapsed and current stage, then a four-segment progress bar (4px tall, 4px gaps) with stage names beneath. The active segment is a partial fill: `linear-gradient(90deg, accent 68%, rgba(255,255,255,.12) 68%)`.

**Run rows**: `150px 1fr 150px 128px 84px` grid, 14px gap, 14px/16px padding, radius 12, `surface` fill.

1. Run id (truncated to `…829T090000Z`) + relative time and duration.
2. Topic titles joined by `·`, single line, ellipsised.
3. Counts: `25 trends → 5 kept`, phrase count.
4. Meme thumbnails, 34px squares, radius 6, max 3 then a dashed `+2` tile.
5. Status pill: `OK · 5` in accent tint, or `FAILED` in `contrast` at 20% with `contrast-light` text.

A failed row swaps column 2 for the error (`RenderError in generate — 3 of 5 briefs written`), column 3 for what survived (`ranked.json intact`), and column 4 for the resume command in `contrast-light`. Its border is `rgba(61,99,230,.35)`.

### 4. Run detail (`2c`)

Breadcrumb `Runs / <run id>`. Header: status badge, run id in mono 700/19, then a config line — sources, `trend_limit`, `posts_per_trend`, `top_count`, model, duration. Right side: ghost **Re-run config** and accent **Resume from &lt;stage&gt;**, both pills.

**Stage cards**, 4-up, 10px gap, radius 10. Each: a 3px accent bar across the top, stage name + duration, a one-line summary in Outfit 400/11.5, and the artifact filename in mono 9.5 `text-30`. Incomplete stages use `border` and `text-30` throughout with no accent bar.

**Ranking list**: `30px 1fr 132px 150px 128px`, 8px gap between rows.

1. Rank numeral (accent on row 1, `text-50` after).
2. Title + a mono subline: trend status, post count, and the top recurring phrase with its count.
3. Sentiment and register chips.
4. `trend 0.91 · meme 0.86` over `final 0.895`, the final score in accent on row 1.
5. Meme thumbnails, 42px, radius 7.

Rank 1 gets `accent-border` and `accent-wash`. Rows below `top_count` are dashed border, no fill, `opacity: .62`, and swap the thumbnails for a `generate ↗` link — they were never briefed, and this is the escape hatch to brief them by hand. The list ends with a centred `19 more below the cut`.

### 5. Topics index (`2d`)

Header: "Topics", `across the last 6 runs · deduplicated by topic id`, and a filter chip row — `trending 9` (accent fill, active), `saturating 6`, `cooling 4`, `stale 31` — the last dimmed to `text-35`.

**Trending now**: 3-up cards, 11px gap. Header line pairs a recurrence label (`▲ SEEN IN 3 RUNS`, or `NEW THIS RUN`) with the meme score in accent. Title Outfit 700/16, chip row, then `<n> posts · <n> memes` in mono. The first card is highlighted with `accent-border` + `accent-wash`.

**Recently trending — saturating & cooling**: a table, 1px gaps over a `divider` background so the hairlines read as borders, radius 11, columns `1fr 122px 108px 92px 78px` — title, sentiment chip, trend status, post count, meme score right-aligned.

### 6. Topic detail (`2e`)

Breadcrumb `Topics / <topic id> · first seen <run id>`.

**Header**: title Outfit 800/28, chip row (sentiment as accent fill, register, `2nd: delight, awe` for secondary sentiments, trend status in `contrast` tint), and three right-aligned stats — TREND, MEME, RANK — each a mono 9px `.1em` label over an Outfit 700/22 numeral. MEME is accent.

**Two dossier cards**, equal columns, 14px gap, radius 9:

- *What happened* — the event summary, then entity chips (`5px 8px`, 1px border, radius 4).
- *How the conversation is going* — the register description, a hairline, then `score_components · bluesky 0.91 · corroboration 1.00`.

**Replies + phrases**, `1fr 300px`:

- *Replies — no handles stored*. Each: `12px 14px` padding, `border`, a 2px left border in accent (or white 15% for an off-consensus reply), radius `0 7px 7px 0`, body Outfit 400/13, then `1,412 likes · 14:31` in mono 9.5. The left-border colour is the only signal of whether a reply matches the dominant sentiment. **No author, handle or avatar** — the pipeline does not store them.
- *Recurring phrases* — a single card, phrases scaled by frequency (15px → 13px → 12px, the top one in accent), each with `48× · 31 authors` beneath. Footer: `7 more below phrase_min_authors=3`.

**Generation**, `1fr 340px`, and the visual split between the two panels is load-bearing:

- **Ask the LLM** — solid `accent-border`, `accent-wash` fill. Subhead: "Writes fresh briefs from the dossier, then renders them. Costs a model call each." A TEMPLATE label with "optional" right-aligned, then a radio row **Let the LLM choose** (selected by default, accent border and fill, sublabel "picks the templates that suit funny / riffing"), then the four template tiles at `opacity: .6` as optional overrides. Each tile: 60px stripe preview, template id in mono 700/10, slot count beneath. Bottom row: HOW MANY as 1 / 3 / 5 pills (3 default), and the accent **Generate 3 memes** button, label reflecting the count.
- **Write it yourself** — dashed `rgba(255,255,255,.16)` border, near-transparent fill, muted labels, ghost button. Template selector as a single row with a `change ▾` affordance, then one empty field per slot of the chosen template, each labelled with the real slot name (`REJECTED`, `PREFERRED`) and placeholder "type a caption…". Button reads **Render**. Subhead: "Straight to the renderer. No model call."

The asymmetry is intentional: the LLM path is the primary action and is visually solid; the manual path is a deliberate, quieter alternative.

**Rendered from this topic**: 4-up tiles, radius 8. Each has a stripe preview and a footer with `<template> · auto|manual` and a `✕`. Three states are drawn:

1. Normal — `✕` in `text-35`.
2. Confirming — footer swaps to `contrast` at 10% fill, "Delete this render?" in `contrast-light`, with `yes` / `no`. Inline, not a modal.
3. Generating — accent border, a 3px progress bar at 45%, "writing brief…" in accent, and the `✕` acts as cancel.

Header line above the grid: `2 from run_0829T0900 · 1 generating`.

### 7. New run (`4a`)

Reached from the **New run** button on Topics and Runs. Breadcrumb `Runs / new`, title "New run", metadata line `defaults come from .env · changes apply to this run only`. Layout `1fr 320px`, 18px gap, columns aligned to the top.

Left column, 16px gap between cards, all radius 12, `surface`, `17px 19px` padding:

- **MODEL** — two halves. *Provider* as pills, `anthropic` / `ollama`, matching the `llm_provider` literal; the selected one is accent-filled. Beneath, a mono `key present · ANTHROPIC_API_KEY` line (or a warning when the key is missing). *Model* as a radio list, one row per model, `10px 12px` padding, radius 8, mono 600/11.5 for the id, with a right-aligned annotation (`default`, `slower`, `cheap`). **The model list is per-provider and swaps when the provider changes** — ollama shows local model tags, not Claude ids. Both lists come from a pre-configured registry; there is no free-text model field by design.
- **PLATFORM** — 3-up radio cards with `exactly one` as the right-aligned hint, enforcing the config's single-source rule. Bluesky is selected, sublabel "clusters its own trends". Lemmy and Wikipedia render at `opacity: .4` with a dashed border and the sublabel "dormant · no clustering" — they are in `ITEM_SOURCES`, have no trend clustering, and the config rejects them. Show them; never let them be picked.
- **MEMES TO GENERATE** — the one card with `accent-border` and `accent-wash`, because it is the setting that changes the output. Label right-hinted `topic_count · default 5`. Explanatory line, then pills 1 / 3 / 5 / 10 / custom (5 selected) and a mono `of 25 trends analysed` note tying it to `trend_limit`.
- **TEMPLATES** — right-hinted `default: whole library`, then chips: `all 4` (selected) followed by one per template id. Maps to `--templates`; selecting `all 4` sends null rather than an explicit list.

Right column: a single `surface` card, 16px gap. A notice in `contrast` at 8% with a `rgba(61,99,230,.35)` border and `contrast-light` text — "A run is already in flight. Starting this one queues it behind …140200Z." — shown only when a run is active. Then the accent **Start run** button, full width, 14px padding, radius 9.

Everything not on this screen keeps its `.env` value. The advanced tuning fields (`trend_limit`, `posts_per_trend`, `meme_potential_weight`, `phrase_min_authors`, `distil_concurrency`, `distil_char_budget`) were deliberately cut — do not add them back as a form. A settings screen for them is a future consideration, not part of this handoff.

### 8. Run detail, in flight (`5a`, `5b`)

The same screen as `2c` — identical stage cards, identical ranking grid — with three differences that follow from the run still being live. Once it completes, this screen *is* `2c`: bars go solid, the log collapses, header actions swap to Re-run config / Resume.

**Header.** Status badge becomes `RUNNING`: accent fill with a 6px dark dot at the left, and the elapsed time `t+06:41` in accent rather than `text-35`. Config line ends with `started 14:02` instead of a duration. Actions become ghost **Stop after this stage** and **Abort**, the latter bordered `rgba(61,99,230,.45)` with `contrast-light` text.

**Stage cards.** Completed stages are unchanged. The active card gets `rgba(255,217,61,.35)` border and `accent-wash`; its top bar is a partial fill (`linear-gradient(90deg, accent <pct>%, rgba(255,255,255,.12) <pct>%)`), the duration slot becomes a stage-relative counter (`17 / 25`, `2 / 5`), the summary line says what is happening right now ("distilling · 4 calls in flight", "rendering hearing-sneeze"), and the artifact line becomes an estimate in accent (`~4m left`). Queued stages show `—` and `queued` in `text-30`.

**Live log.** Replaces `2c`'s post-mortem block, same `surface-log` fill and mono 400/11 at 1.9. Header row: "LIVE LOG" label, an accent "following" indicator with a 6px dot, and a `verbose` toggle mapping to the CLI's `--verbose`. Lines carry the real logger names (`zeitgeist.pipeline`, `zeitgeist.analysis.distil`, `zeitgeist.media.brief`, `zeitgeist.media.render`). Older lines fade via `opacity` .4/.55 so the eye lands on recent ones; `WARNING` is accent; the final line — the in-flight work — is fully accent. Auto-scroll while "following"; scrolling up releases it.

**Ranking, mid-analyse (`5a`).** Order is not decided until evaluate, so the rank column shows `·` instead of a numeral, the final-score slot reads `final pending` in `text-30`, and there is no thumbnail column (grid drops to `30px 1fr 132px 150px`). Rows append as each topic is distilled. Below them, a dashed accent row with a 120px progress bar and "distilling 4 more", then a centred `8 distilled · 17 to go`. Section hint: `final order is set in evaluate`.

**Ranking, mid-generate (`5b`).** Full `2c` grid with real ranks and final scores. The row being rendered keeps `accent-border`, swaps its subline for `rendering · tmpl=expanding_brain` in accent, and shows a 42px tile with an inset 3px progress bar instead of a thumbnail. Rows still queued sit at `opacity: .7` with `queued for brief` and a dashed empty tile. Section header `RANKING — TOP 5 OF 25`, right-hinted `2 rendered · 3 to go`.

## Interactions & Behavior

**Navigation.** Sidebar switches between Topics and Runs. Topic cards and ranking rows open topic detail. Run rows open run detail. Meme tiles open a full-size view (not designed — see Not Yet Designed).

**In-flight run.** Poll or stream stage progress. The sidebar card, the `2a` in-flight card, the `2b` run strip and the `5a`/`5b` run detail all reflect it. Stage bars fill partially within the active stage using the item count (`17/25`). Log lines stream and auto-scroll while "following" is on; scrolling up releases it. Ranking rows append as topics are distilled — do not wait for the stage to finish. **Stop after this stage** lets the current stage write its checkpoint and then halts, leaving the run resumable; **Abort** stops immediately.

**Start run.** Submitting `4a` creates the run and navigates to `5a`. If a run is already in flight the new one queues, which is what the notice in the right column says.

**Delete a render.** `✕` swaps the tile footer to the inline confirm state. `yes` deletes the PNG and its brief entry; `no` reverts. No modal, no toast — the tile disappearing is the confirmation.

**Generate.** Both buttons immediately append placeholder tiles to the rendered grid in the generating state, one per requested meme. Each resolves independently. A failed render should keep its tile and show the error in the footer in `contrast-light` rather than vanishing.

**Resume.** "Resume from &lt;stage&gt;" starts a run from the named checkpoint. The stage name comes from the last successful checkpoint, so it is computed, not fixed copy.

**Below-the-cut rows.** `generate ↗` on a dimmed ranking row briefs and renders that single topic without re-running the pipeline — same backend path as the topic-detail LLM panel.

**Hover.** Not specified in the mocks. Suggested: rows and cards lighten their border to `rgba(255,255,255,.16)`; the accent button darkens ~6%; the `✕` goes from `text-35` to `text`. Keep transitions at 120–150ms ease-out.

**Empty states.** Not designed. Needed for: no runs yet, no trending topics, a topic with no memes (the card copy "no memes yet" covers the inline case), and a run whose generate stage produced nothing.

**Responsive.** These are desktop layouts. Mobile versions of the feed and dossier were explored in turn 1 (`1g`) but not carried into turn 2 — treat mobile as undesigned rather than inferring it from these.

## State Management

Per screen:

- **Topics**: `topics[]` for the current window, filter by `trend_status`, sentiment distribution aggregate, `runs[]` (last 3), `activeRun`.
- **Runs**: `runs[]` paginated, `activeRun` polled.
- **Run detail**: one `run` with `stages[]` (status, duration, artifact, size), `rankedTopics[]` including those below `top_count`, and `logLines[]` for the failed stage.
- **Topic detail**: one `topic` dossier, `renders[]` with per-render status (`ready` / `generating` / `deleting` / `failed`), plus local form state — `selectedTemplate` (nullable, null = let the LLM choose), `count` (1/3/5), `manualTemplate`, `manualSlots{}`.

`activeRun` is the only thing needing live updates. Everything else can be fetched on navigation.

## Data Mapping

Every displayed value maps to the pipeline's own model — build the API around these rather than inventing a parallel vocabulary:

| UI | Source |
| --- | --- |
| Run id (`20260829T140200Z`) | Run directory name |
| Stage names | ingest / analyse / evaluate / generate |
| Stage artifacts | `evidence.json`, `topics.json`, `ranked.json`, `briefs.json` |
| Trend status | trending / saturating / cooling / stale |
| Sentiment chip | `event_sentiment` (funny, cute, schadenfreude, mundane, …) |
| Register chip | `conversation_register` (riffing, dunking, delight, resignation, gallows, …) |
| MEME score | `meme_potential` |
| TREND score | trend score from `score_components` |
| Final score | ranking score, `0.7 · trend + 0.3 · meme` |
| Cut line | `top_count` |
| Recurring phrases | phrase extraction, filtered by `phrase_min_authors` |
| Template ids and slot names | the template manifests (`drake` → rejected/preferred, `always_has_been` → realisation/response, `expanding_brain` → level1–4, `panik_kalm_panik` → panik/kalm/panik) |
| Config line on run detail | `trend_limit`, `posts_per_trend`, `top_count`, model id |
| Provider pills | `llm_provider` — literal `anthropic` \| `ollama` |
| Model list | `llm_model`, from a per-provider registry |
| Platform cards | `TREND_SOURCES` selectable, `ITEM_SOURCES` shown disabled; config requires exactly one |
| Memes to generate | `topic_count` |
| Template chips | `--templates`; `all 4` = null = whole library |
| Log lines | Python logger names and levels, as emitted |
| Verbose toggle | `--verbose` |

Slot names in the manual render panel must be read from the selected template's manifest, not hardcoded — the panel's field list changes with the template.

## Assets

- **Fonts**: Outfit and IBM Plex Mono, Google Fonts. Weights used: Outfit 400/500/600/700/800, IBM Plex Mono 400/500/600/700.
- **Icons**: none. The few glyphs used are text characters — `✕`, `↗`, `▾`, `▲`, `·`. Substitute a real icon set if the codebase has one.
- **Images**: none. All meme thumbnails are CSS stripe placeholders standing in for PNGs from `output/`.

## Not Yet Designed

Flag these before you start so they get designed rather than improvised:

- **Full-size meme detail view.** The largest gap: memes only ever appear as thumbnails, so there is no screen for viewing a PNG at real scale, seeing the brief and slot text that produced it, or downloading it. Needed before the UI meets its own brief.
- **Empty / first-run states.** No runs, no topics, no memes. This is the first screen anyone sees.
- **Failure and abort states** beyond the failed run in `2a`/`2c`: the abort confirmation, a partial-failure run (3 of 5 rendered, 2 errored — the renderer fails per-meme, so this is real), and a source outage where ingest returns nothing.
- **Settings screen** for the `.env` values deliberately cut from `4a`.
- **Mobile layouts.** Explicitly out of scope for now.
- Music output, which the pipeline may add later. The topic-detail grid has a dashed "Track — not built yet" tile as a placeholder for where a second output type would live.

## Files

- `Zeitgeist Mockups.dc.html` — the design file. Turns 2, 4 and 5 are canonical; turns 1 and 3 are superseded exploration.
- `support.js` — runtime the design file needs to render. Not part of the design.

Open the HTML in a browser. Turns are stacked newest-first, each with a numbered header; every option carries its id (`2b`, `4a`, `5a`…) in the top-left corner.
