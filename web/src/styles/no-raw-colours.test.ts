/**
 * @vitest-environment node
 *
 * Pure filesystem work — no DOM needed. Forced explicitly because this
 * suite's default `jsdom` environment breaks `new URL(relative, base)`
 * once *any* module in the file imports a `node:` builtin: `import.meta.url`
 * itself still reports a correct `file://` string, but resolving a relative
 * URL against it silently falls back to jsdom's own `http://localhost:3000/`
 * document location instead of throwing or honouring the given base. Under
 * `node`, the platform's own `URL` is used and resolves correctly.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = fileURLToPath(new URL("..", import.meta.url));

function stylesheets(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return stylesheets(path);
    return entry.name.endsWith(".module.css") ? [path] : [];
  });
}

/**
 * The one invariant over the stylesheets that a person cannot hold.
 *
 * Not a check that `tokens.css` says what it says — that would grep its own
 * source and prove only that the source is the source. This is a cross-file
 * rule with a real failure mode: a component that hardcodes `#ffd93d`
 * instead of `var(--accent)` looks correct on the day it is written and
 * stops tracking the palette forever after, and nobody catches it by eye
 * across twenty stylesheets.
 *
 * `tokens.css` itself is excluded because it is where the colours are
 * defined; it is not a `.module.css`, so the walk never reaches it.
 */
describe("component stylesheets", () => {
  it("name no colour of their own", () => {
    const offenders = stylesheets(SRC)
      .map((path) => ({ path, text: readFileSync(path, "utf8") }))
      .filter(({ text }) => /#[0-9a-f]{3,8}\b/i.test(text) || /\brgba?\(/i.test(text))
      // StageBar's gradient carries its own trailing stop, which the
      // handoff writes inline as part of the gradient rather than as a
      // token. It is the one documented exception.
      .filter(({ path }) => !path.endsWith("StageBar.module.css"))
      .map(({ path }) => path.slice(SRC.length));

    expect(offenders).toEqual([]);
  });
});
