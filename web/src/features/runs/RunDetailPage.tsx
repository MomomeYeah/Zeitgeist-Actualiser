import { useRef, useState } from "react";
import { useParams } from "react-router-dom";

import type { RankedTopic, RunDetail, StageRecord } from "@/api/types";
import {
  useActiveRun,
  useRanking,
  useRun,
  useRunEvents,
  useRunLog,
} from "@/api/queries";
import { Breadcrumb } from "@/components/Breadcrumb";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { StatusPill } from "@/components/StatusPill";
import { LiveLog } from "@/features/runs/LiveLog";
import { RankingList } from "@/features/runs/RankingList";
import { RunActions } from "@/features/runs/RunActions";
import { StageCards } from "@/features/runs/StageCards";
import { activeStage } from "@/features/runs/progress";
import { survivedFor } from "@/features/runs/survived";
import { useNow } from "@/features/runs/useNow";
import { formatClock, formatDuration, formatElapsed, shortRunId } from "@/format";

import styles from "./RunDetailPage.module.css";

/**
 * Sources, the three fan-out numbers, the model, and either how long it
 * took or when it started.
 *
 * A live run has no duration to report, and `formatDuration` correctly
 * answers `—` for one. An em dash at the end of the config line reads as a
 * missing value; `started 14:02` is what a run that has not finished
 * actually knows about its own clock.
 */
function configLine(detail: RunDetail, live: boolean): string {
  const { run } = detail;
  const config = run.config;
  return [
    config.sources.join(" · "),
    `trend_limit ${config.trend_limit}`,
    `posts_per_trend ${config.posts_per_trend}`,
    `top_count ${config.top_count}`,
    config.llm_model,
    live
      ? `started ${formatClock(run.started_at)}`
      : formatDuration(run.started_at, run.finished_at),
  ].join(" · ");
}

/**
 * The generate stage ran and produced nothing.
 *
 * Both halves are needed: a run that died in analyse also has zero renders,
 * and telling that user every brief failed would send them looking for a
 * renderer problem that does not exist.
 */
function everyBriefFailed(stages: StageRecord[], ranking: RankedTopic[]): boolean {
  const generate = stages.find((stage) => stage.stage === "generate");
  if (
    generate === undefined ||
    generate.status === "queued" ||
    generate.status === "running"
  ) {
    return false;
  }
  return ranking.length > 0 && ranking.every((entry) => entry.render_count === 0);
}

export function RunDetailPage() {
  const { runId } = useParams();
  const run = useRun(runId);
  const ranking = useRanking(runId);
  const active = useActiveRun();
  const [verbose, setVerbose] = useState(false);
  const header = useRef<HTMLElement | null>(null);

  // The run's own row, not `active`: a run that has just ended is no longer
  // current, and the screen must stop following it the moment its status
  // settles rather than one poll later. `active` is still read, because a
  // queued run's row also says `running` and only `active.queued` tells the
  // two apart for the sidebar — this screen treats both as live, which is
  // right: a queued run has an open stream and a working abort.
  const live = run.data?.run.status === "running";
  const streamed = useRunEvents(runId, live);
  // Gated on the run query's own resolution, not just `!live`: `run.data`
  // is undefined on the first render, so `live` reads `false` until the run
  // query settles. Enabling on `!live` alone would fire a real log request
  // for every live run before its status is even known. Waiting for
  // `run.isSuccess` keeps the log query disabled until `live` is the truth,
  // not a placeholder — the two log sources stay genuinely exclusive.
  const history = useRunLog(runId, verbose, run.isSuccess && !live);
  const now = useNow(live);

  return (
    <QueryBoundary query={run} missing="No such run.">
      {(detail) => {
        const current = activeStage(detail.stages);
        const queued = active.data?.queued.includes(detail.run.run_id) ?? false;
        return (
          <div className={styles.page}>
            <Breadcrumb
              trail={[
                { label: "Runs", to: "/runs" },
                // Shortened rather than the mockup's full id: the header
                // two lines down already shows it in full, and `findByText`
                // (and a reader's eye) needs the run id to appear once, not
                // twice, in identical text.
                { label: shortRunId(detail.run.run_id) },
              ]}
            />

            {/* Focusable by script only (-1 keeps it out of the tab order):
                it is where `RunActions` sends focus when an accepted abort
                or resume replaces the button that held it, because the
                header is the one element that survives both. Reached
                there, a screen reader reads the run's status and id — what
                the action just changed. */}
            <header className={styles.header} ref={header} tabIndex={-1}>
              <div className={styles.headRow}>
                <div className={styles.identity}>
                  <StatusPill status={detail.run.status} />
                  <span className={styles.runId}>{detail.run.run_id}</span>
                  {live && (
                    <span className={styles.elapsed}>
                      {formatElapsed(detail.run.started_at, now)}
                    </span>
                  )}
                </div>
                <RunActions
                  // Remounts on every live↔over transition, which clears
                  // every mutation's state along with it. Without this, a
                  // resumed run going live again on this same page would
                  // carry a stale `stop.isSuccess` from its previous life
                  // straight into the buttons for its new one — see
                  // `RunActions`'s own doc comment for the pending-state
                  // guards this makes safe.
                  key={live ? "live" : "over"}
                  detail={detail}
                  live={live}
                  onFocusHome={() => header.current?.focus()}
                />
              </div>
              <MetaLine>{configLine(detail, live)}</MetaLine>
              {queued && (
                <p className={styles.queued}>
                  Waiting behind the run in flight. Nothing has started yet.
                </p>
              )}
              {detail.run.error !== null && (
                <p className={styles.error}>
                  {detail.run.error.kind} in {detail.run.error.stage} —{" "}
                  {detail.run.error.message} · {survivedFor(detail.run.error.stage)}
                </p>
              )}
            </header>

            <StageCards stages={detail.stages} live={live} />

            <QueryBoundary query={ranking} missing="No such run.">
              {(rows) =>
                rows.length === 0 ? (
                  live ? (
                    <RankingList
                      ranking={[]}
                      topCount={detail.run.config.top_count}
                      everyBriefFailed={false}
                      distilling={current === "ingest" || current === "analyse"}
                    />
                  ) : (
                    <p className={styles.noRanking}>
                      This run wrote no ranking — it did not reach evaluate.
                    </p>
                  )
                ) : (
                  <RankingList
                    ranking={rows}
                    topCount={detail.run.config.top_count}
                    everyBriefFailed={everyBriefFailed(detail.stages, rows)}
                  />
                )
              }
            </QueryBoundary>

            <LiveLog
              lines={live ? streamed : (history.data ?? [])}
              live={live}
              verbose={verbose}
              onVerboseChange={setVerbose}
              // The history query's own states, which `?? []` alone threw
              // away: a finished run read "This run logged nothing." while
              // its log was still loading, and for good if `/log` failed.
              loading={!live && history.isPending}
              failure={!live && history.isError ? history.error.detail : undefined}
            />
          </div>
        );
      }}
    </QueryBoundary>
  );
}
