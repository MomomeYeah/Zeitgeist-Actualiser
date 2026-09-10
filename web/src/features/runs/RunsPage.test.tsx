import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { RunsPage } from "@/features/runs/RunsPage";
import {
  makeActiveRuns,
  makeRunDetail,
  makeRunPage,
  makeRunSummary,
  makeStageRecord,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

function servePage(page = makeRunPage()) {
  server.use(
    http.get("/api/runs", () => HttpResponse.json(page)),
    http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
  );
}

describe("RunsPage", () => {
  it("draws a row per run, truncating the id the way the design does", async () => {
    servePage(
      makeRunPage([
        makeRunSummary({ runId: "20260829T090000Z" }),
        makeRunSummary({ runId: "20260828T090000Z" }),
      ]),
    );

    renderWithProviders(<RunsPage />);

    expect(await screen.findByText("…829T090000Z")).toBeInTheDocument();
    expect(screen.getByText("…828T090000Z")).toBeInTheDocument();
  });

  it("joins the topic titles with the design's separator", async () => {
    servePage(
      makeRunPage([makeRunSummary({ labels: ["Airport cat", "Stadium rat"] })]),
    );

    renderWithProviders(<RunsPage />);

    expect(await screen.findByText("Airport cat · Stadium rat")).toBeInTheDocument();
  });

  it("reports the fan-out and what survived it", async () => {
    servePage(makeRunPage([makeRunSummary({ trendsFound: 25, topicsKept: 5 })]));

    renderWithProviders(<RunsPage />);

    expect(await screen.findByText("25 trends → 5 kept")).toBeInTheDocument();
    expect(screen.getByText("18 phrases")).toBeInTheDocument();
  });

  it("links each row to that run's detail page", async () => {
    servePage(makeRunPage([makeRunSummary({ runId: "20260829T090000Z" })]));

    renderWithProviders(<RunsPage />);

    const list = await screen.findByRole("list");
    expect(within(list).getByRole("link")).toHaveAttribute(
      "href",
      "/runs/20260829T090000Z",
    );
  });

  it("draws at most three thumbnails and counts the rest", async () => {
    servePage(
      makeRunPage([makeRunSummary({ renderIds: ["a", "b", "c", "d", "e"] })]),
    );

    renderWithProviders(<RunsPage />);

    expect(await screen.findAllByRole("img")).toHaveLength(3);
    expect(screen.getByText("+2")).toBeInTheDocument();
  });

  it("draws no overflow tile when three renders fit exactly", async () => {
    servePage(makeRunPage([makeRunSummary({ renderIds: ["a", "b", "c"] })]));

    renderWithProviders(<RunsPage />);

    expect(await screen.findAllByRole("img")).toHaveLength(3);
    expect(screen.queryByText(/^\+/)).not.toBeInTheDocument();
  });

  it("shows the error, what survived and the resume affordance on a failure", async () => {
    servePage(
      makeRunPage([
        makeRunSummary({
          status: "failed",
          finishedAt: null,
          error: {
            kind: "RenderError",
            message: "3 of 5 briefs written",
            stage: "generate",
          },
        }),
      ]),
    );

    renderWithProviders(<RunsPage />);

    expect(
      await screen.findByText("RenderError in generate — 3 of 5 briefs written"),
    ).toBeInTheDocument();
    expect(screen.getByText("ranked checkpoint intact")).toBeInTheDocument();
    expect(screen.getByText("resume from generate ↗")).toBeInTheDocument();
  });

  it("offers a re-run rather than a resume when ingest returned nothing", async () => {
    // A source outage writes no checkpoint, so `resume_stage` is None and
    // the UI must not offer a resume it cannot honour.
    servePage(
      makeRunPage([
        makeRunSummary({
          status: "failed",
          finishedAt: null,
          error: {
            kind: "SourceError",
            message: "no trends returned",
            stage: "ingest",
          },
        }),
      ]),
    );

    renderWithProviders(<RunsPage />);

    expect(
      await screen.findByText("SourceError in ingest — no trends returned"),
    ).toBeInTheDocument();
    expect(screen.getByText("nothing written")).toBeInTheDocument();
    expect(screen.getByText("re-run ↗")).toBeInTheDocument();
    expect(screen.queryByText(/resume from/)).not.toBeInTheDocument();
  });

  it("counts the page it is showing, not an archive total it was not sent", async () => {
    // The aborted run is what makes this test bite. `RunStatus` has five
    // members and the line names whichever are present, so a counter that
    // grouped everything-not-ok under "failed" would call an aborted run a
    // failure, and one that only counted "ok" and "failed" would print
    // four runs adding up to three.
    servePage(
      makeRunPage([
        makeRunSummary({ runId: "a" }),
        makeRunSummary({ runId: "b" }),
        makeRunSummary({
          runId: "c",
          status: "failed",
          error: { kind: "RenderError", message: "boom", stage: "generate" },
        }),
        makeRunSummary({ runId: "d", status: "aborted", finishedAt: null }),
      ]),
    );

    renderWithProviders(<RunsPage />);

    expect(
      await screen.findByText("4 shown · 2 ok · 1 failed · 1 aborted · bluesky"),
    ).toBeInTheDocument();
  });

  it("names every source when a page mixes them", async () => {
    servePage(
      makeRunPage([
        makeRunSummary({ runId: "a", config: { sources: ["bluesky"] } }),
        makeRunSummary({ runId: "b", config: { sources: ["lemmy"] } }),
      ]),
    );

    renderWithProviders(<RunsPage />);

    expect(await screen.findByText(/bluesky · lemmy$/)).toBeInTheDocument();
  });

  it("explains the app when nothing has ever run", async () => {
    servePage(makeRunPage([]));

    renderWithProviders(<RunsPage />);

    expect(
      await screen.findByRole("heading", { name: "Nothing has run yet" }),
    ).toBeInTheDocument();
  });

  it("reports a server failure rather than an empty list", async () => {
    // An empty list and a broken server look identical without this, and
    // "nothing has run yet" would be a lie about a database that is fine.
    server.use(
      http.get("/api/runs", () =>
        HttpResponse.json({ detail: "database is locked" }, { status: 500 }),
      ),
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );

    renderWithProviders(<RunsPage />);

    expect(await screen.findByText(/database is locked/)).toBeInTheDocument();
    expect(screen.queryByText("Nothing has run yet")).not.toBeInTheDocument();
  });

  it("marks a failed row so the whole row reads as failed, not just its pill", async () => {
    // The design gives a failed row its own `contrast` border. Asserting
    // the pill's text would pass with that border removed, because the
    // pill draws itself from `run.status` and knows nothing about the row.
    servePage(
      makeRunPage([
        makeRunSummary({
          runId: "20260829T090000Z",
          status: "failed",
          error: { kind: "RenderError", message: "boom", stage: "generate" },
        }),
        makeRunSummary({ runId: "20260828T090000Z", status: "ok" }),
      ]),
    );

    renderWithProviders(<RunsPage />);

    const rows = await screen.findAllByRole("link");
    const failedRow = rows.find((row) => row.textContent?.includes("boom"));
    const okRow = rows.find((row) => row !== failedRow);

    expect(failedRow?.className).toContain("failed");
    expect(okRow?.className).not.toContain("failed");
  });

  it("pins the in-flight run above the list", async () => {
    server.use(
      http.get("/api/runs", () =>
        HttpResponse.json(makeRunPage([makeRunSummary({ runId: "20260829T090000Z" })])),
      ),
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: "20260829T140200Z" })),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({
            runId: "20260829T140200Z",
            status: "running",
            stages: [
              makeStageRecord({ stage: "ingest" }),
              makeStageRecord({
                stage: "analyse",
                status: "running",
                finishedAt: null,
                done: 17,
                total: 25,
              }),
            ],
          }),
        ),
      ),
    );

    renderWithProviders(<RunsPage />);

    expect(await screen.findByText("RUNNING")).toBeInTheDocument();
    expect(screen.getByText("20260829T140200Z")).toBeInTheDocument();

    // Above the list, which is the whole point of the card: a run in
    // flight is the thing you came to look at. Asserting only that it
    // rendered would pass with it moved to the foot of the page.
    const card = screen.getByRole("link", { name: /20260829T140200Z/ });
    const list = screen.getByRole("list");
    expect(
      card.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    // Four segments, filled from the stage records — `RunRow` draws no
    // progressbar, so these are the card's own. 17 of 25 is 68%: the
    // fixture's counters have to reach the DOM as a width, or the card
    // says a stage is running without saying how far in.
    expect(
      screen.getAllByRole("progressbar").map((bar) => bar.getAttribute("aria-valuenow")),
    ).toEqual(["100", "68", "0", "0"]);
  });

  it("draws no in-flight card while nothing is running", async () => {
    server.use(
      http.get("/api/runs", () => HttpResponse.json(makeRunPage())),
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: null })),
      ),
    );

    renderWithProviders(<RunsPage />);
    await screen.findByRole("heading", { name: "Runs" });

    expect(screen.queryByText("RUNNING")).not.toBeInTheDocument();
  });

  it("offers New run from the header", async () => {
    server.use(
      http.get("/api/runs", () => HttpResponse.json(makeRunPage())),
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );

    renderWithProviders(<RunsPage />);

    expect(await screen.findByRole("link", { name: "New run" })).toHaveAttribute(
      "href",
      "/runs/new",
    );
  });

  it("offers New run from the empty state, which is the only thing to do there", async () => {
    server.use(
      http.get("/api/runs", () => HttpResponse.json(makeRunPage([]))),
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );

    renderWithProviders(<RunsPage />);

    expect(await screen.findByText("Nothing has run yet")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "New run" })).toHaveLength(2);
  });
});
