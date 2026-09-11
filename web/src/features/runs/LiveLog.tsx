import { useEffect, useLayoutEffect, useRef, useState } from "react";

import type { LogLine } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";

import styles from "./LiveLog.module.css";

/**
 * Within this many pixels of the bottom still counts as following.
 *
 * A threshold, never an equality test: the log is 11px mono at line-height
 * 1.9, so lines are 20.9px and exact equality effectively never holds.
 */
const FOLLOW_THRESHOLD_PX = 24;

/** Lines at the end that stay at full-ish opacity, so the eye lands late. */
const RECENT = 20;

/**
 * The run's log, live or post-mortem.
 *
 * Follow behaviour is the one piece of mechanics here worth reading
 * carefully. `following` lives in a ref and is mirrored into state only
 * when it flips, so the header can render an indicator without the
 * component re-rendering on every scroll event. The listener is attached
 * imperatively and passive, which is what makes the ref necessary rather
 * than merely tidy: a listener registered once in a mount-only effect
 * captures its render's variables permanently, so reading state inside it
 * would compare against the first render's value forever.
 *
 * New lines pin to the bottom from a `useLayoutEffect`, which runs before
 * paint, so the jump never renders as a flicker.
 *
 * `verbose` is a filter over lines already held, not a request for
 * different ones — which is what makes flipping it work retroactively, and
 * is what anyone toggling it mid-run wants. The stream sends everything
 * regardless (`control.py` applies no filter of its own).
 *
 * `loading` and `failure` are a finished run's log query's own states,
 * shown in place of the lines. Without them an empty `lines` could only
 * read "This run logged nothing." — which is false while the log is still
 * on its way, and false for good when it could not be read. They are
 * props rather than a `QueryBoundary` around this component so the
 * section and its verbose toggle stay put while a toggled log reloads.
 */
export function LiveLog({
  lines,
  live,
  verbose,
  onVerboseChange,
  loading = false,
  failure,
}: {
  lines: LogLine[];
  live: boolean;
  verbose: boolean;
  onVerboseChange: (verbose: boolean) => void;
  loading?: boolean;
  /** The server's own sentence for why the log could not be read. */
  failure?: string;
}) {
  const scroller = useRef<HTMLDivElement | null>(null);
  const following = useRef(true);
  const [released, setReleased] = useState(false);

  const shown = verbose ? lines : lines.filter((line) => line.level !== "DEBUG");

  useEffect(() => {
    const node = scroller.current;
    if (node === null) return;

    const onScroll = () => {
      const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
      const next = distance <= FOLLOW_THRESHOLD_PX;
      if (next === following.current) return;
      following.current = next;
      setReleased(!next);
    };

    node.addEventListener("scroll", onScroll, { passive: true });
    return () => node.removeEventListener("scroll", onScroll);
  }, []);

  useLayoutEffect(() => {
    const node = scroller.current;
    if (node === null || !following.current) return;
    node.scrollTop = node.scrollHeight;
  }, [shown.length]);

  function jump() {
    const node = scroller.current;
    if (node === null) return;
    node.scrollTop = node.scrollHeight;
    following.current = true;
    setReleased(false);
  }

  return (
    <section className={styles.section}>
      <SectionLabel
        hint={
          <span className={styles.controls}>
            {live &&
              (released ? (
                // The handoff draws the indicator but no way back. This is
                // the way back: the same dot, made a button.
                <button type="button" className={styles.jump} onClick={jump}>
                  <span className={styles.dot} />
                  jump to latest
                </button>
              ) : (
                <span className={styles.following}>
                  <span className={styles.dot} />
                  following
                </span>
              ))}
            <button
              type="button"
              className={verbose ? styles.toggleOn : styles.toggle}
              aria-pressed={verbose}
              onClick={() => onVerboseChange(!verbose)}
            >
              verbose
            </button>
          </span>
        }
      >
        {live ? "Live log" : "Log"}
      </SectionLabel>

      <div className={styles.block} data-testid="log-scroller" ref={scroller}>
        {failure !== undefined ? (
          <p className={styles.failure}>{failure}</p>
        ) : loading ? (
          <p className={styles.empty}>Loading the log…</p>
        ) : shown.length === 0 ? (
          <p className={styles.empty}>
            {live ? "Waiting for the first line…" : "This run logged nothing."}
          </p>
        ) : (
          shown.map((line, index) => (
            <p
              key={line.seq}
              className={[styles.line, toneOf(line, index, shown.length, live)]
                .filter(Boolean)
                .join(" ")}
            >
              <span className={styles.logger}>{line.logger}</span>
              <span className={styles.message}>{line.message}</span>
            </p>
          ))
        )}
      </div>
    </section>
  );
}

/**
 * Older lines fade so the eye lands on recent ones, and the line being
 * worked on right now is fully accent.
 *
 * A warning or an error outranks both: it is the reason to read the log at
 * all, and dimming one because it scrolled up would hide the thing someone
 * opened this to find.
 *
 * No explicit return type: under `noUncheckedIndexedAccess`, a CSS module's
 * properties type as `string | undefined`, same as `PhraseCard`'s
 * `sizeClass`.
 */
function toneOf(line: LogLine, index: number, count: number, live: boolean) {
  if (line.level === "WARNING" || line.level === "ERROR" || line.level === "CRITICAL") {
    return styles.warn;
  }
  if (live && index === count - 1) return styles.current;
  return index < count - RECENT ? styles.dim : styles.mid;
}
