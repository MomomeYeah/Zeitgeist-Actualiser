# Paging between renders inside the modal

The render modal shows one meme at a time, and the only way to see the next
one is to close it and click another tile. Looking through the eight renders
a topic has accumulated therefore costs sixteen clicks, half of them spent
dismissing something. This design adds prev/next to the modal, opens it for
renders that are still generating or have failed, and marks the open render
in the grid behind.

The previous design (`2026-09-20-render-modal-design.md`) listed this as out
of scope — "the grid is still visible behind it and nothing asks for this
yet". Something asks for it now.

## Scope

In:

- Prev/next chevrons and a position counter in the modal, walking every
  render the topic has.
- Opening the modal on a `generating` or `failed` render, from its tile and
  by paging onto it, with a panel that shows what there is to show.
- The failed tile's footer reduced to `Render failed`, its reason moved into
  the modal.
- Deleting from inside the modal advancing to the next render instead of
  closing.
- An accent outline on the open render's tile, readable through the scrim.

Out:

- Any change to the address bar. Paging is component state, as opening was.
  The permanent route still names the render and **Copy link** still hands
  it out; browsing a grid of memes writes no history.
- Any backend change. No route, response model or `openapi.json` movement,
  so `uv run pytest`'s contract assertion is untouched.
- Wrap-around at the ends. See "The ends".
- The pending placeholders. A request in flight has no render id, nothing
  to draw at full size, and becomes a real `generating` row within a poll.
- Preloading the next render's PNG. The grid tiles already request the full
  image at `size="grid"`, so the browser has it cached by the time you page
  onto it.

## What the cycle is

Every row in `TopicDetail.renders`, in the order the grid draws them, which
is the order the store returns: `ORDER BY created_at, id`. Paging therefore
walks the tiles left to right and top to bottom, and the order is stable
across polls.

Failed and generating rows are in the cycle. The alternative — stepping
only through ready images — was considered and rejected: a counter reading
`2 / 5` on a topic whose grid shows seven tiles invites the reader to work
out which two are missing, and skipping a tile the arrows just passed over
is a silent disagreement between the modal and the grid behind it. Being in
the cycle means being openable directly too, so every tile opens the modal,
whatever state it is in.

## The controls

Two chevron `<button>`s on the image frame's left and right edges,
vertically centred, at `--text-40`, going `--text` on hover **and** on
keyboard focus. They carry `aria-label="Previous render"` and
`aria-label="Next render"`; the glyphs are `‹` and `›`, which say nothing
to a screen reader. A `2 / 7` counter sits centred at the foot of the frame,
inside its 18px padding band rather than over the image, in `--font-mono` at
`--text-35`.

Persistent-but-dim was chosen over revealing them on hover. Hover-reveal
looks better in a screenshot and leaves the meme unobstructed, but it hides
the feature's own existence: a modal that has quietly gained paging teaches
nobody it has, and a touch screen has no hover to teach with. At 40% the
chevrons are visible without competing with the image, and the resting
state is the only difference between the two designs.

`←` and `→` page as well.

With one render there is nothing to page to, so the grid passes no `nav` at
all and the modal draws neither chevrons nor counter. A topic with a single
meme looks exactly as it does today.

### The ends

At the first render the prev chevron is `disabled`, at the last the next
one is; neither wraps. With a visible counter, going from `7 / 7` to
`1 / 7` reads as a glitch rather than a loop, and a dimmed arrow says
"this is the end" without a second indicator to draw. `disabled` also
keeps the buttons out of the Tab order at the ends, which is the behaviour
a keyboard user expects from a control that cannot do anything.

## What the modal shows for a render that is not ready

`RenderDetail` currently assumes an image. Three states now, and the rules
are `RenderTile`'s own rather than new ones — the tile and the modal should
not disagree about what a failed render is.

**failed.** The dashed panel that today reads "has no image on disk" takes
the row's own `error` instead, in full and at readable size, with
`"No reason was recorded."` when the column is null. No **Download PNG**:
there is no PNG. **Copy link** stays, because a failure is a thing worth
sending someone. The delete action becomes **Dismiss**: a plain button in
place of the `InlineConfirm`, firing the mutation on its only click, exactly
as the tile's `✕` does — there is no image to lose.

**generating.** The sweeping bar and the tile's own `writing brief…` or
`rendering…`, at panel scale. No Download. The delete action becomes
**Cancel**, also unconfirmed, matching the tile: the job keeps running
server-side and its result is dropped, because a deleted row stays deleted
(`generation._draw`). When a poll turns the row ready the panel swaps to
the image where it stands — the id has not changed and the record is looked
up fresh each pass, so nothing reopens.

