import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { TopicDetail } from "@/api/types";
import { TopicDetailPage } from "@/features/topics/TopicDetailPage";
import {
  makeConfigOptions,
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
    http.get("/api/config/options", () => HttpResponse.json(makeConfigOptions())),
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

  it("says a topic is new when the run it was first seen in is this one", async () => {
    // A topic only this run has carried is first seen here, and the store
    // answers with this run's own id rather than null. "First seen" then
    // points at the run you are already looking at, which reads as a
    // second, earlier sighting that does not exist.
    serve(
      makeTopicDetail({
        runId: RUN_ID,
        firstSeenRunId: RUN_ID,
        runCount: 1,
      }),
    );

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

  it("takes a deleted render off the page, and leaves the others", async () => {
    // "The tile disappearing is the confirmation", per the handoff. The
    // server's list shrinks with the deletion, so the refetch that follows
    // agrees with what the page already drew.
    let renders = [
      makeRenderRecord({ id: "r1", templateId: "drake" }),
      makeRenderRecord({ id: "r2", templateId: "two_buttons" }),
    ];
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json(makeTopicDetail({ renders })),
      ),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
      http.get("/api/config/options", () => HttpResponse.json(makeConfigOptions())),
      http.delete("/api/renders/:renderId", ({ params }) => {
        renders = renders.filter((render) => render.id !== params.renderId);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    const tile = (await screen.findByAltText("drake meme")).closest("li");
    if (!(tile instanceof HTMLElement)) throw new Error("drake's tile is not a list item");
    await user.click(within(tile).getByRole("button", { name: "Delete render" }));
    await user.click(within(tile).getByRole("button", { name: "yes" }));

    await waitFor(() => expect(screen.queryByAltText("drake meme")).not.toBeInTheDocument());
    expect(screen.getByAltText("two_buttons meme")).toBeInTheDocument();
  });

  it("puts focus back on the grid when the tile holding it is deleted", async () => {
    // The `✕` that was focused unmounts with its tile, and focus would
    // otherwise fall to the top of the document — a keyboard user would
    // have to tab back through the whole page to reach the next tile.
    let renders = [makeRenderRecord({ id: "r1", templateId: "drake" })];
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json(makeTopicDetail({ renders })),
      ),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
      http.get("/api/config/options", () => HttpResponse.json(makeConfigOptions())),
      http.delete("/api/renders/:renderId", ({ params }) => {
        renders = renders.filter((render) => render.id !== params.renderId);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Delete render" }));
    await user.click(screen.getByRole("button", { name: "yes" }));

    await waitFor(() =>
      expect(screen.queryByAltText("drake meme")).not.toBeInTheDocument(),
    );
    const anchor = screen
      .getByText("Rendered from this topic")
      .closest('div[tabindex="-1"]');
    expect(anchor).toHaveFocus();
  });

  it("stays open on the next render when one is deleted from the modal", async () => {
    // What paging is for: clearing three duds out of seven costs one open
    // and three clicks, not three of each. The row genuinely leaves the
    // cache here, which is why this lives on the screen rather than in
    // `RenderGrid.test.tsx` — that harness holds a fixed list, so there the
    // deleted tile never actually goes.
    let renders = [
      makeRenderRecord({ id: "r1", templateId: "drake" }),
      makeRenderRecord({ id: "r2", templateId: "two_buttons" }),
    ];
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json(makeTopicDetail({ renders })),
      ),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
      http.get("/api/config/options", () => HttpResponse.json(makeConfigOptions())),
      http.delete("/api/renders/:renderId", ({ params }) => {
        renders = renders.filter((render) => render.id !== params.renderId);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByAltText("drake meme"));
    const dialog = await screen.findByRole("dialog", { name: "drake" });
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "yes" }));

    // The modal is still up, on the render that took the deleted one's
    // place, and the counter has shrunk with the list.
    expect(await screen.findByRole("dialog", { name: "two_buttons" })).toBeInTheDocument();
    expect(screen.queryByAltText("drake meme")).not.toBeInTheDocument();
    // One render left, so there is nothing to page to any more.
    expect(screen.queryByRole("button", { name: "Next render" })).not.toBeInTheDocument();
  });

  it("closes the modal and lands focus on the grid when the last render goes", async () => {
    // The one case where `Modal` cannot hand focus back: the tile it would
    // return it to has unmounted with the row, and a detached node cannot
    // take focus, so it would fall to the top of the document.
    let renders = [makeRenderRecord({ id: "r1", templateId: "drake" })];
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json(makeTopicDetail({ renders })),
      ),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
      http.get("/api/config/options", () => HttpResponse.json(makeConfigOptions())),
      http.delete("/api/renders/:renderId", ({ params }) => {
        renders = renders.filter((render) => render.id !== params.renderId);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByAltText("drake meme"));
    const dialog = await screen.findByRole("dialog", { name: "drake" });
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "yes" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.queryByAltText("drake meme")).not.toBeInTheDocument();
    const anchor = screen
      .getByText("Rendered from this topic")
      .closest('div[tabindex="-1"]');
    expect(anchor).toHaveFocus();
  });

  it("pages through the topic's renders from the modal", async () => {
    // End to end on the real screen, against the list the API actually
    // returned — including a failed row, which the arrows must be able to
    // land on and leave again.
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json(
          makeTopicDetail({
            renders: [
              makeRenderRecord({ id: "r1", templateId: "drake" }),
              makeRenderRecord({
                id: "f1",
                templateId: "two_buttons",
                status: "failed",
                error: "caption for rejected overflows its box",
              }),
            ],
          }),
        ),
      ),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
      http.get("/api/config/options", () => HttpResponse.json(makeConfigOptions())),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByAltText("drake meme"));
    expect(await screen.findByText("1 / 2")).toBeInTheDocument();

    await user.keyboard("{ArrowRight}");

    const dialog = screen.getByRole("dialog", { name: "two_buttons" });
    expect(
      within(dialog).getByText("caption for rejected overflows its box"),
    ).toBeInTheDocument();
    expect(screen.getByText("2 / 2")).toBeInTheDocument();

    await user.keyboard("{ArrowLeft}");

    expect(screen.getByRole("dialog", { name: "drake" })).toBeInTheDocument();
  });

  it("says which topic is missing rather than showing an empty page", async () => {
    server.use(
      http.get("/api/runs/:runId/topics/:topicId", () =>
        HttpResponse.json({ detail: "No such topic" }, { status: 404 }),
      ),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
      http.get("/api/config/options", () => HttpResponse.json(makeConfigOptions())),
    );

    renderPage();

    expect(await screen.findByText("No such topic in this run.")).toBeInTheDocument();
  });
});
