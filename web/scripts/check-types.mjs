// Fails when `src/api/schema.ts` no longer matches what `openapi.json`
// generates. Folded into `npm run typecheck` because the spec puts contract
// drift there, and because a generated file that nothing regenerates is a
// contract nobody is holding to.
//
// It regenerates into a temp file rather than in place: a checker that
// rewrites the working tree turns a failing gate into a passing one on the
// second run, which is the one behaviour a drift gate must not have.

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const scratch = mkdtempSync(join(tmpdir(), "zeitgeist-types-"));
const candidate = join(scratch, "schema.ts");

try {
  execFileSync(
    process.execPath,
    ["node_modules/openapi-typescript/bin/cli.js", "openapi.json", "-o", candidate],
    { stdio: ["ignore", "ignore", "inherit"] },
  );

  if (readFileSync(candidate, "utf8") !== readFileSync("src/api/schema.ts", "utf8")) {
    console.error(
      [
        "src/api/schema.ts is stale.",
        "",
        "If you changed a backend response model, regenerate both:",
        "  uv run python scripts/dump_openapi.py",
        "  npm --prefix web run generate:types",
        "",
        "If you did not, someone hand-edited a generated file. Regenerate it.",
      ].join("\n"),
    );
    process.exit(1);
  }
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
