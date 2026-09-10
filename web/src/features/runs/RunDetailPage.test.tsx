import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { RankedTopic, RunDetail } from "@/api/types";
import { RunDetailPage } from "@/features/runs/RunDetailPage";
import {
  makeRankedTopic,
  makeRunDetail,
  makeStageRecord,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

const RUN_ID = "20260829T090000Z";

function serve(detail: RunDetail, ranking: RankedTopic[]) {
  server.use(
    http.get("/api/runs/:runId", () => HttpResponse.json(detail)),
    http.get("/api/runs/:runId/topics", () => HttpResponse.json(ranking)),
  );
}

function renderPage() {
  return renderWithProviders(<RunDetailPage />, {
    route: `/runs/${RUN_ID}`,
    path: "/runs/:runId",
  });
}

describe("RunDetailPage", () => {
  it("shows the run id and the config it froze", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [makeRankedTopic()]);

    renderPage();

    expect(await screen.findByText(RUN_ID)).toBeInTheDocument();
    expect(
      screen.getByText(
        "bluesky · trend_limit 25 · posts_per_trend 30 · top_count 5 · claude-opus-5 · 6m 41s",
      ),
    ).toBeInTheDocument();
  });

  it("draws a card per stage with its artifact and size", async () => {
    serve(
      makeRunDetail({
        runId: RUN_ID,
        stages: [
          makeStageRecord({ stage: "ingest", payloadBytes: 1_363_148 }),
          makeStageRecord({ stage: "analyse", payloadBytes: 88_000 }),
          makeStageRecord({ stage: "evaluate", payloadBytes: 9_100 }),
          makeStageRecord({
            stage: "generate",
            payloadBytes: 4_100,
            summary: "3 of 5 rendered",
          }),
        ],
      }),
      [makeRankedTopic()],
    );

    renderPage();

    expect(await screen.findByText("evidence · 1.4 MB")).toBeInTheDocument();
    expect(screen.getByText("ranked · 9.1 kB")).toBeInTheDocument();
    // The pipeline's own words for a partially failed generate stage. This
    // is where partial failure is shown — see the plan's decision 7.
    expect(screen.getByText("3 of 5 rendered")).toBeInTheDocument();
  });

  it("draws a stage that never ran without a size it does not have", async () => {
    serve(
      makeRunDetail({
        runId: RUN_ID,
        stages: [
          makeStageRecord({ stage: "ingest" }),
          makeStageRecord({
            stage: "analyse",
            status: "failed",
            finishedAt: null,
            payloadBytes: null,
            summary: "DistilError",
          }),
        ],
      }),
      [],
    );

    renderPage();

    expect(await screen.findByText("topics · —")).toBeInTheDocument();
  });

  it("draws a card for a stage the run never reached at all", async () => {
    // `stages_for_run` returns only the stages that were recorded. A run
    // that died in analyse has no evaluate row, and the design draws four
    // cards regardless — the last two queued.
    serve(
      makeRunDetail({ runId: RUN_ID, stages: [makeStageRecord({ stage: "ingest" })] }),
      [],
    );

    renderPage();

    expect(await screen.findByText("generate")).toBeInTheDocument();
    expect(screen.getAllByText("queued")).toHaveLength(3);
  });

  it("ranks the topics and shows each one's scores", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({
        topicId: "t1",
        label: "Airport cat",
        finalRank: 1,
        trendScore: 0.91,
        memePotential: 0.86,
        finalScore: 0.895,
      }),
    ]);

    renderPage();

    expect(await screen.findByText("Airport cat")).toBeInTheDocument();
    expect(screen.getByText("trend 0.91 · meme 0.86")).toBeInTheDocument();
    expect(screen.getByText("final 0.895")).toBeInTheDocument();
  });

  it("shows the topic's own subline: status, posts and its top phrase", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({
        trendStatus: "saturating",
        postCount: 412,
        topPhrase: "absolute unit",
        topPhraseAuthors: 31,
      }),
    ]);

    renderPage();

    expect(
      await screen.findByText("saturating · 412 posts · “absolute unit” 31 authors"),
    ).toBeInTheDocument();
  });

  it("drops the phrase clause for a topic that had no recurring phrase", async () => {
    // `top_phrase` is null when the dossier found nothing above
    // phrase_min_authors. An empty quote would read as a phrase that is
    // literally nothing.
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ trendStatus: "cooling", postCount: 90, topPhrase: null }),
    ]);

    renderPage();

    expect(await screen.findByText("cooling · 90 posts")).toBeInTheDocument();
  });

  it("links each ranking row to that topic's detail page", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "topic-9" }),
    ]);

    renderPage();

    const rows = await screen.findAllByRole("link");
    expect(rows.some((link) => link.getAttribute("href") === `/topics/${RUN_ID}/topic-9`)).toBe(
      true,
    );
  });

  it("offers generate on a below-the-cut row instead of thumbnails", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "t1", finalRank: 1, aboveCut: true }),
      makeRankedTopic({
        topicId: "t2",
        finalRank: 6,
        aboveCut: false,
        renderCount: 0,
      }),
    ]);

    renderPage();

    expect(await screen.findByText("generate ↗")).toBeInTheDocument();
  });

  it("counts the rows below the cut", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "t1", finalRank: 1, aboveCut: true }),
      makeRankedTopic({ topicId: "t2", finalRank: 2, aboveCut: false }),
      makeRankedTopic({ topicId: "t3", finalRank: 3, aboveCut: false }),
    ]);

    renderPage();

    expect(await screen.findByText("2 more below the cut")).toBeInTheDocument();
  });

  it("says nothing about a cut when every topic is above it", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "t1", finalRank: 1, aboveCut: true }),
    ]);

    renderPage();

    expect(await screen.findByText("Airport cat")).toBeInTheDocument();
    expect(screen.queryByText(/below the cut/)).not.toBeInTheDocument();
  });

  it("says so when the generate stage produced nothing at all", async () => {
    // Not an empty screen: the ranking is still there, and every row shows
    // generate rather than a thumbnail.
    serve(
      makeRunDetail({
        runId: RUN_ID,
        stages: [makeStageRecord({ stage: "generate", summary: "0 of 5 rendered" })],
      }),
      [
        makeRankedTopic({ topicId: "t1", finalRank: 1, renderCount: 0 }),
        makeRankedTopic({ topicId: "t2", finalRank: 2, renderCount: 0 }),
      ],
    );

    renderPage();

    expect(
      await screen.findByText("No memes were rendered — every brief failed"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("generate ↗")).toHaveLength(2);
  });

  it("does not claim every brief failed while generate is still running", async () => {
    // Phase 6 polls a live run. Watched from the moment generate starts,
    // every render_count reads 0 for the same reason as the never-reached
    // case above — nothing has landed yet — and the message would be just
    // as wrong here.
    serve(
      makeRunDetail({
        runId: RUN_ID,
        stages: [makeStageRecord({ stage: "generate", status: "running" })],
      }),
      [
        makeRankedTopic({ topicId: "t1", finalRank: 1, label: "Stadium rat", renderCount: 0 }),
        makeRankedTopic({ topicId: "t2", finalRank: 2, label: "Airport cat", renderCount: 0 }),
      ],
    );

    renderPage();

    expect(await screen.findByText("Airport cat")).toBeInTheDocument();
    expect(screen.queryByText(/every brief failed/)).not.toBeInTheDocument();
  });

  it("does not claim every brief failed on a run that never reached generate", async () => {
    // The ranking has to be non-empty for this to test anything: an empty
    // one takes a different branch and never consults the generate stage
    // at all. Here evaluate wrote a ranking and generate never ran, so
    // every render_count is 0 because nothing tried — not because every
    // brief failed. Without the stage guard the screen reads the first as
    // the second and sends someone hunting a renderer bug.
    serve(
      makeRunDetail({
        runId: RUN_ID,
        status: "failed",
        error: { kind: "DistilError", message: "model returned nothing", stage: "analyse" },
        stages: [makeStageRecord({ stage: "ingest" })],
      }),
      [makeRankedTopic({ topicId: "t1", finalRank: 1, renderCount: 0 })],
    );

    renderPage();

    expect(await screen.findByText(/DistilError in analyse/)).toBeInTheDocument();
    expect(screen.queryByText(/every brief failed/)).not.toBeInTheDocument();
  });

  it("shows the failure and what survived it", async () => {
    serve(
      makeRunDetail({
        runId: RUN_ID,
        status: "failed",
        error: {
          kind: "RenderError",
          message: "3 of 5 briefs written",
          stage: "generate",
        },
        resumeStage: "generate",
      }),
      [makeRankedTopic()],
    );

    renderPage();

    expect(
      await screen.findByText(
        "RenderError in generate — 3 of 5 briefs written · ranked checkpoint intact",
      ),
    ).toBeInTheDocument();
  });

  it("says which run is missing rather than showing an empty page", async () => {
    server.use(
      http.get("/api/runs/:runId", () =>
        HttpResponse.json({ detail: "No such run" }, { status: 404 }),
      ),
      http.get("/api/runs/:runId/topics", () =>
        HttpResponse.json({ detail: "No such run" }, { status: 404 }),
      ),
    );

    renderPage();

    expect(await screen.findByText("No such run.")).toBeInTheDocument();
  });

  it("breadcrumbs back to the runs list", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [makeRankedTopic()]);

    renderPage();

    const crumb = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumb).getByRole("link", { name: "Runs" })).toHaveAttribute(
      "href",
      "/runs",
    );
  });
});
