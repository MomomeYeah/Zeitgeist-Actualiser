import type { StageRecord } from "@/api/types";
import { ARTIFACT_NAMES, STAGES } from "@/api/types";
import { StageBar } from "@/components/StageBar";
import { formatBytes, formatDuration } from "@/format";

import styles from "./StageCards.module.css";

/**
 * Four cards, always.
 *
 * `stages_for_run` returns only the stages that were recorded, so a run that
 * died in analyse has no evaluate or generate row at all. The design draws
 * four regardless — the ones that never ran are `queued` in `text-30` with
 * no accent bar — because "this stage has not happened" is information, and
 * a three-card row would just look like a different screen.
 */
export function StageCards({ stages }: { stages: StageRecord[] }) {
  const recorded = new Map(stages.map((stage) => [stage.stage, stage]));

  return (
    <ul className={styles.grid}>
      {STAGES.map((name) => {
        // The accent bar means "this stage completed". A failed, skipped or
        // absent stage gets the muted treatment, which is what the design's
        // "incomplete stages use `border` and `text-30` throughout with no
        // accent bar" asks for. Phase 6 adds the partial fill for a stage
        // that is running.
        const record = recorded.get(name);
        const complete = record?.status === "ok";
        return (
          <li key={name} className={`${styles.card} ${complete ? "" : styles.idle}`}>
            {complete ? <StageBar fill={1} /> : <StageBar fill={0} tone="muted" />}
            <div className={styles.head}>
              <span className={styles.name}>{name}</span>
              <span className={styles.duration}>
                {record === undefined || record.started_at === null
                  ? "—"
                  : formatDuration(record.started_at, record.finished_at)}
              </span>
            </div>
            <p className={styles.summary}>{record?.summary ?? "queued"}</p>
            <span className={styles.artifact}>
              {ARTIFACT_NAMES[name]} · {formatBytes(record?.payload_bytes)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
