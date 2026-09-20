import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Modal } from "@/components/Modal";

function open(onClose = vi.fn()) {
  const view = render(
    <Modal label="drake" onClose={onClose}>
      <button type="button">first</button>
      <button type="button">last</button>
    </Modal>,
  );
  return { onClose, user: userEvent.setup(), view };
}

describe("Modal", () => {
  it("names itself, and says it is modal", () => {
    // The accessible name is how a screen reader announces what has just
    // taken over the screen, and `aria-modal` is what tells it the rest of
    // the page is inert. A panel with neither is a div on top of things.
    open();

    const dialog = screen.getByRole("dialog", { name: "drake" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("renders through a portal, outside the tree it was mounted in", () => {
    // The panel has to escape any ancestor with `overflow: hidden` or a
    // stacking context of its own — the topic grid is inside both — or it
    // is clipped behind the page it is supposed to cover.
    const { view } = open();

    expect(view.container).not.toContainElement(screen.getByRole("dialog"));
    expect(document.body).toContainElement(screen.getByRole("dialog"));
  });

  it("takes focus when it opens", () => {
    // Without this the keyboard is still on the page behind, so Escape and
    // the Tab trap — both handlers on the panel — never see a keystroke.
    open();

    expect(screen.getByRole("dialog")).toHaveFocus();
  });

  it("gives focus back to whatever had it when it closes", () => {
    // The tile that opened the modal is where the keyboard was, and where
    // it belongs afterwards — otherwise focus falls to the top of the
    // document and the user tabs back through the whole page.
    function Host({ open: showing }: { open: boolean }) {
      return (
        <>
          <button type="button">opener</button>
          {showing && (
            <Modal label="drake" onClose={vi.fn()}>
              <button type="button">inside</button>
            </Modal>
          )}
        </>
      );
    }
    const { rerender } = render(<Host open={false} />);
    const opener = screen.getByRole("button", { name: "opener" });
    opener.focus();

    rerender(<Host open={true} />);
    expect(screen.getByRole("dialog")).toHaveFocus();

    rerender(<Host open={false} />);

    expect(opener).toHaveFocus();
  });

  it("closes on Escape", async () => {
    const { onClose, user } = open();

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on a click that lands on the backdrop", async () => {
    const { onClose, user } = open();
    const backdrop = screen.getByRole("dialog").parentElement;
    if (backdrop === null) throw new Error("the panel should sit inside a backdrop");

    await user.click(backdrop);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("stays open when the click landed on something inside it", async () => {
    // The pair to the case above, and the one that fails if the handler
    // forgets to compare the target: without that check every click
    // anywhere in the panel closes it.
    const { onClose, user } = open();

    await user.click(screen.getByRole("button", { name: "first" }));

    expect(onClose).not.toHaveBeenCalled();
  });

  it("keeps Tab inside itself, wrapping at the end", async () => {
    // A modal whose Tab escapes puts the keyboard on a page the user
    // cannot see, which is the failure `aria-modal` promises is not
    // happening.
    const { user } = open();

    await user.tab();
    expect(screen.getByRole("button", { name: "first" })).toHaveFocus();

    await user.tab();
    expect(screen.getByRole("button", { name: "last" })).toHaveFocus();

    await user.tab();
    expect(screen.getByRole("button", { name: "first" })).toHaveFocus();
  });

  it("wraps backwards too", async () => {
    const { user } = open();

    await user.tab({ shift: true });

    expect(screen.getByRole("button", { name: "last" })).toHaveFocus();
  });
});
