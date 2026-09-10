/**
 * What the stage records say about a run that is still going.
 *
 * Pure, and shared: the stage cards, the Runs in-flight card and the
 * sidebar card each need the same three answers, and a rule reimplemented
 * in three components drifts in two of them.
 */
import type { Stage, StageRecord } from "@/api/types";
import { STAGES } from "@/api/types";

/** A stage that will not change again. */
function settled(record: StageRecord): boolean {
  return record.status !== "running" && record.status !== "queued";
}

function counted(
  record: StageRecord,
): { done: number; total: number } | null {
  const { done, total } = record;
  if (done === null || done === undefined) return null;
  if (total === null || total === undefined || total <= 0) return null;
  return { done, total };
}

export function byStage(stages: StageRecord[]): Map<Stage, StageRecord> {
  return new Map(stages.map((record) => [record.stage, record]));
}

/**
 * Which stage is happening now, or undefined if none is.
 *
 * The `running` row is the direct answer, and the runner writes one as
 * every stage begins. The fallback covers the window between the worker
 * opening the run row and its first stage announcing itself: nothing is
 * running and nothing has finished, and the first stage with no row is the
 * one about to start.
 */
export function activeStage(stages: StageRecord[]): Stage | undefined {
  const running = stages.find((record) => record.status === "running");
  if (running !== undefined) return running.stage;
  const done = new Set(stages.filter(settled).map((record) => record.stage));
  return STAGES.find((stage) => !done.has(stage));
}

/** 0-1, for `StageBar`. A stage with nothing to count stays at 0. */
export function stageFill(record: StageRecord | undefined): number {
  if (record === undefined) return 0;
  if (record.status === "ok" || record.status === "skipped") return 1;
  if (record.status !== "running") return 0;
  const progress = counted(record);
  return progress === null ? 0 : progress.done / progress.total;
}

/**
 * `17 / 25`, or null where the design draws a duration instead.
 *
 * Only a running stage that counts something has one. Ingest is a single
 * opaque fetch and evaluate a single ranking pass, so both report null and
 * their cards show an indeterminate bar rather than a fabricated fraction.
 */
export function stageCounter(record: StageRecord | undefined): string | null {
  if (record === undefined || record.status !== "running") return null;
  const progress = counted(record);
  return progress === null ? null : `${progress.done} / ${progress.total}`;
}
