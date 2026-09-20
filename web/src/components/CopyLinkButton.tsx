import { useEffect, useRef, useState } from "react";

import styles from "./CopyLinkButton.module.css";

/**
 * Puts a link on the clipboard, absolute.
 *
 * `path` is app-relative because that is what callers hold — a route, not
 * an address. A relative path pasted into a chat window addresses nothing,
 * so it is resolved against the origin the app is being served from.
 *
 * `writeText` rejects outside a secure context and when permission is
 * refused. That is reported rather than swallowed: the URL is shown as
 * selectable text, which is the thing the user was after anyway.
 */
export function CopyLinkButton({ path }: { path: string }) {
  const [copied, setCopied] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const revert = useRef<ReturnType<typeof setTimeout> | null>(null);

  // The revert outlives a click by two seconds; clear it on unmount so it
  // cannot set state on a component that has gone — the modal closing
  // straight after a copy is the ordinary way that happens.
  useEffect(() => {
    return () => {
      if (revert.current) clearTimeout(revert.current);
    };
  }, []);

  async function copy() {
    const absolute = new URL(path, window.location.origin).href;
    try {
      await navigator.clipboard.writeText(absolute);
      setRefused(null);
      setCopied(true);
      revert.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
      setRefused(absolute);
    }
  }

  return (
    <>
      <button type="button" className={styles.button} onClick={() => void copy()}>
        {copied ? "Copied" : "Copy link"}
      </button>
      {refused !== null && (
        <p role="alert" className={styles.refused}>
          {`The clipboard is not available — ${refused}`}
        </p>
      )}
    </>
  );
}
