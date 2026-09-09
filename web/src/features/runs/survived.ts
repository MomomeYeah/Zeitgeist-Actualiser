import type { RunError, Stage } from "@/api/types";

/**
 * What a failed run managed to write, from the stage it died in.
 *
 * The stages run in order and a stage only fails after its predecessors
 * wrote, so the failed stage names the last checkpoint that exists. That is
 * the same fact `RunDetail.resume_stage` encodes, reached without a second
 * request — `RunSummary` carries no stage records.
 *
 * The extensions are gone (`ranked`, not `ranked.json`): these are database
 * rows now, and a filename for a row would be a small lie on a screen whose
 * whole job is telling you what a run actually did.
 */
const SURVIVED: Readonly<Record<Stage, string>> = {
  ingest: "nothing written",
  analyse: "evidence checkpoint intact",
  evaluate: "topics checkpoint intact",
  generate: "ranked checkpoint intact",
};

export function survivedFor(stage: Stage): string {
  return SURVIVED[stage];
}

/**
 * Where a resume would start, or null when there is nothing to resume from.
 *
 * Null is the source outage: ingest wrote no checkpoint, so the run has to
 * start over. The UI must not offer a resume it cannot honour.
 */
export function resumeStageFor(error: RunError | null | undefined): Stage | null {
  if (!error) return null;
  return error.stage === "ingest" ? null : error.stage;
}
