import userEvent from "@testing-library/user-event";
import { act, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { RankedTopic, RunDetail } from "@/api/types";
import { RunDetailPage } from "@/features/runs/RunDetailPage";
import stageStyles from "@/features/runs/StageCards.module.css";
import { FakeEventSource } from "@/test/eventsource";
import {
  FIXED_END,
  makeActiveRuns,
  makeLogLine,
  makeQueuedRun,
  makeRankedTopic,
  makeRenderRecord,
  makeRunDetail,
  makeStageRecord,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

const RUN_ID = "20260829T090000Z";

/** Where a navigation ended up, for the tests that leave this page. */
function Landed() {
  const { pathname } = useLocation();
  return <p>{`landed on ${pathname}`}</p>;
}

function serve(detail: RunDetail, ranking: RankedTopic[]) {
  server.use(
    // `/api/runs/active` must be registered before `/api/runs/:runId`: MSW
    // matches handlers in registration order, and `:runId` would otherwise
    // swallow the literal `active` segment as a run id.
    http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    http.get("/api/runs/:runId", () => HttpResponse.json(detail)),
    http.get("/api/runs/:runId/topics", () => HttpResponse.json(ranking)),
    http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
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

    expect(await screen.findByRole("button", { name: "generate ↗" })).toBeInTheDocument();
  });

  it("generates one meme for a topic below the cut, the model choosing, then opens it", async () => {
    // The handoff: "briefs and renders that single topic without re-running
    // the pipeline — same backend path as the topic-detail LLM panel".
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "t1", finalRank: 1, aboveCut: true }),
      makeRankedTopic({ topicId: "t2", finalRank: 6, aboveCut: false, renderCount: 0 }),
    ]);
    let posted: unknown = null;
    let postedFor = "";
    server.use(
      http.post("/api/runs/:runId/topics/:topicId/renders", async ({ request, params }) => {
        posted = await request.json();
        postedFor = String(params.topicId);
        return HttpResponse.json(
          [
            makeRenderRecord({
              id: "new-1",
              topicId: "t2",
              status: "generating",
              templateId: null,
              captionSlots: {},
            }),
          ],
          { status: 202 },
        );
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route path="*" element={<Landed />} />
      </Routes>,
      { route: `/runs/${RUN_ID}` },
    );

    await user.click(await screen.findByRole("button", { name: "generate ↗" }));

    // The pathname, not just "some topic page": a destination built from
    // the wrong row, or with run and topic swapped, lands somewhere else.
    expect(await screen.findByText(`landed on /topics/${RUN_ID}/t2`)).toBeInTheDocument();
    expect(postedFor).toBe("t2");
    expect(posted).toEqual({ mode: "llm", template_id: null, count: 1 });
  });

  it("says why on the row when the server will not generate", async () => {
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "t2", finalRank: 6, aboveCut: false, renderCount: 0 }),
    ]);
    server.use(
      http.post("/api/runs/:runId/topics/:topicId/renders", () =>
        HttpResponse.json(
          { detail: "ANTHROPIC_API_KEY is required for the anthropic provider" },
          { status: 400 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "generate ↗" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "ANTHROPIC_API_KEY is required for the anthropic provider",
    );
  });

  it("does not brief the topic twice while the first request is on its way", async () => {
    // Each click is a model call. Refused at the end, so the row stays on
    // this page to be counted from rather than navigating away.
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "t2", finalRank: 6, aboveCut: false, renderCount: 0 }),
    ]);
    let posts = 0;
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post("/api/runs/:runId/topics/:topicId/renders", async () => {
        posts += 1;
        await held;
        return HttpResponse.json(
          { detail: "ANTHROPIC_API_KEY is required for the anthropic provider" },
          { status: 400 },
        );
      }),
    );
    const user = userEvent.setup();
    renderPage();

    const generate = await screen.findByRole("button", { name: "generate ↗" });
    await user.click(generate);
    await waitFor(() => expect(generate).toBeDisabled());
    await user.click(generate);
    release();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(posts).toBe(1);
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
    // Nor does a kept topic offer generate while the stage that is about
    // to render it is still running.
    expect(screen.queryByRole("button", { name: "generate ↗" })).not.toBeInTheDocument();
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
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json({ detail: "No such run" }, { status: 404 }),
      ),
      http.get("/api/runs/:runId/topics", () =>
        HttpResponse.json({ detail: "No such run" }, { status: 404 }),
      ),
      http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
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

  it("marks the running stage and counts it", async () => {
    server.use(
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: "20260829T090000Z" })),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({
            status: "running",
            stages: [
              makeStageRecord({ stage: "ingest" }),
              makeStageRecord({
                stage: "analyse",
                status: "running",
                finishedAt: null,
                payloadBytes: null,
                summary: "airport cat",
                done: 17,
                total: 25,
              }),
            ],
          }),
        ),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
      http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
    );

    renderWithProviders(<RunDetailPage />, {
      route: "/runs/20260829T090000Z",
      path: "/runs/:runId",
    });

    expect(await screen.findByText("17 / 25")).toBeInTheDocument();
    expect(screen.getByText("airport cat")).toBeInTheDocument();
  });

  it("draws an aborted run's still-running stage as interrupted, not live", async () => {
    // `_RunRecorder` writes a `running` stage row and nothing closes it when
    // a run is aborted, failed or interrupted by a restart. The run's own
    // status is authoritative: once it has ended, a row still saying
    // `running` is a stage that was cut off, not one still going.
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({
            status: "aborted",
            finishedAt: FIXED_END,
            stages: [
              makeStageRecord({ stage: "ingest" }),
              makeStageRecord({
                stage: "analyse",
                status: "running",
                finishedAt: null,
                payloadBytes: null,
                done: 8,
                total: 12,
              }),
            ],
          }),
        ),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
      http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
    );

    renderPage();

    expect(await screen.findByText("interrupted · 8 of 12")).toBeInTheDocument();
    expect(screen.queryByText("8 / 12")).not.toBeInTheDocument();
    expect(screen.getByText("analyse").closest("li")).not.toHaveClass(
      stageStyles.running ?? "",
    );
  });

  it("keeps a live run's running stage counting, as the control case", async () => {
    // Same record as above, but on a run that is still `running`. This is
    // what proves the new branch keys on the run's own liveness rather than
    // the stage record alone — a version that always drew `running` rows as
    // interrupted would pass the test above and fail this one.
    server.use(
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: "20260829T090000Z" })),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({
            status: "running",
            finishedAt: null,
            stages: [
              makeStageRecord({ stage: "ingest" }),
              makeStageRecord({
                stage: "analyse",
                status: "running",
                finishedAt: null,
                payloadBytes: null,
                done: 8,
                total: 12,
              }),
            ],
          }),
        ),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
    );

    renderPage();

    expect(await screen.findByText("8 / 12")).toBeInTheDocument();
    expect(screen.getByText("analyse").closest("li")).toHaveClass(
      stageStyles.running ?? "",
    );
  });

  it("shows no checkpoint size for a stage that has not written one", async () => {
    // `evidence · —` reads as a size that went missing. `evidence` alone
    // reads as a checkpoint not yet written, which is what is true.
    server.use(
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: "20260829T090000Z" })),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({
            status: "running",
            stages: [
              makeStageRecord({
                stage: "ingest",
                status: "running",
                finishedAt: null,
                payloadBytes: null,
              }),
            ],
          }),
        ),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
      http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
    );

    renderWithProviders(<RunDetailPage />, {
      route: "/runs/20260829T090000Z",
      path: "/runs/:runId",
    });

    expect(await screen.findByText("evidence")).toBeInTheDocument();
    expect(screen.queryByText(/evidence · /)).not.toBeInTheDocument();
  });

  /** Every handler a live run's detail page asks for. */
  function liveRun(overrides: Partial<Parameters<typeof makeRunDetail>[0]> = {}) {
    return [
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: "20260829T140200Z" })),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({
            runId: "20260829T140200Z",
            status: "running",
            finishedAt: null,
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
            ...overrides,
          }),
        ),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
    ];
  }

  function renderDetail(runId = "20260829T140200Z") {
    return renderWithProviders(<RunDetailPage />, {
      route: `/runs/${runId}`,
      path: "/runs/:runId",
    });
  }

  it("counts up while the run is live, and says when it started", async () => {
    // The fixture's `started_at` is frozen, so the clock it is measured
    // against has to be too: comparing a fixed date to the real `new Date()`
    // makes the rendered elapsed time a function of the day the suite runs,
    // and a `/^t\+\d\d:\d\d$/` shape assertion would pass just as happily for
    // an elapsed computed off the wrong field or with the sign flipped.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-08-29T09:06:41Z"));
    try {
      server.use(...liveRun());

      renderDetail();

      expect(await screen.findByText("RUNNING")).toBeInTheDocument();
      expect(screen.getByText("t+06:41")).toBeInTheDocument();
      expect(screen.getByText(/started 09:00/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("counts a resumed run from its resume, not from its first start", async () => {
    // `started_at` is when the run *first* began, which is what the Runs
    // list orders by; a resume deliberately leaves it alone. Counting the
    // elapsed clock from it meant a run resumed the next day opened at
    // "1d 0h" and climbed from there. Nine hours apart, so a clock reading
    // the wrong field cannot land on the right answer by rounding.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-08-30T18:06:41Z"));
    try {
      server.use(
        ...liveRun({
          attemptStartedAt: "2026-08-30T18:00:00Z",
        }),
      );

      renderDetail();

      expect(await screen.findByText("RUNNING")).toBeInTheDocument();
      expect(screen.getByText("t+06:41")).toBeInTheDocument();
      // The config line sits directly under the counter and has to agree
      // with it: "started 09:00" beside "t+06:41" would be yesterday's
      // time next to this minute's count.
      expect(screen.getByText(/started 18:00/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("draws no stage as running while a run waits in the queue", async () => {
    // A resumed run keeps its previous attempt's stage rows, including
    // whichever one was `running` when that attempt was cut off — and a
    // queued run's own row says `running` too, so the page reads as live.
    // Together those drew the earlier attempt's stage with the live
    // treatment, on a run that had not started: an accent border, a
    // partial bar and a `17 / 25` counter, all describing something that
    // ended some time ago. The counter is the assertion because it is the
    // one thing only a genuinely running stage ever gets.
    server.use(
      http.get("/api/runs/active", () =>
        HttpResponse.json(
          makeActiveRuns({
            current: "20260829T140200Z",
            queued: ["20260829T150000Z"],
          }),
        ),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({
            runId: "20260829T150000Z",
            status: "running",
            finishedAt: null,
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
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
    );

    renderDetail("20260829T150000Z");
    await screen.findByText(/Waiting behind the run in flight/);

    expect(screen.queryByText("17 / 25")).not.toBeInTheDocument();
    expect(screen.getByText("interrupted · 17 of 25")).toBeInTheDocument();
  });

  it("still draws the running stage once the run is actually executing", async () => {
    // The negative of the test above: gating on `queued` must not turn the
    // live treatment off for the run that really is going, which is the
    // only run that ever had it.
    server.use(...liveRun());

    renderDetail();

    expect(await screen.findByText("17 / 25")).toBeInTheDocument();
  });

  it("says a queued run has not started", async () => {
    // A queued run's row says `running` too — `enqueue` opens it that way —
    // so `active.queued` is the only thing that separates the two, and this
    // notice is the only place the screen reads it.
    server.use(
      http.get("/api/runs/active", () =>
        HttpResponse.json(
          makeActiveRuns({
            current: "20260829T140200Z",
            queued: ["20260829T150000Z"],
          }),
        ),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({ runId: "20260829T150000Z", status: "running", stages: [] }),
        ),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
    );

    renderDetail("20260829T150000Z");

    expect(
      await screen.findByText(
        "Waiting behind the run in flight. Nothing has started yet.",
      ),
    ).toBeInTheDocument();
  });

  it("does not call the run in flight queued", async () => {
    // The negative case, because a notice rendered unconditionally — or from
    // an inverted condition — would pass the test above while telling
    // everyone watching a live run that nothing had started.
    server.use(...liveRun());

    renderDetail();
    await screen.findByText("RUNNING");

    expect(
      screen.queryByText(/Waiting behind the run in flight/),
    ).not.toBeInTheDocument();
  });

  it("offers stop and abort while live, and neither afterwards", async () => {
    server.use(...liveRun());
    renderDetail();

    expect(
      await screen.findByRole("button", { name: "Stop after this stage" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Abort" })).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Re-run config" }),
    ).not.toBeInTheDocument();
  });

  it("stop needs no confirmation, because it is not destructive", async () => {
    const user = userEvent.setup();
    let stopped = "";
    server.use(
      ...liveRun(),
      http.post("/api/runs/:runId/stop", ({ params }) => {
        stopped = String(params.runId);
        return HttpResponse.json(
          { run_id: stopped, requested: "stop" },
          { status: 202 },
        );
      }),
    );
    renderDetail();

    await user.click(
      await screen.findByRole("button", { name: "Stop after this stage" }),
    );

    await waitFor(() => expect(stopped).toBe("20260829T140200Z"));
  });

  it("abort asks first, and aborts only when told twice", async () => {
    const user = userEvent.setup();
    let aborted = "";
    server.use(
      ...liveRun(),
      http.post("/api/runs/:runId/abort", ({ params }) => {
        aborted = String(params.runId);
        return HttpResponse.json(
          { run_id: aborted, requested: "abort" },
          { status: 202 },
        );
      }),
    );
    renderDetail();

    await user.click(await screen.findByRole("button", { name: "Abort" }));
    expect(screen.getByText("Abort run?")).toBeInTheDocument();
    expect(aborted).toBe("");

    await user.click(screen.getByRole("button", { name: "yes" }));
    await waitFor(() => expect(aborted).toBe("20260829T140200Z"));
  });

  it("acknowledges a pending stop until the stage actually ends", async () => {
    // A 202 means only that the request was accepted — the stage the run
    // is on can take minutes to finish. Nothing said so before this fix,
    // and the button stayed enabled and unchanged the whole time.
    const user = userEvent.setup();
    server.use(
      ...liveRun(),
      http.post("/api/runs/:runId/stop", () =>
        HttpResponse.json(
          { run_id: "20260829T140200Z", requested: "stop" },
          { status: 202 },
        ),
      ),
    );
    renderDetail();

    await user.click(
      await screen.findByRole("button", { name: "Stop after this stage" }),
    );

    expect(await screen.findByRole("button", { name: "Stopping…" })).toBeDisabled();
    // A user who asked for a clean stop can still escalate.
    expect(screen.getByRole("button", { name: "Abort" })).toBeEnabled();
  });

  it("acknowledges a pending abort, and disables stop along with it", async () => {
    const user = userEvent.setup();
    server.use(
      ...liveRun(),
      http.post("/api/runs/:runId/abort", () =>
        HttpResponse.json(
          { run_id: "20260829T140200Z", requested: "abort" },
          { status: 202 },
        ),
      ),
    );
    renderDetail();

    await user.click(await screen.findByRole("button", { name: "Abort" }));
    await user.click(screen.getByRole("button", { name: "yes" }));

    expect(await screen.findByRole("button", { name: "Aborting…" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Stop after this stage" }),
    ).toBeDisabled();
  });

  it("keeps focus on the run's header once a stop is accepted", async () => {
    // Stop disables itself the instant it succeeds — a disabled button
    // cannot hold focus, so the keyboard user who pressed it was dropped
    // on `<body>` with no indication that anything had happened. Unlike
    // Abort and Resume, Stop has no confirm to return focus to first.
    const user = userEvent.setup();
    server.use(
      ...liveRun(),
      http.post("/api/runs/:runId/stop", () =>
        HttpResponse.json(
          { run_id: "20260829T140200Z", requested: "stop" },
          { status: 202 },
        ),
      ),
    );
    renderDetail();

    await user.click(
      await screen.findByRole("button", { name: "Stop after this stage" }),
    );
    await screen.findByRole("button", { name: "Stopping…" });

    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toContainElement(
      screen.getByText("20260829T140200Z"),
    );
  });

  it("keeps focus on the run's header when a resume is refused", async () => {
    // The refusal path, which `onSuccess` never covered. Between the click
    // and the 409, Resume's trigger is disabled by its own pending guard —
    // long enough for the browser to drop focus — and then comes back
    // enabled with the error beside it. Nothing moved focus back, so the
    // user was reading a message they could not reach.
    const user = userEvent.setup();
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({ runId: RUN_ID, status: "aborted", resumeStage: "generate" }),
        ),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
      http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
      http.post("/api/runs/:runId/resume", () =>
        HttpResponse.json(
          { detail: `Run ${RUN_ID} is already queued or executing` },
          { status: 409 },
        ),
      ),
    );

    renderWithProviders(<RunDetailPage />, {
      route: `/runs/${RUN_ID}`,
      path: "/runs/:runId",
    });

    await user.click(
      await screen.findByRole("button", { name: "Resume from generate" }),
    );
    await user.click(screen.getByRole("button", { name: "yes" }));
    await screen.findByText(/already queued or executing/);

    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toContainElement(screen.getByText(RUN_ID));
  });

  it("keeps focus on the run's header once an abort is accepted", async () => {
    // After "yes", focus goes back to the Abort trigger — which the accepted
    // abort then replaces with "Aborting…". The focused button unmounted,
    // and a keyboard user was dropped at the top of the document: the
    // walk's D5 again, by a different route.
    const user = userEvent.setup();
    server.use(
      ...liveRun(),
      http.post("/api/runs/:runId/abort", () =>
        HttpResponse.json(
          { run_id: "20260829T140200Z", requested: "abort" },
          { status: 202 },
        ),
      ),
    );
    renderDetail();

    await user.click(await screen.findByRole("button", { name: "Abort" }));
    await user.click(screen.getByRole("button", { name: "yes" }));
    await screen.findByRole("button", { name: "Aborting…" });

    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toContainElement(screen.getByText("20260829T140200Z"));
  });

  it("keeps focus on the run's header once a resume is accepted and the run goes live", async () => {
    // The actions remount when the run goes live (they are keyed on it), so
    // every button that could have held focus is replaced at once.
    const user = userEvent.setup();
    let resumed = false;
    server.use(
      http.get("/api/runs/active", () =>
        HttpResponse.json(
          makeActiveRuns({ current: resumed ? "20260829T090000Z" : null }),
        ),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          resumed
            ? makeRunDetail({
                runId: "20260829T090000Z",
                status: "running",
                finishedAt: null,
                stages: [
                  makeStageRecord({ stage: "ingest" }),
                  makeStageRecord({ stage: "analyse" }),
                  makeStageRecord({ stage: "evaluate" }),
                  makeStageRecord({
                    stage: "generate",
                    status: "running",
                    finishedAt: null,
                  }),
                ],
              })
            : makeRunDetail({ runId: "20260829T090000Z", resumeStage: "generate" }),
        ),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
      http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
      http.post("/api/runs/:runId/resume", () => {
        resumed = true;
        return HttpResponse.json(makeQueuedRun({ runId: "20260829T090000Z" }), {
          status: 202,
        });
      }),
    );
    renderDetail("20260829T090000Z");

    await user.click(
      await screen.findByRole("button", { name: "Resume from generate" }),
    );
    await user.click(screen.getByRole("button", { name: "yes" }));
    expect(
      await screen.findByRole("button", { name: "Stop after this stage" }),
    ).toBeInTheDocument();

    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toContainElement(screen.getByText("20260829T090000Z"));
  });

  it("posts one resume, however often it is asked before the run goes live", async () => {
    // Stop is disabled while pending and after it succeeds; Resume was not.
    // Between the 202 and the refetch that flips the page live it could be
    // armed and confirmed again, and the second POST drew a 409 that
    // flashed on screen until the remount cleared it.
    const user = userEvent.setup();
    let posts = 0;
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({ runId: "20260829T090000Z", resumeStage: "generate" }),
        ),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
      http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
      http.post("/api/runs/:runId/resume", () => {
        posts += 1;
        return HttpResponse.json(makeQueuedRun({ runId: "20260829T090000Z" }), {
          status: 202,
        });
      }),
    );
    renderDetail("20260829T090000Z");

    await user.click(
      await screen.findByRole("button", { name: "Resume from generate" }),
    );
    await user.click(screen.getByRole("button", { name: "yes" }));
    await waitFor(() => expect(posts).toBe(1));

    const again = screen.getByRole("button", { name: "Resume from generate" });
    await user.click(again);

    expect(screen.queryByRole("button", { name: "yes" })).not.toBeInTheDocument();
    expect(again).toBeDisabled();
    expect(posts).toBe(1);
  });

  it("clears a pending stop or abort label once the run itself has ended", async () => {
    // The pending state is client-side only and must not leak: a resumed
    // run goes live again on the same page, and a stale `isSuccess` from
    // the previous life would mislabel it. Here the run query itself
    // refetches a finished detail — the same mechanism a real stop uses —
    // and the finished buttons must replace the pending ones entirely.
    //
    // The second response is gated on a promise this test controls: the
    // invalidate a successful Stop fires refetches the run query almost
    // immediately, and an ungated handler resolved it before "Stopping…"
    // ever painted, making the assertion below a race rather than a test.
    const user = userEvent.setup();
    let calls = 0;
    let releaseSecondFetch: (() => void) | undefined;
    const secondFetchGate = new Promise<void>((resolve) => {
      releaseSecondFetch = resolve;
    });
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
      http.get("/api/runs/:runId", async () => {
        calls += 1;
        if (calls === 2) await secondFetchGate;
        return HttpResponse.json(
          makeRunDetail({
            runId: "20260829T140200Z",
            status: calls === 1 ? "running" : "aborted",
            finishedAt: calls === 1 ? null : FIXED_END,
            resumeStage: "generate",
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
        );
      }),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
      http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
      http.post("/api/runs/:runId/stop", () =>
        HttpResponse.json(
          { run_id: "20260829T140200Z", requested: "stop" },
          { status: 202 },
        ),
      ),
    );

    renderDetail();
    await user.click(
      await screen.findByRole("button", { name: "Stop after this stage" }),
    );
    expect(await screen.findByRole("button", { name: "Stopping…" })).toBeInTheDocument();

    // The stop mutation's own `onSuccess` invalidates `["runs"]`, which
    // refetches this run's detail — now finished — the same way a real
    // poll or reload would notice the run has ended.
    releaseSecondFetch?.();

    expect(await screen.findByRole("link", { name: "Re-run config" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stopping…" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Aborting…" })).not.toBeInTheDocument();
  });

  it("streams the log while live", async () => {
    server.use(...liveRun());
    renderDetail();
    await screen.findByText("RUNNING");

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() =>
      FakeEventSource.latest().emitLog([
        makeLogLine({ logger: "zeitgeist.analysis.distil", message: "Distilled 'cat'" }),
      ]),
    );

    expect(await screen.findByText("Distilled 'cat'")).toBeInTheDocument();
  });

  it("says the ranking is not decided yet while analyse is running", async () => {
    // The order is set in evaluate, so there is nothing honest to draw here
    // until the stage ends. Saying so beats an empty section.
    server.use(...liveRun());
    renderDetail();

    expect(
      await screen.findByText("Distilling — the ranking appears when analyse finishes."),
    ).toBeInTheDocument();
    expect(screen.getByText("final order is set in evaluate")).toBeInTheDocument();
  });

  it("reads a finished run's log from the server, and opens no stream", async () => {
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
      http.get("/api/runs/:runId/log", () =>
        HttpResponse.json([makeLogLine({ message: "Fetched 25 trends" })]),
      ),
    );

    renderDetail("20260829T090000Z");

    expect(await screen.findByText("Fetched 25 trends")).toBeInTheDocument();
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("says a finished run's log could not be read, rather than that it logged nothing", async () => {
    // `history.data ?? []` threw the log query's error away, so a failed
    // `/log` read "This run logged nothing." for good — a false statement
    // standing in for an error.
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
      http.get("/api/runs/:runId/log", () =>
        HttpResponse.json({ detail: "log_lines is unreadable" }, { status: 500 }),
      ),
    );

    renderDetail("20260829T090000Z");

    expect(await screen.findByText("log_lines is unreadable")).toBeInTheDocument();
    expect(screen.queryByText("This run logged nothing.")).not.toBeInTheDocument();
  });

  it("says a finished run's log is loading while it is", async () => {
    // The same `?? []` read a log still in flight as an empty one.
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
      http.get("/api/runs/:runId/log", async () => {
        await gate;
        return HttpResponse.json([makeLogLine({ message: "Fetched 25 trends" })]);
      }),
    );

    renderDetail("20260829T090000Z");

    expect(await screen.findByText("Loading the log…")).toBeInTheDocument();
    expect(screen.queryByText("This run logged nothing.")).not.toBeInTheDocument();

    release?.();
    expect(await screen.findByText("Fetched 25 trends")).toBeInTheDocument();
    expect(screen.queryByText("Loading the log…")).not.toBeInTheDocument();
  });

  it("asks the log endpoint for nothing while the run is live", async () => {
    // The inverse of the test above. `live` is computed from `run.data`,
    // which is undefined on the very first render — a gate written as
    // `useRunLog(runId, verbose, !live)` reads that as "not live" and
    // mounts the query enabled for one render before the next render
    // disables it, which is enough to fire a real request. Rendered output
    // cannot catch that: the page never reads the response either way. Only
    // counting the calls a handler actually receives can.
    let logCalls = 0;
    server.use(
      ...liveRun(),
      http.get("/api/runs/:runId/log", () => {
        logCalls += 1;
        return HttpResponse.json([]);
      }),
    );

    renderDetail();
    await screen.findByText("RUNNING");

    expect(logCalls).toBe(0);
  });

  it("offers Re-run config and Resume once a run is over", async () => {
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(makeRunDetail({ resumeStage: "generate" })),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
      http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
    );

    renderDetail("20260829T090000Z");

    // Named for what it does to *this* run, not "New run": the header pill
    // of that name starts from settings, and a finished run's header
    // offering the same words could not say it prefills from this one.
    // Found on a real run's page, where the two read identically.
    expect(
      await screen.findByRole("link", { name: "Re-run config" }),
    ).toHaveAttribute("href", "/runs/new?from=20260829T090000Z");
    expect(
      screen.getByRole("button", { name: "Resume from generate" }),
    ).toBeInTheDocument();
  });

  it("hides Resume entirely when there is nothing to resume from", async () => {
    // A source outage: ingest returned nothing, so no checkpoint exists. The
    // spec is explicit that the button is absent rather than disabled — a
    // disabled control still says the action exists.
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({
            status: "failed",
            resumeStage: null,
            error: { kind: "SourceError", message: "no trends returned", stage: "ingest" },
          }),
        ),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
      http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
    );

    renderDetail("20260829T090000Z");

    await screen.findByText("FAILED");
    expect(screen.queryByRole("button", { name: /Resume/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Re-run config" })).toBeInTheDocument();
  });

  it("asks before resuming rather than acting on the first click", async () => {
    // A click aimed at Abort as a live run completes can land on Resume
    // instead — the buttons swap in place. Resume must arm a question, not
    // re-run generate on the click that was meant to abort.
    const user = userEvent.setup();
    let resumed = false;
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(makeRunDetail({ resumeStage: "generate" })),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
      http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
      http.post("/api/runs/:runId/resume", () => {
        resumed = true;
        return HttpResponse.json(makeQueuedRun(), { status: 202 });
      }),
    );

    renderDetail("20260829T090000Z");
    await user.click(
      await screen.findByRole("button", { name: "Resume from generate" }),
    );

    expect(screen.getByText("Resume from generate?")).toBeInTheDocument();
    expect(resumed).toBe(false);
  });

  it("resumes from the computed stage without naming one", async () => {
    // The button posts an empty body: `resume_stage` is the server's own
    // computation, and a client that echoed it back could send a stale one.
    const user = userEvent.setup();
    let body: unknown = null;
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(makeRunDetail({ resumeStage: "generate" })),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
      http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
      http.post("/api/runs/:runId/resume", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(makeQueuedRun({ runId: "20260829T090000Z" }), {
          status: 202,
        });
      }),
    );

    renderDetail("20260829T090000Z");
    await user.click(
      await screen.findByRole("button", { name: "Resume from generate" }),
    );
    // Going through the confirm is a direct consequence of the ruling, not
    // a weakened test: the assertion below (an empty body) is unchanged.
    await user.click(screen.getByRole("button", { name: "yes" }));

    await waitFor(() => expect(body).toEqual({}));
  });

  it("reports a refused action rather than swallowing it", async () => {
    // The 409 the server answers a double-clicked Resume with. Silence here
    // would leave someone clicking a button that has already worked.
    const user = userEvent.setup();
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(makeRunDetail({ resumeStage: "generate" })),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
      http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
      http.post("/api/runs/:runId/resume", () =>
        HttpResponse.json(
          { detail: "Run 20260829T090000Z is already queued or executing" },
          { status: 409 },
        ),
      ),
    );

    renderDetail("20260829T090000Z");
    await user.click(
      await screen.findByRole("button", { name: "Resume from generate" }),
    );
    await user.click(screen.getByRole("button", { name: "yes" }));

    expect(
      await screen.findByText("Run 20260829T090000Z is already queued or executing"),
    ).toBeInTheDocument();
  });

  it("offers generate on a kept topic whose own brief failed", async () => {
    // Partial failure: the stage ran, one topic rendered, the other did
    // not. Generate used to be offered here only when *every* brief
    // failed, so the one row that needs it read "0 memes" instead.
    serve(
      makeRunDetail({
        runId: RUN_ID,
        stages: [makeStageRecord({ stage: "generate", summary: "1 of 2 rendered" })],
      }),
      [
        makeRankedTopic({ topicId: "t1", finalRank: 1, label: "Stadium rat", renderCount: 1 }),
        makeRankedTopic({ topicId: "t2", finalRank: 2, label: "Airport cat", renderCount: 0 }),
      ],
    );

    renderPage();

    expect(await screen.findByRole("button", { name: "generate ↗" })).toBeInTheDocument();
    expect(screen.getByText("1 meme")).toBeInTheDocument();
  });

  it("counts the memes a below-the-cut row has, beside its generate link", async () => {
    // Generating for a topic below the cut leaves it with memes, and the
    // row said nothing about them: it drew the link alone.
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "t1", finalRank: 1, aboveCut: true }),
      makeRankedTopic({ topicId: "t2", finalRank: 6, aboveCut: false, renderCount: 2 }),
    ]);

    renderPage();

    expect(await screen.findByText("2 memes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "generate ↗" })).toBeInTheDocument();
  });

  it("lets you try again on the row after the server refuses", async () => {
    // The refusal is usually a missing key, which is fixed elsewhere and
    // then wants another go. Without this the row kept the sentence until
    // the page was remounted.
    serve(makeRunDetail({ runId: RUN_ID }), [
      makeRankedTopic({ topicId: "t2", finalRank: 6, aboveCut: false, renderCount: 0 }),
    ]);
    server.use(
      http.post("/api/runs/:runId/topics/:topicId/renders", () =>
        HttpResponse.json(
          { detail: "ANTHROPIC_API_KEY is required for the anthropic provider" },
          { status: 400 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "generate ↗" }));
    await user.click(
      await screen.findByRole("button", { name: "Try generating again" }),
    );

    expect(await screen.findByRole("button", { name: "generate ↗" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
