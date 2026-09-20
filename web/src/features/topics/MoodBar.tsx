import { foldNarrowSegments, moodLine, moodSegments } from "@/features/topics/ordering";

import styles from "./MoodBar.module.css";

/** A 28px segmented bar, one segment per sentiment, sized by share. */
export function MoodBar({
  totals,
  previous,
}: {
  totals: Record<string, number>;
  previous: Record<string, number>;
}) {
  // The line describes the whole window; the bar draws only what it can
  // label, which is why each reads a different list.
  const segments = foldNarrowSegments(moodSegments(totals));
  if (segments.length === 0) return null;

  return (
    <section data-testid="mood">
      <div className={styles.bar}>
        {segments.map((segment) => (
          <span
            key={segment.key}
            className={`${styles.segment} ${styles[segment.tone]}`}
            style={{ "--share": `${segment.share * 100}%` }}
            title={segment.title}
          >
            {segment.label}
          </span>
        ))}
      </div>
      <p className={styles.line}>{moodLine(totals, previous)}</p>
    </section>
  );
}
