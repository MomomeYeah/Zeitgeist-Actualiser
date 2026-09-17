import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import type { SettingField } from "@/api/types";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { apiKeyField, makeConfigOptions, makeSettingFields } from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

function settingsHandler(fields: SettingField[]) {
  return [
    http.get("/api/settings", () => HttpResponse.json(fields)),
    http.get("/api/config/options", () => HttpResponse.json(makeConfigOptions())),
  ];
}

/** Every `PUT` body the screen sent, in order. */
function captureSaves(fields: SettingField[]): unknown[] {
  const saved: unknown[] = [];
  server.use(
    http.put("/api/settings", async ({ request }) => {
      saved.push(await request.json());
      return HttpResponse.json(fields);
    }),
  );
  return saved;
}

describe("SettingsPage", () => {
  it("draws global fields and run defaults under separate headings", async () => {
    server.use(...settingsHandler(makeSettingFields()));

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    expect(
      await screen.findByRole("heading", { name: /global/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /defaults for new runs/i }),
    ).toBeInTheDocument();
  });

  it("shows an unset API key as not set, with no value in the document", async () => {
    server.use(...settingsHandler([apiKeyField({ source: "default" })]));

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    expect(await screen.findByText(/not set/i)).toBeInTheDocument();
    expect(screen.getByLabelText("anthropic_api_key")).toHaveValue("");
  });

  it("sends a typed API key and does not send the untouched fields beside it", async () => {
    /* The bug this guards is the one the existing `changedValues` comment
       describes: sending every field writes a row for each, pinning values
       that were only ever defaults. */
    const user = userEvent.setup();
    const fields = makeSettingFields();
    server.use(...settingsHandler(fields));
    const saved = captureSaves(fields);

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    await user.type(
      await screen.findByLabelText("anthropic_api_key"),
      "sk-ant-typed",
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(saved).toEqual([{ values: { anthropic_api_key: "sk-ant-typed" } }]),
    );
  });

  it("clears a stored API key", async () => {
    /* `changedValues` drops every empty draft, so a Clear routed through the
       draft map can never reach the wire — this is the test that says so.
       `onClear` must put the `""` into the payload by another route. */
    const user = userEvent.setup();
    const fields = [apiKeyField({ source: "settings" })];
    server.use(...settingsHandler(fields));
    const saved = captureSaves(fields);

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    await user.click(await screen.findByRole("button", { name: "Clear" }));

    await waitFor(() =>
      expect(saved).toEqual([{ values: { anthropic_api_key: "" } }]),
    );
  });

  it("offers no Clear for a key that was never set", async () => {
    /* The negative half. A Clear rendered unconditionally would pass the test
       above while inviting a no-op click on a key there is nothing to clear. */
    server.use(...settingsHandler([apiKeyField({ source: "default" })]));

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    expect(await screen.findByText(/not set/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();
  });

  it("treats a reformatted number as unchanged but a real edit as changed", async () => {
    /* Both halves together: an implementation comparing raw strings passes
       the second assertion and fails the first, and one that never compares
       at all passes the first and fails the second. */
    const user = userEvent.setup();
    const fields = makeSettingFields();
    server.use(...settingsHandler(fields));
    const saved = captureSaves(fields);

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    const input = await screen.findByLabelText("meme_potential_weight");
    await user.clear(input);
    await user.type(input, "0.30");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    await user.clear(input);
    await user.type(input, "0.45");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(saved).toEqual([{ values: { meme_potential_weight: "0.45" } }]),
    );
  });

  it("compares a string field textually rather than numerically", async () => {
    /* `Number("http://...")` is NaN, so a numeric-only comparison would
       decide every host edit was unchanged and silently disable Save. */
    const user = userEvent.setup();
    const fields = makeSettingFields();
    server.use(...settingsHandler(fields));
    const saved = captureSaves(fields);

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    const input = await screen.findByLabelText("ollama_host");
    await user.clear(input);
    await user.type(input, "http://10.0.0.2:11434");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(saved).toEqual([{ values: { ollama_host: "http://10.0.0.2:11434" } }]),
    );
  });

  it("saves the run defaults the config cards own, under their setting names", async () => {
    /* Four of the fourteen settable keys are reachable only through the cards,
       and `RunConfig` and `Settings` use different names for them —
       `top_count` against `topic_count`, `trend_limit` against
       `bluesky_trend_limit`. A card wired to the `RunConfig` vocabulary would
       `PUT` keys the endpoint rejects, so this asserts the wire format rather
       than the card's own state. */
    const user = userEvent.setup();
    const fields = makeSettingFields();
    server.use(...settingsHandler(fields));
    const saved = captureSaves(fields);

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    await user.click(await screen.findByRole("button", { name: "ollama" }));
    await user.click(screen.getByRole("radio", { name: "qwen3.5:latest" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(saved).toEqual([
        { values: { llm_provider: "ollama", llm_model: "qwen3.5:latest" } },
      ]),
    );
  });

  it("seeds the cards from the stored run defaults rather than from their own defaults", async () => {
    /* A card that ignored the `GET` and started from its component default
       would show "anthropic / claude-sonnet-5" over a database saying
       otherwise, and Save would then be disabled on a screen that disagrees
       with what the next run will use. */
    server.use(
      ...settingsHandler(
        makeSettingFields({
          llm_provider: { value: "ollama", source: "settings" },
          llm_model: { value: "qwen3.5:latest", source: "settings" },
          topic_count: { value: 10, source: "settings" },
        }),
      ),
    );

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    expect(await screen.findByRole("button", { name: "ollama" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("radio", { name: "qwen3.5:latest" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("button", { name: "10" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("resets every settable field except the API key", async () => {
    /* The keys written out, not an `every` over the values: `Object.values({})
       .every(...)` is `true`, so a Reset that sent an empty payload — or only
       the fields already drafted — would pass an `every` check while
       resetting nothing.

       Thirteen, not fourteen. `anthropic_api_key` is deliberately exempt:
       losing your key to a button labelled "Reset to defaults" is a trap, and
       the secret row's own Clear is the explicit way to do it. */
    const user = userEvent.setup();
    const fields = makeSettingFields();
    server.use(...settingsHandler(fields));
    const saved = captureSaves(fields);

    renderWithProviders(<SettingsPage />, { route: "/settings" });
    await screen.findByLabelText("phrase_min_authors");

    await user.click(screen.getByRole("button", { name: "Reset to defaults" }));

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]).toEqual({
      values: {
        bluesky_fetch_concurrency: "",
        bluesky_posts_per_trend: "",
        bluesky_trend_limit: "",
        distil_char_budget: "",
        distil_concurrency: "",
        font_path: "",
        llm_model: "",
        llm_provider: "",
        meme_potential_weight: "",
        ollama_host: "",
        phrase_min_authors: "",
        sources: "",
        topic_count: "",
      },
    });
  });
});
