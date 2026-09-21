import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WorkingBar } from "@/components/WorkingBar";
import styles from "@/components/WorkingBar.module.css";

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

  it("takes the larger look only when it is asked for", async () => {
    // The two callers' boxes are 112px and a whole modal frame apart, and at
    // tile scale in the frame the bar leaves it about 57px tall — between a
    // failed panel's 320px and an image's 60vh, so paging swings the frame's
    // edges, and the chevrons sitting on them, by hundreds of pixels. The
    // grid's tile keeps what it had, which is what the default is for: this
    // is the assertion that catches the variant leaking into it, since the
    // tile's own tests read the sentence and not its size.
    const { container: inPanel } = render(<WorkingBar doing="rendering…" size="panel" />);
    const { container: inTile } = render(<WorkingBar doing="rendering…" />);

    expect(within(inPanel).getByText("rendering…")).toHaveClass(styles.panelDoing ?? "");
    expect(within(inTile).getByText("rendering…")).not.toHaveClass(
      styles.panelDoing ?? "",
    );
  });
});
