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
- `jsdom` `^25.0.1` → `^26`, so `HTMLDialogElement.showModal` exists under
  test.

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

**`RenderModal.tsx`** — a `<dialog>` around `RenderDetail`, plus a close
`✕`. Takes the `RenderRecord` and an `onClose`.

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

Three ways out, and the native element gives two of them. `showModal()` is
called from an effect on mount, which brings Escape, the focus trap, the
`::backdrop` pseudo-element, top-layer stacking and inerting of everything
behind it. The `✕` calls `close()`. A click on the backdrop is not handled
by the platform, so the dialog carries an `onClick` that closes when
`event.target === dialogRef.current` — a click that landed on the dialog
box itself rather than any of its children, which for a `<dialog>` in the
top layer means the backdrop.

`onClose` on the element is what clears the grid's state, so every route
out — Escape, `✕`, backdrop, a completed delete — converges on one place.

### Escape and the delete confirm

`InlineConfirm` handles Escape to disarm itself but does not stop the
event. Inside a dialog that means one Escape would both disarm a
`Delete this render?` and close the modal, losing the view as a
side effect of cancelling something else.

`InlineConfirm` will call `preventDefault()` on the Escape it handles.
Escape is then claimed innermost-first: the first press disarms the
confirm, a second closes the modal. This is correct on its own terms —
an armed confirm is the innermost dismissible thing on the screen, and
today it silently lets the keystroke carry on to whatever is outside it —
so it gets its own test in `InlineConfirm.test.tsx` rather than being
folded into the modal's.

If `jsdom` 26 turns out not to honour a cancelled keydown as a suppressed
close request, the fallback is a `cancel` handler on the dialog that
`preventDefault()`s while a confirm is armed. The `InlineConfirm` change
stands either way.

## Deleting

From the modal, a confirmed delete closes it rather than navigating:
`useDeleteRender` has already dropped the row from the topic's cache, so
the grid behind has lost the tile before the dialog goes. Focus is the
part the platform cannot do here — a `<dialog>` restores focus to the
element that opened it, but that tile has unmounted. `RenderGrid` already
solves this for tile-level deletes by focusing its section-label anchor,
and the modal's delete reuses that path.

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

## Dependency

`jsdom` moves from `^25.0.1` to `^26` in `web/package.json`, with
`package-lock.json` regenerated. jsdom 25 does not implement
`HTMLDialogElement.prototype.showModal` and throws on the call, so without
this the modal could only be tested against a stub of the behaviour under
test.

This is the first step of implementation, ahead of any component work, and
the whole web suite has to stay green across it. If it does not, the
fallback is a hand-rolled `role="dialog" aria-modal="true"` portal owning
its own Escape handler, focus-on-open, focus restore and Tab trap — the
same external behaviour, roughly sixty more lines of our own a11y code,
and no dependency change.

## Accessibility

The modal's accessible name is the template, carried by `aria-label` on the
dialog. The dialog needs a name and the template is what distinguishes one
render of a topic from another; the topic itself is named by the page
behind the modal and by the `<h1>` on the standalone route. Pointing
`aria-labelledby` at the template chip would say the same thing, but `Chip`
renders a bare `<span>` with no id, and growing a shared component an `id`
prop for one caller is worse than naming the dialog directly.

The `✕` carries `aria-label="Close"`. Everything else — the focus trap,
returning focus to the tile on close in the ordinary case, keeping the
background from receiving focus — comes from `showModal()`.

## Tests

New:

- `RenderModal.test.tsx` — a tile click opens the dialog and a modified
  click does not; Escape closes; a backdrop click closes and a click
  inside does not; an armed delete confirm swallows the first Escape and
  the modal survives it; a confirmed delete closes the modal.
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
