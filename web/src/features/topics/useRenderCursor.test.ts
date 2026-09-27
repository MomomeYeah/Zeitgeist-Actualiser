import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RenderRecord } from "@/api/types";
import { useRenderCursor } from "@/features/topics/useRenderCursor";
import { makeRenderRecord } from "@/test/factories";

/** A list of renders named by id, which is all these tests distinguish. */
function rows(...ids: string[]): RenderRecord[] {
  return ids.map((id) => makeRenderRecord({ id }));
}

function mount(initial: RenderRecord[]) {
  return renderHook((renders: RenderRecord[]) => useRenderCursor(renders), {
    initialProps: initial,
  });
}

describe("useRenderCursor", () => {
  it("is closed until a render is opened", () => {
    const { result } = mount(rows("r1", "r2", "r3"));

    expect(result.current.record).toBeNull();
    expect(result.current.index).toBe(-1);
    // The count is the list's, open or not: the grid's hint and the modal's
    // counter both describe the same list.
    expect(result.current.count).toBe(3);
    // Nothing to step from, so neither direction is offered.
    expect(result.current.hasPrev).toBe(false);
    expect(result.current.hasNext).toBe(false);
  });

  it("opens the render it is asked for, wherever it sits", () => {
    const { result } = mount(rows("r1", "r2", "r3"));

    act(() => result.current.open("r2"));

    expect(result.current.record?.id).toBe("r2");
    expect(result.current.index).toBe(1);
    expect(result.current.hasPrev).toBe(true);
    expect(result.current.hasNext).toBe(true);
  });

  it("steps forwards and back through the list", () => {
    const { result } = mount(rows("r1", "r2", "r3"));

    act(() => result.current.open("r1"));
    act(() => result.current.next());
    expect(result.current.record?.id).toBe("r2");

    act(() => result.current.next());
    expect(result.current.record?.id).toBe("r3");

    act(() => result.current.prev());
    expect(result.current.record?.id).toBe("r2");
  });

  it("will not step off the front of the list", () => {
    const { result } = mount(rows("r1", "r2"));

    act(() => result.current.open("r1"));
    expect(result.current.hasPrev).toBe(false);

    act(() => result.current.prev());

    // Still on r1 rather than wrapping to r2, which is what `disabled`
    // chevrons promise and what the arrow keys must honour too.
    expect(result.current.record?.id).toBe("r1");
  });

  it("will not step off the end of the list", () => {
    const { result } = mount(rows("r1", "r2"));

    act(() => result.current.open("r2"));
    expect(result.current.hasNext).toBe(false);

    act(() => result.current.next());

    expect(result.current.record?.id).toBe("r2");
  });

  it("shows the render that took the place of one deleted from the middle", () => {
    // The point of the whole feature: a delete from inside the modal leaves
    // the modal open on the next render along.
    const view = mount(rows("r1", "r2", "r3"));

    act(() => view.result.current.open("r2"));
    view.rerender(rows("r1", "r3"));

    expect(view.result.current.record?.id).toBe("r3");
    expect(view.result.current.index).toBe(1);
    expect(view.result.current.count).toBe(2);
  });

  it("shows the render before one deleted from the end", () => {
    // There is no "next" to advance to, so the clamp falls back to what is
    // now the last render rather than closing.
    const view = mount(rows("r1", "r2", "r3"));

    act(() => view.result.current.open("r3"));
    view.rerender(rows("r1", "r2"));

    expect(view.result.current.record?.id).toBe("r2");
    expect(view.result.current.hasNext).toBe(false);
  });

  it("closes when the render it was showing was the only one", () => {
    const view = mount(rows("r1"));

    act(() => view.result.current.open("r1"));
    view.rerender([]);

    expect(view.result.current.record).toBeNull();
    expect(view.result.current.index).toBe(-1);
  });

  it("stays where it is when a render arrives while one is open", () => {
    // Polling appends rows. Jumping the modal to a render the user did not
    // ask for would make the screen move under them.
    const view = mount(rows("r1", "r2"));

    act(() => view.result.current.open("r1"));
    view.rerender(rows("r1", "r2", "r3"));

    expect(view.result.current.record?.id).toBe("r1");
    expect(view.result.current.index).toBe(0);
    expect(view.result.current.count).toBe(3);
    expect(view.result.current.hasNext).toBe(true);
  });

  it("follows the open row through a change of status", () => {
    // A generating render turning ready is the same render, so the modal
    // stays on it and swaps what it draws.
    const view = mount([
      makeRenderRecord({ id: "r1" }),
      makeRenderRecord({ id: "g1", status: "generating" }),
    ]);

    act(() => view.result.current.open("g1"));
    view.rerender([
      makeRenderRecord({ id: "r1" }),
      makeRenderRecord({ id: "g1", status: "ready" }),
    ]);

    expect(view.result.current.record?.id).toBe("g1");
    expect(view.result.current.record?.status).toBe("ready");
  });

  it("re-reads its position when a render before the open one goes", () => {
    // The falsifiable case for keeping the stored index in step with the
    // list. Open r3 at index 2; r1 is then deleted from behind the modal,
    // putting r3 at index 1; then r3 itself is deleted, leaving three rows.
    // Resolving from the fresh index 1 lands on r4, which is the render
    // that took r3's place. Resolving from the stale index 2 lands on r5
    // and silently skips one.
    const view = mount(rows("r1", "r2", "r3", "r4", "r5"));

    act(() => view.result.current.open("r3"));
    view.rerender(rows("r2", "r3", "r4", "r5"));
    expect(view.result.current.index).toBe(1);

    view.rerender(rows("r2", "r4", "r5"));

    expect(view.result.current.record?.id).toBe("r4");
  });

  it("closes on request, and can be reopened", () => {
    const { result } = mount(rows("r1", "r2"));

    act(() => result.current.open("r2"));
    act(() => result.current.close());
    expect(result.current.record).toBeNull();

    act(() => result.current.open("r1"));
    expect(result.current.record?.id).toBe("r1");
  });

  it("ignores a request to open a render that is not in the list", () => {
    // A stale id must not put the modal up on nothing.
    const { result } = mount(rows("r1"));

    act(() => result.current.open("gone"));

    expect(result.current.record).toBeNull();
  });
});
