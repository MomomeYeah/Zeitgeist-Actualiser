import userEvent from "@testing-library/user-event";
import { render, screen } from "@testing-library/react";
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

  it("reverts when focus leaves it entirely", async () => {
    const { user } = setup();
    render(<button type="button">elsewhere</button>);

    await user.click(screen.getByRole("button", { name: "Abort" }));
    await user.click(screen.getByRole("button", { name: "elsewhere" }));

    expect(screen.getByRole("button", { name: "Abort" })).toBeInTheDocument();
  });

  it("stays open while focus moves between yes and no", async () => {
    // The blur revert must not fire on the tab from `yes` to `no`, or the
    // keyboard path through this control would be unusable.
    const { user } = setup();

    await user.click(screen.getByRole("button", { name: "Abort" }));
    await user.tab();
    await user.tab();

    expect(screen.getByText("Abort run?")).toBeInTheDocument();
  });
});
