import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { TopicsPage } from "@/features/topics/TopicsPage";
import {
  makeIndexedTopic,
  makeRunPage,
  makeRunSummary,
  makeTopicDetail,
  makeTopicIndex,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

function serve(
  index = makeTopicIndex(),
  runs = makeRunPage([makeRunSummary()]),
  detail = makeTopicDetail(),
) {
  server.use(
    http.get("/api/topics", () => HttpResponse.json(index)),
    http.get("/api/runs", () => HttpResponse.json(runs)),
    http.get("/api/runs/:runId/topics/:topicId", () => HttpResponse.json(detail)),
  );
}

describe("TopicsPage", () => {
  it("titles the page and counts each status in the window", async () => {
    serve();

    renderWithProviders(<TopicsPage />);

    expect(await screen.findByRole("heading", { name: "Right now" })).toBeInTheDocument();
    expect(screen.getByText(/9 trending · 6 saturating · 4 cooling/)).toBeInTheDocument();
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
});
