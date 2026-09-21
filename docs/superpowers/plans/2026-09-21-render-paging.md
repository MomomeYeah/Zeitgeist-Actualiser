# Render Paging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Page between a topic's renders from inside the render modal, with
chevrons and arrow keys, including the generating and failed rows the modal
cannot open today.

**Architecture:** A `useRenderCursor` hook owns which render is open and
resolves it against the live list each render pass, so a deleted row advances
the modal rather than closing it. `RenderDetail` grows panels for the two
non-ready states and an optional `nav` prop for the chevrons. `Modal` gains one
named key. Nothing is fetched that is not already in `TopicDetail.renders`, and
no backend file is touched.

**Tech Stack:** React 19, TypeScript, CSS modules, vitest + @testing-library/react,
msw.

**Design spec:** `docs/superpowers/specs/2026-09-21-render-paging-design.md`

## Global Constraints

- **Definition of Done** (all seven, from `CLAUDE.md`, run from the repo root):
  `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`,
  `uv run pytest`, `npm --prefix web run lint`, `npm --prefix web run typecheck`,
  `npm --prefix web test`. A task is not finished until they pass.
- **No Python changes in this plan.** No route, response model or
  `web/openapi.json` movement, so `uv run pytest`'s contract assertion is
  untouched. The four Python commands still have to pass; they have nothing to
  do.
- **TypeScript: no `any`, no `!`, no type assertions of any kind.** Enforced by
  eslint (`@typescript-eslint/no-explicit-any`, `no-non-null-assertion`,
  `consistent-type-assertions: { assertionStyle: "never" }`). Write the
  undefined check instead.
- **`noUncheckedIndexedAccess` is on.** `renders[i]` has type
  `RenderRecord | undefined`. Every index access needs an `undefined` branch —
  which this plan uses deliberately as the bounds check.
- **`verbatimModuleSyntax` is on.** Type-only imports must say `import type`.
- **No literal colours in `*.module.css`.** `web/src/styles/no-raw-colours.test.ts`
  fails on hex and `rgba()`. Use the tokens in `web/src/styles/tokens.css`.
- **Import alias:** `@/` is `web/src/`.
- **Formatting:** no prettier in this project. Match the surrounding file —
  2-space indent, double quotes, semicolons, ~90 columns.
- **Commit messages:** sentence-case imperative, no `feat:`/`fix:` prefix, and
  end with the trailer shown in each commit step.
- Run `npm` commands as `npm --prefix web <script>` from the repo root, and
  single test files as
  `npm --prefix web test -- src/path/to/File.test.tsx`.

---

## File Structure

**Created:**

| File | Responsibility |
| --- | --- |
| `web/src/features/topics/useRenderCursor.ts` | Which render is open, and how it survives the list changing under it. |
| `web/src/features/topics/useRenderCursor.test.ts` | The cursor's rules, against plain arrays. |
| `web/src/components/WorkingBar.tsx` | The sweeping bar and its doing line, shared by the tile and the modal. |
| `web/src/components/WorkingBar.module.css` | That bar's look and its keyframes, defined once. |
| `web/src/components/WorkingBar.test.tsx` | The bar's one contract: the track is decorative, the words are not. |
| `web/src/features/renders/RenderDetail.test.tsx` | The body's own tests — it has none today. |

**Modified:**

| File | Change |
| --- | --- |
| `web/src/components/Modal.tsx` | `onArrowKey` alongside Escape and the Tab trap. |
| `web/src/components/Modal.test.tsx` | Arrow-key cases. |
| `web/src/features/renders/RenderDetail.tsx` | Generating and failed panels, action labels, the optional `nav`. |
| `web/src/features/renders/RenderDetail.module.css` | Chevrons, counter, the dismiss button, a positioned frame. |
| `web/src/features/renders/RenderModal.tsx` | Passes `nav` down, keys the body, wires the arrow keys. |
| `web/src/features/renders/RenderModal.test.tsx` | Paging and per-record reset. |
| `web/src/features/renders/RenderDetailPage.test.tsx` | The standalone route drawing a failed render. |
| `web/src/features/topics/RenderTile.tsx` | `Render failed` footer; failed and generating previews become links. |
| `web/src/features/topics/RenderTile.module.css` | Sheds the sweep rules; gains `.previewLink`. |
| `web/src/features/topics/RenderGrid.tsx` | Uses the cursor; marks the open tile. |
| `web/src/features/topics/RenderGrid.module.css` | The open tile's outline. |
| `web/src/features/topics/RenderGrid.test.tsx` | Paging, the new tile states, the highlight. |
| `web/src/features/topics/TopicDetailPage.test.tsx` | Delete-advances and delete-the-last, through the real cache. |

---

## Task 1: The cursor

**Files:**
- Create: `web/src/features/topics/useRenderCursor.ts`
- Test: `web/src/features/topics/useRenderCursor.test.ts`

**Interfaces:**
- Consumes: `RenderRecord` from `@/api/types`; `makeRenderRecord` from
  `@/test/factories`.
- Produces:
  ```ts
  export interface RenderCursor {
    record: RenderRecord | null;
    index: number;   // 0-based; -1 when closed
    count: number;
    hasPrev: boolean;
    hasNext: boolean;
    open: (id: string) => void;
    close: () => void;
    prev: () => void;
    next: () => void;
  }
  export function useRenderCursor(renders: RenderRecord[]): RenderCursor;
  ```
  Task 8 is the only consumer.

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/topics/useRenderCursor.test.ts`:

```ts
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RenderRecord } from "@/api/types";
import { useRenderCursor } from "@/features/topics/useRenderCursor";
import { makeRenderRecord } from "@/test/factories";

/** A list of renders named by id, which is all these tests distinguish. */
function rows(...ids: string[]): RenderRecord[] {
  return ids.map((id) => makeRenderRecord({ id }));
}

function mount(initial: RenderRecord[]) {
  return renderHook((renders: RenderRecord[]) => useRenderCursor(renders), {
    initialProps: initial,
  });
}

