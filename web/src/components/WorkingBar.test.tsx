import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WorkingBar } from "@/components/WorkingBar";

describe("WorkingBar", () => {
  it("says what is being done, and hides the bar from a screen reader", () => {
    // The sweep reports no progress — nothing knows how far along a brief
    // is — so it is decoration, and the sentence is the only thing worth
    // announcing. A track without `aria-hidden` is an unlabelled element
    // read out between the tile and its footer.
    //
    // Asserted as "the decoration is hidden" rather than as a count of
    // hidden elements: a second decorative span is a change someone is
    // entitled to make, and a count would fail on it while catching no bug.
    const { container } = render(<WorkingBar doing="writing brief…" />);

    expect(screen.getByText("writing brief…")).toBeInTheDocument();
    expect(container.querySelector("[aria-hidden='true']")).not.toBeNull();
  });
});
