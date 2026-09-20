# Viewing a render in a modal

Clicking a meme on a topic screen navigates away to
`/runs/{run_id}/renders/{render_id}`. Getting back to the grid you were
browsing costs a round trip through the router and a refetch of the topic,
which is a heavy price for glancing at one tile among a dozen. This design
opens the render over the topic instead, keeps the standalone route for
sharing, and trims what both of them show.

## Scope

In:

- A modal render view, opened from a tile on the topic screen.
- A **Copy link** action giving the render's absolute permanent URL.
- Dropping the caption slots, the run id, the generated time and the
  decoded image dimensions from the render view.
- Splitting `RenderDetailPage` into a fetching route and a body both it and
  the modal draw.
- A shared `Modal` primitive: a portalled `role="dialog"` panel owning
  Escape, focus-on-open, focus restore, a Tab trap and a backdrop click.

Out:

- Any change to the address bar when the modal opens. The modal is
  component state; the URL keeps naming the topic. This was chosen over
  the background-location routing pattern and over a `?render=` query
  parameter, both of which buy a working Back button at the cost of
  router machinery for a view that is one click from being reopened.
- Any backend change. No route, response model or `openapi.json` movement,
  so `uv run pytest`'s contract assertion is untouched.
- Paging between renders from inside the modal (prev/next). The grid is
  still visible behind it and nothing asks for this yet.

## Three components where there was one

`RenderDetailPage` currently fetches, lays out and acts in one function.
The modal needs the middle of those without the first, so the file becomes
three in `web/src/features/renders/`.

**`RenderDetail.tsx`** — the body. Takes a `RenderRecord` it does not
fetch and an `onDeleted` callback, and derives the template label from the
record so the chip, the alt text and the download filename cannot drift
apart. Draws the image frame and its failed state, the two chips, the rationale,
and the three actions. It owns the `useDeleteRender` mutation and its
error line. It knows nothing about routing beyond the path it hands to
**Copy link**, and renders no heading — its callers supply whatever
surrounds it.

**`RenderModal.tsx`** — `Modal` around `RenderDetail`, plus a close `✕`.
Takes the `RenderRecord`, an `onClose` and an `onDeleted`.

`Modal` itself is a fourth file and a shared one, at
`web/src/components/Modal.tsx` — nothing about it is specific to renders,
and the next modal this app grows should not reimplement a focus trap.

**`RenderDetailPage.tsx`** — keeps the route. `useRender` inside a
`QueryBoundary`, `useTopicDetail` for the breadcrumb and the `<h1>`, then
`RenderDetail` beneath them, exactly as today.

The modal fetches nothing. `TopicDetail.renders` already carries every
field a render view needs, so the grid passes the record it is holding and
the modal opens on the current frame — no spinner, no second
`GET /api/renders/{id}`, no way for the modal to disagree with the tile
that opened it. `useRender` stays for the standalone route, which arrives
with nothing but two ids.

## What the body shows

Removed:

- The `caption_slots` `<dl>`. The slot text is drawn on the meme in the
  frame above it; restating it is the same words twice.
- The whole `MetaLine` — run id, `formatClock(created_at)` and the decoded
  image size. With it goes the `size` state and the `<img onLoad>` handler
  that measured `naturalWidth`/`naturalHeight`, which existed only to feed
  that line.

Kept:

- The image, at `imageUrl(record.id, "full")`, and its `onError` failed
  state. The database stays authoritative for whether a render exists, so
  a PNG deleted from under the row is still a styled panel naming the
  shortened id rather than a broken-image icon.
- Two chips: the template name (accent) and `origin.provenance`.
  `template_id` is nullable — a `generating` row that left the choice to
  the model, or a `failed` row whose brief never got that far — so the
  chip and the download filename keep today's `"no template chosen"`
  fallback.
- For `auto`, the **Why this template** label and `origin.rationale`. For
  `manual`, the `written by hand` line. This is the part the user came for
  and it is unchanged.

