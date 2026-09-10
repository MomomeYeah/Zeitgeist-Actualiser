import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { TopicsPage } from "@/features/topics/TopicsPage";
import {
  makeActiveRuns,
  makeIndexedTopic,
  makeRunDetail,
  makeRunPage,
  makeRunSummary,
  makeTopicDetail,
  makeTopicIndex,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

import styles from "@/features/runs/RunStrip.module.css";

function serve(
  index = makeTopicIndex(),
  runs = makeRunPage([makeRunSummary()]),
  detail = makeTopicDetail(),
) {
  server.use(
    http.get("/api/topics", () => HttpResponse.json(index)),
    http.get("/api/runs", () => HttpResponse.json(runs)),
    http.get("/api/runs/:runId/topics/:topicId", () => HttpResponse.json(detail)),
    http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
  );
}

describe("TopicsPage", () => {
  it("titles the page and counts each status in the window", async () => {
    serve();

    renderWithProviders(<TopicsPage />);

    expect(await screen.findByRole("heading", { name: "Right now" })).toBeInTheDocument();
    expect(screen.getByText(/9 trending · 6 saturating · 4 cooling/)).toBeInTheDocument();
  });

  it("does not claim there are no runs when the runs request failed", async () => {
    // An empty list and a broken server look identical without this, and
    // "no runs yet" would be a lie about a database that is fine — the
    // topics below are proof runs have happened.
    server.use(
      http.get("/api/topics", () => HttpResponse.json(makeTopicIndex())),
      http.get("/api/runs", () =>
        HttpResponse.json({ detail: "database is locked" }, { status: 500 }),
      ),
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json(makeTopicDetail()),
      ),
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );

    renderWithProviders(<TopicsPage />);

    expect(await screen.findByRole("heading", { name: "Right now" })).toBeInTheDocument();
    expect(screen.queryByText(/no runs yet/)).not.toBeInTheDocument();
  });

  it("heroes the highest-scoring topic, not the most recent one", async () => {
    serve(
      makeTopicIndex({
        topics: [
          makeIndexedTopic({ topicId: "recent", label: "Stadium rat", finalScore: 0.4 }),
          makeIndexedTopic({ topicId: "best", label: "Airport cat", finalScore: 0.95 }),
        ],
      }),
    );

    renderWithProviders(<TopicsPage />);

    const hero = await screen.findByTestId("hero");
    expect(within(hero).getByText("Airport cat")).toBeInTheDocument();
  });

  it("writes the hero's kicker from the topic's own status and score", async () => {
    serve(
      makeTopicIndex({
        topics: [
          makeIndexedTopic({ trendStatus: "saturating", memePotential: 0.86 }),
        ],
      }),
    );

    renderWithProviders(<TopicsPage />);

    expect(
      await screen.findByText("TOP RIGHT NOW · SATURATING · MEME 0.86"),
    ).toBeInTheDocument();
  });

  it("fills the hero's summary from that topic's dossier", async () => {
    // TopicIndex carries no prose — TopicRow has no summary field — so the
    // hero fetches the one topic it is showing. One request, real words.
    serve(
      makeTopicIndex({ topics: [makeIndexedTopic({ topicId: "t1" })] }),
      makeRunPage([makeRunSummary()]),
      makeTopicDetail({
        dossier: {
          what_happened: "A cat got loose in an airport terminal.",
          key_entities: [],
          conversation_summary: "",
          conversation_register: "riffing",
          secondary_registers: [],
          event_sentiment: "funny",
          meme_potential: 0.86,
          recurring_phrases: [],
        },
      }),
    );

    renderWithProviders(<TopicsPage />);

    expect(
      await screen.findByText("A cat got loose in an airport terminal."),
    ).toBeInTheDocument();
  });

  it("draws the mood bar with a segment per sentiment", async () => {
    serve(
      makeTopicIndex({
        sentimentTotals: { funny: 9, cute: 5 },
        previousSentimentTotals: { funny: 7, cute: 6 },
      }),
    );

    renderWithProviders(<TopicsPage />);

    const mood = await screen.findByTestId("mood");
    expect(within(mood).getByText("funny 9")).toBeInTheDocument();
    expect(within(mood).getByText("cute 5")).toBeInTheDocument();
  });

  it("says how the leading sentiment moved against the previous run", async () => {
    serve(
      makeTopicIndex({
        sentimentTotals: { funny: 9, cute: 5, mundane: 2 },
        previousSentimentTotals: { funny: 7, cute: 6 },
      }),
    );

    renderWithProviders(<TopicsPage />);

    expect(
      await screen.findByText(
        "funny leads at 56% of the window · up 2 points on the previous run",
      ),
    ).toBeInTheDocument();
  });

  it("labels a recurring topic with how many runs carried it", async () => {
    serve(makeTopicIndex({ topics: [makeIndexedTopic({ runCount: 3 })] }));

    renderWithProviders(<TopicsPage />);

    expect(await screen.findByText("▲ SEEN IN 3 RUNS")).toBeInTheDocument();
  });

  it("labels a topic seen once as new, not as seen in 1 run", async () => {
    serve(makeTopicIndex({ topics: [makeIndexedTopic({ runCount: 1 })] }));

    renderWithProviders(<TopicsPage />);

    expect(await screen.findByText("NEW THIS RUN")).toBeInTheDocument();
  });

  it("pluralises a single render as 1 meme, not 1 memes", async () => {
    // Every other fixture uses a count of 2, which is why no test caught
    // the unconditional "memes" in HeroTopic's chip.
    serve(makeTopicIndex({ topics: [makeIndexedTopic({ renderCount: 1 })] }));

    renderWithProviders(<TopicsPage />);

    expect(await screen.findByText("1 meme")).toBeInTheDocument();
  });

  it("says a topic has no memes yet, which is the cue to go generate some", async () => {
    serve(makeTopicIndex({ topics: [makeIndexedTopic({ renderCount: 0 })] }));

    renderWithProviders(<TopicsPage />);

    expect(await screen.findByText("no memes yet")).toBeInTheDocument();
  });

  it("links each card to that topic in the run it was last seen in", async () => {
    serve(
      makeTopicIndex({
        topics: [makeIndexedTopic({ runId: "20260829T090000Z", topicId: "topic-7" })],
      }),
    );

    renderWithProviders(<TopicsPage />);

    const links = await screen.findAllByRole("link");
    expect(
      links.some(
        (link) => link.getAttribute("href") === "/topics/20260829T090000Z/topic-7",
      ),
    ).toBe(true);
  });

  it("draws at most three trending cards even when more exist", async () => {
    // The grid is 3-up. Without the cap a busy window renders a fourth card
    // that wraps onto its own row, which is the layout breaking rather than
    // extending.
    serve(
      makeTopicIndex({
        topics: [
          makeIndexedTopic({ topicId: "a", label: "Card A", finalScore: 0.9 }),
          makeIndexedTopic({ topicId: "b", label: "Card B", finalScore: 0.8 }),
          makeIndexedTopic({ topicId: "c", label: "Card C", finalScore: 0.7 }),
          makeIndexedTopic({ topicId: "d", label: "Card D", finalScore: 0.6 }),
        ],
      }),
    );

    renderWithProviders(<TopicsPage />);

    const trending = await screen.findByTestId("trending-now");
    expect(within(trending).getAllByRole("heading", { level: 3 })).toHaveLength(3);
    expect(within(trending).queryByText("Card D")).not.toBeInTheDocument();
  });

  it("puts saturating and cooling topics in the second list, not the first", async () => {
    serve(
      makeTopicIndex({
        topics: [
          makeIndexedTopic({ topicId: "a", label: "Trending one", trendStatus: "trending" }),
          makeIndexedTopic({ topicId: "b", label: "Cooling one", trendStatus: "cooling" }),
        ],
      }),
    );

    renderWithProviders(<TopicsPage />);

    const trending = await screen.findByTestId("trending-now");
    const recent = screen.getByTestId("recently-trending");
    expect(within(trending).getByText("Trending one")).toBeInTheDocument();
    expect(within(recent).getByText("Cooling one")).toBeInTheDocument();
  });

  it("renders a stale topic in the second list when filtered for", async () => {
    // The second list's predicate used to name only "saturating" and
    // "cooling", so filtering for stale re-queried, got a stale topic back,
    // and rendered nothing at all — the empty-state line never fired
    // because `data.topics.length` was not zero.
    serve(
      makeTopicIndex({
        topics: [
          makeIndexedTopic({ topicId: "a", label: "Old meme", trendStatus: "stale" }),
        ],
      }),
    );

    renderWithProviders(<TopicsPage />);
    await screen.findByRole("heading", { name: "Right now" });

    await userEvent.click(screen.getByRole("button", { name: /stale 31/ }));

    const recent = await screen.findByTestId("recently-trending");
    expect(within(recent).getByText("Old meme")).toBeInTheDocument();
  });

  it("refetches with the status the filter chip names", async () => {
    let lastQuery = "";
    server.use(
      http.get("/api/topics", ({ request }) => {
        lastQuery = new URL(request.url).search;
        return HttpResponse.json(makeTopicIndex());
      }),
      http.get("/api/runs", () => HttpResponse.json(makeRunPage([makeRunSummary()]))),
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json(makeTopicDetail()),
      ),
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );

    renderWithProviders(<TopicsPage />);
    await screen.findByRole("heading", { name: "Right now" });

    await userEvent.click(screen.getByRole("button", { name: /cooling 4/ }));

    expect(lastQuery).toContain("status=cooling");
  });

  it("drops the filter when the active chip is clicked again", async () => {
    let lastQuery = "";
    server.use(
      http.get("/api/topics", ({ request }) => {
        lastQuery = new URL(request.url).search;
        return HttpResponse.json(makeTopicIndex());
      }),
      http.get("/api/runs", () => HttpResponse.json(makeRunPage([makeRunSummary()]))),
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json(makeTopicDetail()),
      ),
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );

    renderWithProviders(<TopicsPage />);
    await screen.findByRole("heading", { name: "Right now" });

    await userEvent.click(screen.getByRole("button", { name: /cooling 4/ }));
    await userEvent.click(screen.getByRole("button", { name: /cooling 4/ }));

    expect(lastQuery).not.toContain("status=");
  });

  it("says so lightly when a filter matched nothing", async () => {
    // The user did this to themselves and the remedy is one click away, so
    // it is a line rather than the empty-state card.
    serve(makeTopicIndex({ topics: [] }));

    renderWithProviders(<TopicsPage />);
    await screen.findByRole("heading", { name: "Right now" });

    await userEvent.click(screen.getByRole("button", { name: /stale 31/ }));

    expect(await screen.findByText("No topics with this status.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Nothing has run yet/ })).toBeNull();
  });

  it("explains the app when nothing has ever run", async () => {
    serve(makeTopicIndex({ topics: [] }), makeRunPage([]));

    renderWithProviders(<TopicsPage />);

    expect(
      await screen.findByRole("heading", { name: "Nothing has run yet" }),
    ).toBeInTheDocument();
  });

  it("says everything has gone stale when runs exist but nothing is current", async () => {
    serve(
      makeTopicIndex({ topics: [], statusTotals: { stale: 31 } }),
      makeRunPage([makeRunSummary()]),
    );

    renderWithProviders(<TopicsPage />);

    expect(
      await screen.findByRole("heading", { name: "No topics in the last 6 runs" }),
    ).toBeInTheDocument();
  });

  it("shows the last three runs beside the mood bar", async () => {
    server.use(
      http.get("/api/topics", () => HttpResponse.json(makeTopicIndex())),
      http.get("/api/runs", () =>
        HttpResponse.json(
          makeRunPage([
            makeRunSummary({ runId: "20260829T090000Z" }),
            makeRunSummary({ runId: "20260828T090000Z", status: "failed" }),
          ]),
        ),
      ),
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );

    renderWithProviders(<TopicsPage />);

    const strip = await screen.findByTestId("run-strip");
    expect(within(strip).getByText("…829T090000Z")).toBeInTheDocument();
    expect(within(strip).getByText("…828T090000Z")).toBeInTheDocument();
  });

  it("marks only the active run's row, whatever the list says about it", async () => {
    server.use(
      http.get("/api/topics", () => HttpResponse.json(makeTopicIndex())),
      http.get("/api/runs", () =>
        HttpResponse.json(
          makeRunPage([
            makeRunSummary({ runId: "20260829T140200Z", status: "running" }),
            makeRunSummary({ runId: "20260828T090000Z", status: "ok" }),
          ]),
        ),
      ),
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: "20260829T140200Z" })),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({ runId: "20260829T140200Z", status: "running" }),
        ),
      ),
    );

    renderWithProviders(<TopicsPage />);

    const strip = await screen.findByTestId("run-strip");
    const live = within(strip).getByRole("link", { name: /829T140200Z/ });
    const over = within(strip).getByRole("link", { name: /828T090000Z/ });

    // The accent treatment is the only thing `activeRunId` decides: a run in
    // flight already carries the status `running` in its own row, so
    // asserting the word alone would pass with the prop removed entirely.
    expect(live).toHaveClass(styles.running ?? "");
    expect(over).not.toHaveClass(styles.running ?? "");
  });

  it("asks for only the three runs the strip draws", async () => {
    // `RunStrip` maps over what it is given with no slice of its own, so the
    // cap is the query's `limit` and this is the only place it is enforced.
    // Raise it to `DEFAULT_RUN_LIMIT` and twenty-five rows appear beside a
    // mood bar sized for three, with no other test noticing.
    let limit: string | null = null;
    server.use(
      http.get("/api/topics", () => HttpResponse.json(makeTopicIndex())),
      http.get("/api/runs", ({ request }) => {
        limit = new URL(request.url).searchParams.get("limit");
        return HttpResponse.json(makeRunPage());
      }),
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );

    renderWithProviders(<TopicsPage />);
    await screen.findByTestId("run-strip");

    expect(limit).toBe("3");
  });
});
