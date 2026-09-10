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
import { dirname, join } from "node:path";
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

function allFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return allFiles(path);
    return [path];
  });
}

/**
 * The classes a stylesheet actually defines.
 *
 * Comments are stripped first — `.head` mentioned in a CSS comment as an
 * aside is prose, not a rule, and would otherwise mask a real phantom by
 * making it look defined. What is left is every `.name` token in a selector,
 * compound selectors (`.highlighted .rank`) and grouped ones
 * (`.a, .b { ... }`) included, which is the class's real footprint in the
 * file regardless of which rule introduces it.
 */
function definedClasses(cssText: string): Set<string> {
  const withoutComments = cssText.replace(/\/\*[\s\S]*?\*\//g, "");
  const names = withoutComments.match(/\.([A-Za-z_][\w-]*)/g) ?? [];
  return new Set(names.map((name) => name.slice(1)));
}

/**
 * The CSS-module classes one component file references via static dot
 * access (`styles.foo`).
 *
 * Deliberately blind to dynamic access — `styles[tone]`,
 * `styles[segment.tone]`, a `sizeClass()` helper that returns `styles.x`
 * from inside an `if` (that one's dot accesses are still static and are
 * matched normally). Bracket access never matches `\bstyles\.\w+` at all,
 * so those components are silently skipped rather than mis-flagged — this
 * check cannot resolve a runtime key, and does not try to.
 */
function staticStylesReferences(componentText: string): string[] {
  const matches = componentText.match(/\bstyles\.([A-Za-z_$][\w$]*)/g) ?? [];
  return matches.map((match) => match.slice("styles.".length));
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

  /**
   * A `styles.foo` reference to a class the paired stylesheet never
   * defines. Vitest's CSS modules run with `css: false`, so the import is a
   * proxy that manufactures a class name for any key asked of it — nothing
   * about running the component or its tests distinguishes a real class
   * from a typo or a class deleted mid-refactor. This walks the source
   * text instead, which is the only place the paired names can be checked
   * against each other.
   *
   * Static dot access only. `Chip.tsx`'s `styles[tone]`, `MoodBar.tsx`'s
   * `styles[segment.tone]`, and any other bracket access resolve a runtime
   * key this check cannot know — those components are silently skipped
   * rather than flagged, which is the correct outcome for a key this check
   * cannot resolve.
   */
  it("references no CSS-module class its stylesheet does not define", () => {
    const offenders = allFiles(SRC)
      .filter((path) => path.endsWith(".tsx") || path.endsWith(".ts"))
      .filter((path) => !path.endsWith(".test.ts") && !path.endsWith(".test.tsx"))
      .flatMap((componentPath) => {
        const text = readFileSync(componentPath, "utf8");
        const moduleImport = /from\s+["']\.\/([\w.-]+)\.module\.css["']/.exec(text);
        if (moduleImport === null) return [];

        const cssPath = join(dirname(componentPath), `${moduleImport[1]}.module.css`);
        const defined = definedClasses(readFileSync(cssPath, "utf8"));

        return staticStylesReferences(text)
          .filter((name) => !defined.has(name))
          .map((name) => `${componentPath.slice(SRC.length)}: styles.${name}`);
      });

    expect(offenders).toEqual([]);
  });
});