Because the right-hand column now holds two chips and a paragraph, the
two-column grid goes: both surfaces stack, image above and a band of
chips, rationale and actions below. One layout serves the page and the
modal, so `RenderDetail` takes no `layout` prop and there is no second
arrangement to keep in step.

## Opening the modal

`RenderTile` keeps rendering a real `<Link>` to the permanent URL. The
`href` is what makes the tile shareable without opening it: hover shows the
address, and ⌘-click, ctrl-click or middle-click still open the permalink
in a new tab. `MemeTile` gains an optional `onActivate(event)` prop, passed
through to the `<Link>`'s `onClick`. On an unmodified primary click the
handler calls `preventDefault()` and the grid opens the modal; a click
carrying `metaKey`, `ctrlKey`, `shiftKey` or `altKey`, or coming from a
non-primary button, falls through untouched and the browser navigates.

Open state lives in `RenderGrid` as the id of the render being shown —
an id rather than the record, so a row that changes underneath is not
frozen in a stale copy. The record handed to the modal is looked up from
`renders` on each render pass; if the id is no longer in the list, the
modal is closed.

## Closing it

Three ways out, and `Modal` owns two of them: Escape, handled on the panel
that takes focus when it opens, and a click whose target is the backdrop
itself rather than anything inside the panel. The `✕` is `RenderModal`'s
own, because a modal primitive has no business deciding what chrome its
caller wants.

All three call the same `onClose`, which clears the grid's state. `Modal`
never unmounts itself — `onClose` is a request, and the caller decides
whether to honour it, which is what lets a delete that fails leave the
modal up with its error showing.

### Escape and the delete confirm

`InlineConfirm` handles Escape to disarm itself. Inside a dialog, one
Escape would otherwise both disarm a `Delete this render?` and close the
modal, losing the view as a side effect of cancelling something else.

Escape is claimed innermost-first: the first press disarms the confirm, a
second closes the modal. `InlineConfirm` calls `stopPropagation()` on the
Escape it handles, so the keystroke never reaches `Modal`'s handler on the
way up, and `preventDefault()` alongside it marks the event handled for
anything that inspects it rather than receiving it.

This is correct on its own terms, not a modal workaround — an armed
confirm is the innermost dismissible thing on the screen, and today it
silently lets the keystroke carry on to whatever encloses it. So it gets
its own test rather than being folded into the modal's.

## Deleting

From the modal, a confirmed delete closes it rather than navigating:
`useDeleteRender` has already dropped the row from the topic's cache, so
the grid behind has lost the tile before the modal goes. Focus is the part
that needs care — `Modal` restores focus to whatever held it, but that
tile has unmounted, and a detached node cannot take focus. `RenderGrid`
already solves this for tile-level deletes by focusing its section-label
anchor, and the modal's delete reuses that path.

From the standalone page, a confirmed delete still navigates back to the
topic, because there is no grid behind it to return to.

The mutation's error line (`role="alert"`, the server's `detail`) lives in
`RenderDetail` and so appears in both.

## Copy link

`CopyLinkButton` takes a `path` and writes
`new URL(path, window.location.origin).href` through
`navigator.clipboard.writeText`. Absolute, because the whole point is to
paste it somewhere that is not this app.

On success the label becomes `Copied` for two seconds, then reverts; the
timeout is cleared on unmount so it cannot set state on a gone component,
the way `InlineConfirm` already guards its own deferred revert.
`writeText` returns a promise that rejects in a non-secure context or
without permission, and on rejection the button drops a `role="alert"`
line showing the URL as selectable text. The button never silently does
nothing.

It appears in both the modal and the standalone page. On the page the
address bar already holds the URL, but it is one component either way and
a click beats selecting the omnibox.

## Styling

