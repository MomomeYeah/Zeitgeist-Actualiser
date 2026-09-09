import type { ReplyOut } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";
import { formatClock } from "@/format";

import styles from "./ReplyList.module.css";

/**
 * Every reply gets the accent left border.
 *
 * The design draws accent when a reply matches the dominant sentiment and
 * white 15% when it does not, and says that border is the only signal on
 * these cards. Nothing computes per-reply sentiment, and doing it properly
 * is a model call per reply. Fabricating the signal on a screen whose whole
 * purpose is showing what people actually said would be worse than not
 * having it — so it is absent, and the spec has flagged it back to the
 * designer as needing either a real source or removal.
 *
 * No author, handle or avatar: `ReplyOut` carries none, and an API that
 * returned them would undo the project's own no-personal-data position.
 */
export function ReplyList({ replies }: { replies: ReplyOut[] }) {
  return (
    <section>
      <SectionLabel hint="no handles stored">Replies</SectionLabel>
      <ul className={styles.list}>
        {replies.map((reply, index) => (
          <li key={`${reply.created_at}-${index}`} className={styles.reply}>
            <p className={styles.text}>{reply.text}</p>
            <span className={styles.meta}>
              {reply.like_count.toLocaleString("en-GB")} likes ·{" "}
              {formatClock(reply.created_at)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
