import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { SettingsPage } from "@/features/settings/SettingsPage";
import { makeSettingField, makeSettingFields } from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

describe("SettingsPage", () => {
  it("groups the seven writable fields into the three cards", async () => {
    server.use(
      http.get("/api/settings", () => HttpResponse.json(makeSettingFields())),
    );

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    expect(await screen.findByText("Fan-out")).toBeInTheDocument();
    expect(screen.getByText("Ranking")).toBeInTheDocument();
    expect(screen.getByText("Distillation")).toBeInTheDocument();
    expect(screen.getAllByRole("spinbutton")).toHaveLength(7);
  });

  it("names each field by the key a layer would actually match", async () => {
    // Not `trend_limit`. The environment variable, the .env line and the
    // settings row are all `bluesky_trend_limit`, and a screen whose whole
    // job is showing which layer won must not print a name no layer uses.
    server.use(
      http.get("/api/settings", () => HttpResponse.json(makeSettingFields())),
    );

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    expect(await screen.findByText("bluesky_trend_limit")).toBeInTheDocument();
    expect(screen.queryByText("trend_limit")).not.toBeInTheDocument();
  });

  it("says where each value came from, including the environment", async () => {
    // Four layers, though the design drew three. A shell variable outranks
    // the settings table, so `environment` is a real answer — and it is the
    // one state where saving cannot change what the next run uses.
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json([
          makeSettingField({ key: "phrase_min_authors", source: "settings" }),
          makeSettingField({ key: "distil_concurrency", source: "environment" }),
          makeSettingField({ key: "distil_char_budget", source: "dotenv" }),
          makeSettingField({ key: "meme_potential_weight", source: "default" }),
        ]),
      ),
    );

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    expect(await screen.findByText("SET HERE")).toBeInTheDocument();
    expect(screen.getByText("FROM ENV")).toBeInTheDocument();
    expect(screen.getByText("FROM .env")).toBeInTheDocument();
    expect(screen.getByText("DEFAULT")).toBeInTheDocument();
  });

  it("carries the API ceiling on the field that has one", async () => {
    server.use(
      http.get("/api/settings", () => HttpResponse.json(makeSettingFields())),
    );

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    expect(await screen.findByText("max 25 · API ceiling")).toBeInTheDocument();
  });

  it("saves only the fields that were edited", async () => {
    // Sending all seven would write a settings row for every one of them,
    // pinning six values that were only ever defaults — and a later .env
    // edit would then be invisible.
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      http.get("/api/settings", () => HttpResponse.json(makeSettingFields())),
      http.put("/api/settings", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeSettingFields());
      }),
    );

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    const field = await screen.findByLabelText("phrase_min_authors");
    await user.clear(field);
    await user.type(field, "9");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(sent).toEqual({ values: { phrase_min_authors: "9" } }),
    );
  });

  it("resets every field to its .env value by clearing the rows", async () => {
    // An empty string deletes the row so the fallback applies again.
    // Writing the default back would pin the value and make a later .env
    // edit invisible — the endpoint's own reasoning, honoured here.
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      http.get("/api/settings", () => HttpResponse.json(makeSettingFields())),
      http.put("/api/settings", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeSettingFields());
      }),
    );

    renderWithProviders(<SettingsPage />, { route: "/settings" });
    await screen.findByLabelText("phrase_min_authors");

    await user.click(screen.getByRole("button", { name: "Reset to .env" }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent).toEqual({
      values: {
        bluesky_fetch_concurrency: "",
        bluesky_posts_per_trend: "",
        bluesky_trend_limit: "",
        distil_char_budget: "",
        distil_concurrency: "",
        meme_potential_weight: "",
        phrase_min_authors: "",
      },
    });
  });

  it("shows the server's own rejection when a value is out of range", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/settings", () => HttpResponse.json(makeSettingFields())),
      http.put("/api/settings", () =>
        HttpResponse.json(
          {
            detail:
              "meme_potential_weight: Input should be less than or equal to 1",
          },
          { status: 400 },
        ),
      ),
    );

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    const field = await screen.findByLabelText("meme_potential_weight");
    await user.clear(field);
    await user.type(field, "2");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText(
        "meme_potential_weight: Input should be less than or equal to 1",
      ),
    ).toBeInTheDocument();
  });
});
