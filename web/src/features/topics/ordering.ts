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

export type MoodTone = "top" | "second" | "tail" | "rest";

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
 * Accent for the leader, accent at 50% for the second, then white at 16%
 * and 8% for the rest. Tone means rank and nothing else: schadenfreude used
 * to take `contrast` wherever it ranked, which made it the one segment whose
 * colour did not answer "how big is this".
 *
 * This is the whole distribution, which is what `moodLine` describes. What
 * the bar can actually draw is `foldNarrowSegments` of this.
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
      tone: toneFor(index),
    }));
}

function toneFor(index: number): MoodTone {
  if (index === 0) return "top";
  if (index === 1) return "second";
  return index === 2 ? "tail" : "rest";
}

export interface DisplaySegment {
  /** React key: the sentiment, or `others` for the folded remainder. */
  key: string;
  label: string;
  /** 0-1. The segment's flex-basis. */
  share: number;
  tone: MoodTone;
  /** What an `others` segment swallowed. Absent on a sentiment. */
  title?: string;
}

/**
 * The bar's column in pixels: `--content-width` less the runs column and the
 * gap between them, per `.bottom` in `TopicsPage.module.css`.
 */
const COLUMN_PX = 1000 - 320 - 18;

/** One character of a segment label: 9.5px in the mono face, plus padding. */
const CHAR_PX = 5.7;
const LABEL_PADDING_PX = 12;

/**
 * Collapse the segments too narrow to read into one `+N others`.
 *
 * Shares are a share of the window, not of a readable width. The taxonomy
 * has eleven members and a live window is lopsided — 51% for the leader in
 * the run this was written against — so the tail lands at a few percent
 * each, ten to twenty pixels, and renders as a clipped letter or two.
 *
 * A segment fits when its share buys the pixels its own label needs, so the
 * threshold is per-label: `awe 2` clears 6% where `schadenfreude 3` wants
 * 15%. One flat threshold cannot serve both without either clipping the
 * long names or folding away readable short ones.
 *
 * The fold takes a suffix, so everything drawn outranks everything folded.
 * A tie spread across many sentiments therefore collapses to the leader and
 * an aggregate rather than showing the tie — the trade for not having to
 * explain why a visible segment is smaller than a folded one.
 */
export function foldNarrowSegments(segments: MoodSegment[]): DisplaySegment[] {
  const firstNarrow = segments.findIndex(
    (segment) => !fits(labelFor(segment), segment.share),
  );
  if (firstNarrow === -1) return segments.map(asDisplay);

  // `+1 others` is wider than most names and carries less, so a lone
  // straggler is drawn clipped rather than folded.
  if (segments.length - firstNarrow === 1) return segments.map(asDisplay);

  // The aggregate has to fit its own label too, and never at the cost of
  // the leader: a bar reading only `+11 others` names nothing.
  let kept = Math.max(firstNarrow, 1);
  while (kept > 1 && !fits(othersLabel(segments.length - kept), othersShare(segments, kept))) {
    kept -= 1;
  }

  const folded = segments.slice(kept);
  return [
    ...segments.slice(0, kept).map(asDisplay),
    {
      key: "others",
      label: othersLabel(folded.length),
      share: othersShare(segments, kept),
      tone: "rest",
      title: folded.map(labelFor).join(", "),
    },
  ];
}

function fits(label: string, share: number): boolean {
  return share * COLUMN_PX >= label.length * CHAR_PX + LABEL_PADDING_PX;
}

function labelFor(segment: MoodSegment): string {
  return `${segment.sentiment} ${segment.count}`;
}

function othersLabel(count: number): string {
  return `+${count} others`;
}

function othersShare(segments: MoodSegment[], kept: number): number {
  return segments.slice(kept).reduce((sum, segment) => sum + segment.share, 0);
}

function asDisplay(segment: MoodSegment): DisplaySegment {
  return {
    key: segment.sentiment,
    label: labelFor(segment),
    share: segment.share,
    tone: segment.tone,
  };
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
