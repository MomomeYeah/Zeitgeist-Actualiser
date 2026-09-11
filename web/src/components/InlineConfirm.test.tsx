import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InlineConfirm } from "@/components/InlineConfirm";

function setup(onConfirm = vi.fn()) {
  render(<InlineConfirm label="Abort" question="Abort run?" onConfirm={onConfirm} />);
  return { onConfirm, user: userEvent.setup() };
}

describe("InlineConfirm", () => {
  it("asks in place rather than opening a dialog", async () => {
    const { user } = setup();

    await user.click(screen.getByRole("button", { name: "Abort" }));

    // The question takes the trigger's place rather than appearing beside
    // it. A `queryByRole("dialog")` assertion is deliberately absent: this
    // component has no dialog and never had one, so that could only fail
    // if someone deliberately added a modal — a decision, not a break.
    expect(screen.getByText("Abort run?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Abort" })).not.toBeInTheDocument();
  });

  it("does nothing until yes is chosen", async () => {
    const { onConfirm, user } = setup();

    await user.click(screen.getByRole("button", { name: "Abort" }));
    expect(onConfirm).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "yes" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("reverts on no", async () => {
    const { onConfirm, user } = setup();

    await user.click(screen.getByRole("button", { name: "Abort" }));
    await user.click(screen.getByRole("button", { name: "no" }));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Abort" })).toBeInTheDocument();
  });

  it("reverts on Escape", async () => {
    // Escape is the one way out that costs nothing to reach. A confirm you
    // can only leave by aiming at a 20px "no" is a confirm people click
    // through.
    const { onConfirm, user } = setup();

    await user.click(screen.getByRole("button", { name: "Abort" }));
    await user.keyboard("{Escape}");

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Abort" })).toBeInTheDocument();
  });

  it("hands focus back to the trigger when Escape reverts it", async () => {
    // Found on a real run's page: the question takes focus (onto `no`), and
    // Escape then unmounted the focused button, dropping a keyboard user at
    // the top of the document mid-run. The one revert that must not move
    // focus is blur, below — focus has already gone where someone put it.
    const { user } = setup();

    await user.click(screen.getByRole("button", { name: "Abort" }));
    await user.keyboard("{Escape}");

    expect(screen.getByRole("button", { name: "Abort" })).toHaveFocus();
  });

  it("hands focus back to the trigger after either answer", async () => {
    const { user } = setup();

    await user.click(screen.getByRole("button", { name: "Abort" }));
    await user.click(screen.getByRole("button", { name: "no" }));
    expect(screen.getByRole("button", { name: "Abort" })).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Abort" }));
    await user.click(screen.getByRole("button", { name: "yes" }));
    expect(screen.getByRole("button", { name: "Abort" })).toHaveFocus();
  });

  it("reverts when focus leaves it entirely", async () => {
    const { user } = setup();
    render(<button type="button">elsewhere</button>);

    await user.click(screen.getByRole("button", { name: "Abort" }));
    await user.click(screen.getByRole("button", { name: "elsewhere" }));

    expect(screen.getByRole("button", { name: "Abort" })).toBeInTheDocument();
  });

  it("reverts when focus leaves to nowhere trackable (relatedTarget null)", async () => {
    // Real browsers fire blur/focusout with a null relatedTarget whenever
    // the window/tab itself loses focus — alt-tab, clicking the address
    // bar, switching tabs — not only when focus moves to another element
    // inside the control. That case must still revert; a guard that treats
    // every null relatedTarget as "still inside" would leave an abandoned
    // confirm armed on the screen indefinitely.
    const { onConfirm, user } = setup();

    await user.click(screen.getByRole("button", { name: "Abort" }));
    const no = screen.getByRole("button", { name: "no" });
    expect(no).toHaveFocus();

    // Calling .blur() directly (rather than focusing another element)
    // reproduces the real-browser/jsdom window-blur case: focus goes to
    // nowhere trackable and the resulting event carries relatedTarget:
    // null, exactly as jsdom's HTMLOrSVGElement-impl does.
    no.blur();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Abort" })).toBeInTheDocument();
    });
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("stays open while focus moves between yes and no", async () => {
    // The blur revert must not fire on the tab from `yes` to `no`, or the
    // keyboard path through this control would be unusable.
    //
    // Asserted twice. The first Tab here passes through `document.body`
    // with a null `relatedTarget`, which the component answers with a check
    // deferred 100ms — so an assertion made straight after the tabs runs
    // before that check has, and passes however broken it is. That branch
    // has regressed once already. Waiting past the deferral is what makes
    // this test able to see it.
    const { user } = setup();

    await user.click(screen.getByRole("button", { name: "Abort" }));
    await user.tab();
    await user.tab();

    expect(screen.getByText("Abort run?")).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(screen.getByText("Abort run?")).toBeInTheDocument();
  });
});
