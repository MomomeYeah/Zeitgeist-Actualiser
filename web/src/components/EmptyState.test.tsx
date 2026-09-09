import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyState } from "@/components/EmptyState";
import { renderWithProviders } from "@/test/render";

describe("EmptyState", () => {
  it("renders the headline and body", () => {
    renderWithProviders(
      <EmptyState
        headline="Nothing has run yet"
        body="A run reads Bluesky, works out what is trending, and generates memes about it. The first one takes a few minutes."
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Nothing has run yet" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/reads Bluesky/)).toBeInTheDocument();
  });

  it("renders no action when it was given none", () => {
    // Phase 5 has no New run screen to send anyone to, so every caller in
    // this phase omits it. A disabled button would be worse than no button.
    renderWithProviders(<EmptyState headline="Nothing has run yet" body="…" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders the action it was given, which is what phase 6 fills", () => {
    renderWithProviders(
      <EmptyState headline="h" body="b" action={<button>New run</button>} />,
    );
    expect(screen.getByRole("button", { name: "New run" })).toBeInTheDocument();
  });
});
