import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { AppLayout } from "@/app/AppLayout";
import { AppRoutes } from "@/app/routes";
import {
  makeActiveRuns,
  makeConfigOptions,
  makeSettingFields,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

describe("Sidebar", () => {
  it("names the app and its three destinations, in the handoff's order", async () => {
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );
    renderWithProviders(<AppLayout />, { route: "/" });

    expect(screen.getByText("Zeitgeist")).toBeInTheDocument();
    const nav = (await screen.findAllByRole("link")).map(
      (link) => link.textContent,
    );
    expect(nav).toEqual(["Topics", "Runs", "Settings"]);
  });

  it("marks the destination matching the current route as current", async () => {
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );
    renderWithProviders(<AppLayout />, { route: "/runs" });

    expect(
      await screen.findByRole("link", { name: "Runs" }),
    ).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Topics" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("does not mark Topics current on a run's own page", async () => {
    // "/" would match every route under a prefix match, so Topics needs an
    // exact one. Without it both nav items highlight on /runs.
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );
    renderWithProviders(<AppLayout />, { route: "/runs/20260829T090000Z" });

    expect(
      await screen.findByRole("link", { name: "Topics" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("keeps Runs current on a run's detail page", async () => {
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );
    renderWithProviders(<AppLayout />, { route: "/runs/20260829T090000Z" });

    expect(
      await screen.findByRole("link", { name: "Runs" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("navigates without a page load", async () => {
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );
    renderWithProviders(<AppLayout />, { route: "/" });

    await userEvent.click(await screen.findByRole("link", { name: "Runs" }));

    expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});

describe("AppRoutes", () => {
  it("renders an empty state with the sidebar for an unmatched URL", async () => {
    // No `path="*"` used to mean React Router rendered nothing for a
    // mistyped URL — and because the layout route carries no path of its
    // own, the sidebar vanished with it, leaving a blank page with no way
    // back.
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );
    renderWithProviders(<AppRoutes />, { route: "/nowhere" });

    expect(screen.getByRole("heading", { name: "Nothing here" })).toBeInTheDocument();
    expect(await screen.findByText("Zeitgeist")).toBeInTheDocument();
  });

  it("routes /runs/new and /settings", async () => {
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
      http.get("/api/config/options", () =>
        HttpResponse.json(makeConfigOptions()),
      ),
      http.get("/api/settings", () => HttpResponse.json(makeSettingFields())),
    );

    renderWithProviders(<AppRoutes />, { route: "/runs/new" });
    expect(
      await screen.findByRole("heading", { name: "New run" }),
    ).toBeInTheDocument();

    renderWithProviders(<AppRoutes />, { route: "/settings" });
    expect(
      await screen.findByRole("heading", { name: "Settings" }),
    ).toBeInTheDocument();
  });
});
