import { SectionLabel } from "@/components/SectionLabel";

import styles from "./CountCard.module.css";

const PRESETS = [1, 3, 5, 10];

/**
 * The one card with an accent border, because it is the setting that
 * changes the output.
 *
 * `custom` is a number input rather than a fifth pill: the presets cover
 * what anyone picks in practice, and the input is there for the time they
 * do not.
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
  const custom = !PRESETS.includes(count);

  return (
    <section className={styles.card}>
      <SectionLabel hint="topic_count · default 5">Memes to generate</SectionLabel>
      <p className={styles.explain}>
        How many of the ranked topics get briefed and rendered.
      </p>

      <div className={styles.pills}>
        {PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            aria-pressed={count === preset}
            className={count === preset ? styles.pillOn : styles.pill}
            onClick={() => onCount(preset)}
          >
            {preset}
          </button>
        ))}
        <label className={custom ? styles.customOn : styles.custom}>
          custom
          <input
            type="number"
            min={1}
            aria-label="custom count"
            className={styles.input}
            value={custom ? count : ""}
            onChange={(event) => {
              const next = Number(event.target.value);
              if (Number.isFinite(next) && next > 0) onCount(next);
            }}
          />
        </label>
      </div>

      <p className={styles.note}>of {trendLimit} trends analysed</p>
    </section>
  );
}
