import type { StageRecord } from "@/api/types";
import { ARTIFACT_NAMES, STAGES } from "@/api/types";
import { StageBar } from "@/components/StageBar";
import { byStage, stageCounter, stageFill } from "@/features/runs/progress";
import { formatBytes, formatDuration } from "@/format";

import styles from "./StageCards.module.css";

/**
 * Four cards, always.
 *
 * `stages_for_run` returns only the stages that were recorded, so a run
 * that died in analyse has no evaluate or generate row at all. The design
 * draws four regardless — the ones that never ran are `queued` in
 * `text-30` with no accent bar — because "this stage has not happened" is
 * information, and a three-card row would just look like a different
 * screen.
 *
 * Three treatments: complete (accent bar full), running (accent border,
 * accent wash, partial bar, a counter where the duration goes), and idle.
 * The artifact line drops its size on a running card, because a stage
 * that has not written its checkpoint has no size to report and `—` beside
 * a name reads as a missing value rather than an unwritten one.
 */
export function StageCards({ stages }: { stages: StageRecord[] }) {
  const recorded = byStage(stages);

  return (
    <ul className={styles.grid}>
      {STAGES.map((name) => {
        const record = recorded.get(name);
        const complete = record?.status === "ok" || record?.status === "skipped";
        const running = record?.status === "running";
        const counter = stageCounter(record);
        return (
          <li
            key={name}
            className={[
              styles.card,
              running ? styles.running : "",
              complete || running ? "" : styles.idle,
            ]
              .filter(Boolean)
              .join(" ")}
          >
            {complete || running ? (
              <StageBar fill={stageFill(record)} />
            ) : (
              <StageBar fill={0} tone="muted" />
            )}
            <div className={styles.head}>
              <span className={styles.name}>{name}</span>
              <span className={running ? styles.counter : styles.duration}>
                {counter ??
                  (record === undefined || record.started_at === null
                    ? "—"
                    : formatDuration(record.started_at, record.finished_at))}
              </span>
            </div>
            <p className={styles.summary}>{record?.summary ?? "queued"}</p>
            <span className={styles.artifact}>
              {running
                ? ARTIFACT_NAMES[name]
                : `${ARTIFACT_NAMES[name]} · ${formatBytes(record?.payload_bytes)}`}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
