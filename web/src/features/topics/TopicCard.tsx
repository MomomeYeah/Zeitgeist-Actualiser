import { Link } from "react-router-dom";

import type { IndexedTopic } from "@/api/types";
import { Chip } from "@/components/Chip";
import { formatScore } from "@/format";

import styles from "./TopicCard.module.css";

/**
 * `▲ SEEN IN 3 RUNS` or `NEW THIS RUN`.
 *
 * A floor rather than a count: the slug fixes case and punctuation drift
 * across runs but not wording drift, so a relabelled topic reads as new.
 * "Seen in" is the honest verb for that; "appeared in exactly 3 runs" is not.
 */
function recurrence(runCount: number): string {
  return runCount > 1 ? `▲ SEEN IN ${runCount} RUNS` : "NEW THIS RUN";
}

export function TopicCard({
  entry,
  highlighted,
}: {
  entry: IndexedTopic;
  highlighted: boolean;
}) {
  const { topic, run_count, render_count } = entry;
  const to = `/topics/${encodeURIComponent(topic.run_id)}/${encodeURIComponent(topic.topic_id)}`;

  return (
    <Link to={to} className={`${styles.card} ${highlighted ? styles.highlighted : ""}`}>
      <span className={styles.head}>
        <span className={styles.recurrence}>{recurrence(run_count)}</span>
        <span className={styles.score}>{formatScore(topic.meme_potential)}</span>
      </span>

      <h3 className={styles.title}>{topic.label}</h3>

      <span className={styles.chips}>
        {topic.event_sentiment != null && <Chip tone="accent">{topic.event_sentiment}</Chip>}
        {topic.conversation_register != null && <Chip>{topic.conversation_register}</Chip>}
      </span>

      <span className={styles.counts}>
        {topic.post_count} posts ·{" "}
        {render_count === 0 ? (
          <span className={styles.noMemes}>no memes yet</span>
        ) : (
          `${render_count} memes`
        )}
      </span>
    </Link>
  );
}
