import type { IndexedTopic } from "@/api/types";

/**
 * Rank order, which the API does not return.
 *
 * `GET /api/topics` deduplicates on `label_slug` over `topics_for_runs`,
 * which is newest-run-first — recency, not rank. The hero says "TOP RIGHT
 * NOW", so the client sorts.
 *
 * This is presentation, not a second ranking: `final_score` is already
 * `rank_score`'s output, computed once in `projection.flatten`. Sorting by
 * it cannot disagree with the backend the way re-deriving the blend would.
 *
 * The `topic_id` tiebreak makes the order total. Two topics can genuinely
 * share a score, and without it the first card would depend on input order.
 */
export function byRank(topics: IndexedTopic[]): IndexedTopic[] {
  return [...topics].sort((left, right) => {
    const delta = right.topic.final_score - left.topic.final_score;
    return delta !== 0 ? delta : left.topic.topic_id.localeCompare(right.topic.topic_id);
  });
}

export type MoodTone = "top" | "second" | "schadenfreude" | "tail" | "rest";

export interface MoodSegment {
  sentiment: string;
  count: number;
  /** 0-1. The segment's flex-basis. */
  share: number;
  tone: MoodTone;
}

/**
 * One segment per sentiment, largest first.
 *
 * Accent for the leader, accent at 50% for the second, `contrast` for
 * schadenfreude wherever it ranks — the handoff singles it out by name, not
 * by position — then white at 16% and 8% for the rest.
 */
export function moodSegments(totals: Record<string, number>): MoodSegment[] {
  const entries = Object.entries(totals).filter(([, count]) => count > 0);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  if (total === 0) return [];

  return entries
    .sort((left, right) => right[1] - left[1])
    .map(([sentiment, count], index) => ({
      sentiment,
      count,
      share: count / total,
      tone: toneFor(sentiment, index),
    }));
}

function toneFor(sentiment: string, index: number): MoodTone {
  if (sentiment === "schadenfreude") return "schadenfreude";
  if (index === 0) return "top";
  if (index === 1) return "second";
  return index === 2 ? "tail" : "rest";
}

/**
 * The line beneath the bar.
 *
 * The handoff has it cover register skew and average meme potential versus
 * the previous run. `TopicIndex` carries neither — no register totals, and
 * no previous-window rows to average over — and the contract is frozen, so
 * this reports what the contract does carry: the leader, its share, and its
 * change against the previous run.
 *
 * The comparison is dropped rather than shown as zero when there is no
 * previous run: "no previous run" and "no change" are different facts.
 */
export function moodLine(
  totals: Record<string, number>,
  previous: Record<string, number>,
): string {
  const segments = moodSegments(totals);
  const leader = segments[0];
  if (leader === undefined) return "";

  const share = Math.round(leader.share * 100);
  const head = `${leader.sentiment} leads at ${share}% of the window`;

  const previousTotal = Object.values(previous).reduce((sum, count) => sum + count, 0);
  if (previousTotal === 0) return head;

  const before = Math.round(((previous[leader.sentiment] ?? 0) / previousTotal) * 100);
  const delta = share - before;
  if (delta === 0) return `${head} · unchanged on the previous run`;
  const direction = delta > 0 ? "up" : "down";
  return `${head} · ${direction} ${Math.abs(delta)} points on the previous run`;
}
