# Render modal implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open a render in a modal over its topic, keep the permanent route for sharing behind a Copy link action, and trim both views to the meme, its template and the model's rationale.

**Architecture:** `RenderDetailPage` splits into a fetching route, a body (`RenderDetail`) that takes a `RenderRecord` it does not fetch, and a modal wrapper (`RenderModal`) built on a new `Modal` primitive. `RenderGrid` holds the open render's id and passes the record it already has, so the modal makes no request. The address bar does not change when the modal opens.

**Tech Stack:** React 19, react-router-dom 7, TanStack Query 5, CSS modules, Vitest + Testing Library + MSW, jsdom.

Design spec: `docs/superpowers/specs/2026-09-20-render-modal-design.md`.

## Global Constraints

- Node tests run from the repo root as `npm --prefix web test`; a single file is `npm --prefix web test -- src/path/File.test.tsx`.
- CSS modules may contain no raw hex or `rgba()`. Every colour is a `var(--token)` defined in `web/src/styles/tokens.css`. Enforced by `web/src/styles/no-raw-colours.test.ts`.
- A CSS module must define every class its component references via `styles.name`. Also enforced by `no-raw-colours.test.ts`.
- Imports use the `@/` alias for `web/src`, and are ordered: external packages, then `@/` imports, then relative — matching every existing file.
- No backend change in this plan. Do not touch `web/openapi.json`, `web/src/api/schema.ts`, or anything under `zeitgeist/`.
- Definition of Done (from `CLAUDE.md`) — all seven must pass before the work is reported finished:
  `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, `uv run pytest`, `npm --prefix web run lint`, `npm --prefix web run typecheck`, `npm --prefix web test`.
- Modals are built on `Modal` (Task 1), not the native `<dialog>`. No Node DOM implements that element — verified across jsdom 25.0.1, 26.1.0 and 30.1.0, happy-dom 20, and `dialog-polyfill` 0.5.6 — so its dismissal could not be tested.
- Commit after every task.

---

### Task 1: `Modal` — the primitive the render modal is built on

A `role="dialog" aria-modal="true"` panel in a portal, owning Escape, focus-on-open, focus restore, a Tab trap and a backdrop click.

**Why not the native `<dialog>`.** It was the first choice and it does not survive contact with the test environment. Measured, not assumed:

- jsdom's `HTMLDialogElement.prototype` carries only `constructor` and `open` — no `showModal`, no `close` — in 25.0.1 (this repo's pin), 26.1.0 and 30.1.0. There is no version to upgrade to.
- happy-dom 20 implements the methods but never closes on Escape.
- `dialog-polyfill` 0.5.6 (the latest) does everything asked of it, but gates its Escape handling on the legacy `event.keyCode === 27`, which `@testing-library/user-event` never sets and jsdom never synthesizes from `key`. Making it work needs either a magic `keyCode: 27` in every Escape test or a global `KeyboardEvent` shim.

Every route to the platform element ends in a test-only hack that moves the suite further from what ships. This owns ~60 lines instead, and the tests drive exactly the code the browser runs.

**Files:**
- Create: `web/src/components/Modal.tsx`
- Create: `web/src/components/Modal.module.css`
- Modify: `web/src/styles/tokens.css` (one token, `--scrim`)
- Test: `web/src/components/Modal.test.tsx`

**Interfaces:**
- Consumes: nothing.
- Produces: `Modal({ label, onClose, children }: { label: string; onClose: () => void; children: ReactNode })`. `label` becomes the dialog's accessible name. `onClose` fires on Escape and on a backdrop click; the component never unmounts itself, so the caller owns whether it is shown. Task 5 wraps `RenderDetail` in it.

Note for Task 5: this deliberately has no close button of its own. What sits inside the panel is the caller's business.

- [ ] **Step 1: Write the failing tests**

Create `web/src/components/Modal.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Modal } from "@/components/Modal";

function open(onClose = vi.fn()) {
  const view = render(
    <Modal label="drake" onClose={onClose}>
      <button type="button">first</button>
      <button type="button">last</button>
    </Modal>,
  );
  return { onClose, user: userEvent.setup(), view };
}

