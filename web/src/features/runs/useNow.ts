import { useEffect, useState } from "react";

/**
 * A clock that ticks only while something is watching it.
 *
 * Nothing on the wire says how long a run has been going, so every elapsed
 * display is computed against now — and "now" has to advance for the
 * display to. `active` is what keeps an idle app from re-rendering once a
 * second forever: every screen showing an elapsed time mounts this, and
 * only one of them ever has a live run behind it.
 */
export function useNow(active: boolean, intervalMs = 1000): Date {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [active, intervalMs]);

  return now;
}
