import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RunStatus } from "@/api/types";
import { StatusPill } from "@/components/StatusPill";
import { renderWithProviders } from "@/test/render";

describe("StatusPill", () => {
  it("renders a completed run with its render count", () => {
    renderWithProviders(<StatusPill status="ok" count={5} />);
    expect(screen.getByText("OK · 5")).toBeInTheDocument();
  });

  it("renders a completed run that rendered nothing without a dangling separator", () => {
    // A run whose every brief failed still completed. "OK · " with nothing
    // after it reads as a truncation bug.
    renderWithProviders(<StatusPill status="ok" count={0} />);
    expect(screen.getByText("OK")).toBeInTheDocument();
  });

  it("renders a failure without a count", () => {
    // The count is meaningless on a run that never reached generate, and
    // the design's failed pill carries the word alone.
    renderWithProviders(<StatusPill status="failed" count={0} />);
    expect(screen.getByText("FAILED")).toBeInTheDocument();
  });

  // RunStatus is a five-member literal. A status with no label renders an
  // empty pill, which is the failure mode this catches. Typed rather than
  // `as const`, which the lint rules ban.
  const LABELS: [RunStatus, string][] = [
    ["running", "RUNNING"],
    ["ok", "OK"],
    ["failed", "FAILED"],
    ["aborted", "ABORTED"],
    ["interrupted", "INTERRUPTED"],
  ];

  it.each(LABELS)("labels the %s status as %s", (status, label) => {
    renderWithProviders(<StatusPill status={status} />);
    expect(screen.getByText(new RegExp(`^${label}`))).toBeInTheDocument();
  });
});
