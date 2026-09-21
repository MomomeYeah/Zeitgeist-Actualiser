import { describe, expect, it } from "vitest";

import { focusIsLost } from "@/components/focus";

describe("focusIsLost", () => {
  it("counts a disabled control as focus lost, and an enabled one as not", () => {
    // The predicate is the whole of the chevron fix: the browser behaviour
    // it answers cannot be reproduced here, but the answer is this code's
    // and is worth pinning on both sides. A real `<button disabled>` is
    // built rather than described.
    const enabled = document.createElement("button");
    const spent = document.createElement("button");
    spent.disabled = true;

    expect(focusIsLost(spent)).toBe(true);
    expect(focusIsLost(enabled)).toBe(false);
  });

  it("counts nothing, and the document body, as focus lost", () => {
    // The node-removal path: the platform drops focus to `<body>`, and
    // `activeElement` is nullable in the DOM's own typing.
    expect(focusIsLost(null)).toBe(true);
    expect(focusIsLost(document.body)).toBe(true);
  });

  it("leaves focus on an ordinary element alone", () => {
    // A deliberate placement outside the panel — a nested dialog, a
    // portalled control — is somebody's decision, and recovering from it
    // would fight whoever made it.
    const div = document.createElement("div");
    div.tabIndex = -1;

    expect(focusIsLost(div)).toBe(false);
  });

  it("reads the disabled flag of every form control that has one", () => {
    // `HTMLButtonElement` is the case in hand; the other three are in the
    // predicate because they are equally capable of being focused and then
    // disabled, and a reader should be able to see that they all answer.
    // Spelled out rather than looped, because `createElement` is only
    // typed to the right element for a literal tag name.
    const field = document.createElement("input");
    const choice = document.createElement("select");
    const area = document.createElement("textarea");

    expect(focusIsLost(field)).toBe(false);
    expect(focusIsLost(choice)).toBe(false);
    expect(focusIsLost(area)).toBe(false);

    field.disabled = true;
    choice.disabled = true;
    area.disabled = true;

    expect(focusIsLost(field)).toBe(true);
    expect(focusIsLost(choice)).toBe(true);
    expect(focusIsLost(area)).toBe(true);
  });
});

