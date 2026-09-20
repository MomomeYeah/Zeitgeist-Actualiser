import userEvent from "@testing-library/user-event";
import { act, createEvent, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { useState } from "react";
import { useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { GenerationRequest, RenderRecord } from "@/api/types";
import { RenderGrid } from "@/features/topics/RenderGrid";
import { makeRenderRecord } from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

// `makeRenderRecord`'s own run, so a tile's link and the grid's hint agree.
const RUN_ID = "20260829T090000Z";

function renderGrid(renders: RenderRecord[], pending: GenerationRequest[] = []) {
  return renderWithProviders(
    <RenderGrid renders={renders} runId={RUN_ID} pending={pending} />,
  );
}

/** Every render id the grid sends a DELETE for, in order. */
function recordDeletes(): string[] {
  const deleted: string[] = [];
  server.use(
    http.delete("/api/renders/:renderId", ({ params }) => {
      deleted.push(String(params.renderId));
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return deleted;
}

/** Where the router is, for the test that asserts the modal did not move it. */
function Where() {
  const { pathname } = useLocation();
  return <p>{`at ${pathname}`}</p>;
}

describe("RenderGrid", () => {
  it("draws a ready render as its image, linked to the full-size view", () => {
    // Hand-written rather than the factory's default `auto`, so a footer
    // that printed "auto" without reading the row's provenance would fail.
    renderGrid([makeRenderRecord({ id: "r1", templateId: "drake", rationale: null })]);

    expect(screen.getByAltText("drake meme").closest("a")).toHaveAttribute(
      "href",
      `/runs/${RUN_ID}/renders/r1`,
    );
    expect(screen.getByText("drake · manual")).toBeInTheDocument();
  });

  it("draws a generating model render as a brief being written, with no image yet", () => {
    renderGrid([makeRenderRecord({ id: "g1", status: "generating" })]);

    expect(screen.getByText("writing brief…")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("says a generating hand-written render is going straight to the renderer", () => {
    // The handoff draws "writing brief…" on a manual tile. A hand-written
    // render has no brief to write.
    renderGrid([makeRenderRecord({ id: "g1", status: "generating", rationale: null })]);

    expect(screen.getByText("rendering…")).toBeInTheDocument();
    expect(screen.queryByText("writing brief…")).not.toBeInTheDocument();
  });

  it("names no template on a render the model has not chosen one for yet", () => {
    renderGrid([
      makeRenderRecord({
        id: "g1",
        status: "generating",
        templateId: null,
        captionSlots: {},
      }),
    ]);

    expect(screen.getByText("choosing… · auto")).toBeInTheDocument();
  });

  it("keeps a failed render's tile, carrying the server's reason", () => {
    // Per the handoff: a failed render keeps its tile rather than vanishing.
    renderGrid([
      makeRenderRecord({
        id: "f1",
        status: "failed",
        error: "caption for rejected overflows its box",
      }),
    ]);

    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("caption for rejected overflows its box")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("names no template on a failed render whose brief failed before choosing one", () => {
    // Task 1's other template-less state. "null · auto" is not a label.
    renderGrid([
      makeRenderRecord({
        id: "f1",
        status: "failed",
        templateId: null,
        captionSlots: {},
        error: "the model is down",
      }),
    ]);

    expect(screen.getByText("no template · auto")).toBeInTheDocument();
  });

  it("counts what is ready, generating and failed above the grid", () => {
    // Three counts that differ — 3 ready; 1 generating row plus 1 meme a
    // request in flight asked for, so 2 generating; 1 failed — so no count
    // can be computed from the wrong status, and a placeholder total that
    // replaced the generating rows instead of adding to them reads 1.
    renderGrid(
      [
        makeRenderRecord({ id: "r1" }),
        makeRenderRecord({ id: "r2" }),
        makeRenderRecord({ id: "r3" }),
        makeRenderRecord({ id: "g1", status: "generating" }),
        makeRenderRecord({ id: "f1", status: "failed", error: "overflow" }),
      ],
      [{ mode: "llm", template_id: null, count: 1 }],
    );

    expect(
      screen.getByText("3 from …829T090000Z · 2 generating · 1 failed"),
    ).toBeInTheDocument();
  });

  it("draws a placeholder for every meme a request in flight asked for", () => {
    // "Both buttons immediately append placeholder tiles", per the handoff:
    // three asked for is three tiles, before the server has answered.
    renderGrid([], [{ mode: "llm", template_id: null, count: 3 }]);

    expect(screen.getAllByText("writing brief…")).toHaveLength(3);
    expect(screen.getByText("0 from …829T090000Z · 3 generating")).toBeInTheDocument();
  });

  it("offers no cancel on a placeholder, which has no row to cancel yet", () => {
    renderGrid(
      [],
      [
        {
          mode: "manual",
          template_id: "drake",
          caption_slots: { rejected: "a", preferred: "b" },
        },
      ],
    );

    expect(screen.getByText("drake · manual")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel render" })).not.toBeInTheDocument();
  });

  it("says nothing has rendered yet, in place of an empty grid", () => {
    renderGrid([]);

    expect(
      screen.getByText("Nothing rendered yet — use the panel above"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/ from …/)).not.toBeInTheDocument();
  });

  it("asks before deleting a ready render, and deletes only on yes", async () => {
    const deleted = recordDeletes();
    const user = userEvent.setup();
    renderGrid([makeRenderRecord({ id: "r1" })]);

    await user.click(screen.getByRole("button", { name: "Delete render" }));
    expect(screen.getByText("Delete this render?")).toBeInTheDocument();
    expect(deleted).toEqual([]);

    await user.click(screen.getByRole("button", { name: "yes" }));
    await waitFor(() => expect(deleted).toEqual(["r1"]));
  });

  it("cancels a generating render at once, without asking", async () => {
    // Nothing has been made yet, so there is nothing to lose but the wait.
    const deleted = recordDeletes();
    const user = userEvent.setup();
    renderGrid([makeRenderRecord({ id: "g1", status: "generating" })]);

    await user.click(screen.getByRole("button", { name: "Cancel render" }));

    await waitFor(() => expect(deleted).toEqual(["g1"]));
    expect(screen.queryByText("Delete this render?")).not.toBeInTheDocument();
  });

  it("dismisses a failed render at once, without asking", async () => {
    // No image to lose: the tile only carries a reason.
    const deleted = recordDeletes();
    const user = userEvent.setup();
    renderGrid([makeRenderRecord({ id: "f1", status: "failed", error: "overflow" })]);

    await user.click(screen.getByRole("button", { name: "Dismiss render" }));

    await waitFor(() => expect(deleted).toEqual(["f1"]));
  });

  it("dims a tile while its deletion is on its way", async () => {
    // One click must not become two DELETEs, and the tile must say it heard.
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.delete("/api/renders/:renderId", async () => {
        await held;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderGrid([makeRenderRecord({ id: "g1", status: "generating" })]);

    await user.click(screen.getByRole("button", { name: "Cancel render" }));

    expect(await screen.findByText("deleting…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel render" })).not.toBeInTheDocument();
    release();
  });

  it("keeps a tile the server would not delete, with the server's reason", async () => {
    server.use(
      http.delete("/api/renders/:renderId", () =>
        HttpResponse.json({ detail: "Permission denied: renders/r1.png" }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderGrid([makeRenderRecord({ id: "r1" })]);

    await user.click(screen.getByRole("button", { name: "Delete render" }));
    await user.click(screen.getByRole("button", { name: "yes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Permission denied: renders/r1.png",
    );
    expect(screen.getByAltText("drake meme")).toBeInTheDocument();
  });

  it.each([
    {
      state: "generating",
      render: makeRenderRecord({ id: "x1", status: "generating" }),
      cross: "Cancel render",
    },
    {
      state: "failed",
      render: makeRenderRecord({ id: "x1", status: "failed", error: "overflow" }),
      cross: "Dismiss render",
    },
  ])("says why a $state tile the server would not delete is still there", async ({ render, cross }) => {
    // Each branch of RenderTile draws the delete error itself — the
    // generating one outside GeneratingTile — so each can drop it alone.
    server.use(
      http.delete("/api/renders/:renderId", () =>
        HttpResponse.json({ detail: "Permission denied: renders/x1.png" }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderGrid([render]);

    await user.click(screen.getByRole("button", { name: cross }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Permission denied: renders/x1.png",
    );
  });

  it("opens a render in a modal rather than navigating away", async () => {
    const user = userEvent.setup();
    renderGrid([makeRenderRecord({ id: "r1", templateId: "drake" })]);

    await user.click(screen.getByAltText("drake meme"));

    expect(await screen.findByRole("dialog", { name: "drake" })).toBeInTheDocument();
  });

  it("leaves the address bar on the topic while the modal is open", async () => {
    // The modal is component state, not a route: browsing a grid of memes
    // should not write a history entry per glance, and Copy link is what
    // hands out the permanent URL.
    //
    // The break this catches is not only that decision being reversed. The
    // tile is a real `<Link>`, so an `onOpen` that opens the modal without
    // cancelling the event leaves the router navigating underneath it —
    // the modal appears over a screen that is already unmounting. Dropping
    // `event.preventDefault()` fails here and nowhere else.
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <RenderGrid
          renders={[makeRenderRecord({ id: "r1", templateId: "drake" })]}
          runId={RUN_ID}
          pending={[]}
        />
        <Where />
      </>,
      { route: "/topics/20260829T090000Z/topic-1" },
    );

    await user.click(screen.getByAltText("drake meme"));

    expect(await screen.findByRole("dialog", { name: "drake" })).toBeInTheDocument();
    expect(
      screen.getByText("at /topics/20260829T090000Z/topic-1"),
    ).toBeInTheDocument();
  });

  it("opens the record the grid already holds, without asking the server for it", async () => {
    // The design turns on this: the topic screen is already holding every
    // field the body needs, so a click opens on the current frame with no
    // spinner and no second request. A `RenderDetail` that fetched by id
    // would satisfy every other case in this file, because they all await.
    const asked: string[] = [];
    const watch = ({ request }: { request: Request }) => {
      asked.push(request.url);
    };
    server.events.on("request:start", watch);
    try {
      const user = userEvent.setup();
      renderGrid([makeRenderRecord({ id: "r1", templateId: "drake" })]);

      await user.click(screen.getByAltText("drake meme"));

      expect(screen.getByRole("dialog", { name: "drake" })).toBeInTheDocument();
      expect(asked).toEqual([]);
    } finally {
      server.events.removeListener("request:start", watch);
    }
  });

  it("shows the open render's current row, not the copy that was on screen at click time", async () => {
    // The grid holds the open render's id rather than the record, because
    // the row behind it changes — a refetch landing, a generating render
    // turning ready — and a copy taken at click time would leave the modal
    // on a frame the grid itself has already moved past.
    let refresh: (rationale: string) => void = () => undefined;
    function Harness() {
      const [rationale, setRationale] = useState("Two panels, one reversal.");
      refresh = setRationale;
      return (
        <RenderGrid
          renders={[makeRenderRecord({ id: "r1", templateId: "drake", rationale })]}
          runId={RUN_ID}
          pending={[]}
        />
      );
    }
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByAltText("drake meme"));
    expect(await screen.findByText("Two panels, one reversal.")).toBeInTheDocument();

    act(() => refresh("Chose the reversal after all."));

    expect(screen.getByText("Chose the reversal after all.")).toBeInTheDocument();
    expect(screen.queryByText("Two panels, one reversal.")).not.toBeInTheDocument();
  });

  it.each([
    { modifier: "⌘", init: { metaKey: true } },
    { modifier: "ctrl", init: { ctrlKey: true } },
    { modifier: "shift", init: { shiftKey: true } },
    { modifier: "alt", init: { altKey: true } },
  ])("leaves a $modifier-click to the browser rather than opening the modal", ({ init }) => {
    // ⌘, ctrl and shift on a link mean "somewhere else" and alt means
    // download. Cancelling the event is *how* those get swallowed, so that
    // is asserted alongside the absent modal: a handler that called
    // preventDefault before consulting the modifiers would open no modal
    // either, and would still have made the tile's href a promise it does
    // not keep. All four are exercised because dropping any one of them
    // from `opensHere` must fail something.
    //
    // The document listener does two jobs. It reads the app's decision
    // after the tile's own handler has run and before the anchor's default
    // action — React delegates at the root container, which is inside
    // `document.body`, so this runs second. Then it cancels the event
    // itself: jsdom cannot navigate, and letting an unprevented click on an
    // `<a href>` through makes it log `Not implemented: navigation`, which
    // is noise in an otherwise clean run.
    renderGrid([makeRenderRecord({ id: "r1", templateId: "drake" })]);
    const tile = screen.getByAltText("drake meme");

    let appPrevented: boolean | undefined;
    const watch = (event: MouseEvent) => {
      appPrevented = event.defaultPrevented;
      event.preventDefault();
    };
    document.addEventListener("click", watch);
    try {
      fireEvent(
        tile,
        createEvent.click(tile, {
          bubbles: true,
          cancelable: true,
          button: 0,
          ...init,
        }),
      );
    } finally {
      document.removeEventListener("click", watch);
    }

    expect(appPrevented).toBe(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes the modal without touching the grid behind it", async () => {
    const user = userEvent.setup();
    renderGrid([
      makeRenderRecord({ id: "r1", templateId: "drake" }),
      makeRenderRecord({ id: "r2", templateId: "two_buttons" }),
    ]);

    await user.click(screen.getByAltText("drake meme"));
    expect(await screen.findByRole("dialog", { name: "drake" })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByAltText("drake meme")).toBeInTheDocument();
    expect(screen.getByAltText("two_buttons meme")).toBeInTheDocument();
  });

  it("deletes the render the modal was opened on, and no other", async () => {
    // `renderGrid` mounts `RenderGrid` with a fixed `renders` prop, so the
    // deleted row does not leave this harness, the modal does not close,
    // and focus does not move — the cache write that removes the row, and
    // the effect that follows it, belong to `RenderGrid` itself and are
    // exercised where they can actually happen: `TopicDetailPage.test.tsx`.
    // What this component owns, and what is honest to assert here, is that
    // the DELETE went out for the render the modal was opened on and left
    // the other tile alone.
    const deleted = recordDeletes();
    const user = userEvent.setup();
    renderGrid([
      makeRenderRecord({ id: "r1", templateId: "drake" }),
      makeRenderRecord({ id: "r2", templateId: "two_buttons" }),
    ]);

    await user.click(screen.getByAltText("drake meme"));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }),
    );
    await user.click(screen.getByRole("button", { name: "yes" }));

    await waitFor(() => expect(deleted).toEqual(["r1"]));
    expect(screen.getByAltText("two_buttons meme")).toBeInTheDocument();
  });
});
