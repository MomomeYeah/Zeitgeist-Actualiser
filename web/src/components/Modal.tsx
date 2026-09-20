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
