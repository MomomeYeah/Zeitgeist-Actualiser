import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CopyLinkButton } from "@/components/CopyLinkButton";

const PATH = "/runs/20260829T090000Z/renders/render-1";

/**
 * jsdom does not define `navigator.clipboard`, and it is read-only where it
 * exists, so it is installed by definition rather than assignment.
 *
 * Call this AFTER `userEvent.setup()`, never before. `setup()` installs a
 * clipboard stub of its own — that is how `user.copy()` works — and it
 * replaces whatever is already there. Stubbing first means the component
 * calls user-event's stub instead of this spy, which resolves happily, so
 * a rejection test sees a successful copy and the spy is never called.
 */
function stubClipboard(writeText: ReturnType<typeof vi.fn>) {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("CopyLinkButton", () => {
  it("copies an absolute URL, not the path it was given", async () => {
    // The point of the button is pasting the link somewhere that is not
    // this app, where a leading-slash path addresses nothing. jsdom serves
    // documents from http://localhost:3000.
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    stubClipboard(writeText);
    render(<CopyLinkButton path={PATH} />);

    await user.click(screen.getByRole("button", { name: "Copy link" }));

    expect(writeText).toHaveBeenCalledWith(
      "http://localhost:3000/runs/20260829T090000Z/renders/render-1",
    );
  });

  it("says it copied, and does not say so for ever", async () => {
    // Two breaks, one case: a copy that reports nothing, and a button left
    // reading "Copied" so the next click gives no feedback at all.
    //
    // The clock is advanced well past the revert rather than exactly onto
    // it. How long the word stays is a decision someone is entitled to
    // change; that it goes away is the behaviour, and pinning 2000 here
    // would fail on the former while catching nothing extra of the latter.
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    stubClipboard(writeText);
    render(<CopyLinkButton path={PATH} />);

    await user.click(screen.getByRole("button", { name: "Copy link" }));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(10_000);

    expect(screen.getByRole("button", { name: "Copy link" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copied" })).not.toBeInTheDocument();
  });

  it("shows the URL to copy by hand when the clipboard refuses", async () => {
    // `writeText` rejects in a non-secure context and when permission is
    // denied. The button must not silently do nothing: the URL becomes
    // selectable text instead.
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    const user = userEvent.setup();
    stubClipboard(writeText);
    render(<CopyLinkButton path={PATH} />);

    await user.click(screen.getByRole("button", { name: "Copy link" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "http://localhost:3000/runs/20260829T090000Z/renders/render-1",
    );
    expect(screen.getByRole("button", { name: "Copy link" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copied" })).not.toBeInTheDocument();
  });

  it("clears the failure once a later copy works", async () => {
    // A denial is about that attempt, not the button. Leaving the alert up
    // after a successful copy would tell the user the link is not on their
    // clipboard when it is.
    const writeText = vi
      .fn()
      .mockRejectedValueOnce(new Error("denied"))
      .mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    stubClipboard(writeText);
    render(<CopyLinkButton path={PATH} />);

    await user.click(screen.getByRole("button", { name: "Copy link" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Copy link" }));

    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
