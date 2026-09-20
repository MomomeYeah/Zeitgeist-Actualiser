import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { RenderModal } from "@/features/renders/RenderModal";
import { makeRenderRecord } from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

function openModal(
  overrides: Parameters<typeof makeRenderRecord>[0] = {},
  handlers: { onClose?: () => void } = {},
) {
  const onClose = handlers.onClose ?? vi.fn();
  renderWithProviders(
    <RenderModal
      record={makeRenderRecord({ id: "r1", templateId: "drake", ...overrides })}
      onClose={onClose}
    />,
  );
  return { onClose, user: userEvent.setup() };
}

describe("RenderModal", () => {
  it("names itself by the template it is showing", () => {
    // A dialog needs an accessible name, and the template is what tells one
    // render of a topic from another — the topic itself is named by the
    // screen behind the modal.
    openModal();

    expect(screen.getByRole("dialog", { name: "drake" })).toBeInTheDocument();
  });

  it("draws the render at full size, with its rationale", () => {
    openModal({ rationale: "Two panels, one reversal." });

    expect(screen.getByRole("img", { name: "drake meme" })).toHaveAttribute(
      "src",
      "/api/renders/r1/image?size=full",
    );
    expect(screen.getByText("Two panels, one reversal.")).toBeInTheDocument();
  });

  it("closes on the close button", async () => {
    // `Modal` has no close button of its own; this one is this component's.
    const { onClose, user } = openModal();

    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("is wired to Modal's own dismissal", async () => {
    // One integration assertion, not a re-test of `Modal`: Escape is
    // covered in `Modal.test.tsx`, and what this catches is `RenderModal`
    // failing to pass `onClose` down at all.
    const { onClose, user } = openModal();

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("lets an armed delete confirm have the first Escape, and closes on the second", async () => {
    // The interaction neither component's own tests can see. Escape is
    // claimed innermost-first, so losing the whole view as a side effect of
    // cancelling a confirm is the bug this prevents.
    const { onClose, user } = openModal();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByText("Delete this render?")).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.queryByText("Delete this render?")).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("stays open, and says why, when the server will not delete", async () => {
    // The error is only readable while the modal is up, so closing on
    // failure would throw away the one thing the user needs to see.
    server.use(
      http.delete("/api/renders/:renderId", () =>
        HttpResponse.json({ detail: "Permission denied: renders/r1.png" }, { status: 500 }),
      ),
    );
    const { onClose, user } = openModal();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "yes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Permission denied: renders/r1.png",
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
