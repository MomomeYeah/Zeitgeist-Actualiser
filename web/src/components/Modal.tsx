import type { KeyboardEvent, ReactNode } from "react";
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import { focusIsLost } from "./focus";
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
 * `showModal()` would also have kept focus inside the dialog once it was
 * there; `recoverFocus` below is that part, and it is the one that has to be
 * written out rather than assumed. Background inerting is the one thing not
 * reproduced — the page behind keeps its `aria-hidden`-less markup, and
 * `aria-modal` is what tells a screen reader to ignore it.
 *
 * It never unmounts itself. `onClose` is a request, and the caller decides
 * whether to honour it, which is what lets a delete that fails leave the
 * modal up with its error showing.
 */
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
  const panel = useRef<HTMLDivElement | null>(null);
  const recovery = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  /**
   * Put focus back on the panel once it has fallen out of the open dialog.
   *
   * Everything this component does about the keyboard — Escape, the Tab
   * trap, the arrow keys — hangs off a handler on the panel, so focus
   * falling out of it disarms all three at once while a container still
   * advertising `aria-modal="true"` sits over the page. The two ways it
   * happens are the caller's ordinary business rather than anything exotic:
   * a control unmounts under the user (the delete inside the render modal
   * takes its own render's body with it) or disables itself (the last press
   * of a next chevron). `focusIsLost`, in `./focus`, is what the two have in
   * common and how they differ — read its comment before this one.
   *
   * Deferred and re-checked rather than acted on at the moment of the loss,
   * which is `InlineConfirm`'s precedent and for its reason: where focus is
   * *going* is ambiguous while it is in flight, where it *landed* is not.
   * `InlineConfirm` deliberately moves focus to its `no` button when armed
   * and back to its trigger when answered, and a recovery that fired
   * mid-move would fight it; a task later the move has finished, the check
   * sees focus on `no`, `focusIsLost` says no, and it does nothing. The one
   * thing the deferral cannot buy is a second look at a disabled control:
   * that reading is the same a task later as it was immediately, which is
   * why the predicate and not the delay is what had to change.
   *
   * It terminates because the panel is a `tabindex="-1"` div that cannot be
   * disabled, so `focusIsLost` is false of it the moment it has focus.
   */
  function recoverFocus() {
    if (recovery.current !== null) clearTimeout(recovery.current);
    recovery.current = setTimeout(() => {
      recovery.current = null;
      const held = panel.current;
      if (held === null || !held.isConnected) return;
      if (!focusIsLost(document.activeElement)) return;
      held.focus();
    });
  }

  // Checked after every commit rather than only on `focusout`, because the
  // removal half announces itself nowhere: it fires no blur event in jsdom
  // and none in Chromium. (Disabling does fire one, but a check hanging off
  // that alone would still have missed the removal.) What the two have in
  // common is happening *during* a DOM update, so every commit is when to
  // look. `onBlur` on the panel covers the rest — a loss with no render
  // behind it, such as a press on the backdrop the caller declines to close
  // on.
  useEffect(() => {
    recoverFocus();
  });

  // As `InlineConfirm` does: the deferred check outlives a single render, so
  // it is cleared on the way out. A modal that has closed must not drag
  // focus back out of wherever the restore above has just put it.
  useEffect(() => {
    return () => {
      if (recovery.current !== null) clearTimeout(recovery.current);
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
        onBlur={recoverFocus}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
