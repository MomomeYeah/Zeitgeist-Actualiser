import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
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

  it("takes focus back when the control holding it disappears", async () => {
    // Everything this component does about the keyboard hangs off one
    // handler on the panel, so focus dropping to `<body>` disarms Escape,
    // the Tab trap and the arrow keys together — and leaves a container
    // still claiming `aria-modal` over a page the user can now tab into. A
    // control that unmounts under the user is ordinary (the render modal's
    // delete takes its own render's body with it), and the platform answers
    // it by putting focus on the document.
    //
    // The same loss happens when the focused control disables itself
    // instead, which is what the last press of a paging chevron does. That
    // one cannot be tested here: jsdom leaves `activeElement` on a button
    // after `disabled` is set, so there is nothing for a test to observe.
    const onClose = vi.fn();
    function Host() {
      const [showing, setShowing] = useState(true);
      return (
        <Modal label="drake" onClose={onClose}>
          {showing && (
            <button type="button" onClick={() => setShowing(false)}>
              remove me
            </button>
          )}
          <span>what is left</span>
        </Modal>
      );
    }
    const user = userEvent.setup();
    render(<Host />);

    await user.click(screen.getByRole("button", { name: "remove me" }));

    await waitFor(() => expect(screen.getByRole("dialog")).toHaveFocus());
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("wraps backwards too", async () => {
    const { user } = open();

    await user.tab({ shift: true });

    expect(screen.getByRole("button", { name: "last" })).toHaveFocus();
  });

  /** A modal that pages, with one stop inside it and a text field. */
  function openPaging(onArrowKey = vi.fn()) {
    render(
      <Modal label="drake" onClose={vi.fn()} onArrowKey={onArrowKey}>
        <button type="button">inside</button>
        <input aria-label="note" />
      </Modal>,
    );
    return { onArrowKey, user: userEvent.setup() };
  }

  it("pages on the arrow keys, from the focus it opens with", async () => {
    // The keys have to work the instant the modal appears, which is when
    // someone is most likely to try them — and at that moment focus is on
    // the panel itself, not on anything inside it. A handler mounted on a
    // wrapper within the panel would see none of this.
    const { onArrowKey, user } = openPaging();
    expect(screen.getByRole("dialog")).toHaveFocus();

    await user.keyboard("{ArrowLeft}");
    expect(onArrowKey).toHaveBeenCalledWith(-1);

    await user.keyboard("{ArrowRight}");
    expect(onArrowKey).toHaveBeenCalledWith(1);
    expect(onArrowKey).toHaveBeenCalledTimes(2);
  });

  it("leaves the arrow keys to a text field inside it", async () => {
    // The caret's keys belong to the field. This modal has no text input
    // today, but the primitive is shared and the next one will.
    const { onArrowKey, user } = openPaging();

    await user.click(screen.getByLabelText("note"));
    await user.keyboard("{ArrowLeft}");

    expect(onArrowKey).not.toHaveBeenCalled();
  });
});
