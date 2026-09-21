import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { RenderDetail } from "@/features/renders/RenderDetail";
import { makeRenderRecord } from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

function draw(overrides: Parameters<typeof makeRenderRecord>[0] = {}) {
  const onDeleted = vi.fn();
  const view = renderWithProviders(
    <RenderDetail
      record={makeRenderRecord({ id: "r1", templateId: "drake", ...overrides })}
      onDeleted={onDeleted}
    />,
  );
  return { onDeleted, user: userEvent.setup(), view };
}

/** Every render id a DELETE went out for, in order. */
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

describe("RenderDetail", () => {
  it("draws a failed render's reason in full, where there is room to read it", () => {
    // The tile now says only that the render failed, so this is the only
    // place the reason can be read. A panel that showed a broken image, or
    // the tile's truncated line, would lose it.
    draw({
      status: "failed",
      error: "caption for rejected overflows its box by 42px",
    });

    expect(
      screen.getByText("caption for rejected overflows its box by 42px"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("says a failed render recorded no reason, rather than nothing at all", () => {
    draw({ status: "failed", error: null });

    expect(screen.getByText("No reason was recorded.")).toBeInTheDocument();
  });

  it("offers no download for a render that has no image", () => {
    // There is no PNG behind the link, so offering it is an error waiting
    // to be clicked.
    draw({ status: "failed", error: "overflow" });

    expect(screen.queryByText("Download PNG")).not.toBeInTheDocument();
    // Copy link stays: a failure is a thing worth sending someone.
    expect(screen.getByRole("button", { name: "Copy link" })).toBeInTheDocument();
  });

  it("dismisses a failed render at once, without asking", async () => {
    // Matching the tile's own ✕: there is no image to lose, so a
    // confirmation is a click for nothing.
    const deleted = recordDeletes();
    const { user } = draw({ status: "failed", error: "overflow" });

    await user.click(screen.getByRole("button", { name: "Dismiss" }));

    await waitFor(() => expect(deleted).toEqual(["r1"]));
    expect(screen.queryByText("Delete this render?")).not.toBeInTheDocument();
  });

  it("draws a generating render as a brief being written", () => {
    draw({ status: "generating" });

    expect(screen.getByText("writing brief…")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByText("Download PNG")).not.toBeInTheDocument();
  });

  it("says a generating hand-written render is going straight to the renderer", () => {
    // `rationale: null` is the factory's manual render. It has no brief to
    // write.
    draw({ status: "generating", rationale: null });

    expect(screen.getByText("rendering…")).toBeInTheDocument();
  });

  it("cancels a generating render at once, without asking", async () => {
    const deleted = recordDeletes();
    const { user } = draw({ status: "generating" });

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(deleted).toEqual(["r1"]));
  });

  it("draws no rationale heading for a render whose brief is not written yet", () => {
    // A generating auto row carries `rationale: ""`, and a heading over an
    // empty paragraph is worse than no heading.
    draw({ status: "generating", rationale: "" });

    expect(screen.queryByText("Why this template")).not.toBeInTheDocument();
  });

  it("still asks before deleting a ready render", async () => {
    // The one state with something to lose keeps its confirmation.
    const deleted = recordDeletes();
    const { user } = draw();

    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(screen.getByText("Delete this render?")).toBeInTheDocument();
    expect(deleted).toEqual([]);

    await user.click(screen.getByRole("button", { name: "yes" }));
    await waitFor(() => expect(deleted).toEqual(["r1"]));
  });

  it("offers no download for a ready render whose image will not load", () => {
    // The database is authoritative for whether a render exists, so a
    // missing PNG is a styled panel — and the download that would 404 goes
    // with it.
    draw();

    fireEvent.error(screen.getByRole("img", { name: "drake meme" }));

    // `shortRunId` leaves an id of 12 characters or fewer alone, and this
    // record's is "r1" (`web/src/format.ts`).
    expect(screen.getByText("Render r1 has no image on disk")).toBeInTheDocument();
    expect(screen.queryByText("Download PNG")).not.toBeInTheDocument();
  });
});
