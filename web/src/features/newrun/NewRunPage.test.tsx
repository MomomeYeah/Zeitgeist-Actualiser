import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { AppRoutes } from "@/app/routes";
import { NewRunPage } from "@/features/newrun/NewRunPage";
import {
  makeActiveRuns,
  makeConfigOptions,
  makeQueuedRun,
  makeRunDetail,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

function options(overrides = {}) {
  return http.get("/api/config/options", () =>
    HttpResponse.json(makeConfigOptions(overrides)),
  );
}

function idle() {
  return http.get("/api/runs/active", () =>
    HttpResponse.json(makeActiveRuns({ current: null })),
  );
}

describe("NewRunPage", () => {
  it("swaps the model list when the provider changes", async () => {
    // The one behaviour the handoff calls out in bold. Ollama shows local
    // model tags, not Claude ids.
    const user = userEvent.setup();
    server.use(options(), idle());

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });
    expect(await screen.findByRole("radio", { name: /claude-opus-5/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "ollama" }));

    expect(screen.getByRole("radio", { name: /qwen3.5:latest/ })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /claude-opus-5/ })).not.toBeInTheDocument();
  });

  it("selects a model from the new provider when the old one does not exist there", async () => {
    // Otherwise the form would post `claude-sonnet-5` to ollama, and the
    // run would fail on the worker thread with a model nobody chose.
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      options(),
      idle(),
      http.post("/api/runs", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeQueuedRun(), { status: 202 });
      }),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });
    await screen.findByRole("button", { name: "ollama" });

    await user.click(screen.getByRole("button", { name: "ollama" }));
    await user.click(screen.getByRole("button", { name: /Start run/ }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent).toMatchObject({
      overrides: { llm_provider: "ollama", llm_model: "qwen3.5:latest" },
    });
  });

  it("shows the dormant platforms without letting them be picked", async () => {
    const user = userEvent.setup();
    server.use(options(), idle());

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    const lemmy = await screen.findByRole("radio", { name: /lemmy/ });
    expect(lemmy).toBeDisabled();
    expect(within(lemmy).getByText("dormant · no clustering")).toBeInTheDocument();

    await user.click(lemmy);
    expect(screen.getByRole("radio", { name: /bluesky/ })).toBeChecked();
  });

  it("warns when the Anthropic key is missing", async () => {
    server.use(options({ anthropicKeyPresent: false }), idle());

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    expect(
      await screen.findByText("ANTHROPIC_API_KEY is not set · this run would fail"),
    ).toBeInTheDocument();
  });

  it("does not warn when the key is there", async () => {
    // The negative case, because a card that ignored `keyPresent` and
    // always warned would pass the test above — and telling someone with a
    // working key that their run will fail is the worse of the two bugs.
    server.use(options({ anthropicKeyPresent: true }), idle());

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    expect(
      await screen.findByText("key present · ANTHROPIC_API_KEY"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("ANTHROPIC_API_KEY is not set · this run would fail"),
    ).not.toBeInTheDocument();
  });

  it("keeps the last good count when the custom box is emptied mid-edit", async () => {
    // `Number("")` is 0, and a run started with topic_count 0 renders
    // nothing. The box has to be allowed to be empty while someone retypes
    // it without the form reading the empty string as a number — which is
    // the whole reason `CountCard`'s guard exists, and nothing else here
    // touches the custom input at all.
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      options(),
      idle(),
      http.post("/api/runs", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeQueuedRun(), { status: 202 });
      }),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    const custom = await screen.findByLabelText("custom count");
    await user.type(custom, "7");
    await user.clear(custom);
    await user.click(screen.getByRole("button", { name: /Start run/ }));

    await waitFor(() =>
      expect(sent).toMatchObject({ overrides: { topic_count: "7" } }),
    );
  });

  it("sends the custom count that was typed, even one that starts like a preset", async () => {
    // Found by the final review. The box rendered the committed count only
    // while it matched no preset, so the "1" of "12" selected the 1 pill,
    // the box emptied under the cursor, and the "2" landed alone: the form
    // posted 2 for a box that had been typed 12.
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      options(),
      idle(),
      http.post("/api/runs", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeQueuedRun(), { status: 202 });
      }),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    const custom = await screen.findByLabelText("custom count");
    await user.type(custom, "12");
    await user.click(screen.getByRole("button", { name: /Start run/ }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent).toMatchObject({ overrides: { topic_count: "12" } });
    expect(custom).toHaveValue(12);
  });

  it("never sends a fractional count, keeping the last whole one typed", async () => {
    // The pipeline briefs a whole number of topics. "2.5" used to be
    // committed to the form as 2.5, and the only thing between it and
    // `topic_count: "2.5"` was the input's own step check — which refused
    // the submit outright, so the run would not start at all. Now the draft
    // is committed only as a whole number, and leaving the box puts back
    // the count that will actually be sent.
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      options(),
      idle(),
      http.post("/api/runs", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeQueuedRun(), { status: 202 });
      }),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    const custom = await screen.findByLabelText("custom count");
    await user.type(custom, "2.5");
    await user.click(screen.getByRole("button", { name: /Start run/ }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent).toMatchObject({ overrides: { topic_count: "2" } });
    expect(JSON.stringify(sent)).not.toContain("2.5");
    expect(custom).toHaveValue(2);
  });

  it("clears the custom box when a preset is picked after it", async () => {
    // The box holds its own draft now, so picking a pill has to empty it:
    // a box still reading 12 beside a lit 3 would leave two answers on
    // screen and only one of them sent.
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      options(),
      idle(),
      http.post("/api/runs", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeQueuedRun(), { status: 202 });
      }),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    const custom = await screen.findByLabelText("custom count");
    await user.type(custom, "12");
    await user.click(screen.getByRole("button", { name: "3" }));

    expect(custom).toHaveValue(null);
    expect(screen.getByRole("button", { name: "3" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: /Start run/ }));
    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent).toMatchObject({ overrides: { topic_count: "3" } });
  });

  it("sends null template ids for the whole library", async () => {
    // `all N` is not an explicit list of every template: null is what the
    // pipeline reads as "the whole library", and stays right as the
    // library changes.
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      options(),
      idle(),
      http.post("/api/runs", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeQueuedRun(), { status: 202 });
      }),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });
    await user.click(await screen.findByRole("button", { name: /Start run/ }));

    await waitFor(() => expect(sent).toMatchObject({ template_ids: null }));
  });

  it("names the count of templates it actually has", async () => {
    // The handoff says `all 4`; the repository ships a different number.
    // The chip is driven by the loaded manifests so it stays true.
    server.use(options(), idle());

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    expect(await screen.findByRole("button", { name: "all 2" })).toBeInTheDocument();
  });

  it("sends the templates that were chosen instead", async () => {
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      options(),
      idle(),
      http.post("/api/runs", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeQueuedRun(), { status: 202 });
      }),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });
    await user.click(await screen.findByRole("button", { name: "drake" }));
    await user.click(screen.getByRole("button", { name: /Start run/ }));

    await waitFor(() => expect(sent).toMatchObject({ template_ids: ["drake"] }));
  });

  it("says what a new run would queue behind", async () => {
    server.use(
      options(),
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: "20260829T140200Z" })),
      ),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    expect(
      await screen.findByText(
        "A run is already in flight. Starting this one queues it behind …829T140200Z.",
      ),
    ).toBeInTheDocument();
  });

  it("goes to the run it just started", async () => {
    const user = userEvent.setup();
    server.use(
      options(),
      idle(),
      http.post("/api/runs", () =>
        HttpResponse.json(makeQueuedRun({ runId: "20260829T150000Z" }), { status: 202 }),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({ runId: "20260829T150000Z", status: "running" }),
        ),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
    );

    renderWithProviders(<AppRoutes />, { route: "/runs/new" });
    await user.click(await screen.findByRole("button", { name: /Start run/ }));

    expect(await screen.findByText("20260829T150000Z")).toBeInTheDocument();
  });

  it("prefills every card from the run it is re-running", async () => {
    server.use(
      options(),
      idle(),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({
            runId: "20260829T090000Z",
            config: {
              llm_provider: "ollama",
              llm_model: "qwen3.5:latest",
              top_count: 10,
              template_ids: ["drake"],
            },
          }),
        ),
      ),
    );

    renderWithProviders(<NewRunPage />, {
      route: "/runs/new?from=20260829T090000Z",
    });

    expect(await screen.findByRole("radio", { name: /qwen3.5:latest/ })).toBeChecked();
    expect(screen.getByRole("button", { name: "10" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "drake" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("sends the source run's frozen tunables as overrides when re-running", async () => {
    // The four cards come from form state (asserted elsewhere), but the six
    // tunables have no card of their own. Chosen to differ from every
    // default in makeConfigOptions, so a version reading current settings
    // instead of the preset would show up immediately.
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      options(),
      idle(),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({
            runId: "20260829T090000Z",
            config: {
              trend_limit: 5,
              posts_per_trend: 7,
              meme_potential_weight: 0.6,
              phrase_min_authors: 9,
              distil_char_budget: 12000,
              distil_concurrency: 2,
            },
          }),
        ),
      ),
      http.post("/api/runs", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeQueuedRun(), { status: 202 });
      }),
    );

    renderWithProviders(<NewRunPage />, {
      route: "/runs/new?from=20260829T090000Z",
    });
    await user.click(await screen.findByRole("button", { name: /Start run/ }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent).toMatchObject({
      overrides: {
        bluesky_trend_limit: "5",
        bluesky_posts_per_trend: "7",
        meme_potential_weight: "0.6",
        phrase_min_authors: "9",
        distil_char_budget: "12000",
        distil_concurrency: "2",
      },
    });
  });

  it("sends none of the six frozen tunables on a fresh run", async () => {
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      options(),
      idle(),
      http.post("/api/runs", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeQueuedRun(), { status: 202 });
      }),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });
    await user.click(await screen.findByRole("button", { name: /Start run/ }));

    await waitFor(() => expect(sent).not.toBeNull());
    const json = JSON.stringify(sent);
    for (const key of [
      "bluesky_trend_limit",
      "bluesky_posts_per_trend",
      "meme_potential_weight",
      "phrase_min_authors",
      "distil_char_budget",
      "distil_concurrency",
    ]) {
      expect(json).not.toContain(key);
    }
  });

  it("shows the frozen trend limit in the count card's note, not settings' current default", async () => {
    server.use(
      options(),
      idle(),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(makeRunDetail({ config: { trend_limit: 5 } })),
      ),
    );

    renderWithProviders(<NewRunPage />, {
      route: "/runs/new?from=20260829T090000Z",
    });

    expect(await screen.findByText("of 5 trends analysed")).toBeInTheDocument();
  });

  it("lets an edited card win over the preset it was seeded from", async () => {
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      options(),
      idle(),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(makeRunDetail({ config: { top_count: 10 } })),
      ),
      http.post("/api/runs", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeQueuedRun(), { status: 202 });
      }),
    );

    renderWithProviders(<NewRunPage />, {
      route: "/runs/new?from=20260829T090000Z",
    });

    expect(await screen.findByRole("button", { name: "10" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "3" }));
    await user.click(screen.getByRole("button", { name: /Start run/ }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent).toMatchObject({ overrides: { topic_count: "3" } });
  });

  it("says defaults come from settings on a fresh form, with a link there", async () => {
    server.use(options(), idle());

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    expect(
      await screen.findByRole("link", { name: "settings" }),
    ).toHaveAttribute("href", "/settings");
  });

  it("says it is re-running a run's frozen config, with no settings link", async () => {
    server.use(
      options(),
      idle(),
      http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
    );

    renderWithProviders(<NewRunPage />, {
      route: "/runs/new?from=20260829T090000Z",
    });

    expect(
      await screen.findByText(
        "re-running …829T090000Z · its frozen config fills every field · changes apply to this run only",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "settings" })).not.toBeInTheDocument();
  });

  it("says so when the run to re-run does not exist, and offers a fresh form", async () => {
    // `?from=` naming no run 404s, and the page used to wait on
    // `source.data` alone — "Loading that run's config…" stayed up for good
    // because nothing ever read `source.error`.
    server.use(
      options(),
      idle(),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json({ detail: "No such run: nope" }, { status: 404 }),
      ),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new?from=nope" });

    expect(await screen.findByText("No such run to re-run.")).toBeInTheDocument();
    expect(screen.queryByText("Loading that run's config…")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start a fresh run instead" })).toHaveAttribute(
      "href",
      "/runs/new",
    );
  });

  it("reports any other failure to read the run with the server's own words", async () => {
    // Not "No such run": a 500 is the server's problem, not a mistyped id,
    // and saying the run is missing would send someone looking for it.
    server.use(
      options(),
      idle(),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json({ detail: "database is locked" }, { status: 500 }),
      ),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new?from=20260829T090000Z" });

    expect(await screen.findByText("database is locked")).toBeInTheDocument();
    expect(screen.queryByText("No such run to re-run.")).not.toBeInTheDocument();
  });

  it("reports a refused start rather than navigating", async () => {
    const user = userEvent.setup();
    server.use(
      options(),
      idle(),
      http.post("/api/runs", () =>
        HttpResponse.json({ detail: "Not settable per run: db_path" }, { status: 400 }),
      ),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });
    await user.click(await screen.findByRole("button", { name: /Start run/ }));

    expect(
      await screen.findByText("Not settable per run: db_path"),
    ).toBeInTheDocument();
  });
});