`tokens.css` gains one token for the backdrop wash — the modal's
`::backdrop`, in keeping with the app's near-black page colour.
`no-raw-colours.test.ts` forbids hex and `rgba()` in `*.module.css`, so
the value has to live in the token sheet like every other colour.

The modal's own surface reuses the tokens the brief panel already uses:
`--surface`, `--border-strong`, `--radius-card`. `RenderDetailPage.module.css`
loses `.body`, `.brief`, `.slots`, `.slot`, `.slotName` and `.caption`.
Nothing enforces that sweep — `no-raw-colours.test.ts` catches a class
referenced but not defined, not one defined and never referenced — so
removing the dead rules is a step in the plan rather than something a gate
will notice.

## Why not the native `<dialog>`

`<dialog>` with `showModal()` is what this design wants: Escape, the focus
trap, `::backdrop`, top-layer stacking and background inerting, none of it
written by us. It is not used, because no Node test environment implements
it and a modal whose dismissal cannot be tested is the wrong trade. Each
route was measured rather than assumed:

- **jsdom**, any version. `HTMLDialogElement.prototype` carries only
  `constructor` and `open` — no `showModal`, no `close` — in 25.0.1 (this
  repo's pin), 26.1.0 and 30.1.0 alike. There is no version to upgrade to.
- **happy-dom** 20 implements `showModal` and `close`, but Escape never
  closes the dialog, so the close request is missing there too.
- **`dialog-polyfill`** 0.5.6, the latest, does everything asked of it —
  but gates its Escape handling on the legacy `event.keyCode === 27`,
  which `@testing-library/user-event` does not set and jsdom does not
  synthesize from `key`. Making it work needs a magic `keyCode: 27` in
  every Escape test, or a global `KeyboardEvent` shim across the suite.

Every route to the platform element ends in a test-only hack that moves
the suite further from what ships. `Modal` owns roughly sixty lines
instead, and the tests drive exactly the code a browser runs.

The one thing not reproduced is background inerting. The page behind a
`Modal` keeps its markup; `aria-modal="true"` is what tells a screen
reader to ignore it, and the backdrop is what stops a mouse reaching it.
A keyboard user cannot leave, because of the Tab trap.

## Accessibility

The modal's accessible name is the template, carried by `aria-label` on the
dialog. The dialog needs a name and the template is what distinguishes one
render of a topic from another; the topic itself is named by the page
behind the modal and by the `<h1>` on the standalone route. Pointing
`aria-labelledby` at the template chip would say the same thing, but `Chip`
renders a bare `<span>` with no id, and growing a shared component an `id`
prop for one caller is worse than naming the dialog directly.

The `✕` carries `aria-label="Close"`. The focus trap, focus-on-open and
returning focus to the tile on close all come from `Modal`, and are tested
there rather than here.

## Tests

New:

- `Modal.test.tsx` — names itself and says it is modal; portals out of the
  tree it was mounted in; takes focus on open and gives it back on close;
  Escape closes; a backdrop click closes and a click inside does not; Tab
  wraps at both ends.
- `RenderModal.test.tsx` — names itself by the template; draws the render
  and its rationale; the close button closes; Escape reaches `Modal`; an
  armed delete confirm swallows the first Escape and the modal survives
  it; a confirmed delete reports; a refused delete leaves it open with the
  error showing.
- `CopyLinkButton.test.tsx` — writes the absolute URL for the path given;
  shows `Copied` and reverts; surfaces a rejected `writeText` as an alert
  carrying the URL.

Changed:

- `RenderDetailPage.test.tsx` — drops the assertions on slot text, run id
  and image dimensions, keeps the failed-image and delete-navigates cases.
- `RenderGrid.test.tsx` and `TopicDetailPage.test.tsx` — keep asserting the
  tile's `href`, since that is the shareable affordance, and gain the case
  that an ordinary click opens the dialog rather than navigating.
- `InlineConfirm.test.tsx` — gains the case that Escape handled by an armed
  confirm is cancelled.
