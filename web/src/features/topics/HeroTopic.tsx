import { Link } from "react-router-dom";

import type { IndexedTopic } from "@/api/types";
import { useTopicDetail } from "@/api/queries";
import { Chip } from "@/components/Chip";
import { formatScore } from "@/format";

import styles from "./HeroTopic.module.css";

/**
 * The accent-filled card, where the palette inverts.
 *
 * The summary comes from a second request. `TopicIndex` carries no prose —
 * `TopicRow` has no summary field, and adding one would reopen a contract
 * phase 4 closed — so the hero fetches the one topic it is showing. The
 * card renders fully without it; the paragraph appears when it arrives.
 */
export function HeroTopic({ entry }: { entry: IndexedTopic }) {
  const { topic } = entry;
  const detail = useTopicDetail(topic.run_id, topic.topic_id);
  const to = `/topics/${encodeURIComponent(topic.run_id)}/${encodeURIComponent(topic.topic_id)}`;

  return (
    <Link to={to} className={styles.hero} data-testid="hero">
      <span className={styles.kicker}>
        {`TOP RIGHT NOW · ${topic.trend_status.toUpperCase()} · MEME ${formatScore(topic.meme_potential)}`}
      </span>
      <h2 className={styles.title}>{topic.label}</h2>
      {detail.data?.dossier != null && (
        <p className={styles.summary}>{detail.data.dossier.what_happened}</p>
      )}
      <span className={styles.chips}>
        {topic.event_sentiment != null && (
          <Chip tone="inverted">{topic.event_sentiment}</Chip>
        )}
        {topic.conversation_register != null && (
          <Chip tone="inverted">{topic.conversation_register}</Chip>
        )}
        {entry.render_count > 0 && (
          <Chip tone="inverted">{`${entry.render_count} memes`}</Chip>
        )}
      </span>
    </Link>
  );
}
