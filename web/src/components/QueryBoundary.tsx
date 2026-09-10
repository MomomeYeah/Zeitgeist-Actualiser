import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";

import type { ApiError } from "@/api/client";

import styles from "./QueryBoundary.module.css";

/**
 * Loading, missing and broken — the three states every screen in this phase
 * shares, in one place.
 *
 * A 404 is separated from every other failure because they are different
 * problems with different fixes: a mistyped run id is the user's, and a 500
 * is the server's. Collapsing them into "something went wrong" would send
 * someone looking in the wrong place.
 *
 * This is deliberately not an error boundary. TanStack Query already holds
 * the failure as data; throwing it so a boundary could catch it would lose
 * the status code that makes the distinction above possible.
 */
export function QueryBoundary<T>({
  query,
  missing,
  children,
}: {
  query: UseQueryResult<T, ApiError>;
  missing: string;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) {
    return <p className={styles.state}>Loading…</p>;
  }
  if (query.isError) {
    return (
      <p className={styles.error}>
        {query.error.status === 404 ? missing : query.error.detail}
      </p>
    );
  }
  return <>{children(query.data)}</>;
}
