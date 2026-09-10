import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StageBar } from "@/components/StageBar";
import { renderWithProviders } from "@/test/render";

describe("StageBar", () => {
  it("reports its fill to assistive technology as a progress bar", () => {
    renderWithProviders(<StageBar fill={0.68} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "68");
  });

  it("clamps a fill outside 0-1 rather than drawing past its track", () => {
    // Phase 6 drives this from `17 / 25` counters, and a stage that
    // overshoots its estimate would otherwise paint outside the card.
    const { rerender } = renderWithProviders(<StageBar fill={1.4} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");

    rerender(<StageBar fill={-2} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });
});