**A `generating` auto row carries `rationale=""`** (`generation.py:535`),
so **Why this template** is omitted when the rationale is empty rather than
drawn as a heading over nothing.

**ready, PNG missing.** Unchanged: the `<img onError>` path still gives the
dashed panel naming the shortened id. Two different failures, two
sentences, one panel style.

## Two consequences for the tiles

**The failed tile's footer says `Render failed`.** The server's sentence
moves wholly into the modal, where there is room to read it. The `title`
tooltip goes with it: leaving it would put the same sentence in two places,
and the tooltip is the worse of the two — it cannot be selected, copied or
reached by keyboard.

**Failed and generating tiles become openable.** Neither is a link today.
Each gets what the ready tile has: the preview box becomes an `<a>` to
`renderPath(render)` carrying the grid's click handler, so an ordinary
click opens the modal and a modified click still opens the permalink in a
new tab. The footer keeps its own `✕`, which must not open anything — it is
outside the anchor, as it already is on a ready tile.

The permanent route draws the same `RenderDetail`, so `/runs/…/renders/…`
gains the failed and generating panels for free. Today that page shows a
failed render as a broken image.

## The cursor

A hook, `useRenderCursor(renders)`, in `web/src/features/topics/`, returning
`{ record, index, count, hasPrev, hasNext, open, close, prev, next }`.
`RenderGrid` calls it and wires tiles to `open` and chevrons to
`prev`/`next`. The reasoning below is the awkward part of this feature, and
putting it in a hook means it is tested against plain arrays rather than
probed through a rendered modal.

Its state is `{ id, index } | null` — the render being shown, and where it
sat when it was chosen. Each render pass resolves that against the current
list:

1. The id is in `renders` → show that record. Its index may have moved;
   the stored one is only a fallback and is re-synced, not trusted.
2. The id has gone and `renders` is not empty → show
   `renders[min(index, renders.length - 1)]`.
3. `renders` is empty → closed.

Rule 2 is both behaviours the feature needs, from one line. Deleting row
*i* slides row *i+1* down into index *i*, so "the same index" **is** "the
next one"; deleting the last row leaves the index past the end, so the
clamp lands on what is now the last, which is the one before the deleted
row. There is no separate end case to get wrong.

The record is derived during the render pass, not assigned in an effect. An
effect would mean one pass with no record and therefore no modal, and an
unmounted `Modal` restores focus to the grid and re-traps it on remount —
a visible flinch in the middle of the very interaction this design exists
to smooth. An effect afterwards only re-syncs the stored `{ id, index }` to
what was shown.

### This reverses a constraint from the previous design

`RenderModal` takes no `onDeleted`, and its doc comment explains why:
react-query does not run a `mutate()` callback on a component that has
already unmounted, and the modal always unmounted when the row left the
cache. Under this design it survives the delete, so the callback would now
work.

The cursor still derives from the list rather than taking a callback. A row
can leave for reasons that are not a delete from the modal — a tile's own
`✕` behind the scrim, another tab, a topic refetch — and one rule that
covers every departure is worth more than a callback that covers the common
one plus a fallback for the rest.

The doc comments on `RenderGrid`, `RenderModal` and `RenderDetail` argue
the old behaviour at length. They need rewriting, not extending; in this
codebase they are load-bearing, and one left describing a modal that
unmounts on delete would be worse than no comment.

### `RenderDetail` is keyed by `record.id`

Not cosmetic. It holds four pieces of per-render state: the image's
`failed` flag, the delete mutation, that mutation's error line, and —
inside `InlineConfirm` — whether a delete is armed. Paging with any of them
carried over is wrong, and two of the four are actively dangerous:

- Page off a render whose PNG is missing and the next render, which has an
  image, would still draw the dashed panel.
- Arm `Delete this render?`, page on, and the confirm is still armed
  pointing at a render you never chose. One click and it is gone.

`key={record.id}` resets all four together, which is also the right rule
for the error line: a failed DELETE belongs to the render it was attempted
on.

## Where the chevrons live

The chevrons sit on the image frame, and the frame belongs to
`RenderDetail` — so `RenderDetail` takes an optional
`nav?: { onPrev, onNext, hasPrev, hasNext, index, count }` and draws the
chevrons and the counter only when it is given one. The standalone route
passes nothing and is unchanged. Positioning them from `RenderModal`
instead would mean guessing the frame's height from outside it, and would
break the moment the frame's padding changed.

