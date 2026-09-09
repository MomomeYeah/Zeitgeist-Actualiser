import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MemeTile } from "@/components/MemeTile";
import { renderWithProviders } from "@/test/render";

describe("MemeTile", () => {
  it("points at the render's own image endpoint", () => {
    renderWithProviders(<MemeTile renderId="render-1" size={42} />);
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "/api/renders/render-1/image?size=thumb",
    );
  });

  it("asks for the full-size PNG at the largest size", () => {
    // 96px is the thumbnail's own width, so anything larger would be a
    // scaled-up 96px image.
    renderWithProviders(<MemeTile renderId="render-1" size={96} />);
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "/api/renders/render-1/image?size=full",
    );
  });

  it("links to the full-size view when given a destination", () => {
    renderWithProviders(
      <MemeTile renderId="render-1" size={42} to="/runs/r1/renders/render-1" />,
    );
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/runs/r1/renders/render-1",
    );
  });

  it("renders no link when it has no destination", () => {
    // A tile inside a runs-list row is already inside that row's own link,
    // and nesting one anchor in another is invalid HTML the browser
    // silently reshapes. So the tile must not invent a destination it was
    // not given.
    renderWithProviders(<MemeTile renderId="render-1" size={42} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders a failed tile when the PNG is not on disk", () => {
    // The database is authoritative for whether a render exists, so a row
    // whose image 404s is a failed render, not a crash. This is also how a
    // partially failed run shows itself on the runs list.
    renderWithProviders(<MemeTile renderId="render-1" size={42} />);

    fireEvent.error(screen.getByRole("img"));

    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("stops being a link once its image has failed", () => {
    // Nothing to open at full size, so the affordance goes with it.
    renderWithProviders(
      <MemeTile renderId="render-1" size={42} to="/runs/r1/renders/render-1" />,
    );

    fireEvent.error(screen.getByRole("img"));

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("names the template in its alt text", () => {
    // The only description of a meme this app has. "meme" alone would tell
    // a screen reader nothing the surrounding row does not already say.
    renderWithProviders(
      <MemeTile renderId="render-1" size={42} templateId="drake" />,
    );
    expect(screen.getByAltText("drake meme")).toBeInTheDocument();
  });
});
