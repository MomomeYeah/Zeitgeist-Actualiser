import { moodLine, moodSegments } from "@/features/topics/ordering";

import styles from "./MoodBar.module.css";

/** A 28px segmented bar, one segment per sentiment, sized by share. */
export function MoodBar({
  totals,
  previous,
}: {
  totals: Record<string, number>;
  previous: Record<string, number>;
}) {
  const segments = moodSegments(totals);
  if (segments.length === 0) return null;

  return (
    <section data-testid="mood">
      <div className={styles.bar}>
        {segments.map((segment) => (
          <span
            key={segment.sentiment}
            className={`${styles.segment} ${styles[segment.tone]}`}
            style={{ "--share": `${segment.share * 100}%` }}
          >
            {segment.sentiment} {segment.count}
          </span>
        ))}
      </div>
      <p className={styles.line}>{moodLine(totals, previous)}</p>
    </section>
  );
}
