import { Link } from "react-router-dom";

import type { IndexedTopic } from "@/api/types";
import { Chip } from "@/components/Chip";
import { formatScore } from "@/format";

import styles from "./RecentTable.module.css";

/**
 * Saturating and cooling, as rows.
 *
 * 1px gaps over a `divider` background, so the hairlines read as borders
 * without every row carrying one — which is what the handoff specifies and
 * what keeps a long list from looking striped.
 */
export function RecentTable({ topics }: { topics: IndexedTopic[] }) {
  return (
    <div className={styles.table} data-testid="recently-trending">
      {topics.map(({ topic }) => (
        <Link
          key={`${topic.run_id}-${topic.topic_id}`}
          to={`/topics/${encodeURIComponent(topic.run_id)}/${encodeURIComponent(topic.topic_id)}`}
          className={styles.row}
        >
          <span className={styles.title}>{topic.label}</span>
          <span>
            {topic.event_sentiment != null && <Chip>{topic.event_sentiment}</Chip>}
          </span>
          <span className={styles.meta}>{topic.trend_status}</span>
          <span className={styles.meta}>{topic.post_count} posts</span>
          <span className={styles.score}>{formatScore(topic.meme_potential)}</span>
        </Link>
      ))}
    </div>
  );
}
