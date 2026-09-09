import { Link } from "react-router-dom";

import type { RankedTopic } from "@/api/types";
import { Chip } from "@/components/Chip";
import { formatScore } from "@/format";

import styles from "./RankRow.module.css";

/**
 * `trending · 412 posts · “absolute unit” 31 authors`.
 *
 * The phrase clause is dropped rather than emptied when the dossier found
 * nothing above `phrase_min_authors`: an empty quote reads as a phrase that
 * is literally nothing.
 */
function subline(topic: RankedTopic["topic"]): string {
  const parts = [topic.trend_status, `${topic.post_count} posts`];
  if (topic.top_phrase !== null && topic.top_phrase !== undefined) {
    parts.push(`“${topic.top_phrase}” ${topic.top_phrase_authors ?? 0} authors`);
  }
  return parts.join(" · ");
}

export function RankRow({
  entry,
  highlighted,
  offerGenerate,
}: {
  entry: RankedTopic;
  highlighted: boolean;
  /**
   * Draw `generate ↗` where the thumbnails would be. True below the cut —
   * those topics were never briefed — and true for every row when the
   * generate stage rendered nothing at all.
   */
  offerGenerate: boolean;
}) {
  const { topic, render_count, above_cut } = entry;
  const to = `/topics/${encodeURIComponent(topic.run_id)}/${encodeURIComponent(topic.topic_id)}`;

  return (
    <Link
      to={to}
      className={[
        styles.row,
        highlighted ? styles.highlighted : "",
        above_cut ? "" : styles.belowCut,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span className={styles.rank}>{topic.final_rank}</span>

      <span className={styles.identity}>
        <span className={styles.label}>{topic.label}</span>
        <span className={styles.subline}>{subline(topic)}</span>
      </span>

      <span className={styles.chips}>
        {topic.event_sentiment !== null && topic.event_sentiment !== undefined && (
          <Chip tone="accent">{topic.event_sentiment}</Chip>
        )}
        {topic.conversation_register !== null &&
          topic.conversation_register !== undefined && (
            <Chip>{topic.conversation_register}</Chip>
          )}
      </span>

      <span className={styles.scores}>
        <span className={styles.components}>
          trend {formatScore(topic.trend_score)} · meme {formatScore(topic.meme_potential)}
        </span>
        <span className={styles.final}>final {formatScore(topic.final_score, 3)}</span>
      </span>

      <span className={styles.memes}>
        {offerGenerate ? (
          // Phase 7 replaces this with the action itself. Here it is text
          // inside the row's own link, which already goes to topic detail —
          // where that action's panels will live.
          <span className={styles.generate}>generate ↗</span>
        ) : (
          // A count, not thumbnails. `RankedTopic` carries `render_count`
          // from `Store.render_counts` and no render ids, and addressing an
          // image needs an id — only topic detail's `renders` list has
          // those. The design draws 42px tiles here; showing them would mean
          // one extra request per row, on a frozen contract, to render
          // something topic detail shows one click away. So the row states
          // the count and topic detail draws the memes.
          <span className={styles.count}>
            {render_count} {render_count === 1 ? "meme" : "memes"}
          </span>
        )}
      </span>
    </Link>
  );
}
