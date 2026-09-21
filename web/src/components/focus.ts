/**
 * Has focus been lost — is `active` something that cannot answer a keystroke?
 *
 * `Modal`'s focus recovery is the whole of this predicate's job, and it lives
 * here rather than beside it so it can be exported without making that file
 * export a non-component. The two losses an open dialog has to survive are a
 * focused control unmounting under the user (the delete inside the render
 * modal takes its own render's body with it) and a focused control disabling
 * itself under the user (the render modal's Dismiss/Cancel button, disabled
 * while its delete request is in flight), and Chromium answers them
 * differently. Measured in a real browser, not assumed:
 *
 * - **Removed.** `document.activeElement` becomes `<body>` synchronously.
 * - **Disabled.** `blur` and `focusout` both fire on the button, and
 *   `document.activeElement` *stays on that disabled button* — synchronously,
 *   after a 0ms task, and after 100ms. Nothing afterwards moves it. The loss
 *   only becomes visible when a key is pressed: a `keydown` listener on the
 *   enclosing panel receives nothing at all, and only from then does
 *   `activeElement` read `<body>`.
 *
 * So `<body>` alone catches the first and never the second, and there is no
 * later commit or blur to catch it on — waiting for a second chance is
 * waiting for an event that does not come, and the keystroke is simply lost.
 * A disabled control has to count as lost while it still reads as focused.
 *
 * **Why not the more general "focus is not inside the panel".** It sounds
 * like the better predicate and is the worse one here. The panel is a portal
 * with arbitrary children, so elements legitimately holding focus can sit
 * outside its subtree — a nested `Modal` portals its own panel to
 * `document.body`, and React propagates that panel's `focusout` up the
 * *React* tree to the outer one's `onBlur`. A containment check would have
 * the outer dialog pull focus out of the inner one, whose own recovery would
 * pull it back: two recoveries answering each other. Narrowness is what makes
 * termination obvious instead of argued. Focus resting anywhere outside the
 * panel is somebody's deliberate placement; focus resting on a disabled
 * control is nobody's.
 */
export function focusIsLost(active: Element | null): boolean {
  // Nothing focused, or the document itself — where the platform puts focus
  // when the element holding it is removed.
  if (active === null || active === document.body) return true;
  // The four elements with a `disabled` of their own, so `instanceof` narrows
  // to a union that all have the property and nothing needs asserting. Not
  // `<fieldset disabled>` and not `inert`: neither appears in this app, and a
  // predicate reaching for them would be harder to check than the thing it
  // guards — the same reasoning as `Modal`'s `FOCUSABLE`.
  if (
    active instanceof HTMLButtonElement ||
    active instanceof HTMLInputElement ||
    active instanceof HTMLSelectElement ||
    active instanceof HTMLTextAreaElement
  ) {
    return active.disabled;
  }
  return false;
}
