import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { TopicDetail } from "@/api/types";
import { TopicDetailPage } from "@/features/topics/TopicDetailPage";
import {
  makeDossier,
  makeRenderRecord,
  makeRunDetail,
  makeTopicDetail,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

const RUN_ID = "20260829T090000Z";
const TOPIC_ID = "topic-1";

function serve(detail: TopicDetail = makeTopicDetail()) {
  server.use(
    http.get("/api/runs/:runId/topics/:topicId", () => HttpResponse.json(detail)),
    http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
  );
}

function renderPage() {
  return renderWithProviders(<TopicDetailPage />, {
    route: `/topics/${RUN_ID}/${TOPIC_ID}`,
    path: "/topics/:runId/:topicId",
  });
}

describe("TopicDetailPage", () => {
  it("titles the page with the topic's label", async () => {
    serve(makeTopicDetail({ label: "Airport cat" }));

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Airport cat", level: 1 }),
    ).toBeInTheDocument();
  });

  it("breadcrumbs with the topic id and the run it was first seen in", async () => {
    serve(makeTopicDetail({ firstSeenRunId: "20260826T090000Z" }));

    renderPage();

    const crumb = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumb).getByRole("link", { name: "Topics" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(
      within(crumb).getByText("topic-1 · first seen 20260826T090000Z"),
    ).toBeInTheDocument();
  });

  it("says a topic is new when no earlier run carried it", async () => {
    // `first_seen_run_id` is null when the slug matched nothing earlier.
    // "first seen null" would be a bug on screen.
    serve(makeTopicDetail({ firstSeenRunId: null, runCount: 1 }));

    renderPage();

    const crumb = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumb).getByText("topic-1 · new this run")).toBeInTheDocument();
  });

  it("shows the three header stats", async () => {
    serve(
      makeTopicDetail({ trendScore: 0.91, memePotential: 0.86, finalRank: 2 }),
    );

    renderPage();

    const stats = await screen.findByTestId("stats");
    expect(within(stats).getByText("0.91")).toBeInTheDocument();
    expect(within(stats).getByText("0.86")).toBeInTheDocument();
    expect(within(stats).getByText("2")).toBeInTheDocument();
  });

  it("draws the dossier prose and its entity chips", async () => {
    serve(
      makeTopicDetail({
        dossier: makeDossier({
          what_happened: "A cat got loose in an airport terminal.",
          conversation_summary: "Everyone is writing its incident report.",
          key_entities: ["the cat", "ground staff"],
        }),
      }),
    );

    renderPage();

    expect(
      await screen.findByText("A cat got loose in an airport terminal."),
    ).toBeInTheDocument();
    expect(screen.getByText("Everyone is writing its incident report.")).toBeInTheDocument();
    expect(screen.getByText("the cat")).toBeInTheDocument();
    expect(screen.getByText("ground staff")).toBeInTheDocument();
  });

  it("lists the score components under the conversation card", async () => {
    serve(
      makeTopicDetail({ scoreComponents: { bluesky: 0.91, corroboration: 1.0 } }),
    );

    renderPage();

    expect(
      await screen.findByText("score_components · bluesky 0.91 · corroboration 1.00"),
    ).toBeInTheDocument();
  });

  it("still renders when the topic has no dossier", async () => {
    // The dormant path and a stale checkpoint both give dossier=null. The
    // topic was still ranked, so the row still exists and the page must not
    // blank out.
    serve(makeTopicDetail({ dossier: null, scoreComponents: {} }));

    renderPage();

    expect(await screen.findByRole("heading", { name: "Airport cat" })).toBeInTheDocument();
    expect(screen.getByText("No dossier was written for this topic.")).toBeInTheDocument();
  });

  it("shows the replies with their likes, and says no handles are stored", async () => {
    serve(
      makeTopicDetail({
        replies: [
          {
            text: "ground control to major tom",
            like_count: 1412,
            created_at: "2026-08-29T14:31:00Z",
          },
        ],
      }),
    );

    renderPage();

    expect(await screen.findByText("ground control to major tom")).toBeInTheDocument();
    expect(screen.getByText("1,412 likes · 14:31")).toBeInTheDocument();
    expect(screen.getByText(/no handles stored/i)).toBeInTheDocument();
  });

  it("ranks the recurring phrases and reports the threshold that filtered them", async () => {
    serve(
      makeTopicDetail({
        dossier: makeDossier({
          recurring_phrases: [
            { text: "absolute unit", occurrences: 48, distinct_authors: 31 },
            { text: "ground control", occurrences: 22, distinct_authors: 14 },
          ],
        }),
      }),
    );

    renderPage();

    expect(await screen.findByText("absolute unit")).toBeInTheDocument();
    expect(screen.getByText("48× · 31 authors")).toBeInTheDocument();
    // The run's own frozen threshold, from RunDetail — TopicDetail does not
    // carry the config, and the count of phrases *below* it is nowhere in
    // the contract, so the line names the threshold rather than a total.
    expect(screen.getByText("filtered at phrase_min_authors=3")).toBeInTheDocument();
  });

  it("draws a tile per render, linked to its full-size view", async () => {
    serve(
      makeTopicDetail({
        renders: [
          makeRenderRecord({ id: "r1", templateId: "drake" }),
          makeRenderRecord({ id: "r2", templateId: "two_buttons" }),
        ],
      }),
    );

    renderPage();

    expect(await screen.findByAltText("drake meme")).toBeInTheDocument();
    const links = screen.getAllByRole("link");
    expect(
      links.some((link) => link.getAttribute("href") === `/runs/${RUN_ID}/renders/r1`),
    ).toBe(true);
  });

  it("says how many memes came from which run", async () => {
    serve(
      makeTopicDetail({
        renders: [makeRenderRecord({ id: "r1" }), makeRenderRecord({ id: "r2" })],
      }),
    );

    renderPage();

    expect(await screen.findByText("2 from …829T090000Z")).toBeInTheDocument();
  });

  it("shows only the renders that have an image behind them", async () => {
    // A `generating` row has no PNG yet and a `failed` one never will.
    // Phase 7 draws both states; this phase draws neither, so a tile with
    // nothing behind it must not appear.
    serve(
      makeTopicDetail({
        renders: [
          makeRenderRecord({ id: "r1", status: "ready" }),
          makeRenderRecord({ id: "r2", status: "generating" }),
          makeRenderRecord({ id: "r3", status: "failed", error: "caption too long" }),
        ],
      }),
    );

    renderPage();

    expect(await screen.findByText("1 from …829T090000Z")).toBeInTheDocument();
    expect(screen.getAllByRole("img")).toHaveLength(1);
  });

  it("draws no render section at all when nothing has rendered yet", async () => {
    // Not the same as hiding the tiles: an empty section would show the
    // label and a "0 from …" hint under it, which is a worse answer than
    // saying nothing. Phase 7 replaces this with the designed dashed row.
    serve(makeTopicDetail({ renders: [] }));

    renderPage();

    await screen.findByRole("heading", { name: "Airport cat" });
    expect(screen.queryByText("Rendered from this topic")).not.toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("says which topic is missing rather than showing an empty page", async () => {
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json({ detail: "No such topic" }, { status: 404 }),
      ),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
    );

    renderPage();

    expect(await screen.findByText("No such topic in this run.")).toBeInTheDocument();
  });
});
