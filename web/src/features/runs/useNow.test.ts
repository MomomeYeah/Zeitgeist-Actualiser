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
});
