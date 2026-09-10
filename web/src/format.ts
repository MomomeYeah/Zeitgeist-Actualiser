/**
 * Every number and date the screens render, in one place.
 *
 * Pure, and tested as pure functions rather than through six screens. The
 * em dash is the shared convention for "there genuinely is no value here":
 * a stage that wrote no checkpoint, a run that has not finished, a topic the
 * model gave no meme potential. Rendering a zero for any of those would be a
 * claim the pipeline never made.
 */

const NONE = "—";

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return NONE;
  if (bytes < 1000) return `${bytes} B`;
  if (bytes < 1_000_000) return `${(bytes / 1000).toFixed(1)} kB`;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

export function formatDuration(
  startedAt: string,
  finishedAt: string | null | undefined,
): string {
  if (!finishedAt) return NONE;
  const seconds = Math.max(
    0,
    Math.round(
      (new Date(finishedAt).getTime() - new Date(startedAt).getTime()) / 1000,
    ),
  );
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function formatRelative(at: string, now: Date = new Date()): string {
  const seconds = Math.max(0, (now.getTime() - new Date(at).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** The wall clock, `14:02`, that the Topics header's metadata line ends with. */
export function formatClock(at: string, timeZone?: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone,
  }).format(new Date(at));
}

export function formatScore(score: number | null | undefined, digits = 2): string {
  if (score === null || score === undefined) return NONE;
  return score.toFixed(digits);
}

/**
 * `…829T090000Z` — the truncation the runs list draws.
 *
 * A run id is a timestamp, so its leading characters are the part that
 * repeats. Dropping them is what makes a column of twenty-five ids readable.
 */
export function shortRunId(runId: string): string {
  return runId.length > 12 ? `…${runId.slice(-11)}` : runId;
}

/**
 * `t+06:41` — how long a run has been going.
 *
 * Minutes are not wrapped into hours. The whole job of this display is
 * answering "how long has this been going", and `t+72:15` answers it
 * faster than `t+1:12:15` does.
 *
 * Clamped at zero: the client's clock and the server's need not agree, and
 * a run that started "in the future" must read `t+00:00` rather than
 * counting down.
 */
export function formatElapsed(startedAt: string, now: Date = new Date()): string {
  const seconds = Math.max(
    0,
    Math.floor((now.getTime() - new Date(startedAt).getTime()) / 1000),
  );
  const minutes = Math.floor(seconds / 60);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `t+${pad(minutes)}:${pad(seconds % 60)}`;
}
