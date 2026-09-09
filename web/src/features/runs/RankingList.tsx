import type { RankedTopic } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";
import { RankRow } from "@/features/runs/RankRow";

import styles from "./RankingList.module.css";

export function RankingList({
  ranking,
  topCount,
  everyBriefFailed,
}: {
  ranking: RankedTopic[];
  topCount: number;
  everyBriefFailed: boolean;
}) {
  const below = ranking.filter((entry) => !entry.above_cut).length;

  return (
    <section className={styles.section}>
      <SectionLabel hint={`top ${topCount} of ${ranking.length}`}>Ranking</SectionLabel>

      {everyBriefFailed && (
        <p className={styles.noMemes}>No memes were rendered — every brief failed</p>
      )}

      <ul className={styles.rows}>
        {ranking.map((entry, index) => (
          <li key={entry.topic.topic_id}>
            <RankRow
              entry={entry}
              highlighted={index === 0 && entry.above_cut}
              offerGenerate={everyBriefFailed || !entry.above_cut}
            />
          </li>
        ))}
      </ul>

      {below > 0 && <p className={styles.cut}>{below} more below the cut</p>}
    </section>
  );
}