One arrangement still serves both surfaces. `RenderDetail` gains no
`layout` prop.

`RenderModal` takes the same optional `nav` and is the only place the two
halves meet: it passes `nav` down to `RenderDetail` for the chevrons, and
passes `Modal` an `onArrowKey` that calls `nav.onPrev` or `nav.onNext` —
declining the step when the corresponding `hasPrev`/`hasNext` is false, so a
keypress at the end of the list does what the disabled chevron does. With no
`nav` it passes no `onArrowKey`, and the arrow keys are inert.

## Arrow keys belong to `Modal`

`Modal` gains `onArrowKey?: (step: -1 | 1) => void`, called for `←` with
`-1` and `→` with `1`.

It has to go there. The panel is what takes focus when the modal opens, so
a handler on a wrapper *inside* the panel would receive nothing until the
user had tabbed onto some control — the keys would be dead exactly when the
modal first appears, which is when they are most likely to be tried.

The prop is narrow rather than a general `onKeyDown` escape hatch: the
modal primitive keeps owning Escape and the Tab trap, and gains one more
named key. It ignores the keys when the event's target is an `input` or
`textarea`, so the next modal to grow a text field does not find its arrow
keys stolen by the container.

Escape's existing innermost-first arrangement is untouched: an armed
`InlineConfirm` still swallows the first press. Nothing else in the modal
uses the arrow keys.

## The highlight

The open render's `<li>` in the grid takes
`outline: 1px solid var(--accent)` with an `outline-offset`, from
`RenderGrid.module.css`. An outline rather than a border because it does
not affect layout — a border would resize the tile and reflow the row
behind the scrim as you page.

It goes on the `<li>`, not inside `RenderTile`. All four tile states are
openable now, and one rule on the wrapper works for every one of them
without the tile needing to know it is the current one.

`--accent` is `#ffd93d` at full strength against a `rgba(10, 8, 5, 0.72)`
scrim, which is what makes it readable through the wash.
`no-raw-colours.test.ts` forbids literal colours in `*.module.css`, so the
token is the only way to write this anyway.

Because the cursor is null whenever the modal is closed, no tile is ever
outlined without a modal over it.

## Tests

`useRenderCursor` — unit, against plain arrays:

- `open` selects; `prev` and `next` step; `hasPrev`/`hasNext` are false at
  the respective ends and the cursor does not move when they are called
  there.
- A row removed from the middle while open shows the one that took its
  place.
- The last row removed while open shows the one before it.
- The only row removed while open closes the cursor.
- A row appended while open leaves the cursor where it is, with `count`
  grown.
- The open row changing status keeps it open on the same id.

`RenderGrid.test.tsx` — integration:

- An ordinary click on a failed tile and on a generating tile opens the
  dialog; both keep their `href`.
- The chevrons page, `←`/`→` page, and the counter reads `2 / 7`.
- A confirmed delete from the modal leaves the modal open on the next
  render.
- Deleting the last remaining render closes the modal and puts focus on
  the section-label anchor.
- The outlined tile is the open one, and follows the arrows.
- With one render, no chevrons and no counter are drawn.

`RenderDetail.test.tsx`:

- A failed record draws its `error` in full, offers no **Download PNG**,
  and its delete action is labelled **Dismiss** and needs no confirmation.
- A null `error` draws `No reason was recorded.`
- A generating record draws the doing line, offers no Download, and its
  action is **Cancel**.
- An auto record with `rationale: ""` draws no **Why this template**.
- Given `nav`, draws both chevrons and the counter; without it, neither.
- Paging from a record whose image failed to one that loads draws the
  image — the keyed-reset case, which is the bug this design would
  otherwise ship.
- Arming the delete confirm and then changing the record leaves the next
  render unarmed.

`RenderTile.test.tsx`:

- A failed tile's footer reads `Render failed` and carries no `title`.
- Failed and generating previews are links to `renderPath`, and their `✕`
  is not inside the link.

`Modal.test.tsx`:

- `←` and `→` call `onArrowKey` with `-1` and `1` while focus is on the
  panel itself, immediately after opening.
- Neither key does anything when `onArrowKey` is absent.
- Neither fires when the event comes from an `input`.

`RenderDetailPage.test.tsx` — the route draws a failed render's reason
rather than a broken image.