describe("Modal", () => {
  it("names itself, and says it is modal", () => {
    // The accessible name is how a screen reader announces what has just
    // taken over the screen, and `aria-modal` is what tells it the rest of
    // the page is inert. A panel with neither is a div on top of things.
    open();

    const dialog = screen.getByRole("dialog", { name: "drake" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("renders through a portal, outside the tree it was mounted in", () => {
    // The panel has to escape any ancestor with `overflow: hidden` or a
    // stacking context of its own — the topic grid is inside both — or it
    // is clipped behind the page it is supposed to cover.
    const { view } = open();

    expect(view.container).not.toContainElement(screen.getByRole("dialog"));
    expect(document.body).toContainElement(screen.getByRole("dialog"));
  });

  it("takes focus when it opens", () => {
    // Without this the keyboard is still on the page behind, so Escape and
    // the Tab trap — both handlers on the panel — never see a keystroke.
    open();

    expect(screen.getByRole("dialog")).toHaveFocus();
  });

  it("gives focus back to whatever had it when it closes", () => {
    // The tile that opened the modal is where the keyboard was, and where
    // it belongs afterwards — otherwise focus falls to the top of the
    // document and the user tabs back through the whole page.
    function Host({ open: showing }: { open: boolean }) {
      return (
        <>
          <button type="button">opener</button>
          {showing && (
            <Modal label="drake" onClose={vi.fn()}>
              <button type="button">inside</button>
            </Modal>
          )}
        </>
      );
    }
    const { rerender } = render(<Host open={false} />);
    const opener = screen.getByRole("button", { name: "opener" });
    opener.focus();

    rerender(<Host open={true} />);
    expect(screen.getByRole("dialog")).toHaveFocus();

    rerender(<Host open={false} />);

    expect(opener).toHaveFocus();
  });

  it("closes on Escape", async () => {
    const { onClose, user } = open();

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on a click that lands on the backdrop", async () => {
    const { onClose, user } = open();
    const backdrop = screen.getByRole("dialog").parentElement;
    if (backdrop === null) throw new Error("the panel should sit inside a backdrop");

    await user.click(backdrop);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("stays open when the click landed on something inside it", async () => {
    // The pair to the case above, and the one that fails if the handler
    // forgets to compare the target: without that check every click
    // anywhere in the panel closes it.
    const { onClose, user } = open();

    await user.click(screen.getByRole("button", { name: "first" }));

    expect(onClose).not.toHaveBeenCalled();
  });

  it("keeps Tab inside itself, wrapping at the end", async () => {
    // A modal whose Tab escapes puts the keyboard on a page the user
    // cannot see, which is the failure `aria-modal` promises is not
    // happening.
    const { user } = open();

    await user.tab();
    expect(screen.getByRole("button", { name: "first" })).toHaveFocus();

    await user.tab();
    expect(screen.getByRole("button", { name: "last" })).toHaveFocus();

    await user.tab();
    expect(screen.getByRole("button", { name: "first" })).toHaveFocus();
  });

  it("wraps backwards too", async () => {
    const { user } = open();

    await user.tab({ shift: true });

    expect(screen.getByRole("button", { name: "last" })).toHaveFocus();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/components/Modal.test.tsx`
Expected: FAIL — `Failed to resolve import "@/components/Modal"`.

- [ ] **Step 3: Add the backdrop token**

In `web/src/styles/tokens.css`, add to the `:root` block, immediately after the `--mood-rest` line:

```css
  --scrim: rgba(10, 8, 5, 0.72);
```

And add to the file's header comment, in the list of tokens the handoff does not name as rows, after the `--contrast-border-strong` entry:

```
 *   --scrim            rgba(10,8,5,.72) — the wash behind a modal.
 *                      Darker and browner than plain black, so the page
 *                      reads as dimmed rather than covered.
```

- [ ] **Step 4: Write the component**

Create `web/src/components/Modal.tsx`:

```tsx
import type { KeyboardEvent, ReactNode } from "react";
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import styles from "./Modal.module.css";

/**
 * What the Tab trap counts as a stop. Deliberately the plain list rather
 * than anything clever: the panel's contents are this app's own controls,
 * and a selector that tried to be exhaustive would be harder to check than
 * the thing it guards.
 */
const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

/**
 * A panel that takes over the screen until it is dismissed.
 *
 * This is the job `<dialog>` and `showModal()` exist to do, and the native
 * element would be the right answer in a browser. It is not used because
 * no Node DOM implements it — jsdom exposes `HTMLDialogElement` with only
 * `open` on its prototype in every released version, happy-dom never
 * closes on Escape, and `dialog-polyfill` keys its Escape handling on the
 * legacy `keyCode` that `user-event` does not send. Each route ends in a
 * test-only shim, and a modal whose dismissal is untested is the part most
 * worth testing. See the design spec, "Dependency".
 *
 * So the four things the platform would have given are owned here: focus
 * on open and restore on close, Escape, a Tab trap, and a backdrop click.
 * Background inerting is the one thing not reproduced — the page behind
 * keeps its `aria-hidden`-less markup, and `aria-modal` is what tells a
 * screen reader to ignore it.
 *
 * It never unmounts itself. `onClose` is a request, and the caller decides
 * whether to honour it, which is what lets a delete that fails leave the
 * modal up with its error showing.
 */
export function Modal({
  label,
  onClose,
  children,
}: {
  /** The dialog's accessible name. */
  label: string;
  /** Escape, or a click on the backdrop. Never called for a click inside. */
  onClose: () => void;
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const opener = document.activeElement;
    panel.current?.focus();
    return () => {
      // Only if it is still on the page: the control that opened a modal is
      // often a tile the modal's own action has just deleted, and focusing
      // a detached node silently sends focus to the document instead.
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  function trap(event: KeyboardEvent<HTMLDivElement>) {
    const held = panel.current;
    if (held === null) return;
    const stops = Array.from(held.querySelectorAll<HTMLElement>(FOCUSABLE));
    const first = stops.at(0);
    const last = stops.at(-1);
    if (first === undefined || last === undefined) {
      // Nothing to move to, so Tab would leave. The panel itself holds
      // focus in that case.
      event.preventDefault();
      return;
    }
    const active = document.activeElement;
    // The panel counts as "before the first stop": it is what holds focus
    // when the modal opens, so a first Shift+Tab has to wrap to the end
    // rather than escaping upwards.
    if (event.shiftKey && (active === first || active === held)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      onClose();
      return;
    }
    if (event.key === "Tab") trap(event);
  }

  return createPortal(
    <div
      className={styles.scrim}
      onClick={(event) => {
        // Only a click that landed on the backdrop itself — a click inside
        // the panel bubbles up to here with a different target.
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        className={styles.panel}
        onKeyDown={onKeyDown}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
```

Create `web/src/components/Modal.module.css`:

```css
/* Fixed to the viewport and portalled to `document.body`, so no ancestor's
   `overflow` or stacking context can clip it. */
.scrim {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--gap-page);
  background: var(--scrim);
}

.panel {
  position: relative;
  width: min(560px, 100%);
  max-height: 100%;
  overflow-y: auto;
  padding: 14px;
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-card);
  color: var(--text);
  font-family: var(--font-ui);
}

/* The panel takes focus on open, which would otherwise draw the browser's
   focus ring around the whole modal. Its own contents keep theirs. */
.panel:focus {
  outline: none;
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/components/Modal.test.tsx`
Expected: PASS, all nine.

If the Tab-wrapping cases fail, check what `user.tab()` reports as `document.activeElement` before assuming the trap is wrong — jsdom and `user-event` agree about tab order for the plain controls used here, but the panel's own `tabIndex={-1}` means it is focusable without being a tab stop, which is what the `active === held` branch exists for.

- [ ] **Step 6: Run the stylesheet gate**

Run: `npm --prefix web test -- src/styles/no-raw-colours.test.ts`
Expected: PASS. `--scrim` is the only new colour and it lives in `tokens.css`.

- [ ] **Step 7: Lint, type-check and the whole suite**

Run: `npm --prefix web run lint`
Run: `npm --prefix web run typecheck`
Run: `npm --prefix web test`
Expected: PASS all three. `noUncheckedIndexedAccess` is on, which is why the trap reads `stops.at(0)` and checks for `undefined` rather than indexing — there is no `!` and no `as` available to shortcut it.

- [ ] **Step 8: Commit**

```bash
git add web/src/components/Modal.tsx web/src/components/Modal.module.css web/src/components/Modal.test.tsx web/src/styles/tokens.css
git commit -m "Add a modal panel that owns its own focus and dismissal"
```

---

### Task 2: `CopyLinkButton`

A button that puts a render's absolute permanent URL on the clipboard. Self-contained and used by Task 4.

**Files:**
- Create: `web/src/components/CopyLinkButton.tsx`
- Create: `web/src/components/CopyLinkButton.module.css`
- Test: `web/src/components/CopyLinkButton.test.tsx`

**Interfaces:**
- Consumes: nothing.
- Produces: `CopyLinkButton({ path }: { path: string })`. `path` is app-relative (`/runs/x/renders/y`); the button makes it absolute against `window.location.origin`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/components/CopyLinkButton.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CopyLinkButton } from "@/components/CopyLinkButton";

const PATH = "/runs/20260829T090000Z/renders/render-1";

/**
 * jsdom does not define `navigator.clipboard`, and it is read-only where it
 * exists, so it is installed by definition rather than assignment.
 */
function stubClipboard(writeText: ReturnType<typeof vi.fn>) {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("CopyLinkButton", () => {
  it("copies an absolute URL, not the path it was given", async () => {
    // The point of the button is pasting the link somewhere that is not
    // this app, where a leading-slash path addresses nothing. jsdom serves
    // documents from http://localhost:3000.
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    const user = userEvent.setup();
    render(<CopyLinkButton path={PATH} />);

    await user.click(screen.getByRole("button", { name: "Copy link" }));

    expect(writeText).toHaveBeenCalledWith(
      "http://localhost:3000/runs/20260829T090000Z/renders/render-1",
    );
  });

  it("says it copied, and does not say so for ever", async () => {
    // Two breaks, one case: a copy that reports nothing, and a button left
    // reading "Copied" so the next click gives no feedback at all.
    //
    // The clock is advanced well past the revert rather than exactly onto
    // it. How long the word stays is a decision someone is entitled to
    // change; that it goes away is the behaviour, and pinning 2000 here
    // would fail on the former while catching nothing extra of the latter.
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    vi.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<CopyLinkButton path={PATH} />);

    await user.click(screen.getByRole("button", { name: "Copy link" }));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(10_000);

    expect(screen.getByRole("button", { name: "Copy link" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copied" })).not.toBeInTheDocument();
  });

  it("shows the URL to copy by hand when the clipboard refuses", async () => {
    // `writeText` rejects in a non-secure context and when permission is
    // denied. The button must not silently do nothing: the URL becomes
    // selectable text instead.
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    stubClipboard(writeText);
    const user = userEvent.setup();
    render(<CopyLinkButton path={PATH} />);

    await user.click(screen.getByRole("button", { name: "Copy link" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "http://localhost:3000/runs/20260829T090000Z/renders/render-1",
    );
    expect(screen.getByRole("button", { name: "Copy link" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copied" })).not.toBeInTheDocument();
  });

  it("clears the failure once a later copy works", async () => {
    // A denial is about that attempt, not the button. Leaving the alert up
    // after a successful copy would tell the user the link is not on their
    // clipboard when it is.
    const writeText = vi
      .fn()
      .mockRejectedValueOnce(new Error("denied"))
      .mockResolvedValueOnce(undefined);
    stubClipboard(writeText);
    const user = userEvent.setup();
    render(<CopyLinkButton path={PATH} />);

    await user.click(screen.getByRole("button", { name: "Copy link" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Copy link" }));

    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/components/CopyLinkButton.test.tsx`
Expected: FAIL — `Failed to resolve import "@/components/CopyLinkButton"`.

- [ ] **Step 3: Write the component**

Create `web/src/components/CopyLinkButton.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";

import styles from "./CopyLinkButton.module.css";

/**
 * Puts a link on the clipboard, absolute.
 *
 * `path` is app-relative because that is what callers hold — a route, not
 * an address. A relative path pasted into a chat window addresses nothing,
 * so it is resolved against the origin the app is being served from.
 *
 * `writeText` rejects outside a secure context and when permission is
 * refused. That is reported rather than swallowed: the URL is shown as
 * selectable text, which is the thing the user was after anyway.
 */
export function CopyLinkButton({ path }: { path: string }) {
  const [copied, setCopied] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const revert = useRef<ReturnType<typeof setTimeout> | null>(null);

  // The revert outlives a click by two seconds; clear it on unmount so it
  // cannot set state on a component that has gone — the modal closing
  // straight after a copy is the ordinary way that happens.
  useEffect(() => {
    return () => {
      if (revert.current) clearTimeout(revert.current);
    };
  }, []);

  async function copy() {
    const absolute = new URL(path, window.location.origin).href;
    try {
      await navigator.clipboard.writeText(absolute);
      setRefused(null);
      setCopied(true);
      revert.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
      setRefused(absolute);
    }
  }

  return (
    <>
      <button type="button" className={styles.button} onClick={() => void copy()}>
        {copied ? "Copied" : "Copy link"}
      </button>
      {refused !== null && (
        <p role="alert" className={styles.refused}>
          {`The clipboard is not available — ${refused}`}
        </p>
      )}
    </>
  );
}
```

Create `web/src/components/CopyLinkButton.module.css`:

```css
/* The quiet sibling of RenderDetail's accent Download button: same pill
   geometry, an outline instead of a fill, because one surface gets one
   accent action. */
.button {
  display: inline-flex;
  align-items: center;
  padding: 8px 13px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  background: none;
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  transition: border-color var(--transition);
}

.button:hover {
  border-color: var(--border-hover);
}

.refused {
  flex-basis: 100%;
  margin-top: 10px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.5;
  overflow-wrap: anywhere;
  color: var(--contrast-light);
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/components/CopyLinkButton.test.tsx`
Expected: PASS, all four.

- [ ] **Step 5: Run the stylesheet gate**

Run: `npm --prefix web test -- src/styles/no-raw-colours.test.ts`
Expected: PASS. Catches a raw colour or a `styles.x` with no matching rule.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/CopyLinkButton.tsx web/src/components/CopyLinkButton.module.css web/src/components/CopyLinkButton.test.tsx
git commit -m "Add a button that copies a link to the clipboard"
```

---

### Task 3: An armed `InlineConfirm` consumes its Escape

`InlineConfirm` disarms on Escape but lets the keystroke carry on. Inside `Modal`, whose panel handles Escape on an ancestor of the confirm, one press both cancels the confirm and closes the modal. Escape should be claimed innermost-first.

**Files:**
- Modify: `web/src/components/InlineConfirm.tsx` (the `onKeyDown` handler)
- Test: `web/src/components/InlineConfirm.test.tsx` (add one case)

**Interfaces:**
- Consumes: nothing.
- Produces: `InlineConfirm`'s Escape handling now calls `preventDefault()` and `stopPropagation()`. `stopPropagation` is what keeps the keystroke from reaching `Modal`'s handler, so Task 5 relies on it.

- [ ] **Step 1: Write the failing test**

Append inside the existing `describe("InlineConfirm", ...)` block in `web/src/components/InlineConfirm.test.tsx`:

```tsx
  it("consumes the Escape that disarms it rather than letting it travel on", async () => {
    // An armed confirm is the innermost dismissible thing on the screen.
    // Without this, one Escape inside the render modal disarms the confirm
    // *and* closes the modal, losing the view as a side effect of
    // cancelling something else.
    //
    // Both halves matter and are checked separately: `defaultPrevented` is
    // what suppresses a `<dialog>`'s close request, and the outer handler
    // is what an ordinary React ancestor would see.
    const outer = vi.fn();
    let preventedAtDocument: boolean | undefined;
    const watch = (event: KeyboardEvent) => {
      preventedAtDocument = event.defaultPrevented;
    };
    document.addEventListener("keydown", watch);
    try {
      const user = userEvent.setup();
      render(
        <div onKeyDown={outer}>
          <InlineConfirm label="Abort" question="Abort run?" onConfirm={vi.fn()} />
        </div>,
      );

      await user.click(screen.getByRole("button", { name: "Abort" }));
      await user.keyboard("{Escape}");

      expect(screen.getByRole("button", { name: "Abort" })).toBeInTheDocument();
      expect(preventedAtDocument).toBe(true);
      expect(outer).not.toHaveBeenCalled();
    } finally {
      document.removeEventListener("keydown", watch);
    }
  });

  it("leaves an Escape alone when it is not armed", async () => {
    // The pair to the case above: a resting trigger must not swallow a
    // keystroke meant for whatever surrounds it, or Escape would never
    // close the render modal while a tile's confirm sat idle inside it.
    const outer = vi.fn();
    const user = userEvent.setup();
    render(
      <div onKeyDown={outer}>
        <InlineConfirm label="Abort" question="Abort run?" onConfirm={vi.fn()} />
      </div>,
    );

    screen.getByRole("button", { name: "Abort" }).focus();
    await user.keyboard("{Escape}");

    expect(outer).toHaveBeenCalledTimes(1);
  });
```

- [ ] **Step 2: Run the tests to verify the first fails**

Run: `npm --prefix web test -- src/components/InlineConfirm.test.tsx`
Expected: the armed case FAILS — `preventedAtDocument` is `false` and `outer` was called once. The unarmed case already passes.

- [ ] **Step 3: Make the handler claim the key**

In `web/src/components/InlineConfirm.tsx`, replace:

```tsx
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") answer();
  }
```

with:

```tsx
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Escape") return;
    // An armed confirm is the innermost dismissible thing on the screen, so
    // it consumes the keystroke rather than also dismissing whatever
    // surrounds it. `stopPropagation` is what keeps it from reaching
    // `Modal`'s own Escape handler, an ancestor of every confirm drawn
    // inside one; `preventDefault` marks it handled for anything that
    // inspects the event rather than receiving it.
    event.preventDefault();
    event.stopPropagation();
    answer();
  }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/components/InlineConfirm.test.tsx`
Expected: PASS, the whole file — the existing cases cover disarming on Escape, on `no` and on blur, and none of them should move.

- [ ] **Step 5: Run every suite that uses an inline confirm**

Run: `npm --prefix web test`
Expected: PASS. `RunActions`, `RenderTile`, `RenderGrid`, `RunDetailPage` and `RenderDetailPage` all mount one.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/InlineConfirm.tsx web/src/components/InlineConfirm.test.tsx
git commit -m "Let an armed confirm swallow the Escape that disarms it"
```

---

### Task 4: `RenderDetail` — the shared, trimmed body

Pull the body out of `RenderDetailPage` so the modal can draw it, and trim it in the same move: no caption slots, no run id, no generated time, no image dimensions.

**Files:**
- Create: `web/src/features/renders/RenderDetail.tsx`
- Create: `web/src/features/renders/RenderDetail.module.css`
- Modify: `web/src/features/renders/RenderDetailPage.tsx` (rewritten to fetch, head and delegate)
- Modify: `web/src/features/renders/RenderDetailPage.module.css` (dead classes removed)
- Test: `web/src/features/renders/RenderDetailPage.test.tsx` (modified)

**Interfaces:**
- Consumes: `CopyLinkButton({ path })` from Task 2.
- Produces:
  - `templateLabel(record: RenderRecord): string` — the template id or `"no template chosen"`.
  - `renderPath(record: RenderRecord): string` — `/runs/{run}/renders/{id}`, both segments URI-encoded.
  - `RenderDetail({ record, onDeleted }: { record: RenderRecord; onDeleted: () => void })`.
  Tasks 5 and 6 import all three.

- [ ] **Step 1: Rewrite the page's test for the trimmed body**

In `web/src/features/renders/RenderDetailPage.test.tsx`:

**Delete** these three cases outright — they assert the things being removed:
- `"lays out one block per caption slot, with the slot's real name"`
- `"reports the image's real dimensions once it has loaded"`
- `"carries the run id and created time in its metadata line"`

**Change** the `"says no template was chosen…"` case: the import of `fireEvent` stays (other cases use it), but the case no longer reads the metadata line. It is unchanged otherwise — the chip, breadcrumb, alt text and download name all still need a word.

Do **not** add cases asserting that the slot text, the run id, the clock and the dimensions are absent. Nothing but a deliberate decision can put a deleted JSX block back, so such a test fires on a redesign and sleeps through every bug — and the `naturalWidth`/`fireEvent.load` setup one would need is inert once the line it fed is gone. What the trimmed body must positively do is pinned by the cases that survive: the full-size `src`, the chips, the breadcrumb, the rationale branch, Download, Copy link and Delete.

**Add** these cases inside the same `describe`:

```tsx
  it("offers a copy of its own permanent link", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    const user = userEvent.setup();
    serve();

    renderPage();

    await user.click(await screen.findByRole("button", { name: "Copy link" }));

    expect(writeText).toHaveBeenCalledWith(
      `http://localhost:3000/runs/${RUN_ID}/renders/${RENDER_ID}`,
    );
  });

  it("still names the topic it belongs to, for someone who arrived by link", async () => {
    // The one screen built to be deep-linked. The modal drops the heading
    // because the topic is on the screen behind it; here there is nothing
    // behind it.
    serve();

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Airport cat", level: 1 }),
    ).toBeInTheDocument();
  });
```

The `vitest` import at the top of the file gains `vi`:

```tsx
import { describe, expect, it, vi } from "vitest";
```

- [ ] **Step 2: Run the file to verify the new cases fail**

Run: `npm --prefix web test -- src/features/renders/RenderDetailPage.test.tsx`
Expected: FAIL — `"offers a copy of its own permanent link"` finds no such button. `"still names the topic"` already passes; it is here as regression cover for the refactor, since the heading is the one piece of the old page that must survive it.

- [ ] **Step 3: Write `RenderDetail`**

Create `web/src/features/renders/RenderDetail.tsx`:

```tsx
import { useState } from "react";

import { imageUrl } from "@/api/client";
import { useDeleteRender } from "@/api/queries";
import type { RenderRecord } from "@/api/types";
import { Chip } from "@/components/Chip";
import { CopyLinkButton } from "@/components/CopyLinkButton";
import { InlineConfirm } from "@/components/InlineConfirm";
import { SectionLabel } from "@/components/SectionLabel";
import { shortRunId } from "@/format";

import styles from "./RenderDetail.module.css";

/**
 * What to call a render's template.
 *
 * `template_id` is null on a render whose model never chose one — a
 * `generating` row that left the choice open, or a `failed` row whose brief
 * died first. The chip, the alt text, the download's file name and the
 * page's breadcrumb all still need a word, and it has to be the same word
 * in each.
 */
export function templateLabel(record: RenderRecord): string {
  return record.template_id ?? "no template chosen";
}

/** A render's permanent address — the route, and what Copy link copies. */
export function renderPath(record: RenderRecord): string {
  return (
    `/runs/${encodeURIComponent(record.run_id)}` +
    `/renders/${encodeURIComponent(record.id)}`
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
 * dimensions — see the design spec, "What the body shows".
 */
export function RenderDetail({
  record,
  onDeleted,
}: {
  record: RenderRecord;
  /** Called once the row has gone: the page navigates, the modal closes. */
  onDeleted: () => void;
}) {
  const [failed, setFailed] = useState(false);
  const remove = useDeleteRender();
  const template = templateLabel(record);

  return (
    <div className={styles.detail}>
      <div className={styles.chips} data-testid="chips">
        <Chip tone="accent">{template}</Chip>
        <Chip>{record.origin.provenance}</Chip>
      </div>

      <figure className={styles.frame}>
        {failed ? (
          // The database is authoritative for whether a render exists, so a
          // PNG deleted out from under this row is a styled failed state,
          // not a broken-image icon — the same rule `MemeTile` follows for
          // the tiles that open this. The id is shortened because a full
          // 32-character one is noise rather than something to hold onto.
          <span className={styles.failed}>
            {`Render ${shortRunId(record.id)} has no image on disk`}
          </span>
        ) : (
          <img
            className={styles.image}
            src={imageUrl(record.id, "full")}
            alt={`${template} meme`}
            onError={() => setFailed(true)}
          />
        )}
      </figure>

      {record.origin.provenance === "auto" ? (
        <>
          <SectionLabel>Why this template</SectionLabel>
          <p className={styles.rationale}>{record.origin.rationale}</p>
        </>
      ) : (
        <p className={styles.byHand}>written by hand</p>
      )}

      <div className={styles.footer}>
        {!failed && (
          <a
            className={styles.download}
            href={imageUrl(record.id, "full")}
            download={`${template}-${record.id}.png`}
          >
            Download PNG
          </a>
        )}
        <CopyLinkButton path={renderPath(record)} />
        {/* Offered whether or not the image loaded: a render whose PNG is
            gone is the likeliest to want deleting. Pushed away from the two
            safe actions rather than sitting beside them.

            The margin is on a wrapper, not on `InlineConfirm`'s `className`:
            that prop reaches only the resting trigger, so the question that
            replaces it would lose the margin and jump left across the
            footer at the moment of being read. */}
        <div className={styles.delete}>
          <InlineConfirm
            label="Delete"
            question="Delete this render?"
            disabled={remove.isPending}
            onConfirm={() => remove.mutate(record, { onSuccess: onDeleted })}
          />
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

Create `web/src/features/renders/RenderDetail.module.css`:

```css
/* Stacked rather than split. The right-hand column held the slot captions;
   with those gone it would be two chips and a paragraph beside a large
   picture, so both surfaces take the full width and the meme leads. */
.detail {
  display: flex;
  flex-direction: column;
}

.chips {
  display: flex;
  gap: var(--gap-tight);
  margin-bottom: 10px;
}

.frame {
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 0 var(--gap-section);
  padding: 18px;
  background: var(--surface-log);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
}

/* Never upscaled past its natural size: these are 1180px templates, and a
   stretched meme looks broken. */
.image {
  max-width: 100%;
  max-height: 60vh;
  width: auto;
  height: auto;
  object-fit: contain;
}

.failed {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 320px;
  padding: 24px;
  border: 1px dashed var(--contrast-border);
  border-radius: var(--radius-card);
  color: var(--contrast-light);
  font-family: var(--font-mono);
  font-size: 12px;
  text-align: center;
}

.rationale {
  margin: 6px 0 0;
  max-width: 60ch;
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
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-tight);
  margin-top: 16px;
}

/* Destructive, so it sits apart from Download and Copy link rather than
   one click away from them. On the wrapper rather than the control: the
   control swaps itself for a question when armed, and the margin has to
   survive that swap. */
.delete {
  margin-left: auto;
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

.deleteError {
  margin-top: 10px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--contrast-light);
}
```

- [ ] **Step 4: Rewrite the page around it**

Replace the whole of `web/src/features/renders/RenderDetailPage.tsx` with:

```tsx
import { useNavigate, useParams } from "react-router-dom";

import { useRender, useTopicDetail } from "@/api/queries";
import { Breadcrumb } from "@/components/Breadcrumb";
import { QueryBoundary } from "@/components/QueryBoundary";
import { RenderDetail, templateLabel } from "@/features/renders/RenderDetail";

import styles from "./RenderDetailPage.module.css";

/**
 * A render at its permanent address — what Copy link hands out, and the
 * only way in for someone who did not arrive from a tile.
 *
 * It fetches; the modal does not. Arriving here there are two ids and
 * nothing else, so the record and the topic's title both have to be asked
 * for. The body below the heading is the same component the modal draws.
 */
export function RenderDetailPage() {
  const { renderId } = useParams();
  const render = useRender(renderId);
  // The breadcrumb and the heading want the topic's title, which
  // `RenderRecord` does not carry — it carries the ids that address it.
  const topic = useTopicDetail(render.data?.run_id, render.data?.topic_id);
  const navigate = useNavigate();

  return (
    <QueryBoundary query={render} missing="No such render.">
      {(record) => {
        // Used for both the heading and its own breadcrumb entry, so the
        // two can never drift apart.
        const topicLabel = topic.data?.topic.label ?? record.topic_id;

        return (
          <div className={styles.page}>
            <Breadcrumb
              trail={[
                { label: "Topics", to: "/" },
                {
                  label: topicLabel,
                  to: `/topics/${encodeURIComponent(record.run_id)}/${encodeURIComponent(record.topic_id)}`,
                },
                { label: templateLabel(record) },
              ]}
            />

            <header className={styles.header}>
              <h1 className={styles.title}>{topicLabel}</h1>
            </header>

            <RenderDetail
              record={record}
              onDeleted={() =>
                void navigate(
                  `/topics/${encodeURIComponent(record.run_id)}` +
                    `/${encodeURIComponent(record.topic_id)}`,
                )
              }
            />
          </div>
        );
      }}
    </QueryBoundary>
  );
}
```

- [ ] **Step 5: Strip the page's stylesheet to what it still uses**

Replace the whole of `web/src/features/renders/RenderDetailPage.module.css` with:

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
```

Everything else — `.chips`, `.body`, `.frame`, `.image`, `.failed`, `.brief`, `.slots`, `.slot`, `.slotName`, `.caption`, `.rationale`, `.byHand`, `.footer`, `.download`, `.deleteError` — has either moved to `RenderDetail.module.css` or gone with the slots. Nothing fails on a class left defined but unreferenced, so this step is the sweep.

- [ ] **Step 6: Run the page's tests**

Run: `npm --prefix web test -- src/features/renders/RenderDetailPage.test.tsx`
Expected: PASS, the whole file.

- [ ] **Step 7: Run the stylesheet gate and the type checker**

Run: `npm --prefix web test -- src/styles/no-raw-colours.test.ts`
Expected: PASS.

Run: `npm --prefix web run typecheck`
Expected: PASS. Catches a `styles.x` that no longer exists and the now-unused `formatClock` import if it was left behind.

- [ ] **Step 8: Commit**

```bash
git add web/src/features/renders/
git commit -m "Split the render body out of its page, and trim it"
```

---

### Task 5: `RenderModal`

`Modal` around `RenderDetail`, plus the close button `Modal` deliberately does not provide.

**Files:**
- Create: `web/src/features/renders/RenderModal.tsx`
- Create: `web/src/features/renders/RenderModal.module.css`
- Test: `web/src/features/renders/RenderModal.test.tsx`

**Interfaces:**
- Consumes: `Modal` from Task 1; `RenderDetail`, `templateLabel` from Task 4; `InlineConfirm`'s Escape claim from Task 3.
- Produces: `RenderModal({ record, onClose, onDeleted }: { record: RenderRecord; onClose: () => void; onDeleted: () => void })`. Task 6 mounts it.

**What this task does not test.** Escape, the backdrop click, the focus trap and focus restore belong to `Modal` and are covered by `Modal.test.tsx` in Task 1. Re-asserting them here would pin the same behaviour twice. The one exception is the armed-confirm case: that is an interaction *between* `InlineConfirm` and `Modal` that neither component's own tests can see, and it is the subtlest thing on this screen.

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/renders/RenderModal.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { RenderModal } from "@/features/renders/RenderModal";
import { makeRenderRecord } from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

function openModal(
  overrides: Parameters<typeof makeRenderRecord>[0] = {},
  handlers: { onClose?: () => void; onDeleted?: () => void } = {},
) {
  const onClose = handlers.onClose ?? vi.fn();
  const onDeleted = handlers.onDeleted ?? vi.fn();
  renderWithProviders(
    <RenderModal
      record={makeRenderRecord({ id: "r1", templateId: "drake", ...overrides })}
      onClose={onClose}
      onDeleted={onDeleted}
    />,
  );
  return { onClose, onDeleted, user: userEvent.setup() };
}

describe("RenderModal", () => {
  it("names itself by the template it is showing", () => {
    // A dialog needs an accessible name, and the template is what tells one
    // render of a topic from another — the topic itself is named by the
    // screen behind the modal.
    openModal();

    expect(screen.getByRole("dialog", { name: "drake" })).toBeInTheDocument();
  });

  it("draws the render at full size, with its rationale", () => {
    openModal({ rationale: "Two panels, one reversal." });

    expect(screen.getByRole("img", { name: "drake meme" })).toHaveAttribute(
      "src",
      "/api/renders/r1/image?size=full",
    );
    expect(screen.getByText("Two panels, one reversal.")).toBeInTheDocument();
  });

  it("closes on the close button", async () => {
    // `Modal` has no close button of its own; this one is this component's.
    const { onClose, user } = openModal();

    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("is wired to Modal's own dismissal", async () => {
    // One integration assertion, not a re-test of `Modal`: Escape is
    // covered in `Modal.test.tsx`, and what this catches is `RenderModal`
    // failing to pass `onClose` down at all.
    const { onClose, user } = openModal();

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("lets an armed delete confirm have the first Escape, and closes on the second", async () => {
    // The interaction neither component's own tests can see. Escape is
    // claimed innermost-first, so losing the whole view as a side effect of
    // cancelling a confirm is the bug this prevents.
    const { onClose, user } = openModal();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByText("Delete this render?")).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.queryByText("Delete this render?")).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("reports a confirmed delete once it has gone through", async () => {
    let deleted = "";
    server.use(
      http.delete("/api/renders/:renderId", ({ params }) => {
        deleted = String(params.renderId);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { onDeleted, user } = openModal();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "yes" }));

    await vi.waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
    expect(deleted).toBe("r1");
  });

  it("stays open, and says why, when the server will not delete", async () => {
    // The error is only readable while the modal is up, so closing on
    // failure would throw away the one thing the user needs to see.
    server.use(
      http.delete("/api/renders/:renderId", () =>
        HttpResponse.json({ detail: "Permission denied: renders/r1.png" }, { status: 500 }),
      ),
    );
    const { onClose, onDeleted, user } = openModal();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "yes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Permission denied: renders/r1.png",
    );
    expect(onDeleted).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/features/renders/RenderModal.test.tsx`
Expected: FAIL — `Failed to resolve import "@/features/renders/RenderModal"`.

- [ ] **Step 3: Write the component**

Create `web/src/features/renders/RenderModal.tsx`:

```tsx
import type { RenderRecord } from "@/api/types";
import { Modal } from "@/components/Modal";
import { RenderDetail, templateLabel } from "@/features/renders/RenderDetail";

import styles from "./RenderModal.module.css";

/**
 * A render, opened over the topic it came from.
 *
 * Everything about being a modal — Escape, the focus trap, focus restore,
 * the backdrop — belongs to `Modal`. What is added here is the close
 * button, which `Modal` leaves to its caller, and the decision about what
 * a finished delete means.
 *
 * The address bar does not change while this is open. The permanent route
 * is still there and `Copy link` hands it out, but browsing a grid of
 * memes should not write a history entry per glance.
 */
export function RenderModal({
  record,
  onClose,
  onDeleted,
}: {
  record: RenderRecord;
  /** Escape, the backdrop, or the close button. */
  onClose: () => void;
  /**
   * The row has been deleted. Separate from `onClose` because the caller
   * has more to do — the tile this modal was opened from has gone with the
   * row, so focus needs somewhere to land.
   */
  onDeleted: () => void;
}) {
  return (
    <Modal label={templateLabel(record)} onClose={onClose}>
      <button
        type="button"
        className={styles.close}
        aria-label="Close"
        onClick={onClose}
      >
        ✕
      </button>
      <RenderDetail record={record} onDeleted={onDeleted} />
    </Modal>
  );
}
```

Create `web/src/features/renders/RenderModal.module.css`:

```css
/* Sits over the chips row rather than taking a header of its own. `Modal`'s
   panel is the positioned ancestor. */
.close {
  position: absolute;
  top: 14px;
  right: 14px;
  padding: 2px 6px;
  border: none;
  background: none;
  color: var(--text-40);
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  transition: color var(--transition);
}

.close:hover {
  color: var(--text);
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/features/renders/RenderModal.test.tsx`
Expected: PASS, all seven.

If `"lets an armed delete confirm have the first Escape"` fails with `onClose` called on the first press, the cause is Task 3: `InlineConfirm`'s Escape handler must call `stopPropagation()`, or the keystroke reaches `Modal`'s handler on the way up. Check that task landed rather than adding a second mechanism here.

- [ ] **Step 5: Run the stylesheet gate**

Run: `npm --prefix web test -- src/styles/no-raw-colours.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/renders/RenderModal.tsx web/src/features/renders/RenderModal.module.css web/src/features/renders/RenderModal.test.tsx
git commit -m "Add a modal that shows one render over its topic"
```

---

### Task 6: Open the modal from the topic's grid

The last wiring: a tile click opens the modal instead of navigating, while the tile stays a real link.

**Files:**
- Modify: `web/src/components/MemeTile.tsx` (new `onActivate` prop)
- Modify: `web/src/features/topics/RenderTile.tsx` (new `onOpen` prop, passed through)
- Modify: `web/src/features/topics/RenderGrid.tsx` (open state, the modal, the modified-click rule)
- Test: `web/src/features/topics/RenderGrid.test.tsx` (add cases; `MemeTile.test.tsx` is deliberately untouched — see Step 1)

**Interfaces:**
- Consumes: `RenderModal` from Task 5; `renderPath` from Task 4.
- Produces: nothing later tasks depend on. This is the last component task.

- [ ] **Step 1: Write the failing tests**

`MemeTile.test.tsx` gets nothing. `onActivate` is handed straight to `Link`'s `onClick` with no validation, defaulting or side effect of its own — every decision lives in `RenderGrid.opensHere` — so an isolated case would assert only that React passes a prop. The first consumer-visible result of that forwarding is the modal opening, and `"opens a render in a modal rather than navigating away"` below exercises it through the real `MemeTile` → `RenderTile` → `RenderGrid` chain, covering both hops.

Add to `web/src/features/topics/RenderGrid.test.tsx`, inside the existing `describe`:

```tsx
  it("opens a render in a modal rather than navigating away", async () => {
    const user = userEvent.setup();
    renderGrid([makeRenderRecord({ id: "r1", templateId: "drake" })]);

    await user.click(screen.getByAltText("drake meme"));

    expect(await screen.findByRole("dialog", { name: "drake" })).toBeInTheDocument();
  });

  it("leaves the address bar on the topic while the modal is open", async () => {
    // The modal is component state, not a route: browsing a grid of memes
    // should not write a history entry per glance, and Copy link is what
    // hands out the permanent URL.
    //
    // The break this catches is not only that decision being reversed. The
    // tile is a real `<Link>`, so an `onOpen` that opens the modal without
    // cancelling the event leaves the router navigating underneath it —
    // the modal appears over a screen that is already unmounting. Dropping
    // `event.preventDefault()` fails here and nowhere else.
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <RenderGrid
          renders={[makeRenderRecord({ id: "r1", templateId: "drake" })]}
          runId={RUN_ID}
          pending={[]}
        />
        <Where />
      </>,
      { route: "/topics/20260829T090000Z/topic-1" },
    );

    await user.click(screen.getByAltText("drake meme"));

    expect(await screen.findByRole("dialog", { name: "drake" })).toBeInTheDocument();
    expect(
      screen.getByText("at /topics/20260829T090000Z/topic-1"),
    ).toBeInTheDocument();
  });

  it("opens the record the grid already holds, without asking the server for it", async () => {
    // The design turns on this: the topic screen is already holding every
    // field the body needs, so a click opens on the current frame with no
    // spinner and no second request. A `RenderDetail` that fetched by id
    // would satisfy every other case in this file, because they all await.
    const asked: string[] = [];
    const watch = ({ request }: { request: Request }) => {
      asked.push(request.url);
    };
    server.events.on("request:start", watch);
    try {
      const user = userEvent.setup();
      renderGrid([makeRenderRecord({ id: "r1", templateId: "drake" })]);

      await user.click(screen.getByAltText("drake meme"));

      expect(screen.getByRole("dialog", { name: "drake" })).toBeInTheDocument();
      expect(asked).toEqual([]);
    } finally {
      server.events.removeListener("request:start", watch);
    }
  });

  it("shows the open render's current row, not the copy that was on screen at click time", async () => {
    // The grid holds the open render's id rather than the record, because
    // the row behind it changes — a refetch landing, a generating render
    // turning ready — and a copy taken at click time would leave the modal
    // on a frame the grid itself has already moved past.
    let refresh: (rationale: string) => void = () => undefined;
    function Harness() {
      const [rationale, setRationale] = useState("Two panels, one reversal.");
      refresh = setRationale;
      return (
        <RenderGrid
          renders={[makeRenderRecord({ id: "r1", templateId: "drake", rationale })]}
          runId={RUN_ID}
          pending={[]}
        />
      );
    }
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByAltText("drake meme"));
    expect(await screen.findByText("Two panels, one reversal.")).toBeInTheDocument();

    act(() => refresh("Chose the reversal after all."));

    expect(screen.getByText("Chose the reversal after all.")).toBeInTheDocument();
    expect(screen.queryByText("Two panels, one reversal.")).not.toBeInTheDocument();
  });

  it.each([
    { modifier: "⌘", init: { metaKey: true } },
    { modifier: "ctrl", init: { ctrlKey: true } },
    { modifier: "shift", init: { shiftKey: true } },
    { modifier: "alt", init: { altKey: true } },
  ])("leaves a $modifier-click to the browser rather than opening the modal", ({ init }) => {
    // ⌘, ctrl and shift on a link mean "somewhere else" and alt means
    // download. Cancelling the event is *how* those get swallowed, so that
    // is asserted alongside the absent modal: a handler that called
    // preventDefault before consulting the modifiers would open no modal
    // either, and would still have made the tile's href a promise it does
    // not keep. All four are exercised because dropping any one of them
    // from `opensHere` must fail something.
    renderGrid([makeRenderRecord({ id: "r1", templateId: "drake" })]);
    const tile = screen.getByAltText("drake meme");

    const click = createEvent.click(tile, {
      bubbles: true,
      cancelable: true,
      button: 0,
      ...init,
    });
    fireEvent(tile, click);

    expect(click.defaultPrevented).toBe(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes the modal without touching the grid behind it", async () => {
    const user = userEvent.setup();
    renderGrid([
      makeRenderRecord({ id: "r1", templateId: "drake" }),
      makeRenderRecord({ id: "r2", templateId: "two_buttons" }),
    ]);

    await user.click(screen.getByAltText("drake meme"));
    expect(await screen.findByRole("dialog", { name: "drake" })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByAltText("drake meme")).toBeInTheDocument();
    expect(screen.getByAltText("two_buttons meme")).toBeInTheDocument();
  });

  it("deleting from the modal closes it and takes the tile with it", async () => {
    const deleted = recordDeletes();
    const user = userEvent.setup();
    renderGrid([
      makeRenderRecord({ id: "r1", templateId: "drake" }),
      makeRenderRecord({ id: "r2", templateId: "two_buttons" }),
    ]);

    await user.click(screen.getByAltText("drake meme"));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }),
    );
    await user.click(screen.getByRole("button", { name: "yes" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(deleted).toEqual(["r1"]);
    expect(screen.getByAltText("two_buttons meme")).toBeInTheDocument();
    // `Modal` restores focus to whatever had it, but that tile went with
    // the row and a detached node cannot take focus. It lands where a
    // tile-level delete already sends it instead of at the top of the
    // document.
    expect(
      screen.getByText("Rendered from this topic").closest('div[tabindex="-1"]'),
    ).toHaveFocus();
  });
```

There is deliberately no new case asserting the tile's `href`. The file's first case, `"draws a ready render as its image, linked to the full-size view"`, already makes exactly that assertion on the same fixture, so swapping the local `to` construction for `renderPath(render)` in Step 4 is covered before this task adds a line.

The imports at the top of this file grow:

```tsx
import { act, createEvent, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { useLocation } from "react-router-dom";
```

and beside the existing `recordDeletes` helper:

```tsx
/** Where the router is, for the test that asserts the modal did not move it. */
function Where() {
  const { pathname } = useLocation();
  return <p>{`at ${pathname}`}</p>;
}
```

Note on the delete case: `renderGrid` mounts `RenderGrid` with a fixed `renders` prop, so the tile does not disappear from this harness — the cache write that removes it belongs to `TopicDetailPage`, which has its own test for exactly that. What is asserted here is what this component owns: the DELETE went out for the right id, the modal closed, and the other tile is untouched.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/features/topics/RenderGrid.test.tsx`
Expected: FAIL. Every new case that opens the modal finds no dialog, because nothing yet turns a click into one. The `it.each` modified-click cases pass already — they are there to stay green while Steps 3–5 land, and to fail if `opensHere` is ever written too broadly.

- [ ] **Step 3: Give `MemeTile` the hook**

In `web/src/components/MemeTile.tsx`, add the import:

```tsx
import type { MouseEvent } from "react";
```

Add the prop to the signature, after `templateId`:

```tsx
  onActivate,
}: {
  renderId: string;
  size: 34 | "grid";
  to?: string;
  templateId?: string;
  /**
   * First refusal on a click of the tile's link. The tile stays an anchor
   * either way — the topic grid opens a modal on an ordinary click but
   * leaves the href for hover and for a modified click — so this decides
   * nothing itself and only hands the event on.
   */
  onActivate?: (event: MouseEvent<HTMLAnchorElement>) => void;
}) {
```

And pass it to the `Link`:

```tsx
      {to === undefined ? image : <Link to={to} onClick={onActivate}>{image}</Link>}
```

- [ ] **Step 4: Pass it through `RenderTile`**

In `web/src/features/topics/RenderTile.tsx`, add the import:

```tsx
import type { MouseEvent } from "react";
```

Add the prop to `RenderTile`'s signature, after `onRemoved`:

```tsx
  onOpen,
}: {
  render: RenderRecord;
  onRemoved?: () => void;
  /** First refusal on a click of a ready tile's image — see `MemeTile`. */
  onOpen?: (event: MouseEvent<HTMLAnchorElement>) => void;
}) {
```

Replace the local `to` construction with the shared one. Delete these lines:

```tsx
  const to =
    `/runs/${encodeURIComponent(render.run_id)}` +
    `/renders/${encodeURIComponent(render.id)}`;
```

Add to the imports:

```tsx
import { renderPath } from "@/features/renders/RenderDetail";
```

And in the returned `MemeTile`:

```tsx
      <MemeTile
        renderId={render.id}
        size="grid"
        to={renderPath(render)}
        templateId={render.template_id ?? undefined}
        onActivate={onOpen}
      />
```

- [ ] **Step 5: Hold the open render in the grid**

In `web/src/features/topics/RenderGrid.tsx`, change the React import and add the others:

```tsx
import type { MouseEvent } from "react";
import { useRef, useState } from "react";

import type { GenerationRequest, RenderRecord } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";
import { RenderModal } from "@/features/renders/RenderModal";
import { GeneratingTile, RenderTile } from "@/features/topics/RenderTile";
import { shortRunId } from "@/format";
```

Add above the `RenderGrid` function:

```tsx
/**
 * Whether a click meant "here" rather than "somewhere else".
 *
 * ⌘, ctrl and shift on a link mean a new tab or window, and alt means
 * download; those belong to the browser, and swallowing them would make the
 * tile's href a promise it does not keep. `button` is belt and braces — a
 * middle click fires `auxclick` rather than `click` in current browsers.
 */
function opensHere(event: MouseEvent): boolean {
  return (
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey &&
    event.button === 0
  );
}
```

Inside `RenderGrid`, after the existing `anchor` ref:

```tsx
  // The id rather than the record: the row behind it can change — a
  // generating render turning ready — and a copy taken at click time would
  // show a frame that has already moved on.
  const [openId, setOpenId] = useState<string | null>(null);
  const open = renders.find((render) => render.id === openId) ?? null;
```

Give the tile its handler:

```tsx
            <RenderTile
              render={render}
              onRemoved={() => anchor.current?.focus()}
              onOpen={(event) => {
                if (!opensHere(event)) return;
                event.preventDefault();
                setOpenId(render.id);
              }}
            />
```

And mount the modal at the end of the `<section>`, after the ternary that draws the grid or the empty line:

```tsx
      {open !== null && (
        <RenderModal
          record={open}
          onClose={() => setOpenId(null)}
          // The tile the dialog would hand focus back to has unmounted with
          // the row, so focus goes where a tile-level delete already sends
          // it: the section label, a tab away from the tiles that remain.
          onDeleted={() => anchor.current?.focus()}
        />
      )}
```

- [ ] **Step 6: Run the grid's and the tile's test files**

Run: `npm --prefix web test -- src/components/MemeTile.test.tsx src/features/topics/RenderGrid.test.tsx`
Expected: PASS. `MemeTile.test.tsx` is unchanged by this task and is run to prove the new prop broke none of it.

- [ ] **Step 7: Run the topic screen's own tests**

Run: `npm --prefix web test -- src/features/topics/TopicDetailPage.test.tsx`
Expected: PASS, unchanged. Its existing case asserts the tile's `href`, which still holds; nothing there clicks a tile.

- [ ] **Step 8: Commit**

```bash
git add web/src/components/MemeTile.tsx web/src/features/topics/RenderTile.tsx web/src/features/topics/RenderGrid.tsx web/src/features/topics/RenderGrid.test.tsx
git commit -m "Open a render in a modal from its topic"
```

---

### Task 7: The full gate

**Files:** none changed unless something below fails.

**Interfaces:**
- Consumes: everything above.
- Produces: a branch that satisfies the Definition of Done.

- [ ] **Step 1: Lint and type-check the web half**

Run: `npm --prefix web run lint`
Expected: PASS.

Run: `npm --prefix web run typecheck`
Expected: PASS. This also regenerates `web/src/api/schema.ts` from `web/openapi.json` and fails if the checked-in file differs — it should not, since no backend change was made.

- [ ] **Step 2: Run the whole web suite**

Run: `npm --prefix web test`
Expected: PASS.

- [ ] **Step 3: Run the Python half**

Run these four; none should be affected by this branch, and a failure means something outside the plan is wrong:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

Expected: PASS.

- [ ] **Step 4: Look at it in a browser**

Development is two processes, in two terminals (see `README.md`, "Development"):

```bash
uv run zeitgeist
```

```bash
npm --prefix web run dev
```

Open the URL Vite prints, go to any topic with a rendered meme, and check the four things tests cannot see:

1. The modal is centred and the backdrop dims the topic behind it rather than covering it.
2. The meme is not upscaled past its natural size, and a narrow window does not give the page a horizontal scrollbar.
3. **Copy link** says `Copied` and puts a working absolute URL on a real clipboard — paste it into the address bar and confirm it loads the standalone page.
4. ⌘-click (or ctrl-click) a tile and confirm it opens the permanent URL in a new tab instead of the modal.

- [ ] **Step 5: Commit anything the gate changed**

```bash
git status
```

If lint or formatting rewrote anything, commit it:

```bash
git add -A
git commit -m "Satisfy the gate"
```
