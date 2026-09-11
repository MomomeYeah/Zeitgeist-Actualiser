import type { StageRecord } from "@/api/types";
import { ARTIFACT_NAMES, STAGES } from "@/api/types";
import { StageBar } from "@/components/StageBar";
import {
  byStage,
  interruptedSummary,
  stageCounter,
  stageFill,
} from "@/features/runs/progress";
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
 * Four treatments: complete (accent bar full), running (accent border,
 * accent wash, partial bar, a counter where the duration goes), interrupted,
 * and idle. The artifact line drops its size on a running or interrupted
 * card, because a stage that has not written its checkpoint has no size to
 * report and `—` beside a name reads as a missing value rather than an
 * unwritten one.
 *
 * `live` is the run's own status, not the stage record's: nothing closes a
 * `running` stage row when a run is aborted, fails, or is interrupted by a
 * restart, so a row still saying `running` in a run that has ended is a
 * stage that was cut off. Such a row gets the idle/muted treatment — no
 * `running` class, no counter, ever — because trusting the row's own status
 * once the run itself has settled would draw an aborted run's page as live
 * forever.
 */
export function StageCards({ stages, live }: { stages: StageRecord[]; live: boolean }) {
  const recorded = byStage(stages);

  return (
    <ul className={styles.grid}>
      {STAGES.map((name) => {
        const record = recorded.get(name);
        const complete = record?.status === "ok" || record?.status === "skipped";
        // A row can say `running` in a run that is not live — see the
        // doc comment above. `running` only lights up the live treatment
        // when the run agrees; `interrupted` catches the disagreement.
        const running = record?.status === "running" && live;
        const interrupted = record?.status === "running" && !live;
        // Gated on `running`, not on the record alone: an interrupted row's
        // counters are real, but the design's rule is "never a counter"
        // for a stage that is not actually going. Falling through to
        // `formatDuration` below is safe because a row that is still
        // `running` has no `finished_at` either way, so it reads `—`.
        const counter = running ? stageCounter(record) : null;
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
            ) : interrupted ? (
              // Muted, but not zeroed: the stage really did get this far
              // before the run ended, and a fabricated empty bar would be
              // as dishonest as a fabricated full one.
              <StageBar fill={stageFill(record)} tone="muted" />
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
            <p className={styles.summary}>
              {interrupted ? interruptedSummary(record) : (record?.summary ?? "queued")}
            </p>
            <span className={styles.artifact}>
              {running || interrupted
                ? ARTIFACT_NAMES[name]
                : `${ARTIFACT_NAMES[name]} · ${formatBytes(record?.payload_bytes)}`}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
