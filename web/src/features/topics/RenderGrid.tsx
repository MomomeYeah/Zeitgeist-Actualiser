import { Link } from "react-router-dom";

import type { RenderRecord } from "@/api/types";
import { MemeTile } from "@/components/MemeTile";
import { SectionLabel } from "@/components/SectionLabel";
import { shortRunId } from "@/format";

import styles from "./RenderGrid.module.css";

/**
 * The 4-up grid of what was rendered from this topic.
 *
 * Only `ready` renders are drawn. A `generating` row has no PNG yet and a
 * `failed` one never will; both states are designed and both belong to
 * phase 7, along with the two tile states that go with them and the
 * nothing-rendered-yet row.
 */
export function RenderGrid({
  renders,
  runId,
}: {
  renders: RenderRecord[];
  runId: string;
}) {
  const ready = renders.filter((render) => render.status === "ready");
  if (ready.length === 0) return null;

  return (
    <section className={styles.section}>
      <SectionLabel hint={`${ready.length} from ${shortRunId(runId)}`}>
        Rendered from this topic
      </SectionLabel>
      <ul className={styles.grid}>
        {ready.map((render) => (
          <li key={render.id} className={styles.cell}>
            <MemeTile
              renderId={render.id}
              size={96}
              templateId={render.template_id}
              to={`/runs/${encodeURIComponent(runId)}/renders/${encodeURIComponent(render.id)}`}
            />
            <Link
              to={`/runs/${encodeURIComponent(runId)}/renders/${encodeURIComponent(render.id)}`}
              className={styles.footer}
            >
              {render.template_id} · {render.origin.provenance}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
