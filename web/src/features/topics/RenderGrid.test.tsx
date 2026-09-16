import userEvent from "@testing-library/user-event";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
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
});
