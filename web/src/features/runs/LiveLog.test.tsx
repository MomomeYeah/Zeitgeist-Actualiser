import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LiveLog } from "@/features/runs/LiveLog";
import styles from "@/features/runs/LiveLog.module.css";
import { makeLogLine } from "@/test/factories";

/**
 * jsdom lays nothing out, so every scroll dimension is 0 and every log is
 * trivially "at the bottom". These make the container a real scroller for
 * the assertions that depend on one.
 */
function makeScrollable(node: HTMLElement, scrollHeight: number, clientHeight = 200) {
  Object.defineProperty(node, "scrollHeight", {
    value: scrollHeight,
    configurable: true,
  });
  Object.defineProperty(node, "clientHeight", {
    value: clientHeight,
    configurable: true,
  });
}

function lines(count: number) {
  return Array.from({ length: count }, (_, index) =>
    makeLogLine({ seq: index, message: `line ${index}` }),
  );
}

describe("LiveLog", () => {
  it("renders each line with the logger that emitted it", () => {
    render(
      <LiveLog
        lines={[makeLogLine({ logger: "zeitgeist.media.render", message: "drawing" })]}
        live
        verbose={false}
        onVerboseChange={vi.fn()}
      />,
    );

    expect(screen.getByText("zeitgeist.media.render")).toBeInTheDocument();
    expect(screen.getByText("drawing")).toBeInTheDocument();
  });

  it("pins to the bottom as lines arrive while following", () => {
    const { rerender } = render(
      <LiveLog lines={lines(3)} live verbose={false} onVerboseChange={vi.fn()} />,
    );
    const scroller = screen.getByTestId("log-scroller");
    makeScrollable(scroller, 1000);

    rerender(
      <LiveLog lines={lines(4)} live verbose={false} onVerboseChange={vi.fn()} />,
    );

    expect(scroller.scrollTop).toBe(1000);
  });

  it("releases follow when scrolled away from the bottom", async () => {
    const user = userEvent.setup();
    render(<LiveLog lines={lines(3)} live verbose={false} onVerboseChange={vi.fn()} />);
    const scroller = screen.getByTestId("log-scroller");
    makeScrollable(scroller, 1000);

    scroller.scrollTop = 200;
    fireEvent.scroll(scroller);

    const jump = await screen.findByRole("button", { name: "jump to latest" });
    expect(screen.queryByText("following")).not.toBeInTheDocument();

    await user.click(jump);

    expect(scroller.scrollTop).toBe(1000);
    expect(screen.getByText("following")).toBeInTheDocument();
  });

  it("keeps following within the threshold of the bottom", () => {
    // The log is 11px mono at line-height 1.9, so lines are 20.9px and an
    // exact equality test would release follow on virtually every line.
    render(<LiveLog lines={lines(3)} live verbose={false} onVerboseChange={vi.fn()} />);
    const scroller = screen.getByTestId("log-scroller");
    makeScrollable(scroller, 1000);

    scroller.scrollTop = 780;
    fireEvent.scroll(scroller);

    expect(screen.getByText("following")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "jump to latest" }),
    ).not.toBeInTheDocument();
  });

  it("hides DEBUG lines until verbose is on, retroactively", async () => {
    const user = userEvent.setup();
    const onVerboseChange = vi.fn();
    const held = [
      makeLogLine({ seq: 1, level: "INFO", message: "Fetched 25 trends" }),
      makeLogLine({ seq: 2, level: "DEBUG", message: "Distilled 'cat' in 2.1s" }),
    ];
    const { rerender } = render(
      <LiveLog lines={held} live verbose={false} onVerboseChange={onVerboseChange} />,
    );

    expect(screen.queryByText("Distilled 'cat' in 2.1s")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "verbose" }));
    expect(onVerboseChange).toHaveBeenCalledWith(true);

    rerender(
      <LiveLog lines={held} live verbose onVerboseChange={onVerboseChange} />,
    );

    expect(screen.getByText("Distilled 'cat' in 2.1s")).toBeInTheDocument();
    expect(screen.getByText("Fetched 25 trends")).toBeInTheDocument();
  });

  it("keeps a warning legible however far it has scrolled up", () => {
    // Older lines fade to 40% so the eye lands on recent ones, and a
    // warning is the one thing someone opens a log to find. Drop the level
    // branch from `toneOf` and a WARNING twenty lines back dims away with
    // everything else — which is a bug, not a restyling.
    const held = [
      makeLogLine({ seq: 0, level: "WARNING", message: "Trend 3 failed" }),
      ...lines(30).map((line) => ({ ...line, seq: line.seq + 1 })),
    ];
    render(<LiveLog lines={held} live verbose={false} onVerboseChange={vi.fn()} />);

    // `?? ""` satisfies `noUncheckedIndexedAccess` only — the vitest CSS
    // proxy always manufactures a class name for any key, so this fallback
    // is never actually exercised.
    expect(screen.getByText("Trend 3 failed").closest("p")).toHaveClass(styles.warn ?? "");
    expect(screen.getByText("line 0").closest("p")).toHaveClass(styles.dim ?? "");
  });

  it("offers neither follow nor jump for a finished run", () => {
    // The post-mortem block is the same component. A "following" indicator
    // on a log that will never gain another line is a lie about what the
    // screen is doing.
    render(
      <LiveLog lines={lines(3)} live={false} verbose={false} onVerboseChange={vi.fn()} />,
    );

    expect(screen.queryByText("following")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "jump to latest" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Log")).toBeInTheDocument();
  });

  it("says so when a run has logged nothing yet", () => {
    render(<LiveLog lines={[]} live verbose={false} onVerboseChange={vi.fn()} />);

    expect(screen.getByText("Waiting for the first line…")).toBeInTheDocument();
  });
});
