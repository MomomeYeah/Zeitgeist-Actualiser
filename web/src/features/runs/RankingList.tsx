import type { RankedTopic } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";
import { RankRow } from "@/features/runs/RankRow";

import styles from "./RankingList.module.css";

export function RankingList({
  ranking,
  topCount,
  everyBriefFailed,
  generateSettled = false,
  distilling = false,
}: {
  ranking: RankedTopic[];
  topCount: number;
  everyBriefFailed: boolean;
  /**
   * The generate stage has finished, one way or another, so a topic with
   * no memes is a topic that is not getting any without being asked. While
   * the stage is still running, a kept topic with none is simply waiting
   * its turn, and offering to generate for it would race the pipeline.
   */
  generateSettled?: boolean;
  /**
   * Ingest or analyse is running and no rows exist yet.
   *
   * The design draws rows appending as topics are distilled. Persisting a
   * half-scored topic needs a rank that does not exist until every topic
   * has been distilled and scored, which is a contract change with its own
   * questions — see the phase 6 plan, "Decisions", 2. So the section says
   * what is happening and where the order comes from, and the live log
   * carries the per-topic detail in the meantime.
   */
  distilling?: boolean;
}) {
  const below = ranking.filter((entry) => !entry.above_cut).length;

  return (
    <section className={styles.section}>
      <SectionLabel
        hint={
          distilling ? "final order is set in evaluate" : `top ${topCount} of ${ranking.length}`
        }
      >
        Ranking
      </SectionLabel>

      {distilling && (
        <p className={styles.distilling}>
          Distilling — the ranking appears when analyse finishes.
        </p>
      )}

      {everyBriefFailed && (
        <p className={styles.noMemes}>No memes were rendered — every brief failed</p>
      )}

      <ul className={styles.rows}>
        {ranking.map((entry, index) => (
          <li key={entry.topic.topic_id}>
            <RankRow
              entry={entry}
              highlighted={index === 0 && entry.above_cut}
              offerGenerate={
                !entry.above_cut || (generateSettled && entry.render_count === 0)
              }
            />
          </li>
        ))}
      </ul>

      {below > 0 && <p className={styles.cut}>{below} more below the cut</p>}
    </section>
  );
}