describe("useRenderCursor", () => {
  it("is closed until a render is opened", () => {
    const { result } = mount(rows("r1", "r2", "r3"));

    expect(result.current.record).toBeNull();
    expect(result.current.index).toBe(-1);
    // The count is the list's, open or not: the grid's hint and the modal's
    // counter both describe the same list.
    expect(result.current.count).toBe(3);
    // Nothing to step from, so neither direction is offered.
    expect(result.current.hasPrev).toBe(false);
    expect(result.current.hasNext).toBe(false);
  });

  it("opens the render it is asked for, wherever it sits", () => {
    const { result } = mount(rows("r1", "r2", "r3"));

    act(() => result.current.open("r2"));

    expect(result.current.record?.id).toBe("r2");
    expect(result.current.index).toBe(1);
    expect(result.current.hasPrev).toBe(true);
    expect(result.current.hasNext).toBe(true);
  });

  it("steps forwards and back through the list", () => {
    const { result } = mount(rows("r1", "r2", "r3"));

    act(() => result.current.open("r1"));
    act(() => result.current.next());
    expect(result.current.record?.id).toBe("r2");

    act(() => result.current.next());
    expect(result.current.record?.id).toBe("r3");

    act(() => result.current.prev());
    expect(result.current.record?.id).toBe("r2");
  });

  it("will not step off the front of the list", () => {
    const { result } = mount(rows("r1", "r2"));

    act(() => result.current.open("r1"));
    expect(result.current.hasPrev).toBe(false);

    act(() => result.current.prev());

    // Still on r1 rather than wrapping to r2, which is what `disabled`
    // chevrons promise and what the arrow keys must honour too.
    expect(result.current.record?.id).toBe("r1");
  });

  it("will not step off the end of the list", () => {
    const { result } = mount(rows("r1", "r2"));

    act(() => result.current.open("r2"));
    expect(result.current.hasNext).toBe(false);

    act(() => result.current.next());

    expect(result.current.record?.id).toBe("r2");
  });

  it("shows the render that took the place of one deleted from the middle", () => {
    // The point of the whole feature: a delete from inside the modal leaves
    // the modal open on the next render along.
    const view = mount(rows("r1", "r2", "r3"));

    act(() => view.result.current.open("r2"));
    view.rerender(rows("r1", "r3"));

    expect(view.result.current.record?.id).toBe("r3");
    expect(view.result.current.index).toBe(1);
    expect(view.result.current.count).toBe(2);
  });

  it("shows the render before one deleted from the end", () => {
    // There is no "next" to advance to, so the clamp falls back to what is
    // now the last render rather than closing.
    const view = mount(rows("r1", "r2", "r3"));

    act(() => view.result.current.open("r3"));
    view.rerender(rows("r1", "r2"));

    expect(view.result.current.record?.id).toBe("r2");
    expect(view.result.current.hasNext).toBe(false);
  });

  it("closes when the render it was showing was the only one", () => {
    const view = mount(rows("r1"));

    act(() => view.result.current.open("r1"));
    view.rerender([]);

    expect(view.result.current.record).toBeNull();
    expect(view.result.current.index).toBe(-1);
  });

  it("stays where it is when a render arrives while one is open", () => {
    // Polling appends rows. Jumping the modal to a render the user did not
    // ask for would make the screen move under them.
    const view = mount(rows("r1", "r2"));

    act(() => view.result.current.open("r1"));
    view.rerender(rows("r1", "r2", "r3"));

    expect(view.result.current.record?.id).toBe("r1");
    expect(view.result.current.index).toBe(0);
    expect(view.result.current.count).toBe(3);
    expect(view.result.current.hasNext).toBe(true);
  });

  it("follows the open row through a change of status", () => {
    // A generating render turning ready is the same render, so the modal
    // stays on it and swaps what it draws.
    const view = mount([
      makeRenderRecord({ id: "r1" }),
      makeRenderRecord({ id: "g1", status: "generating" }),
    ]);

    act(() => view.result.current.open("g1"));
    view.rerender([
      makeRenderRecord({ id: "r1" }),
      makeRenderRecord({ id: "g1", status: "ready" }),
    ]);

    expect(view.result.current.record?.id).toBe("g1");
    expect(view.result.current.record?.status).toBe("ready");
  });

  it("re-reads its position when a render before the open one goes", () => {
    // The falsifiable case for keeping the stored index in step with the
    // list. Open r3 at index 2; r1 is then deleted from behind the modal,
    // putting r3 at index 1; then r3 itself is deleted, leaving three rows.
    // Resolving from the fresh index 1 lands on r4, which is the render
    // that took r3's place. Resolving from the stale index 2 lands on r5
    // and silently skips one.
    const view = mount(rows("r1", "r2", "r3", "r4", "r5"));

    act(() => view.result.current.open("r3"));
    view.rerender(rows("r2", "r3", "r4", "r5"));
    expect(view.result.current.index).toBe(1);

    view.rerender(rows("r2", "r4", "r5"));

    expect(view.result.current.record?.id).toBe("r4");
  });

  it("closes on request, and can be reopened", () => {
    const { result } = mount(rows("r1", "r2"));

    act(() => result.current.open("r2"));
    act(() => result.current.close());
    expect(result.current.record).toBeNull();

    act(() => result.current.open("r1"));
    expect(result.current.record?.id).toBe("r1");
  });

  it("ignores a request to open a render that is not in the list", () => {
    // A stale id must not put the modal up on nothing.
    const { result } = mount(rows("r1"));

    act(() => result.current.open("gone"));

    expect(result.current.record).toBeNull();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/features/topics/useRenderCursor.test.ts`
Expected: FAIL — `Failed to resolve import "@/features/topics/useRenderCursor"`.

- [ ] **Step 3: Write the hook**

Create `web/src/features/topics/useRenderCursor.ts`:

```ts
import { useEffect, useState } from "react";

import type { RenderRecord } from "@/api/types";

/** Where the modal is: which render, and where that render sat. */
interface Position {
  id: string;
  index: number;
}

export interface RenderCursor {
  /** The render to show, or null when the modal is closed. */
  record: RenderRecord | null;
  /** Its 0-based place in the list, or -1 when closed. */
  index: number;
  /** How many renders there are to page through. */
  count: number;
  hasPrev: boolean;
  hasNext: boolean;
  /** Show this render. A id that is not in the list is ignored. */
  open: (id: string) => void;
  close: () => void;
  prev: () => void;
  next: () => void;
}

/**
 * Which render the modal is showing, and what happens to it when the list
 * moves underneath.
 *
 * The state is an id *and* a position, because the id alone cannot survive
 * its own row being deleted — and a delete from inside the modal should
 * carry on to the next render rather than shutting the modal. Resolution
 * each pass:
 *
 * 1. The id is still in the list → show that row, and remember where it
 *    now is.
 * 2. The id has gone → show whatever is at the same index, clamped to the
 *    end of the list.
 * 3. The clamp produced nothing → closed.
 *
 * Rule 2 is both behaviours the screen needs, from one line. Deleting row
 * *i* slides row *i+1* down into index *i*, so "the same index" is "the
 * next one"; deleting the last row leaves the index past the end, so the
 * clamp lands on the new last row, which is the one before it. An emptied
 * list clamps to -1, which is rule 3.
 *
 * The record is worked out during the render pass rather than assigned in
 * an effect. An effect would leave one pass with no record and therefore no
 * modal, and an unmounted modal hands focus back to the grid and re-traps
 * it on the way in — a visible flinch in the middle of the interaction this
 * exists to smooth. The effect below only writes the resolved position
 * back, so the next deletion resolves from where the row actually is.
 */
export function useRenderCursor(renders: RenderRecord[]): RenderCursor {
  const [position, setPosition] = useState<Position | null>(null);

  const held =
    position === null ? -1 : renders.findIndex((render) => render.id === position.id);
  const at =
    position === null
      ? -1
      : held === -1
        ? Math.min(position.index, renders.length - 1)
        : held;
  // Indexing is the bounds check: `noUncheckedIndexedAccess` makes this
  // `RenderRecord | undefined`, so a clamp that produced -1 — or any index
  // the list does not reach — arrives here as `undefined` and closes.
  const shown = at === -1 ? undefined : renders[at];
  const index = shown === undefined ? -1 : at;
  const shownId = shown?.id ?? null;

  useEffect(() => {
    if (position === null) return;
    if (shownId === null) {
      setPosition(null);
      return;
    }
    if (shownId !== position.id || index !== position.index) {
      setPosition({ id: shownId, index });
    }
  }, [position, shownId, index]);

  function step(delta: -1 | 1) {
    if (index === -1) return;
    const target = renders[index + delta];
    // Again the undefined branch is the bounds check — there is no wrapping,
    // so a step off either end does nothing.
    if (target === undefined) return;
    setPosition({ id: target.id, index: index + delta });
  }

  return {
    record: shown ?? null,
    index,
    count: renders.length,
    hasPrev: index > 0,
    hasNext: index !== -1 && index < renders.length - 1,
    open: (id: string) => {
      const found = renders.findIndex((render) => render.id === id);
      if (found !== -1) setPosition({ id, index: found });
    },
    close: () => setPosition(null),
    prev: () => step(-1),
    next: () => step(1),
  };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/features/topics/useRenderCursor.test.ts`
Expected: PASS, 13 tests.

- [ ] **Step 5: Run lint and typecheck**

Run: `npm --prefix web run lint` then `npm --prefix web run typecheck`
Expected: both clean. If `react-hooks/exhaustive-deps` complains about the
effect, fix it by naming the dependency, never by disabling the rule.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/topics/useRenderCursor.ts web/src/features/topics/useRenderCursor.test.ts
git commit -m "$(cat <<'MSG'
Add the render cursor the modal will page with

Holds an id and a position, so a row deleted from under the modal resolves
to the render that took its place rather than closing it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 2: Arrow keys on the modal primitive

**Files:**
- Modify: `web/src/components/Modal.tsx`
- Test: `web/src/components/Modal.test.tsx`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Modal`'s props gain
  `onArrowKey?: (step: -1 | 1) => void`. Task 6 passes it.

- [ ] **Step 1: Write the failing tests**

Add to `web/src/components/Modal.test.tsx`, inside the existing
`describe("Modal", …)` block, after the two Tab-wrapping tests:

```ts
  /** A modal that pages, with one stop inside it and a text field. */
  function openPaging(onArrowKey = vi.fn()) {
    render(
      <Modal label="drake" onClose={vi.fn()} onArrowKey={onArrowKey}>
        <button type="button">inside</button>
        <input aria-label="note" />
      </Modal>,
    );
    return { onArrowKey, user: userEvent.setup() };
  }

  it("pages on the arrow keys, from the focus it opens with", async () => {
    // The keys have to work the instant the modal appears, which is when
    // someone is most likely to try them — and at that moment focus is on
    // the panel itself, not on anything inside it. A handler mounted on a
    // wrapper within the panel would see none of this.
    const { onArrowKey, user } = openPaging();
    expect(screen.getByRole("dialog")).toHaveFocus();

    await user.keyboard("{ArrowLeft}");
    expect(onArrowKey).toHaveBeenCalledWith(-1);

    await user.keyboard("{ArrowRight}");
    expect(onArrowKey).toHaveBeenCalledWith(1);
    expect(onArrowKey).toHaveBeenCalledTimes(2);
  });

  it("leaves the arrow keys alone when it was given no handler", async () => {
    // A modal with nothing to page through must not throw on a keystroke
    // it has no use for: this fails outright if the handler is called
    // without checking it exists.
    const onClose = vi.fn();
    render(
      <Modal label="drake" onClose={onClose}>
        <button type="button">inside</button>
      </Modal>,
    );
    const user = userEvent.setup();

    await user.keyboard("{ArrowLeft}{ArrowRight}");

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("leaves the arrow keys to a text field inside it", async () => {
    // The caret's keys belong to the field. This modal has no text input
    // today, but the primitive is shared and the next one will.
    const { onArrowKey, user } = openPaging();

    await user.click(screen.getByLabelText("note"));
    await user.keyboard("{ArrowLeft}");

    expect(onArrowKey).not.toHaveBeenCalled();
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/components/Modal.test.tsx`
Expected: FAIL — the first two with `onArrowKey` not being a known prop (a
type error at build, or `onArrowKey` never called), the third passing
vacuously for now.

- [ ] **Step 3: Add the prop and the handler**

In `web/src/components/Modal.tsx`, add to the destructured props and the
props type:

```tsx
export function Modal({
  label,
  onClose,
  onArrowKey,
  children,
}: {
  /** The dialog's accessible name. */
  label: string;
  /** Escape, or a click on the backdrop. Never called for a click inside. */
  onClose: () => void;
  /**
   * `←` and `→`, as -1 and 1. Given a home here rather than left to the
   * caller because the panel is what holds focus when the modal opens, so
   * a handler on anything inside it would be deaf until the user had
   * tabbed onto a control. Narrow on purpose: this is one more named key
   * beside Escape and Tab, not a general `onKeyDown` escape hatch.
   */
  onArrowKey?: (step: -1 | 1) => void;
  children: ReactNode;
}) {
```

and in `onKeyDown`, between the Escape branch and the Tab branch:

```tsx
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      if (onArrowKey === undefined) return;
      // A caret's keys belong to the field it is in. `event.target` is what
      // the key was typed into, which is the control that should keep it.
      const typed = event.target;
      if (typed instanceof HTMLInputElement || typed instanceof HTMLTextAreaElement) {
        return;
      }
      onArrowKey(event.key === "ArrowLeft" ? -1 : 1);
      return;
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/components/Modal.test.tsx`
Expected: PASS, all cases including the pre-existing ones.

- [ ] **Step 5: Run lint and typecheck**

Run: `npm --prefix web run lint` then `npm --prefix web run typecheck`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/Modal.tsx web/src/components/Modal.test.tsx
git commit -m "$(cat <<'MSG'
Let a modal page on the arrow keys

The panel owns Escape and the Tab trap because it is what holds focus on
open; the arrow keys have to live there for the same reason.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 3: Share the sweeping bar

A refactor with no behaviour change: the modal is about to draw the same
"still being made" bar as the tile, and the keyframes should exist once. Its
gate is the existing suite staying green.

**Files:**
- Create: `web/src/components/WorkingBar.tsx`
- Create: `web/src/components/WorkingBar.module.css`
- Test: `web/src/components/WorkingBar.test.tsx`
- Modify: `web/src/features/topics/RenderTile.tsx`
- Modify: `web/src/features/topics/RenderTile.module.css`

**Interfaces:**
- Produces: `export function WorkingBar({ doing }: { doing: string })`.
  Task 4 draws it in the modal's frame.

- [ ] **Step 1: Write the failing test**

Create `web/src/components/WorkingBar.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WorkingBar } from "@/components/WorkingBar";

describe("WorkingBar", () => {
  it("says what is being done, and hides the bar from a screen reader", () => {
    // The sweep reports no progress — nothing knows how far along a brief
    // is — so it is decoration, and the sentence is the only thing worth
    // announcing. A track without `aria-hidden` is an unlabelled element
    // read out between the tile and its footer.
    const { container } = render(<WorkingBar doing="writing brief…" />);

    expect(screen.getByText("writing brief…")).toBeInTheDocument();
    expect(container.querySelectorAll("[aria-hidden='true']")).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm --prefix web test -- src/components/WorkingBar.test.tsx`
Expected: FAIL — `Failed to resolve import "@/components/WorkingBar"`.

- [ ] **Step 3: Create the component**

Create `web/src/components/WorkingBar.tsx`:

```tsx
import styles from "./WorkingBar.module.css";

/**
 * A render still being made: a sweeping bar and what is being done.
 *
 * The bar sweeps rather than filling to a fraction, because nothing reports
 * how far along a brief is and a percentage would be a number invented for
 * the screen.
 *
 * Shared by the topic grid's tile and the render modal's frame, which draw
 * it at very different sizes. The caller's box decides how much room it
 * gets; this decides what it looks like, so the keyframes exist once.
 */
export function WorkingBar({ doing }: { doing: string }) {
  return (
    <span className={styles.bar}>
      <span className={styles.track} aria-hidden="true">
        <span className={styles.sweep} />
      </span>
      <span className={styles.doing}>{doing}</span>
    </span>
  );
}
```

Create `web/src/components/WorkingBar.module.css` — the rules moved verbatim
from `RenderTile.module.css`, plus a wrapper that was previously the tile's
own flex column:

```css
/* The column the tile used to lay out itself. Here so both callers get the
   same spacing between the bar and its sentence. */
.bar {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
}

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
    width: 100%;
    opacity: 0.5;
  }
}

.doing {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  line-height: 1;
  color: var(--accent);
}
```

- [ ] **Step 4: Point the tile at it**

In `web/src/features/topics/RenderTile.tsx`, add the import:

```tsx
import { WorkingBar } from "@/components/WorkingBar";
```

and replace the body of `GeneratingTile`'s working box:

```tsx
    <div className={styles.generating}>
      <div className={styles.working}>
        <WorkingBar doing={doing} />
      </div>
```

In `web/src/features/topics/RenderTile.module.css`, delete `.track`,
`.sweep`, `.doing`, the `@keyframes sweep` block and the
`@media (prefers-reduced-motion: reduce)` block that only contained
`.sweep`. Keep `.working` — it is the sized box, and it shares its rule
with `.failedPreview`.

Read the whole file after editing and check that nothing else referenced the
four removed classes. `no-raw-colours.test.ts` catches a class referenced but
not defined; it does not catch one defined and never referenced, so this sweep
is a step here rather than something a gate will notice.

- [ ] **Step 5: Run the new test and the tile's existing tests**

Run: `npm --prefix web test -- src/components/WorkingBar.test.tsx src/features/topics/RenderGrid.test.tsx`
Expected: PASS. The grid's existing "writing brief…" and "rendering…" cases
must be untouched — this task changes no behaviour, and a failure there means
the markup moved further than intended.

- [ ] **Step 6: Run the whole web suite, lint and typecheck**

Run: `npm --prefix web test` then `npm --prefix web run lint` then
`npm --prefix web run typecheck`
Expected: all clean, with no test changed but the one added.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/WorkingBar.tsx web/src/components/WorkingBar.module.css web/src/components/WorkingBar.test.tsx web/src/features/topics/RenderTile.tsx web/src/features/topics/RenderTile.module.css
git commit -m "$(cat <<'MSG'
Share the working bar between the tile and the modal

The modal is about to draw the same sweeping bar for a render that is still
being made, and the keyframes should exist in one place.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 4: The modal body for a render that is not ready

**Files:**
- Modify: `web/src/features/renders/RenderDetail.tsx`
- Modify: `web/src/features/renders/RenderDetail.module.css`
- Create: `web/src/features/renders/RenderDetail.test.tsx`
- Modify: `web/src/features/renders/RenderDetailPage.test.tsx`

**Interfaces:**
- Consumes: `WorkingBar` from Task 3.
- Produces: `RenderDetail`'s props are unchanged (`record`, `onDeleted`); its
  behaviour now branches on `record.status`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/renders/RenderDetail.test.tsx`:

```tsx
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { RenderDetail } from "@/features/renders/RenderDetail";
import { makeRenderRecord } from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

function draw(overrides: Parameters<typeof makeRenderRecord>[0] = {}) {
  const onDeleted = vi.fn();
  const view = renderWithProviders(
    <RenderDetail
      record={makeRenderRecord({ id: "r1", templateId: "drake", ...overrides })}
      onDeleted={onDeleted}
    />,
  );
  return { onDeleted, user: userEvent.setup(), view };
}

/** Every render id a DELETE went out for, in order. */
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

describe("RenderDetail", () => {
  it("draws a failed render's reason in full, where there is room to read it", () => {
    // The tile now says only that the render failed, so this is the only
    // place the reason can be read. A panel that showed a broken image, or
    // the tile's truncated line, would lose it.
    draw({
      status: "failed",
      error: "caption for rejected overflows its box by 42px",
    });

    expect(
      screen.getByText("caption for rejected overflows its box by 42px"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("says a failed render recorded no reason, rather than nothing at all", () => {
    draw({ status: "failed", error: null });

    expect(screen.getByText("No reason was recorded.")).toBeInTheDocument();
  });

  it("offers no download for a render that has no image", () => {
    // There is no PNG behind the link, so offering it is an error waiting
    // to be clicked.
    draw({ status: "failed", error: "overflow" });

    expect(screen.queryByText("Download PNG")).not.toBeInTheDocument();
    // Copy link stays: a failure is a thing worth sending someone.
    expect(screen.getByRole("button", { name: "Copy link" })).toBeInTheDocument();
  });

  it("dismisses a failed render at once, without asking", async () => {
    // Matching the tile's own ✕: there is no image to lose, so a
    // confirmation is a click for nothing.
    const deleted = recordDeletes();
    const { user } = draw({ status: "failed", error: "overflow" });

    await user.click(screen.getByRole("button", { name: "Dismiss" }));

    await waitFor(() => expect(deleted).toEqual(["r1"]));
    expect(screen.queryByText("Delete this render?")).not.toBeInTheDocument();
  });

  it("draws a generating render as a brief being written", () => {
    draw({ status: "generating" });

    expect(screen.getByText("writing brief…")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByText("Download PNG")).not.toBeInTheDocument();
  });

  it("says a generating hand-written render is going straight to the renderer", () => {
    // `rationale: null` is the factory's manual render. It has no brief to
    // write.
    draw({ status: "generating", rationale: null });

    expect(screen.getByText("rendering…")).toBeInTheDocument();
  });

  it("cancels a generating render at once, without asking", async () => {
    const deleted = recordDeletes();
    const { user } = draw({ status: "generating" });

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(deleted).toEqual(["r1"]));
  });

  it("draws no rationale heading for a render whose brief is not written yet", () => {
    // A generating auto row carries `rationale: ""`, and a heading over an
    // empty paragraph is worse than no heading.
    draw({ status: "generating", rationale: "" });

    expect(screen.queryByText("Why this template")).not.toBeInTheDocument();
  });

  it("still asks before deleting a ready render", async () => {
    // The one state with something to lose keeps its confirmation.
    const deleted = recordDeletes();
    const { user } = draw();

    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(screen.getByText("Delete this render?")).toBeInTheDocument();
    expect(deleted).toEqual([]);

    await user.click(screen.getByRole("button", { name: "yes" }));
    await waitFor(() => expect(deleted).toEqual(["r1"]));
  });

  it("offers no download for a ready render whose image will not load", () => {
    // The database is authoritative for whether a render exists, so a
    // missing PNG is a styled panel — and the download that would 404 goes
    // with it.
    draw();

    fireEvent.error(screen.getByRole("img", { name: "drake meme" }));

    // `shortRunId` leaves an id of 12 characters or fewer alone, and this
    // record's is "r1" (`web/src/format.ts`).
    expect(screen.getByText("Render r1 has no image on disk")).toBeInTheDocument();
    expect(screen.queryByText("Download PNG")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/features/renders/RenderDetail.test.tsx`
Expected: FAIL — the failed and generating cases find an `<img>`, and
`Dismiss`/`Cancel` do not exist.

- [ ] **Step 3: Rewrite the component**

Replace `web/src/features/renders/RenderDetail.tsx` with:

```tsx
import { useState } from "react";

import { imageUrl } from "@/api/client";
import { useDeleteRender } from "@/api/queries";
import type { RenderRecord } from "@/api/types";
import { Chip } from "@/components/Chip";
import { CopyLinkButton } from "@/components/CopyLinkButton";
import { InlineConfirm } from "@/components/InlineConfirm";
import { SectionLabel } from "@/components/SectionLabel";
import { WorkingBar } from "@/components/WorkingBar";
import { renderPath, templateLabel } from "@/features/renders/render";
import { shortRunId } from "@/format";

import styles from "./RenderDetail.module.css";

/**
 * What the frame holds.
 *
 * A render only has an image once it is `ready`, and even then the PNG can
 * be gone from disk, so there are four cases and the picture is one of
 * them. The rules are `RenderTile`'s own rather than new ones — the tile
 * and the modal must not disagree about what a failed render is.
 */
function Frame({
  record,
  broken,
  onBroken,
}: {
  record: RenderRecord;
  /** Whether the image has already failed to load. */
  broken: boolean;
  onBroken: () => void;
}) {
  if (record.status === "generating") {
    return (
      <WorkingBar
        doing={record.origin.provenance === "manual" ? "rendering…" : "writing brief…"}
      />
    );
  }

  if (record.status === "failed") {
    // The row's own reason, in full. The tile says only that it failed, so
    // this is the only place it can be read.
    return (
      <span className={styles.failed}>{record.error ?? "No reason was recorded."}</span>
    );
  }

  if (broken) {
    // The database is authoritative for whether a render exists, so a PNG
    // deleted from under the row is a styled panel naming the shortened id,
    // not a broken-image icon. A different failure from the one above, so a
    // different sentence in the same panel.
    return (
      <span className={styles.failed}>
        {`Render ${shortRunId(record.id)} has no image on disk`}
      </span>
    );
  }

  return (
    <img
      className={styles.image}
      src={imageUrl(record.id, "full")}
      alt={`${templateLabel(record)} meme`}
      onError={onBroken}
    />
  );
}

/**
 * One render, at full size: the meme, what made it, and what can be done
 * with it. Drawn by the permanent route and by the modal the topic screen
 * opens, identically — the page adds a breadcrumb and a heading above it,
 * the modal adds a close button, and neither changes what is inside.
 *
 * It takes the record rather than fetching one. The topic screen is already
 * holding every field this needs in `TopicDetail.renders`, so the modal
 * opens on the current frame with no spinner and no second request, and
 * cannot disagree with the tile that opened it.
 *
 * The slot captions are deliberately absent: they are drawn on the meme in
 * the frame above. So are the run id, the generated time and the decoded
 * dimensions — see `2026-09-20-render-modal-design.md`, "What the body
 * shows".
 */
export function RenderDetail({
  record,
  onDeleted,
}: {
  record: RenderRecord;
  /**
   * Called once the row has gone. The standalone page is the real
   * consumer: it navigates back to the topic. The modal path passes a
   * no-op — `RenderGrid`'s cursor derives what to show next from the list
   * itself, because a row can leave for reasons that are not a delete from
   * the modal. See `useRenderCursor`.
   */
  onDeleted: () => void;
}) {
  const [broken, setBroken] = useState(false);
  const remove = useDeleteRender();
  const template = templateLabel(record);
  const destroy = () => remove.mutate(record, { onSuccess: onDeleted });
  // Something to hand over only exists on a ready row whose PNG loaded.
  const downloadable = record.status === "ready" && !broken;

  // For `auto`, the reason the model gave. A `generating` auto row has none
  // yet — the column is an empty string until the brief lands — and a
  // heading over an empty paragraph is worse than no heading.
  const why =
    record.origin.provenance === "manual" ? (
      <p className={styles.byHand}>written by hand</p>
    ) : record.origin.rationale === "" ? null : (
      <>
        <SectionLabel>Why this template</SectionLabel>
        <p className={styles.rationale}>{record.origin.rationale}</p>
      </>
    );

  return (
    <div className={styles.detail}>
      <div className={styles.chips} data-testid="chips">
        <Chip tone="accent">{template}</Chip>
        <Chip>{record.origin.provenance}</Chip>
      </div>

      <figure className={styles.frame}>
        <Frame record={record} broken={broken} onBroken={() => setBroken(true)} />
      </figure>

      {why}

      <div className={styles.footer}>
        {downloadable && (
          <a
            className={styles.download}
            href={imageUrl(record.id, "full")}
            download={`${template}-${record.id}.png`}
          >
            Download PNG
          </a>
        )}
        <CopyLinkButton path={renderPath(record)} />
        {/* Offered whether or not there is an image: a render whose PNG is
            gone, or which never had one, is the likeliest to want deleting.
            Pushed away from the two safe actions rather than sitting beside
            them.

            The margin is on a wrapper, not on `InlineConfirm`'s
            `className`: that prop reaches only the resting trigger, so the
            question that replaces it would lose the margin and jump left
            across the footer at the moment of being read.

            Only a ready render asks first. A failed or generating row has
            no image to lose, which is why the tile's own ✕ does not ask
            either — one rule, drawn twice. */}
        <div className={styles.delete}>
          {record.status === "ready" ? (
            <InlineConfirm
              label="Delete"
              question="Delete this render?"
              disabled={remove.isPending}
              onConfirm={destroy}
            />
          ) : (
            <button
              type="button"
              className={styles.dismiss}
              disabled={remove.isPending}
              onClick={destroy}
            >
              {record.status === "failed" ? "Dismiss" : "Cancel"}
            </button>
          )}
        </div>
      </div>
      {remove.isError && (
        <p role="alert" className={styles.deleteError}>
          {remove.error.detail}
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Add the styles**

In `web/src/features/renders/RenderDetail.module.css`, add to the existing
`.failed` rule so a sentence of prose reads as one:

```css
/* Long enough for a reason, narrow enough to read. */
.failed {
  max-width: 56ch;
  line-height: 1.6;
}
```

(Merge these two properties into the existing `.failed` block rather than
adding a second one.) Then add the dismiss button:

```css
/* Deliberately `InlineConfirm`'s resting trigger, token for token: this
   button occupies the same footer slot as that control and swapping between
   them as you page must not change the footer's shape. Written out rather
   than composed, because reaching into another component's stylesheet
   couples this file to that component's internals. */
.dismiss {
  padding: 8px 14px;
  border: 1px solid var(--contrast-border-strong);
  border-radius: var(--radius-pill);
  background: none;
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  color: var(--contrast-light);
  cursor: pointer;
  transition: background var(--transition), border-color var(--transition);
}

.dismiss:hover:not(:disabled) {
  background: var(--contrast-confirm);
}

.dismiss:disabled {
  opacity: 0.5;
  cursor: default;
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/features/renders/RenderDetail.test.tsx`
Expected: PASS, 10 tests.

- [ ] **Step 6: Add the standalone route's case**

In `web/src/features/renders/RenderDetailPage.test.tsx`, add a test that the
permanent route draws a failed render's reason. Follow the file's existing
handler setup for `GET /api/renders/:renderId` and
`GET /api/runs/:runId/topics/:topicId`; read the file first and match how its
other tests stub those.

```tsx
  it("draws a failed render's reason rather than a broken image", async () => {
    // The route shows the same body as the modal, so it gains the failed
    // panel too — today it draws an `<img>` at a URL that 404s.
    server.use(
      http.get("/api/renders/:renderId", () =>
        HttpResponse.json(
          makeRenderRecord({
            id: "r1",
            status: "failed",
            error: "the model is down",
          }),
        ),
      ),
    );

    renderPage();

    expect(await screen.findByText("the model is down")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
```

Use whatever the file already calls its mount helper instead of `renderPage`
if the name differs, and keep its existing handlers for the topic request that
feeds the breadcrumb.

- [ ] **Step 7: Run the render feature's tests, lint and typecheck**

Run: `npm --prefix web test -- src/features/renders` then
`npm --prefix web run lint` then `npm --prefix web run typecheck`
Expected: PASS and clean. `RenderModal.test.tsx` must still pass untouched —
its ready-render cases are unaffected by this task.

- [ ] **Step 8: Commit**

```bash
git add web/src/features/renders/RenderDetail.tsx web/src/features/renders/RenderDetail.module.css web/src/features/renders/RenderDetail.test.tsx web/src/features/renders/RenderDetailPage.test.tsx
git commit -m "$(cat <<'MSG'
Show a render that is generating or failed at full size

The body assumed an image. A failed row now shows its reason in full, a
generating row shows the bar the tile draws, and neither offers a download
for a PNG that does not exist.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 5: The chevrons and the counter

**Files:**
- Modify: `web/src/features/renders/RenderDetail.tsx`
- Modify: `web/src/features/renders/RenderDetail.module.css`
- Test: `web/src/features/renders/RenderDetail.test.tsx`

**Interfaces:**
- Produces:
  ```ts
  export interface RenderNav {
    onPrev: () => void;
    onNext: () => void;
    hasPrev: boolean;
    hasNext: boolean;
    /** 0-based. The counter draws `index + 1`. */
    index: number;
    count: number;
  }
  ```
  exported from `@/features/renders/RenderDetail`, plus `RenderDetail`'s new
  optional `nav?: RenderNav`. Tasks 6 and 8 use both.

- [ ] **Step 1: Write the failing tests**

Add to `web/src/features/renders/RenderDetail.test.tsx`. First a helper
beside `draw`:

```tsx
function drawWithNav(
  nav: Partial<RenderNav> = {},
  overrides: Parameters<typeof makeRenderRecord>[0] = {},
) {
  const onPrev = vi.fn();
  const onNext = vi.fn();
  renderWithProviders(
    <RenderDetail
      record={makeRenderRecord({ id: "r1", templateId: "drake", ...overrides })}
      onDeleted={vi.fn()}
      nav={{ onPrev, onNext, hasPrev: true, hasNext: true, index: 1, count: 7, ...nav }}
    />,
  );
  return { onPrev, onNext, user: userEvent.setup() };
}
```

and add `import type { RenderNav } from "@/features/renders/RenderDetail";`
to the imports. Then the cases:

```tsx
  it("draws no chevrons and no counter when it was given nothing to page", () => {
    // The standalone route, and a topic with a single render.
    draw();

    expect(screen.queryByRole("button", { name: "Previous render" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next render" })).not.toBeInTheDocument();
    expect(screen.queryByText(/\d+ \/ \d+/)).not.toBeInTheDocument();
  });

  it("counts from one, so the first render reads 1 / 7", () => {
    // The index is 0-based and the counter is not. Off by one here is the
    // kind of thing nobody notices until it says 0 / 7.
    drawWithNav({ index: 0, count: 7, hasPrev: false });

    expect(screen.getByText("1 / 7")).toBeInTheDocument();
  });

  it("pages on the chevrons", async () => {
    const { onPrev, onNext, user } = drawWithNav();

    await user.click(screen.getByRole("button", { name: "Previous render" }));
    expect(onPrev).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Next render" }));
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it("disables the chevron that would step off the front of the list", () => {
    // Disabled rather than wrapping, and disabled rather than merely
    // ignored: a dimmed arrow says where you are, and a disabled button
    // drops out of the modal's Tab order.
    drawWithNav({ hasPrev: false, index: 0 });

    expect(screen.getByRole("button", { name: "Previous render" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next render" })).toBeEnabled();
  });

  it("disables the chevron that would step off the end of the list", () => {
    drawWithNav({ hasNext: false, index: 6 });

    expect(screen.getByRole("button", { name: "Next render" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous render" })).toBeEnabled();
  });

  it("keeps the chevrons on a render that has no image to page away from", () => {
    // Paging has to work from a failed render too, or the cycle has holes
    // you can fall into and not get out of.
    drawWithNav({}, { status: "failed", error: "overflow" });

    expect(screen.getByRole("button", { name: "Next render" })).toBeEnabled();
    expect(screen.getByText("2 / 7")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/features/renders/RenderDetail.test.tsx`
Expected: FAIL — `nav` is not a known prop and the chevrons do not exist. The
first case ("no chevrons") passes vacuously.

- [ ] **Step 3: Add the prop, the chevrons and the counter**

In `web/src/features/renders/RenderDetail.tsx`, add above the `Frame`
component:

```tsx
/**
 * What a caller that can page hands down.
 *
 * It lives on `RenderDetail` rather than on `RenderModal` because the
 * chevrons sit on the image frame, and the frame is this component's.
 * Positioning them from outside would mean guessing the frame's height and
 * would break the moment its padding changed.
 */
export interface RenderNav {
  onPrev: () => void;
  onNext: () => void;
  hasPrev: boolean;
  hasNext: boolean;
  /** 0-based. The counter draws `index + 1`. */
  index: number;
  count: number;
}
```

Add to `RenderDetail`'s props:

```tsx
  /**
   * Prev/next, when there is more than one render to look at. Absent on the
   * standalone route and on a topic with a single render, and then the
   * frame draws no chevrons and no counter.
   */
  nav?: RenderNav;
```

and replace the `<figure>` with:

```tsx
      <figure className={styles.frame}>
        {nav !== undefined && (
          <button
            type="button"
            className={`${styles.chevron} ${styles.prev}`}
            aria-label="Previous render"
            disabled={!nav.hasPrev}
            onClick={nav.onPrev}
          >
            ‹
          </button>
        )}
        <Frame record={record} broken={broken} onBroken={() => setBroken(true)} />
        {nav !== undefined && (
          <>
            <button
              type="button"
              className={`${styles.chevron} ${styles.next}`}
              aria-label="Next render"
              disabled={!nav.hasNext}
              onClick={nav.onNext}
            >
              ›
            </button>
            {/* The glyphs above say nothing to a screen reader, which is
                what the aria-labels are for; this line is for the eye and
                needs no label of its own. */}
            <span className={styles.counter}>{`${nav.index + 1} / ${nav.count}`}</span>
          </>
        )}
      </figure>
```

- [ ] **Step 4: Style them**

In `web/src/features/renders/RenderDetail.module.css`, add
`position: relative;` to the existing `.frame` rule (the chevrons and the
counter are positioned against it), then append:

```css
/* On the frame's edges rather than hidden until hover: a modal that has
   quietly gained paging teaches nobody it has, and a touch screen has no
   hover to teach with. 40% at rest is quiet enough not to fight the meme. */
.chevron {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 56px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--scrim);
  color: var(--text-40);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  transition: color var(--transition), background var(--transition);
}

/* Focus as well as hover, or the keyboard gets a control it cannot see. */
.chevron:hover:not(:disabled),
.chevron:focus-visible {
  color: var(--text);
}

.chevron:disabled {
  opacity: 0.35;
  cursor: default;
}

.prev {
  left: 6px;
}

.next {
  right: 6px;
}

/* In the frame's own padding band, under the image rather than over it. */
.counter {
  position: absolute;
  bottom: 4px;
  left: 0;
  right: 0;
  text-align: center;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.06em;
  color: var(--text-35);
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/features/renders/RenderDetail.test.tsx`
Expected: PASS, 16 tests.

- [ ] **Step 6: Run lint, typecheck and the colour gate**

Run: `npm --prefix web run lint` then `npm --prefix web run typecheck` then
`npm --prefix web test -- src/styles/no-raw-colours.test.ts`
Expected: all clean. Every colour above is a token; a literal would fail the
third command.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/renders/RenderDetail.tsx web/src/features/renders/RenderDetail.module.css web/src/features/renders/RenderDetail.test.tsx
git commit -m "$(cat <<'MSG'
Draw prev/next chevrons and a counter on the render frame

Dim at rest and bright on hover or focus, disabled at either end rather
than wrapping, and absent entirely when the caller has nothing to page.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 6: Wire the modal

**Files:**
- Modify: `web/src/features/renders/RenderModal.tsx`
- Test: `web/src/features/renders/RenderModal.test.tsx`

**Interfaces:**
- Consumes: `Modal`'s `onArrowKey` (Task 2), `RenderNav` (Task 5).
- Produces: `RenderModal` gains `nav?: RenderNav`. Task 8 passes it.

- [ ] **Step 1: Write the failing tests**

In `web/src/features/renders/RenderModal.test.tsx`, extend the `openModal`
helper to take a `nav` and return the view, then add the cases. Replace the
helper with:

```tsx
function openModal(
  overrides: Parameters<typeof makeRenderRecord>[0] = {},
  handlers: { onClose?: () => void; nav?: RenderNav } = {},
) {
  const onClose = handlers.onClose ?? vi.fn();
  const view = renderWithProviders(
    <RenderModal
      record={makeRenderRecord({ id: "r1", templateId: "drake", ...overrides })}
      onClose={onClose}
      nav={handlers.nav}
    />,
  );
  return { onClose, user: userEvent.setup(), view };
}

/** A `nav` whose two callbacks are spies, with both directions available. */
function paging(overrides: Partial<RenderNav> = {}) {
  const onPrev = vi.fn();
  const onNext = vi.fn();
  return {
    onPrev,
    onNext,
    nav: { onPrev, onNext, hasPrev: true, hasNext: true, index: 1, count: 3, ...overrides },
  };
}
```

Add `import type { RenderNav } from "@/features/renders/RenderDetail";` and
`import { makeRenderRecord } from "@/test/factories";` (already present) to
the imports. Then the new cases:

```tsx
  it("hands the chevrons down to the body", async () => {
    // One integration assertion rather than a re-test of `RenderDetail`:
    // what this catches is `RenderModal` not passing `nav` through at all.
    const { onNext, nav } = paging();
    const { user } = openModal({}, { nav });

    await user.click(screen.getByRole("button", { name: "Next render" }));

    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it("pages on the arrow keys", async () => {
    // `Modal` owns the keystroke; this is the wiring that gives it
    // somewhere to go. Focus is on the panel, which is where it lands when
    // the modal opens — the case a handler inside the panel would miss.
    const { onPrev, onNext, nav } = paging();
    const { user } = openModal({}, { nav });

    await user.keyboard("{ArrowRight}");
    expect(onNext).toHaveBeenCalledTimes(1);

    await user.keyboard("{ArrowLeft}");
    expect(onPrev).toHaveBeenCalledTimes(1);
  });

  it("does not page past the end on the arrow keys", async () => {
    // The disabled chevron and the arrow key have to agree: a keystroke
    // that stepped where the button refuses to would wrap the list by the
    // back door.
    const { onNext, nav } = paging({ hasNext: false });
    const { user } = openModal({}, { nav });

    await user.keyboard("{ArrowRight}");

    expect(onNext).not.toHaveBeenCalled();
  });

  it("does not page past the front on the arrow keys", async () => {
    const { onPrev, nav } = paging({ hasPrev: false });
    const { user } = openModal({}, { nav });

    await user.keyboard("{ArrowLeft}");

    expect(onPrev).not.toHaveBeenCalled();
  });

  it("ignores the arrow keys when there is nothing to page through", async () => {
    // A single-render modal passes no `nav`, so no `onArrowKey` reaches
    // `Modal` and the keys are inert rather than throwing.
    const { onClose, user } = openModal();

    await user.keyboard("{ArrowLeft}{ArrowRight}");

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("starts the next render clean when it pages to one", async () => {
    // The body holds four things about the render it is showing: whether
    // its image failed, the delete mutation, that mutation's error, and
    // whether a delete is armed. Carrying any of them across a page is
    // wrong, and two are dangerous — an armed confirm would point at a
    // render the user never chose, and one click would destroy it.
    const { nav } = paging();
    const { view, user } = openModal({ id: "r1", templateId: "drake" }, { nav });

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByText("Delete this render?")).toBeInTheDocument();

    view.rerender(
      <RenderModal
        record={makeRenderRecord({ id: "r2", templateId: "two_buttons" })}
        onClose={vi.fn()}
        nav={nav}
      />,
    );

    expect(screen.queryByText("Delete this render?")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("draws the next render's image after paging off one that would not load", async () => {
    // The same reset, for the state that is merely wrong rather than
    // dangerous: without it, every render after a missing PNG shows the
    // dashed panel.
    const { nav } = paging();
    const { view } = openModal({ id: "r1", templateId: "drake" }, { nav });

    fireEvent.error(screen.getByRole("img", { name: "drake meme" }));
    expect(screen.queryByRole("img")).not.toBeInTheDocument();

    view.rerender(
      <RenderModal
        record={makeRenderRecord({ id: "r2", templateId: "two_buttons" })}
        onClose={vi.fn()}
        nav={nav}
      />,
    );

    expect(screen.getByRole("img", { name: "two_buttons meme" })).toBeInTheDocument();
  });
```

Add `fireEvent` to the `@testing-library/react` import at the top of the
file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/features/renders/RenderModal.test.tsx`
Expected: FAIL — `nav` is not a known prop; the chevrons and the arrow keys
do nothing; the two reset cases fail because the body keeps its state across a
new record.

- [ ] **Step 3: Rewrite the component**

Replace `web/src/features/renders/RenderModal.tsx` with:

```tsx
import type { RenderRecord } from "@/api/types";
import { Modal } from "@/components/Modal";
import type { RenderNav } from "@/features/renders/RenderDetail";
import { RenderDetail } from "@/features/renders/RenderDetail";
import { templateLabel } from "@/features/renders/render";

import styles from "./RenderModal.module.css";

/**
 * A render, opened over the topic it came from, with the topic's other
 * renders a keystroke away.
 *
 * Everything about being a modal — Escape, the focus trap, focus restore,
 * the backdrop, and now the arrow keys — belongs to `Modal`. What is added
 * here is the close button, which `Modal` leaves to its caller, and the
 * wiring between `Modal`'s keystrokes and the frame's chevrons. This is the
 * only place those two halves meet.
 *
 * There is no `onDeleted` prop. `RenderGrid`'s cursor works out what to
 * show from its own `renders`: a delete advances this modal to the render
 * that took the deleted one's place, and empties it only when the last row
 * goes. Deriving that from the list rather than from a callback is what
 * makes a row leaving for some other reason — a tile's own ✕ behind the
 * scrim, another tab, a refetch — behave the same way. `RenderDetail` still
 * requires the prop, so a no-op is passed through; it is the standalone
 * page's own `onDeleted` that navigates.
 *
 * The address bar does not change while this is open, and paging does not
 * change it either. The permanent route is still there and `Copy link`
 * hands it out, but browsing a grid of memes should not write a history
 * entry per glance.
 */
export function RenderModal({
  record,
  onClose,
  nav,
}: {
  record: RenderRecord;
  /** Escape, the backdrop, or the close button. */
  onClose: () => void;
  /** Prev/next, when the topic has more than one render. */
  nav?: RenderNav;
}) {
  return (
    <Modal
      label={templateLabel(record)}
      onClose={onClose}
      onArrowKey={
        nav === undefined
          ? undefined
          : (step) => {
              // The ends are checked here as well as on the chevrons'
              // `disabled`: a keystroke that stepped where the button
              // refuses to would wrap the list by the back door.
              if (step === -1) {
                if (nav.hasPrev) nav.onPrev();
              } else if (nav.hasNext) {
                nav.onNext();
              }
            }
      }
    >
      <button
        type="button"
        className={styles.close}
        aria-label="Close"
        onClick={onClose}
      >
        ✕
      </button>
      {/* Keyed by the render, so paging resets everything the body holds
          about the one it was showing: a failed image, the delete mutation,
          its error line, and whether a delete is armed. An armed confirm
          carried onto the next render would point at something the user
          never chose. */}
      <RenderDetail
        key={record.id}
        record={record}
        nav={nav}
        onDeleted={() => undefined}
      />
    </Modal>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/features/renders/RenderModal.test.tsx`
Expected: PASS, including the six pre-existing cases.

- [ ] **Step 5: Run lint and typecheck**

Run: `npm --prefix web run lint` then `npm --prefix web run typecheck`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/renders/RenderModal.tsx web/src/features/renders/RenderModal.test.tsx
git commit -m "$(cat <<'MSG'
Page the render modal with the chevrons and the arrow keys

The modal is where `Modal`'s keystrokes meet the frame's chevrons, and it
keys the body by render id so nothing survives a page — least of all an
armed delete confirm.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 7: Openable tiles, and a quieter failed footer

**Files:**
- Modify: `web/src/features/topics/RenderTile.tsx`
- Modify: `web/src/features/topics/RenderTile.module.css`
- Test: `web/src/features/topics/RenderGrid.test.tsx`

Tiles are tested through the grid in this codebase — `RenderTile` has no test
file of its own, and the design spec's mention of `RenderTile.test.tsx` is
answered by putting these cases where the existing tile cases already live.

**Interfaces:**
- Consumes: `renderPath` (already imported by the tile), `onOpen` (already a
  prop).
- Produces: `GeneratingTile` gains `to?: string` and
  `onOpen?: (event: MouseEvent<HTMLAnchorElement>) => void`. `RenderTile`'s
  props do not change.

- [ ] **Step 1: Change the failing test that asserts today's behaviour**

In `web/src/features/topics/RenderGrid.test.tsx`, replace the existing
`"keeps a failed render's tile, carrying the server's reason"` test with:

```tsx
  it("keeps a failed render's tile, saying only that it failed", async () => {
    // Per the handoff a failed render keeps its tile rather than vanishing.
    // The reason moved into the modal, where there is room to read it — a
    // one-line footer either truncates it or stretches the tile.
    const user = userEvent.setup();
    renderGrid([
      makeRenderRecord({
        id: "f1",
        status: "failed",
        error: "caption for rejected overflows its box",
      }),
    ]);

    expect(screen.getByText("Render failed")).toBeInTheDocument();
    expect(
      screen.queryByText("caption for rejected overflows its box"),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();

    await user.click(screen.getByText("failed"));

    expect(
      within(await screen.findByRole("dialog")).getByText(
        "caption for rejected overflows its box",
      ),
    ).toBeInTheDocument();
  });
```

- [ ] **Step 2: Write the other failing tests**

Add after it:

```tsx
  it("carries no tooltip on the failed tile, now that the reason has a home", () => {
    // Two copies of one sentence, and the tooltip is the worse copy: it
    // cannot be selected, copied, or reached by keyboard.
    renderGrid([makeRenderRecord({ id: "f1", status: "failed", error: "overflow" })]);

    expect(screen.getByText("Render failed")).not.toHaveAttribute("title");
  });

  it("links a failed tile to its permanent address, like a ready one", () => {
    // The href is what makes a tile shareable without opening it, and what
    // a ⌘-click opens in a new tab.
    renderGrid([makeRenderRecord({ id: "f1", status: "failed", error: "overflow" })]);

    expect(screen.getByText("failed").closest("a")).toHaveAttribute(
      "href",
      `/runs/${RUN_ID}/renders/f1`,
    );
  });

  it("opens a generating render in a modal, showing what it is still doing", async () => {
    const user = userEvent.setup();
    renderGrid([makeRenderRecord({ id: "g1", status: "generating" })]);

    await user.click(screen.getByText("writing brief…"));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("writing brief…")).toBeInTheDocument();
  });

  it("links a generating tile to its permanent address", () => {
    renderGrid([makeRenderRecord({ id: "g1", status: "generating" })]);

    expect(screen.getByText("writing brief…").closest("a")).toHaveAttribute(
      "href",
      `/runs/${RUN_ID}/renders/g1`,
    );
  });

  it("leaves a placeholder unlinked, because it has no row to open", async () => {
    // A request still in flight has no render id, so there is nothing to
    // address and nothing to show at full size.
    const user = userEvent.setup();
    renderGrid([], [{ mode: "llm", template_id: null, count: 1 }]);

    expect(screen.getByText("writing brief…").closest("a")).toBeNull();
    await user.click(screen.getByText("writing brief…"));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("dismisses a failed render from its tile without opening the modal", async () => {
    // The ✕ sits outside the link. Inside it, every dismissal would also
    // put the modal up on the render being dismissed.
    const deleted = recordDeletes();
    const user = userEvent.setup();
    renderGrid([makeRenderRecord({ id: "f1", status: "failed", error: "overflow" })]);

    await user.click(screen.getByRole("button", { name: "Dismiss render" }));

    await waitFor(() => expect(deleted).toEqual(["f1"]));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/features/topics/RenderGrid.test.tsx`
Expected: FAIL — no `Render failed` text, the previews are not links, and
clicking them opens nothing.

- [ ] **Step 4: Make the previews links and quieten the footer**

In `web/src/features/topics/RenderTile.tsx`:

Add `Link` to the imports:

```tsx
import { Link } from "react-router-dom";
```

Give `GeneratingTile` the two new props and wrap its box:

```tsx
export function GeneratingTile({
  label,
  doing,
  onCancel,
  to,
  onOpen,
}: {
  label: string;
  doing: string;
  onCancel?: () => void;
  /**
   * The render's permanent address. Absent on the grid's placeholders —
   * a request in flight has no row, so there is nothing to address.
   */
  to?: string;
  /** First refusal on a click of the preview — see `RenderGrid`. */
  onOpen?: (event: MouseEvent<HTMLAnchorElement>) => void;
}) {
  const working = (
    <div className={styles.working}>
      <WorkingBar doing={doing} />
    </div>
  );

  return (
    <div className={styles.generating}>
      {to === undefined ? (
        working
      ) : (
        <Link className={styles.previewLink} to={to} onClick={onOpen}>
          {working}
        </Link>
      )}
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
```

In `RenderTile`'s generating branch, pass them through:

```tsx
  if (render.status === "generating") {
    return (
      <>
        <GeneratingTile
          label={`${render.template_id ?? "choosing…"} · ${provenance}`}
          doing={provenance === "manual" ? "rendering…" : "writing brief…"}
          onCancel={drop}
          to={renderPath(render)}
          onOpen={onOpen}
        />
        {failure}
      </>
    );
  }
```

Replace the failed branch with:

```tsx
  if (render.status === "failed") {
    return (
      <div className={styles.failed}>
        <Link className={styles.previewLink} to={renderPath(render)} onClick={onOpen}>
          <span className={styles.failedPreview}>
            <span className={styles.failedWord}>failed</span>
            <span className={styles.failedLine}>
              {`${render.template_id ?? "no template"} · ${provenance}`}
            </span>
          </span>
        </Link>
        <div className={styles.footer}>
          {/* The server's sentence lives in the modal now. A footer line
              either truncates it or stretches the tile, and the modal has
              room to show it whole. */}
          <span className={styles.error}>Render failed</span>
          <button
            type="button"
            className={styles.cross}
            aria-label="Dismiss render"
            onClick={drop}
          >
            ✕
          </button>
        </div>
        {failure}
      </div>
    );
  }
```

Update the component's doc comment where it describes the failed state — it
currently says "with the server's own sentence in the footer", which is no
longer true:

```
 * - **failed** — kept rather than vanishing, per the handoff. The footer
 *   says only `Render failed`; the server's reason is in the modal the
 *   preview opens, which has room for a sentence. Its `✕` dismisses at
 *   once: there is no image to lose.
```

In `web/src/features/topics/RenderTile.module.css`, add:

```css
/* The anchor wrapping a preview, so the link fills the box rather than
   shrink-wrapping the words inside it. */
.previewLink {
  display: block;
}
```

`.failedPreview` is now a `<span>`; check that its rule does not rely on a
block-level default — it sets `display: flex`, so it does not.

- [ ] **Step 5: Run the grid's tests to verify they pass**

Run: `npm --prefix web test -- src/features/topics/RenderGrid.test.tsx`
Expected: PASS, including every pre-existing case. The `deleting…` and
delete-error cases must be untouched.

- [ ] **Step 6: Run lint, typecheck and the whole web suite**

Run: `npm --prefix web run lint` then `npm --prefix web run typecheck` then
`npm --prefix web test`
Expected: all clean. `TopicDetailPage.test.tsx` may now fail on the
modal-delete case — leave it; Task 9 owns it. If it does fail, note the
failure and continue rather than patching it here.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/topics/RenderTile.tsx web/src/features/topics/RenderTile.module.css web/src/features/topics/RenderGrid.test.tsx
git commit -m "$(cat <<'MSG'
Open a failed or generating render from its tile

Both previews become links, so every tile in the grid opens the modal
whatever state its row is in, and the failed footer drops to "Render
failed" now that its reason has room in the modal.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 8: Give the grid the cursor

**Files:**
- Modify: `web/src/features/topics/RenderGrid.tsx`
- Modify: `web/src/features/topics/RenderGrid.module.css`
- Test: `web/src/features/topics/RenderGrid.test.tsx`

**Interfaces:**
- Consumes: `useRenderCursor` (Task 1), `RenderModal`'s `nav` (Task 6).
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing tests**

Add to `web/src/features/topics/RenderGrid.test.tsx`. A stateful harness is
needed for the paging cases the fixed-prop helper cannot reach — the file
already has this pattern in its "shows the open render's current row" test.

```tsx
  it("pages to the next render on the chevron, without closing", async () => {
    const user = userEvent.setup();
    renderGrid([
      makeRenderRecord({ id: "r1", templateId: "drake" }),
      makeRenderRecord({ id: "r2", templateId: "two_buttons" }),
    ]);

    await user.click(screen.getByAltText("drake meme"));
    expect(await screen.findByRole("dialog", { name: "drake" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next render" }));

    // Named by the template, so the dialog's own accessible name is proof
    // it is a different render rather than the same one redrawn.
    expect(screen.getByRole("dialog", { name: "two_buttons" })).toBeInTheDocument();
  });

  it("pages back on the previous chevron", async () => {
    const user = userEvent.setup();
    renderGrid([
      makeRenderRecord({ id: "r1", templateId: "drake" }),
      makeRenderRecord({ id: "r2", templateId: "two_buttons" }),
    ]);

    await user.click(screen.getByAltText("two_buttons meme"));
    await user.click(screen.getByRole("button", { name: "Previous render" }));

    expect(screen.getByRole("dialog", { name: "drake" })).toBeInTheDocument();
  });

  it("pages on the arrow keys", async () => {
    const user = userEvent.setup();
    renderGrid([
      makeRenderRecord({ id: "r1", templateId: "drake" }),
      makeRenderRecord({ id: "r2", templateId: "two_buttons" }),
    ]);

    await user.click(screen.getByAltText("drake meme"));
    await screen.findByRole("dialog", { name: "drake" });

    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("dialog", { name: "two_buttons" })).toBeInTheDocument();

    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("dialog", { name: "drake" })).toBeInTheDocument();
  });

  it("says where in the topic's renders the open one sits", async () => {
    const user = userEvent.setup();
    renderGrid([
      makeRenderRecord({ id: "r1", templateId: "drake" }),
      makeRenderRecord({ id: "g1", status: "generating" }),
      makeRenderRecord({ id: "f1", status: "failed", error: "overflow" }),
    ]);

    await user.click(screen.getByAltText("drake meme"));

    // Three, not one: the counter counts every row the grid drew, which is
    // what the arrows walk. Counting only ready renders would read 1 / 1
    // beside two tiles the arrows can still reach.
    expect(await screen.findByText("1 / 3")).toBeInTheDocument();
  });

  it("counts the placeholders out, because the arrows cannot reach them", async () => {
    // A request in flight has no row and no id. Including it in the count
    // would promise a render the arrows cannot get to.
    const user = userEvent.setup();
    renderGrid(
      [makeRenderRecord({ id: "r1", templateId: "drake" })],
      [{ mode: "llm", template_id: null, count: 2 }],
    );

    await user.click(screen.getByAltText("drake meme"));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByText(/\d+ \/ \d+/)).not.toBeInTheDocument();
  });

  it("offers no paging on a topic with one render", async () => {
    const user = userEvent.setup();
    renderGrid([makeRenderRecord({ id: "r1", templateId: "drake" })]);

    await user.click(screen.getByAltText("drake meme"));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next render" })).not.toBeInTheDocument();
  });

  it("marks the open render in the grid behind the modal", async () => {
    // The grid stays visible through the scrim, so it can say where the
    // arrows are. `aria-current` is the signal; the outline is what paints
    // it.
    const user = userEvent.setup();
    renderGrid([
      makeRenderRecord({ id: "r1", templateId: "drake" }),
      makeRenderRecord({ id: "r2", templateId: "two_buttons" }),
    ]);

    await user.click(screen.getByAltText("drake meme"));
    await screen.findByRole("dialog", { name: "drake" });

    const marked = () =>
      document.querySelectorAll('li[aria-current="true"]');
    expect(marked()).toHaveLength(1);
    expect(marked()[0]).toContainElement(screen.getByAltText("drake meme"));

    await user.click(screen.getByRole("button", { name: "Next render" }));

    expect(marked()).toHaveLength(1);
    expect(marked()[0]).toContainElement(screen.getByAltText("two_buttons meme"));
  });

  it("marks no tile when the modal is closed", () => {
    renderGrid([makeRenderRecord({ id: "r1", templateId: "drake" })]);

    expect(document.querySelectorAll('li[aria-current="true"]')).toHaveLength(0);
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/features/topics/RenderGrid.test.tsx`
Expected: FAIL — no chevrons, no counter, no `aria-current`.

- [ ] **Step 3: Rewrite the grid's state**

In `web/src/features/topics/RenderGrid.tsx`, replace the imports and the
open-state block. The imports become:

```tsx
import type { MouseEvent } from "react";
import { useEffect, useRef } from "react";

import type { GenerationRequest, RenderRecord } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";
import { RenderModal } from "@/features/renders/RenderModal";
import { GeneratingTile, RenderTile } from "@/features/topics/RenderTile";
import { useRenderCursor } from "@/features/topics/useRenderCursor";
import { shortRunId } from "@/format";
```

Replace the `openId`/`open` state and the effect that followed it with:

```tsx
  // Which render the modal is showing, and what happens to it when a row
  // goes: a delete from inside the modal advances to the render that took
  // its place rather than closing. See `useRenderCursor`.
  const cursor = useRenderCursor(renders);
  const wasOpen = useRef(false);

  // Focus needs rescuing in exactly one case: the modal closing because the
  // last render went. `Modal` hands focus back to whatever opened it, but
  // that tile left with the row, and a detached node cannot take focus — so
  // it falls to the document. Every other close has a tile to return to and
  // `Modal` has already used it, which is why this is guarded on the list
  // being empty rather than on the modal merely closing.
  useEffect(() => {
    const open = cursor.record !== null;
    if (wasOpen.current && !open && renders.length === 0) anchor.current?.focus();
    wasOpen.current = open;
  }, [cursor.record, renders.length]);
```

Update the `<li>` and the modal:

```tsx
          {renders.map((render) => (
            <li
              key={render.id}
              // The open render, marked so the grid behind the scrim says
              // where the arrows are. The attribute carries the meaning and
              // the stylesheet paints from it, so there is one source of
              // truth rather than a class nothing asserts.
              aria-current={render.id === cursor.record?.id ? "true" : undefined}
            >
              <RenderTile
                render={render}
                onRemoved={() => anchor.current?.focus()}
                onOpen={(event) => {
                  if (!opensHere(event)) return;
                  event.preventDefault();
                  cursor.open(render.id);
                }}
              />
            </li>
          ))}
```

```tsx
      {cursor.record !== null && (
        <RenderModal
          record={cursor.record}
          onClose={cursor.close}
          // Nothing to page to with a single render, and then the modal
          // draws neither chevrons nor counter — a topic with one meme looks
          // exactly as it did before paging existed.
          nav={
            cursor.count > 1
              ? {
                  onPrev: cursor.prev,
                  onNext: cursor.next,
                  hasPrev: cursor.hasPrev,
                  hasNext: cursor.hasNext,
                  index: cursor.index,
                  count: cursor.count,
                }
              : undefined
          }
        />
      )}
```

Update the component's doc comment: the paragraph about the section label
doubling as a focus anchor is still right, and a sentence should be added
about paging.

```
 * Clicking any tile opens the render over the topic, and the modal pages
 * between them — see `useRenderCursor` for what happens when the row it is
 * showing is deleted from under it.
```

- [ ] **Step 4: Style the marked tile**

In `web/src/features/topics/RenderGrid.module.css`, add after `.grid`:

```css
/* The open render, marked through the modal's scrim so the grid behind is a
   map of where the arrows are. An outline rather than a border: a border
   would resize the tile and reflow the row while the modal sits over it.
   Selected on the attribute the component sets, so the accessible signal
   and the paint cannot drift apart. */
.grid li[aria-current="true"] {
  outline: 1px solid var(--accent);
  outline-offset: 2px;
  border-radius: var(--radius-tile);
}
```

- [ ] **Step 5: Run the grid's tests to verify they pass**

Run: `npm --prefix web test -- src/features/topics/RenderGrid.test.tsx`
Expected: PASS, every case in the file.

- [ ] **Step 6: Run lint, typecheck and the colour gate**

Run: `npm --prefix web run lint` then `npm --prefix web run typecheck` then
`npm --prefix web test -- src/styles/no-raw-colours.test.ts`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/topics/RenderGrid.tsx web/src/features/topics/RenderGrid.module.css web/src/features/topics/RenderGrid.test.tsx
git commit -m "$(cat <<'MSG'
Page between a topic's renders from inside the modal

The grid hands the modal a cursor over its own list, and marks the open
render so the tiles behind the scrim say where the arrows are.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Task 9: Prove it against the real cache

The grid's own harness holds a fixed `renders` prop, so a delete never
actually removes a row there. Only the topic screen can show what this
feature is for, and one existing test on that screen asserts the opposite of
the new behaviour.

**Files:**
- Modify: `web/src/features/topics/TopicDetailPage.test.tsx`

**Interfaces:**
- Consumes: everything above. Produces nothing.

- [ ] **Step 1: Replace the test that asserts the old behaviour**

In `web/src/features/topics/TopicDetailPage.test.tsx`, replace the whole
`"puts focus back on the grid when a render is deleted from its modal"` test
with the two below. The first inherits its handler setup — a mutable
`renders` array that the DELETE handler filters — which is what makes the row
genuinely leave the cache.

```tsx
  it("stays open on the next render when one is deleted from the modal", async () => {
    // What paging is for: clearing three duds out of seven costs one open
    // and three clicks, not three of each. The row genuinely leaves the
    // cache here, which is why this lives on the screen rather than in
    // `RenderGrid.test.tsx` — that harness holds a fixed list, so there the
    // deleted tile never actually goes.
    let renders = [
      makeRenderRecord({ id: "r1", templateId: "drake" }),
      makeRenderRecord({ id: "r2", templateId: "two_buttons" }),
    ];
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json(makeTopicDetail({ renders })),
      ),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
      http.get("/api/config/options", () => HttpResponse.json(makeConfigOptions())),
      http.delete("/api/renders/:renderId", ({ params }) => {
        renders = renders.filter((render) => render.id !== params.renderId);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByAltText("drake meme"));
    const dialog = await screen.findByRole("dialog", { name: "drake" });
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "yes" }));

    // The modal is still up, on the render that took the deleted one's
    // place, and the counter has shrunk with the list.
    expect(await screen.findByRole("dialog", { name: "two_buttons" })).toBeInTheDocument();
    expect(screen.queryByAltText("drake meme")).not.toBeInTheDocument();
    // One render left, so there is nothing to page to any more.
    expect(screen.queryByRole("button", { name: "Next render" })).not.toBeInTheDocument();
  });

  it("closes the modal and lands focus on the grid when the last render goes", async () => {
    // The one case where `Modal` cannot hand focus back: the tile it would
    // return it to has unmounted with the row, and a detached node cannot
    // take focus, so it would fall to the top of the document.
    let renders = [makeRenderRecord({ id: "r1", templateId: "drake" })];
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json(makeTopicDetail({ renders })),
      ),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
      http.get("/api/config/options", () => HttpResponse.json(makeConfigOptions())),
      http.delete("/api/renders/:renderId", ({ params }) => {
        renders = renders.filter((render) => render.id !== params.renderId);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByAltText("drake meme"));
    const dialog = await screen.findByRole("dialog", { name: "drake" });
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "yes" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.queryByAltText("drake meme")).not.toBeInTheDocument();
    const anchor = screen
      .getByText("Rendered from this topic")
      .closest('div[tabindex="-1"]');
    expect(anchor).toHaveFocus();
  });

  it("pages through the topic's renders from the modal", async () => {
    // End to end on the real screen, against the list the API actually
    // returned — including a failed row, which the arrows must be able to
    // land on and leave again.
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json(
          makeTopicDetail({
            renders: [
              makeRenderRecord({ id: "r1", templateId: "drake" }),
              makeRenderRecord({
                id: "f1",
                templateId: "two_buttons",
                status: "failed",
                error: "caption for rejected overflows its box",
              }),
            ],
          }),
        ),
      ),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
      http.get("/api/config/options", () => HttpResponse.json(makeConfigOptions())),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByAltText("drake meme"));
    expect(await screen.findByText("1 / 2")).toBeInTheDocument();

    await user.keyboard("{ArrowRight}");

    const dialog = screen.getByRole("dialog", { name: "two_buttons" });
    expect(
      within(dialog).getByText("caption for rejected overflows its box"),
    ).toBeInTheDocument();
    expect(screen.getByText("2 / 2")).toBeInTheDocument();

    await user.keyboard("{ArrowLeft}");

    expect(screen.getByRole("dialog", { name: "drake" })).toBeInTheDocument();
  });
```

Check the top of the file for the exact names of its mount helper and its
factories (`renderPage`, `makeTopicDetail`, `makeRunDetail`,
`makeConfigOptions`) and use whatever it already imports. Add `waitFor` and
`within` to the `@testing-library/react` import if they are not already
there.

- [ ] **Step 2: Run the screen's tests**

Run: `npm --prefix web test -- src/features/topics/TopicDetailPage.test.tsx`
Expected: PASS, including the pre-existing tile-level delete and focus tests.

- [ ] **Step 3: Run the full Definition of Done**

From the repo root, all seven:

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: all seven pass. The four Python commands are unaffected by this
plan; if `uv run pytest`'s `openapi.json` contract assertion fails, something
outside this plan's scope has changed and should be investigated rather than
worked around.

- [ ] **Step 4: Commit**

```bash
git add web/src/features/topics/TopicDetailPage.test.tsx
git commit -m "$(cat <<'MSG'
Test paging and delete-advance against the real cache

The grid's own harness holds a fixed list, so only the topic screen can
show a deleted row actually leaving and the modal carrying on to the next
render.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## Self-review

**Spec coverage.** Every section of
`2026-09-21-render-paging-design.md` maps to a task: the cycle and its
ordering (Task 1, Task 8), the controls and their labels (Task 5), the ends
(Tasks 1 and 5, plus the arrow-key agreement in Task 6), the single-render
case (Task 8), the three non-ready panels and the empty rationale (Task 4),
both tile consequences (Task 7), the standalone route's free fix (Task 4),
the cursor and its rules (Task 1), the keyed body (Task 6), the chevrons'
home (Task 5), the arrow keys' home (Task 2), the highlight (Task 8), and the
doc-comment rewrites (Tasks 4, 6, 7, 8).

**Two deliberate departures from the spec**, both about where tests live
rather than what ships:

1. The spec names `RenderTile.test.tsx`. No such file exists — this codebase
   tests tiles through `RenderGrid.test.tsx`, and Task 7 follows that.
2. The spec lists the delete-advance assertions under `RenderGrid`. They are
   in Task 9 on `TopicDetailPage` instead, because the grid's own harness
   holds a fixed `renders` prop and a delete cannot remove a row there — the
   existing file says so in a comment, and asserting it in the grid would
   test the harness rather than the behaviour.

**Naming consistency.** `RenderNav` is defined in Task 5 and consumed under
that name in Tasks 6 and 8. `RenderCursor`'s members — `record`, `index`,
`count`, `hasPrev`, `hasNext`, `open`, `close`, `prev`, `next` — are used
with those exact names in Task 8. `WorkingBar`'s single `doing` prop is used
as such in Tasks 3 and 4. `onArrowKey(step: -1 | 1)` is defined in Task 2 and
called with that signature in Task 6.

**Fixed during review.** Three places wrote something wrong and then
explained it rather than correcting it: an unused `settled` ref in the hook
with a later step to delete it again, a first `RenderModal` test that
asserted against the wrong spy with a corrected copy underneath, and a
`RenderDetail` test importing `fireEvent` inline with a note to go and
check what `shortRunId` returns. All three now say the right thing the
first time — `shortRunId` leaves ids of 12 characters or fewer alone, so
the expected line is `Render r1 has no image on disk`.
