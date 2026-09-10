import { fireEvent, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { RenderRecord } from "@/api/types";
import { RenderDetailPage } from "@/features/renders/RenderDetailPage";
import { shortRunId } from "@/format";
import { makeRenderRecord, makeTopicDetail } from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

const RUN_ID = "20260829T090000Z";
const RENDER_ID = "render-1";

function serve(record: RenderRecord = makeRenderRecord()) {
  server.use(
    http.get("/api/renders/:renderId", () => HttpResponse.json(record)),
    http.get("/api/runs/:runId/topics/:topicId", () =>
      HttpResponse.json(makeTopicDetail({ label: "Airport cat" })),
    ),
  );
}

function renderPage() {
  return renderWithProviders(<RenderDetailPage />, {
    route: `/runs/${RUN_ID}/renders/${RENDER_ID}`,
    path: "/runs/:runId/renders/:renderId",
  });
}

describe("RenderDetailPage", () => {
  it("shows the PNG at full size, not the thumbnail", async () => {
    serve();

    renderPage();

    expect(await screen.findByRole("img")).toHaveAttribute(
      "src",
      `/api/renders/${RENDER_ID}/image?size=full`,
    );
  });

  it("breadcrumbs through the topic to the template", async () => {
    serve(makeRenderRecord({ templateId: "drake" }));

    renderPage();

    const crumb = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumb).getByRole("link", { name: "Topics" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(
      await within(crumb).findByRole("link", { name: "Airport cat" }),
    ).toHaveAttribute("href", `/topics/${RUN_ID}/topic-1`);
    expect(within(crumb).getByText("drake")).toBeInTheDocument();
  });

  it("chips the template and the provenance", async () => {
    serve(makeRenderRecord({ templateId: "drake" }));

    renderPage();

    const chips = await screen.findByTestId("chips");
    expect(within(chips).getByText("drake")).toBeInTheDocument();
    expect(within(chips).getByText("auto")).toBeInTheDocument();
  });

  it("lays out one block per caption slot, with the slot's real name", async () => {
    serve(
      makeRenderRecord({
        captionSlots: {
          rejected: "Filing an incident report",
          preferred: "Becoming the incident",
        },
      }),
    );

    renderPage();

    expect(await screen.findByText("rejected")).toBeInTheDocument();
    expect(screen.getByText("Filing an incident report")).toBeInTheDocument();
    expect(screen.getByText("preferred")).toBeInTheDocument();
    expect(screen.getByText("Becoming the incident")).toBeInTheDocument();
  });

  it("explains the model's choice on an auto render", async () => {
    serve(makeRenderRecord({ rationale: "Two panels, one reversal." }));

    renderPage();

    expect(await screen.findByText("Why this template")).toBeInTheDocument();
    expect(screen.getByText("Two panels, one reversal.")).toBeInTheDocument();
  });

  it("says a hand-written render was hand-written, and explains nothing", async () => {
    // The AutoOrigin/ManualOrigin split is what makes this a presence check
    // rather than an empty-string check: a manual render has no rationale
    // field at all.
    serve(makeRenderRecord({ rationale: null }));

    renderPage();

    expect(await screen.findByText("written by hand")).toBeInTheDocument();
    expect(screen.queryByText("Why this template")).not.toBeInTheDocument();
    expect(screen.getByText("manual")).toBeInTheDocument();
  });

  it("offers the PNG for download", async () => {
    serve();

    renderPage();

    const download = await screen.findByRole("link", { name: "Download PNG" });
    expect(download).toHaveAttribute("href", `/api/renders/${RENDER_ID}/image?size=full`);
    expect(download).toHaveAttribute("download");
  });

  it("reports the image's real dimensions once it has loaded", async () => {
    // The contract carries no width, height or byte size for a render, so
    // the page reads what the browser decoded rather than claiming numbers
    // nothing sent it.
    serve();

    renderPage();

    const image = await screen.findByRole("img");
    Object.defineProperty(image, "naturalWidth", { value: 1180, configurable: true });
    Object.defineProperty(image, "naturalHeight", { value: 1180, configurable: true });
    fireEvent.load(image);

    expect(await screen.findByText(/1180×1180/)).toBeInTheDocument();
  });

  it("carries the run id and created time in its metadata line", async () => {
    // Both parts, on the same element. Asserting only that the run id
    // appears somewhere would pass with the timestamp dropped from the
    // joined line entirely.
    serve(makeRenderRecord({ createdAt: "2026-08-29T14:31:00Z" }));

    renderPage();

    const line = await screen.findByText(new RegExp(RUN_ID));
    expect(line).toHaveTextContent("14:31");
  });

  it("shows a styled failed state, not a broken image, when the PNG is gone", async () => {
    // The database is authoritative for whether a render exists — a row
    // whose PNG has been deleted out from under it is a failed tile, not a
    // native broken-image icon, and there is nothing to download.
    serve();

    renderPage();

    const image = await screen.findByRole("img");
    fireEvent.error(image);

    expect(
      await screen.findByText(`Render ${RENDER_ID} has no image on disk`),
    ).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Download PNG" }),
    ).not.toBeInTheDocument();
  });

  it("shortens a long render id in the missing-image message", async () => {
    // This is the one screen built to be deep-linked, so the most likely to
    // be read by someone who did not arrive from a tile carrying its own
    // short label — but a full 32-character id is still noise, not an
    // identifier a person can hold onto.
    const longId = "78b729fb698648339998828d14f29c45";
    serve(makeRenderRecord({ id: longId }));

    renderPage();

    const image = await screen.findByRole("img");
    fireEvent.error(image);

    expect(
      await screen.findByText(`Render ${shortRunId(longId)} has no image on disk`),
    ).toBeInTheDocument();
    expect(screen.queryByText(longId)).not.toBeInTheDocument();
  });

  it("says which render is missing rather than showing an empty frame", async () => {
    server.use(
      http.get("/api/renders/:renderId", () =>
        HttpResponse.json({ detail: "No such render" }, { status: 404 }),
      ),
    );

    renderPage();

    expect(await screen.findByText("No such render.")).toBeInTheDocument();
  });
});
