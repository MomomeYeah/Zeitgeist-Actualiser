import { useSyncExternalStore } from "react";

/**
 * A clock that ticks only while something is watching it, once for the
 * whole app rather than once per component.
 *
 * Nothing on the wire says how long a run has been going, so every elapsed
 * display is computed against now — and "now" has to advance for the
 * display to. `active` is what keeps an idle app from re-rendering once a
 * second forever: every screen showing an elapsed time mounts this, and
 * only one of them ever has a live run behind it.
 *
 * The tick is shared because more than one component can be watching at
 * once — the run page's header beside its stage cards, the Runs list's
 * in-flight card beside the sidebar's — and an interval each meant each
 * one drifted onto its own phase of the second. Two clocks on one screen
 * then stepped from 0:41 to 0:42 a few hundred milliseconds apart, which
 * reads as one of them being wrong. One interval, shared, makes every
 * elapsed display on the page change in the same frame.
 *
 * `useSyncExternalStore` rather than a context and a provider: this is a
 * value outside React that changes on its own, which is the case that API
 * exists for, and it needs no provider mounted above every screen that
 * happens to show a duration.
 */

/** Everyone currently watching. The interval runs while this is non-empty. */
const watchers = new Set<() => void>();

let timer: ReturnType<typeof setInterval> | null = null;
let intervalMs = 1000;
// A single `Date` shared by every subscriber in a tick.
// `useSyncExternalStore` compares snapshots with `Object.is`, so a fresh
// `Date` per read would never be equal to the last one and every render
// would be treated as a change — an infinite loop rather than a clock.
let now = new Date();

function tick(): void {
  now = new Date();
  for (const notify of watchers) notify();
}

function subscribe(notify: () => void): () => void {
  watchers.add(notify);
  if (timer === null) {
    // Refreshed on the way in, not only on the next tick: a component that
    // mounts 900ms into the current second would otherwise render against
    // a reading that is nearly a second stale.
    now = new Date();
    timer = setInterval(tick, intervalMs);
  }
  return () => {
    watchers.delete(notify);
    if (watchers.size === 0 && timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  };
}

/** Never subscribes, so the interval stays stopped for an idle app. */
function subscribeNothing(): () => void {
  return () => {};
}

function snapshot(): Date {
  return now;
}

export function useNow(active: boolean, tickMs = 1000): Date {
  // Read before subscribing, so a caller asking for a faster tick than the
  // default gets it even when the shared interval is already running for
  // somebody else. Only a test passes anything but the default, and only
  // one clock exists, so the last caller's interval wins rather than each
  // keeping its own — which is the point of sharing.
  if (tickMs !== intervalMs) {
    intervalMs = tickMs;
    if (timer !== null) {
      clearInterval(timer);
      timer = setInterval(tick, intervalMs);
    }
  }
  return useSyncExternalStore(active ? subscribe : subscribeNothing, snapshot);
}
