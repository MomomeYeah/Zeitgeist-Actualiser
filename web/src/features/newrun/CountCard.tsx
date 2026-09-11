import { useState } from "react";

import { SectionLabel } from "@/components/SectionLabel";

import styles from "./CountCard.module.css";

const PRESETS = [1, 3, 5, 10];

/** What the custom box shows for a committed count: nothing, for a preset. */
function draftFor(count: number): string {
  return PRESETS.includes(count) ? "" : String(count);
}

/** A count the pipeline can brief: a whole number, at least one. */
function parseCount(draft: string): number | undefined {
  const next = Number(draft);
  return Number.isInteger(next) && next >= 1 ? next : undefined;
}

/**
 * The one card with an accent border, because it is the setting that
 * changes the output.
 *
 * `custom` is a number input rather than a fifth pill: the presets cover
 * what anyone picks in practice, and the input is there for the time they
 * do not.
 *
 * The box keeps its own string draft, the way `SettingRow` does, rather
 * than rendering the committed count. It used to render `count` only while
 * that matched no preset, so typing "12" committed 1 on the first key,
 * lit the 1 pill, emptied the box under the cursor, and left the "2" to
 * land alone — the form posted 2. Any custom value whose leading digits
 * form a preset did the same. A string draft also lets the box be empty
 * mid-retype without `Number("")` reading as 0.
 *
 * The draft reaches the form only when it parses as a whole number of at
 * least one; anything else leaves the last good count in place. Leaving
 * the box puts back the draft for that count, so a "2.5" left in it is not
 * what the box still says when Start run sends 2 — and the input's own
 * step check never gets a fraction to refuse the submit over.
 *
 * While the draft holds anything, the box is the answer and no pill is
 * lit, even when the draft happens to equal a preset: the box is what
 * someone is typing in, and a pill lighting up under it mid-number reads
 * as the card changing its mind.
 */
export function CountCard({
  count,
  trendLimit,
  onCount,
}: {
  count: number;
  trendLimit: string;
  onCount: (count: number) => void;
}) {
  const [draft, setDraft] = useState(() => draftFor(count));
  const custom = draft !== "" || !PRESETS.includes(count);

  return (
    <section className={styles.card}>
      <SectionLabel hint="topic_count · default 5">Memes to generate</SectionLabel>
      <p className={styles.explain}>
        How many of the ranked topics get briefed and rendered.
      </p>

      <div className={styles.pills}>
        {PRESETS.map((preset) => {
          const on = !custom && count === preset;
          return (
            <button
              key={preset}
              type="button"
              aria-pressed={on}
              className={on ? styles.pillOn : styles.pill}
              onClick={() => {
                setDraft("");
                onCount(preset);
              }}
            >
              {preset}
            </button>
          );
        })}
        <label className={custom ? styles.customOn : styles.custom}>
          custom
          <input
            type="number"
            min={1}
            aria-label="custom count"
            className={styles.input}
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value);
              const next = parseCount(event.target.value);
              if (next !== undefined) onCount(next);
            }}
            onBlur={() => {
              if (parseCount(draft) === undefined) setDraft(draftFor(count));
            }}
          />
        </label>
      </div>

      <p className={styles.note}>of {trendLimit} trends analysed</p>
    </section>
  );
}
