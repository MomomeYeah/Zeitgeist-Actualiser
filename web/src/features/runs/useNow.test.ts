import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useNow } from "@/features/runs/useNow";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useNow", () => {
  it("advances once a second while it is active", () => {
    const { result } = renderHook(() => useNow(true));
    const first = result.current;

    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(result.current.getTime()).toBeGreaterThan(first.getTime());
  });

  it("holds still when it is not", () => {
    // An idle app must not re-render once a second forever. Every screen
    // that shows an elapsed time mounts this, and only one of them ever
    // has a live run behind it.
    const { result } = renderHook(() => useNow(false));
    const first = result.current;

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(result.current).toBe(first);
  });

  it("stops when it becomes inactive", () => {
    const { result, rerender } = renderHook(
      ({ live }: { live: boolean }) => useNow(live),
      { initialProps: { live: true } },
    );

    rerender({ live: false });
    const settled = result.current;
    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(result.current).toBe(settled);
  });

  it("gives every watcher the same reading", () => {
    // One interval for the app, not one per component. Two clocks on one
    // screen — the run header beside its stage cards, the in-flight card
    // beside the sidebar — each had their own interval, so each sat on its
    // own phase of the second and stepped from 0:41 to 0:42 a few hundred
    // milliseconds apart. Identity, not approximate equality: two `Date`s
    // built a moment apart would still read the same second and pass a
    // looser check.
    const left = renderHook(() => useNow(true));
    const right = renderHook(() => useNow(true));

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(left.result.current).toBe(right.result.current);
  });

  it("keeps ticking for the watchers that remain", () => {
    // The shared interval is cleared when the last watcher unsubscribes.
    // Clearing it when *any* watcher unsubscribes would freeze every
    // elapsed display on the page the moment one of them unmounted —
    // which happens on this screen, as the ranking list appears.
    const staying = renderHook(() => useNow(true));
    const leaving = renderHook(() => useNow(true));
    const before = staying.result.current;

    leaving.unmount();
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(staying.result.current.getTime()).toBeGreaterThan(before.getTime());
  });

  it("reads the clock afresh when watching resumes after a gap", () => {
    // The reading is module state, so it holds whatever it was when the
    // last watcher left. An app sits idle with no timer running for as
    // long as no run is live; without a refresh on the way back in, the
    // first render of the next live run measures against a reading from
    // whenever the previous one ended, and the header flashes an elapsed
    // time hours wrong before the next tick corrects it.
    const first = renderHook(() => useNow(true));
    first.unmount();

    vi.setSystemTime(new Date("2026-08-29T09:00:00Z"));
    const second = renderHook(() => useNow(true));

    expect(second.result.current.toISOString()).toBe("2026-08-29T09:00:00.000Z");
  });

  it("stops the shared interval once nobody is watching", () => {
    // The whole point of `active`: an idle app must have no timer running
    // at all, not merely no re-rendering.
    const first = renderHook(() => useNow(true));
    const second = renderHook(() => useNow(true));

    first.unmount();
    second.unmount();

    expect(vi.getTimerCount()).toBe(0);
  });
});
