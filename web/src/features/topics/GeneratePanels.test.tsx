import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { RenderRecord, TemplateOption } from "@/api/types";
import { TopicDetailPage } from "@/features/topics/TopicDetailPage";
import {
  makeConfigOptions,
  makeRenderRecord,
  makeRunDetail,
  makeTopicDetail,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

const RUN_ID = "20260829T090000Z";
const TOPIC_ID = "topic-1";

interface Served {
  /** Every body the page posted, in order. */
  posted: unknown[];
  /** Let a held POST answer. */
  release: () => void;
}

/**
 * Topic detail, its run, the template library, and the renders endpoint,
 * with the topic's renders held as server state so the page's poll and the
 * panels' posts agree about what exists.
 *
 * A fixture that answered every GET with the same list would take back the
 * rows a post had just added the moment the page polled for them, and a
 * test asserting on those rows would be asserting on the fixture.
 */
function serveTopic(
  options: {
    topic?: Parameters<typeof makeTopicDetail>[0];
    templates?: TemplateOption[];
    /** The topic's renders before anything is posted. None by default. */
    initial?: RenderRecord[];
    /** The rows each accepted POST creates. */
    created?: RenderRecord[];
    /** Hold every POST until `release()` is called. */
    hold?: boolean;
    /** Refuse every POST with this 400 detail. */
    refuse?: string;
  } = {},
): Served {
  let renders: RenderRecord[] = options.initial ?? [];
  const posted: unknown[] = [];
  let release: () => void = () => undefined;
  const gate =
    options.hold === true
      ? new Promise<void>((resolve) => {
          release = resolve;
        })
      : Promise.resolve();

  server.use(
    http.get("/api/runs/:runId/topics/:topicId", () =>
      HttpResponse.json(makeTopicDetail({ ...options.topic, renders })),
    ),
    http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
    http.get("/api/config/options", () =>
      HttpResponse.json(makeConfigOptions({ templates: options.templates })),
    ),
    http.post("/api/runs/:runId/topics/:topicId/renders", async ({ request }) => {
      posted.push(await request.json());
      await gate;
      if (options.refuse !== undefined) {
        return HttpResponse.json({ detail: options.refuse }, { status: 400 });
      }
      const created = options.created ?? [];
      renders = [...renders, ...created];
      return HttpResponse.json(created, { status: 202 });
    }),
  );
  return { posted, release: () => release() };
}

function renderPage() {
  return renderWithProviders(<TopicDetailPage />, {
    route: `/topics/${RUN_ID}/${TOPIC_ID}`,
    path: "/topics/:runId/:topicId",
  });
}

/** What the server seeds for "Generate 3 memes" with the model choosing. */
function threeGenerating(): RenderRecord[] {
  return ["new-1", "new-2", "new-3"].map((id) =>
    makeRenderRecord({
      id,
      status: "generating",
      templateId: null,
      captionSlots: {},
      rationale: "",
    }),
  );
}

describe("Ask the LLM", () => {
  it("leaves the template to the model by default, and says what it will choose for", async () => {
    // Not the factory's funny / riffing, which is also the mockup's copy
    // word for word: a panel that printed the mockup's sentence would pass
    // with those.
    serveTopic({ topic: { sentiment: "cute", register: "delight" } });
    renderPage();

    expect(await screen.findByRole("radio", { name: /Let the LLM choose/ })).toBeChecked();
    expect(
      screen.getByText("picks the templates that suit cute / delight"),
    ).toBeInTheDocument();
  });

  it("says it will choose for the topic itself when no mood was recorded", async () => {
    // The dormant path writes no dossier, so no sentiment and no register.
    // "suit " followed by nothing would be a sentence with a hole in it.
    serveTopic({
      topic: { sentiment: null, register: null, dossier: null, scoreComponents: {} },
    });
    renderPage();

    expect(
      await screen.findByText("picks the templates that suit this topic"),
    ).toBeInTheDocument();
  });

  it("offers every template in the library as an override, with its slot count", async () => {
    // Driven by the loaded manifests, not by the four the handoff drew. One
    // slot reads "1 slot": phase 5's walk found a "1 memes".
    serveTopic({
      templates: [
        { id: "drake", slots: ["rejected", "preferred"] },
        { id: "single", slots: ["caption"] },
      ],
    });
    renderPage();

    const panel = within(await screen.findByRole("region", { name: "Ask the LLM" }));
    expect(panel.getByRole("radio", { name: /^drake/ })).not.toBeChecked();
    expect(panel.getByText("2 slots")).toBeInTheDocument();
    expect(panel.getByRole("radio", { name: /^single/ })).not.toBeChecked();
    expect(panel.getByText("1 slot")).toBeInTheDocument();
  });

  it("generates three by default, and the button says how many", async () => {
    serveTopic();
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("button", { name: "Generate 3 memes" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "1" }));
    expect(screen.getByRole("button", { name: "Generate 1 meme" })).toBeInTheDocument();
  });

  it("posts no template when the model is left to choose", async () => {
    const served = serveTopic({ created: threeGenerating() });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Generate 3 memes" }));

    await waitFor(() =>
      expect(served.posted).toEqual([{ mode: "llm", template_id: null, count: 3 }]),
    );
  });

  it("posts the template picked as an override", async () => {
    const served = serveTopic({
      created: [makeRenderRecord({ id: "new-1", status: "generating", captionSlots: {} })],
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("radio", { name: /^drake/ }));
    await user.click(screen.getByRole("button", { name: "1" }));
    await user.click(screen.getByRole("button", { name: "Generate 1 meme" }));

    await waitFor(() =>
      expect(served.posted).toEqual([{ mode: "llm", template_id: "drake", count: 1 }]),
    );
  });

  it("posts no template again once the choice is handed back to the model", async () => {
    // The default is also a choice someone can come back to. A "Let the
    // LLM choose" row that did not clear the tile picked before it would
    // keep posting that tile.
    const served = serveTopic({ created: threeGenerating() });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("radio", { name: /^drake/ }));
    await user.click(screen.getByRole("radio", { name: /Let the LLM choose/ }));
    await user.click(screen.getByRole("button", { name: "Generate 3 memes" }));

    await waitFor(() =>
      expect(served.posted).toEqual([{ mode: "llm", template_id: null, count: 3 }]),
    );
  });

  it("still draws what was rendered when the template library cannot be read", async () => {
    // The panels need the library; the grid does not. A failure loading one
    // must not take the other down with it — the renders are still there
    // to look at and delete.
    serveTopic({ initial: [makeRenderRecord({ id: "r1", templateId: "drake" })] });
    server.use(
      http.get("/api/config/options", () =>
        HttpResponse.json({ detail: "templates_dir does not exist" }, { status: 500 }),
      ),
    );
    renderPage();

    expect(await screen.findByText("templates_dir does not exist")).toBeInTheDocument();
    expect(screen.getByAltText("drake meme")).toBeInTheDocument();
  });

  it("draws a placeholder per meme the moment it is asked for, then the rows the server made", async () => {
    const served = serveTopic({ created: threeGenerating(), hold: true });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Generate 3 memes" }));

    // Before the server has answered: three placeholders, none of them
    // cancellable, because there is no row yet to cancel.
    expect(await screen.findAllByText("writing brief…")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: "Cancel render" })).not.toBeInTheDocument();

    served.release();

    // The server's own rows, which can be cancelled — and still three, not
    // three placeholders plus three rows.
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "Cancel render" })).toHaveLength(3),
    );
    expect(screen.getAllByText("writing brief…")).toHaveLength(3);
  });

  it("will not post a second request while the first is on its way", async () => {
    // Each meme is a model call. A button still armed while its request is
    // in flight turns a double-click into twice the calls and the tiles.
    const served = serveTopic({ created: threeGenerating(), hold: true });
    const user = userEvent.setup();
    renderPage();

    const generate = await screen.findByRole("button", { name: "Generate 3 memes" });
    await user.click(generate);
    await waitFor(() => expect(generate).toBeDisabled());
    await user.click(generate);

    served.release();
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "Cancel render" })).toHaveLength(3),
    );
    expect(served.posted).toHaveLength(1);
  });

  it("shows the server's reason when it will not generate, and leaves nothing drawn", async () => {
    serveTopic({ refuse: "ANTHROPIC_API_KEY is required for the anthropic provider" });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Generate 3 memes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "ANTHROPIC_API_KEY is required for the anthropic provider",
    );
    expect(screen.queryByText("writing brief…")).not.toBeInTheDocument();
    expect(
      screen.getByText("Nothing rendered yet — use the panel above"),
    ).toBeInTheDocument();
  });
});
