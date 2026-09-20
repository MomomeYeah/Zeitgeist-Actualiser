import type { FocusEvent, KeyboardEvent, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import styles from "./InlineConfirm.module.css";

/**
 * A destructive action that asks in place.
 *
 * No modal, per the handoff: the button becomes the question, and the
 * answer is two words beside it. Reverts on `no`, on Escape, and when focus
 * leaves the control entirely — the last one so an abandoned confirm does
 * not sit armed on the screen.
 *
 * Focus moves to `no` when the question appears, which puts the safe answer
 * under the keyboard and under Escape at the same time. It comes back to
 * the trigger when the question goes away by an answer or by Escape: the
 * focused button is unmounted either way, and without this a keyboard user
 * lands at the top of the document. A blur revert leaves focus alone,
 * because it has already gone where someone put it.
 *
 * Two shapes. `"pill"` is Abort's and Resume's: a pill button that becomes
 * a pill-shaped question. `"tile"` is the render tile's footer, per the
 * handoff's 2e: at rest a line of `resting` text and a `✕`; asking, the
 * whole footer becomes the question on contrast at 10%, with `yes` / `no`
 * beside it and no middle dot, because the tile draws none.
 */
export function InlineConfirm({
  label,
  question,
  onConfirm,
  className,
  tone = "contrast",
  disabled = false,
  variant = "pill",
  ariaLabel,
  resting,
}: {
  label: string;
  question: string;
  onConfirm: () => void;
  className?: string;
  /**
   * Disables the trigger, for an action already on its way: Resume, between
   * its 202 and the refetch that replaces it, uses this the way Stop uses
   * its own `disabled`.
   */
  disabled?: boolean;
  /**
   * Which resting look the trigger gets. Defaults to today's contrast
   * look, so Abort and phase 7's delete are unchanged.
   *
   * `"accent"` is for a control that has to read as the design's accent
   * pill at rest — Resume, once it grew this confirm — without gambling on
   * CSS-module class order: `className` alone appends a second single-class
   * selector, and two such selectors from different stylesheets can land in
   * either cascade order depending on import order, which is not something
   * this component controls.
   */
  tone?: "contrast" | "accent";
  /** Which shape — see above. */
  variant?: "pill" | "tile";
  /** The trigger's accessible name, when its visible label is a glyph. */
  ariaLabel?: string;
  /**
   * Tile only: what sits beside the trigger at rest — the tile's
   * `<template> · <provenance>` line — and gives way to the question.
   */
  resting?: ReactNode;
}) {
  const [asking, setAsking] = useState(false);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const cancel = useRef<HTMLButtonElement | null>(null);
  const revertTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refocus = useRef(false);

  useEffect(() => {
    if (asking) {
      cancel.current?.focus();
    } else if (refocus.current) {
      refocus.current = false;
      trigger.current?.focus();
    }
  }, [asking]);

  /** Close the question from inside it, and take focus back to the trigger. */
  function answer() {
    refocus.current = true;
    setAsking(false);
  }

  // The deferred check in `onBlur` below (relatedTarget: null) outlives a
  // single render; clear it on unmount so it cannot call `setAsking` after
  // this component is gone.
  useEffect(() => {
    return () => {
      if (revertTimeout.current) clearTimeout(revertTimeout.current);
    };
  }, []);

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

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Escape") return;
    // An armed confirm is the innermost dismissible thing on the screen, so
    // it consumes the keystroke rather than also dismissing whatever
    // surrounds it — `Modal`'s own Escape handler sits on an ancestor of
    // every confirm drawn inside one.
    //
    // No `preventDefault` beside this: React's `stopPropagation` halts the
    // native event as well, so nothing further up ever runs to inspect the
    // flag, and a call nothing can observe is a call nothing can test.
    event.stopPropagation();
    answer();
  }

  function onBlur(event: FocusEvent<HTMLDivElement>) {
    const container = event.currentTarget;
    const { relatedTarget } = event;

    if (relatedTarget) {
      // The browser told us exactly where focus went — trust it outright.
      // This is the real-world path for tabbing between `yes` and `no`: a
      // genuine Tab keypress blurs and focuses in the same step, so
      // `relatedTarget` correctly names the destination and there is
      // nothing to defer.
      if (!container.contains(relatedTarget)) setAsking(false);
      return;
    }

    // `relatedTarget` is null. That is genuinely ambiguous on its own: it
    // is what real browsers report whenever focus leaves to nowhere
    // trackable — alt-tab, clicking the address bar, switching tabs — the
    // case this revert exists for, so an abandoned confirm does not sit
    // armed on the screen. But it is *also* what this test environment's
    // Tab simulation reports for an ordinary in-control tab: with `no`
    // autofocused as the last tabbable element in an isolated render,
    // user-event's tab algorithm routes the first Tab through
    // `document.body` as an end-of-tab-order sentinel before a second Tab
    // reaches `yes` (see `getTabDestination.js`) — and jsdom reports that
    // hop with a null `relatedTarget` too. Both cases look identical at
    // the moment of this event, so guessing from this event alone is
    // wrong either way. Defer and consult where focus actually settled: a
    // real subsequent focus landing back inside the control (the sentinel
    // hop) is indistinguishable from a genuine loss until we look again.
    // 100ms is imperceptible for a real revert and comfortably outlasts
    // the sentinel hop's second Tab in practice.
    revertTimeout.current = setTimeout(() => {
      revertTimeout.current = null;
      if (!container.contains(document.activeElement)) setAsking(false);
    }, 100);
  }

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
}
