import type { FocusEvent, KeyboardEvent } from "react";
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
 * under the keyboard and under Escape at the same time.
 */
export function InlineConfirm({
  label,
  question,
  onConfirm,
  className,
}: {
  label: string;
  question: string;
  onConfirm: () => void;
  className?: string;
}) {
  const [asking, setAsking] = useState(false);
  const cancel = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (asking) cancel.current?.focus();
  }, [asking]);

  if (!asking) {
    return (
      <button
        type="button"
        className={[styles.trigger, className].filter(Boolean).join(" ")}
        onClick={() => setAsking(true)}
      >
        {label}
      </button>
    );
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") setAsking(false);
  }

  function onBlur(event: FocusEvent<HTMLDivElement>) {
    // Focus moving from `yes` to `no` is still inside the control, and must
    // not close it — otherwise the keyboard path through this is unusable.
    if (!event.relatedTarget || event.currentTarget.contains(event.relatedTarget)) return;
    setAsking(false);
  }

  return (
    <div className={styles.asking} onKeyDown={onKeyDown} onBlur={onBlur}>
      <span className={styles.question}>{question}</span>
      <button
        type="button"
        className={styles.answer}
        onClick={() => {
          setAsking(false);
          onConfirm();
        }}
      >
        yes
      </button>
      <span className={styles.dot}>·</span>
      <button
        ref={cancel}
        type="button"
        className={styles.answer}
        onClick={() => setAsking(false)}
      >
        no
      </button>
    </div>
  );
}
