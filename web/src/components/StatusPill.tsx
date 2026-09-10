import type { RunStatus } from "@/api/types";

import styles from "./StatusPill.module.css";

const LABELS: Readonly<Record<RunStatus, string>> = {
  running: "RUNNING",
  ok: "OK",
  failed: "FAILED",
  aborted: "ABORTED",
  interrupted: "INTERRUPTED",
};

/**
 * `OK · 5` in accent tint, `FAILED` in contrast.
 *
 * The count is only drawn beside a completed run, and only when there is
 * one: a failure that never reached generate has no meaningful number, and
 * `OK · ` with nothing after it reads as a truncation bug.
 *
 * The handoff's partial form, `OK · 3 of 5`, is deliberately absent — see
 * "Decisions this phase is required to make", 7. The count here is how many
 * render rows the run has, from `RunSummary.render_ids`, which does not
 * distinguish ready from failed.
 */
export function StatusPill({
  status,
  count,
}: {
  status: RunStatus;
  count?: number;
}) {
  const tone = status === "ok" ? styles.ok : status === "running" ? styles.running : styles.bad;
  const suffix = status === "ok" && count !== undefined && count > 0 ? ` · ${count}` : "";
  return <span className={`${styles.pill} ${tone}`}>{`${LABELS[status]}${suffix}`}</span>;
}
