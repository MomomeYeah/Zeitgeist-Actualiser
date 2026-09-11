import { Link, useNavigate } from "react-router-dom";

import { useGenerateRenders } from "@/api/queries";
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

/**
 * `generate ↗` — briefs and renders this one topic without re-running the
 * pipeline, through the endpoint topic detail's LLM panel posts to. One
 * meme, with the model choosing the template: the row has no room to ask,
 * and letting the model choose is that panel's own default.
 *
 * On a 202 it opens the topic, where the new tile is already generating.
 * Staying here would show nothing, because the ranking counts ready
 * renders only. A refusal stays on the row, in the server's own words.
 */
function GenerateButton({
  runId,
  topicId,
  to,
}: {
  runId: string;
  topicId: string;
  to: string;
}) {
  const navigate = useNavigate();
  const generation = useGenerateRenders(runId, topicId);

  if (generation.isError) {
    return (
      <span role="alert" className={styles.generateError} title={generation.error.detail}>
        {generation.error.detail}
      </span>
    );
  }
  return (
    <button
      type="button"
      className={styles.generate}
      disabled={generation.isPending}
      onClick={() =>
        generation.mutate(
          { mode: "llm", template_id: null, count: 1 },
          { onSuccess: () => void navigate(to) },
        )
      }
    >
      {generation.isPending ? "generating…" : "generate ↗"}
    </button>
  );
}

export function RankRow({
  entry,
  highlighted,
  offerGenerate,
}: {
  entry: RankedTopic;
  highlighted: boolean;
  /**
   * Draw `generate ↗` where the meme count would be. True below the cut —
   * those topics were never briefed — and true for every row when the
   * generate stage rendered nothing at all.
   */
  offerGenerate: boolean;
}) {
  const { topic, render_count, above_cut } = entry;
  const to = `/topics/${encodeURIComponent(topic.run_id)}/${encodeURIComponent(topic.topic_id)}`;

  // Not one anchor any more: `generate ↗` is a button, and a button inside
  // an anchor is invalid HTML the browser silently reshapes. The title's
  // link stretches over the row instead (see `.label::after`), so the row
  // still opens the topic wherever it is clicked, and the button sits above
  // the stretch.
  return (
    <div
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
        <Link to={to} className={styles.label}>
          {topic.label}
        </Link>
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
          <GenerateButton runId={topic.run_id} topicId={topic.topic_id} to={to} />
        ) : (
          // A count, not thumbnails. `RankedTopic` carries `render_count`
          // from `Store.render_counts` and no render ids, and addressing an
          // image needs an id — only topic detail's `renders` list has
          // those. The design draws 42px tiles here; showing them would mean
          // one extra request per row to render something topic detail
          // shows one click away. So the row states the count and topic
          // detail draws the memes.
          <span className={styles.count}>
            {render_count} {render_count === 1 ? "meme" : "memes"}
          </span>
        )}
      </span>
    </div>
  );
}
