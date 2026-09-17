import { describe, expect, it } from "vitest";

import { SECTIONS } from "@/features/settings/fields";
import { makeSettingFields } from "@/test/factories";

describe("SECTIONS", () => {
  it("covers every key the server returns, plus the four card-driven keys", () => {
    // `SECTIONS` draws every `SettingRow` the screen renders; the four
    // provider/platform/count cards under "Defaults for new runs" are not
    // `FieldSpec`s at all, so they are named explicitly here the same way
    // `RESETTABLE_KEYS` names them. A `run`-scoped field the server starts
    // returning that neither list mentions would render nothing and fail no
    // other test — this is the one that would catch it.
    const sectionKeys = SECTIONS.flatMap((section) =>
      section.cards.flatMap((card) => card.fields.map((field) => field.key)),
    );
    const cardDrivenKeys = ["llm_provider", "llm_model", "sources", "topic_count"];

    const covered = new Set([...sectionKeys, ...cardDrivenKeys]);
    const served = new Set(makeSettingFields().map((field) => field.key));

    expect(covered).toEqual(served);
  });
});
