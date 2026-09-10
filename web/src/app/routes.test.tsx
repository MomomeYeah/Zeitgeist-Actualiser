import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AppLayout } from "@/app/AppLayout";
import { AppRoutes } from "@/app/routes";
import { renderWithProviders } from "@/test/render";

describe("Sidebar", () => {
  it("names the app and its two destinations, in the handoff's order", () => {
    renderWithProviders(<AppLayout />, { route: "/" });

    expect(screen.getByText("Zeitgeist")).toBeInTheDocument();
    const nav = screen.getAllByRole("link").map((link) => link.textContent);
    expect(nav).toEqual(["Topics", "Runs"]);
  });

  it("marks the destination matching the current route as current", () => {
    renderWithProviders(<AppLayout />, { route: "/runs" });

    expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Topics" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("does not mark Topics current on a run's own page", () => {
    // "/" would match every route under a prefix match, so Topics needs an
    // exact one. Without it both nav items highlight on /runs.
    renderWithProviders(<AppLayout />, { route: "/runs/20260829T090000Z" });

    expect(screen.getByRole("link", { name: "Topics" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("keeps Runs current on a run's detail page", () => {
    renderWithProviders(<AppLayout />, { route: "/runs/20260829T090000Z" });

    expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("navigates without a page load", async () => {
    renderWithProviders(<AppLayout />, { route: "/" });

    await userEvent.click(screen.getByRole("link", { name: "Runs" }));

    expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});

describe("AppRoutes", () => {
  it("renders an empty state with the sidebar for an unmatched URL", () => {
    // No `path="*"` used to mean React Router rendered nothing for a
    // mistyped URL — and because the layout route carries no path of its
    // own, the sidebar vanished with it, leaving a blank page with no way
    // back.
    renderWithProviders(<AppRoutes />, { route: "/nowhere" });

    expect(screen.getByRole("heading", { name: "Nothing here" })).toBeInTheDocument();
    expect(screen.getByText("Zeitgeist")).toBeInTheDocument();
  });
});
