import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { ACTIVE_POLL_MS, useTopicIndex } from "@/api/queries";
import { Sidebar } from "@/app/Sidebar";
import { RunsPage } from "@/features/runs/RunsPage";
import { FakeEventSource } from "@/test/eventsource";
import {
  makeActiveRuns,
  makeRunDetail,
  makeRunPage,
  makeStageRecord,
  makeTopicIndex,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

/** Mounts the topics index query, which is all the invalidation test needs. */
function TopicsIndexProbe() {
  useTopicIndex();
  return null;
}

describe("Sidebar", () => {
  it("offers Topics, Runs and Settings, in that order", async () => {
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );

    renderWithProviders(<Sidebar />);

    const links = await screen.findAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Topics",
      "Runs",
      "Settings",
    ]);
  });

  it("shows no in-flight card while nothing is running", async () => {
    server.use(
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: null })),
      ),
    );

    renderWithProviders(<Sidebar />);
    await screen.findByRole("link", { name: "Runs" });

    expect(screen.queryByText("IN FLIGHT")).not.toBeInTheDocument();
  });

  it("names the running stage while one is", async () => {
    server.use(
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
              }),
            ],
          }),
        ),
      ),
    );

    renderWithProviders(<Sidebar />);

    expect(await screen.findByText("IN FLIGHT")).toBeInTheDocument();
    expect(screen.getByText(/analyse/)).toBeInTheDocument();
  });

  it("links the card to the run it is about", async () => {
    server.use(
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: "20260829T140200Z" })),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({ runId: "20260829T140200Z", status: "running" }),
        ),
      ),
    );

    renderWithProviders(<Sidebar />);

    const card = await screen.findByRole("link", { name: /IN FLIGHT/ });
    expect(card).toHaveAttribute("href", "/runs/20260829T140200Z");
  });

  it("moves its stage on as the run does, with no stream open", async () => {
    // Found by the final review. The SSE tick is what refreshes a run's
    // detail, and only run detail opens a stream — so anywhere else the
    // card froze at the stage it first loaded. The active poll refreshes
    // `["runs", "active"]` alone, which names the run but not its stage.
    let detailCalls = 0;
    server.use(
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: "20260829T140200Z" })),
      ),
      http.get("/api/runs/:runId", () => {
        detailCalls += 1;
        return HttpResponse.json(
          makeRunDetail({
            runId: "20260829T140200Z",
            status: "running",
            stages:
              detailCalls === 1
                ? [makeStageRecord({ stage: "ingest", status: "running", finishedAt: null })]
                : [
                    makeStageRecord({ stage: "ingest" }),
                    makeStageRecord({
                      stage: "analyse",
                      status: "running",
                      finishedAt: null,
                    }),
                  ],
          }),
        );
      }),
    );

    renderWithProviders(<Sidebar />);
    expect(await screen.findByText(/^ingest · /)).toBeInTheDocument();

    expect(
      await screen.findByText(/^analyse · /, {}, { timeout: ACTIVE_POLL_MS * 2 }),
    ).toBeInTheDocument();
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("refreshes the runs list and the topics index when the run in flight ends", async () => {
    // A finished run otherwise kept reading "running" in the Runs list, and
    // the Topics index never picked up what it produced, until a stale time
    // ran out. The sidebar is mounted on every screen, which makes it the
    // one place that can notice the end wherever someone is looking.
    let activeCalls = 0;
    let listCalls = 0;
    let topicsCalls = 0;
    server.use(
      http.get("/api/runs/active", () => {
        activeCalls += 1;
        return HttpResponse.json(
          makeActiveRuns({ current: activeCalls === 1 ? "20260829T140200Z" : null }),
        );
      }),
      http.get("/api/runs", () => {
        listCalls += 1;
        return HttpResponse.json(makeRunPage());
      }),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({ runId: "20260829T140200Z", status: "running" }),
        ),
      ),
      http.get("/api/topics", () => {
        topicsCalls += 1;
        return HttpResponse.json(makeTopicIndex());
      }),
    );

    renderWithProviders(
      <>
        <Sidebar />
        <RunsPage />
        <TopicsIndexProbe />
      </>,
    );
    expect(await screen.findByText("IN FLIGHT")).toBeInTheDocument();
    expect(listCalls).toBe(1);
    expect(topicsCalls).toBe(1);

    await waitFor(() => expect(listCalls).toBe(2), { timeout: ACTIVE_POLL_MS * 2 });
    await waitFor(() => expect(topicsCalls).toBe(2));
    expect(screen.queryByText("IN FLIGHT")).not.toBeInTheDocument();
  });
});
