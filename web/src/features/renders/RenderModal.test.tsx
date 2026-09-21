import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { RenderModal } from "@/features/renders/RenderModal";
import type { RenderNav } from "@/features/renders/RenderDetail";
import { makeRenderRecord } from "@/test/factories";
import { server } from "@/test/server";

function openModal(
  overrides: Parameters<typeof makeRenderRecord>[0] = {},
  handlers: { onClose?: () => void; nav?: RenderNav } = {},
) {
  const onClose = handlers.onClose ?? vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );

  const view = render(
    <Wrapper>
      <RenderModal
        record={makeRenderRecord({ id: "r1", templateId: "drake", ...overrides })}
        onClose={onClose}
        nav={handlers.nav}
      />
    </Wrapper>,
  );

  const originalRerender = view.rerender;
  view.rerender = (element: ReactNode) => {
    return originalRerender(<Wrapper>{element}</Wrapper>);
  };

  return { onClose, user: userEvent.setup(), view };
}

/** A `nav` whose two callbacks are spies, with both directions available. */
function paging(overrides: Partial<RenderNav> = {}) {
  const onPrev = vi.fn();
  const onNext = vi.fn();
  return {
    onPrev,
    onNext,
    nav: { onPrev, onNext, hasPrev: true, hasNext: true, index: 1, count: 3, ...overrides },
  };
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

  it("hands the chevrons down to the body", async () => {
    // One integration assertion rather than a re-test of `RenderDetail`:
    // what this catches is `RenderModal` not passing `nav` through at all.
    const { onNext, nav } = paging();
    const { user } = openModal({}, { nav });

    await user.click(screen.getByRole("button", { name: "Next render" }));

    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it("pages on the arrow keys", async () => {
    // `Modal` owns the keystroke; this is the wiring that gives it
    // somewhere to go. Focus is on the panel, which is where it lands when
    // the modal opens — the case a handler inside the panel would miss.
    const { onPrev, onNext, nav } = paging();
    const { user } = openModal({}, { nav });

    await user.keyboard("{ArrowRight}");
    expect(onNext).toHaveBeenCalledTimes(1);

    await user.keyboard("{ArrowLeft}");
    expect(onPrev).toHaveBeenCalledTimes(1);
  });

  it("does not page past the end on the arrow keys", async () => {
    // The disabled chevron and the arrow key have to agree: a keystroke
    // that stepped where the button refuses to would wrap the list by the
    // back door.
    const { onNext, nav } = paging({ hasNext: false });
    const { user } = openModal({}, { nav });

    await user.keyboard("{ArrowRight}");

    expect(onNext).not.toHaveBeenCalled();
  });

  it("does not page past the front on the arrow keys", async () => {
    const { onPrev, nav } = paging({ hasPrev: false });
    const { user } = openModal({}, { nav });

    await user.keyboard("{ArrowLeft}");

    expect(onPrev).not.toHaveBeenCalled();
  });

  it("announces which render paging has arrived at", () => {
    // Otherwise `→` is silence. The counter is a plain span with no live
    // region, and a dialog's `aria-label` changing under a container that
    // already holds focus is not re-announced — nor can the grid's own
    // highlight help, sitting behind `aria-modal="true"`.
    const { nav } = paging({ index: 1, count: 3 });
    const { view } = openModal({ id: "r1", templateId: "drake" }, { nav });
    const region = screen.getByRole("status");
    expect(region).toHaveTextContent("Render 2 of 3");

    view.rerender(
      <RenderModal
        record={makeRenderRecord({ id: "r2", templateId: "two_buttons" })}
        onClose={vi.fn()}
        nav={{ ...nav, index: 2 }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("Render 3 of 3");
    // The same node, not a replacement. A live region has to already be in
    // the document for a change to it to be announced, so one rebuilt on
    // every page — which is what moving this inside the keyed body would do
    // — would announce nothing.
    expect(screen.getByRole("status")).toBe(region);
  });

  it("starts the next render clean when it pages to one", async () => {
    // The body holds four things about the render it is showing: whether
    // its image failed, the delete mutation, that mutation's error, and
    // whether a delete is armed. Carrying any of them across a page is
    // wrong, and two are dangerous — an armed confirm would point at a
    // render the user never chose, and one click would destroy it.
    const { nav } = paging();
    const { view, user } = openModal({ id: "r1", templateId: "drake" }, { nav });

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByText("Delete this render?")).toBeInTheDocument();

    view.rerender(
      <RenderModal
        record={makeRenderRecord({ id: "r2", templateId: "two_buttons" })}
        onClose={vi.fn()}
        nav={nav}
      />,
    );

    expect(screen.queryByText("Delete this render?")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("draws the next render's image after paging off one that would not load", () => {
    // The same reset, for the state that is merely wrong rather than
    // dangerous: without it, every render after a missing PNG shows the
    // dashed panel.
    const { nav } = paging();
    const { view } = openModal({ id: "r1", templateId: "drake" }, { nav });

    fireEvent.error(screen.getByRole("img", { name: "drake meme" }));
    expect(screen.queryByRole("img")).not.toBeInTheDocument();

    view.rerender(
      <RenderModal
        record={makeRenderRecord({ id: "r2", templateId: "two_buttons" })}
        onClose={vi.fn()}
        nav={nav}
      />,
    );

    expect(screen.getByRole("img", { name: "two_buttons meme" })).toBeInTheDocument();
  });
});
