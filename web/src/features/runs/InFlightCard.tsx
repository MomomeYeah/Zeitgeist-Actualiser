import { Link } from "react-router-dom";

import { STAGES } from "@/api/types";
import { useRun } from "@/api/queries";
import { StageBar } from "@/components/StageBar";
import { StatusPill } from "@/components/StatusPill";
import { activeStage, byStage, stageFill } from "@/features/runs/progress";
import { useNow } from "@/features/runs/useNow";
import { formatElapsed } from "@/format";

import styles from "./InFlightCard.module.css";

/**
 * The card pinned above the Runs list while a run is in flight.
 *
 * Four segments rather than one bar, because the four stages are the unit
 * anyone reasons about a run in: a single 43% bar says less than "ingest
 * and analyse are done, evaluate is going".
 *
 * Returns null rather than a skeleton while the run's detail is still
 * loading. The card appearing a moment late is invisible; a placeholder
 * card that then becomes a real one is a layout shift on the screen's most
 * prominent element.
 */
export function InFlightCard({ runId }: { runId: string }) {
  const run = useRun(runId);
  const now = useNow(true);

  if (run.data === undefined) return null;

  const stages = byStage(run.data.stages);
  const current = activeStage(run.data.stages);

  return (
    <Link to={`/runs/${encodeURIComponent(runId)}`} className={styles.card}>
      <div className={styles.head}>
        <StatusPill status="running" />
        <span className={styles.runId}>{runId}</span>
        <span className={styles.elapsed}>
          {formatElapsed(run.data.run.started_at, now)}
        </span>
        {current !== undefined && <span className={styles.stage}>{current}</span>}
      </div>

      <div className={styles.segments}>
        {STAGES.map((stage) => (
          <div key={stage} className={styles.segment}>
            <StageBar fill={stageFill(stages.get(stage))} />
            <span className={styles.segmentName}>{stage}</span>
          </div>
        ))}
      </div>
    </Link>
  );
}
