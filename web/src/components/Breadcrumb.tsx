import { Link } from "react-router-dom";

import styles from "./Breadcrumb.module.css";

export interface Crumb {
  label: string;
  /** Omitted for the final crumb, which is where you already are. */
  to?: string;
}

export function Breadcrumb({ trail }: { trail: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className={styles.trail}>
      {trail.map((crumb, index) => (
        <span key={`${crumb.label}-${index}`} className={styles.crumb}>
          {index > 0 && <span className={styles.separator}>/</span>}
          {crumb.to === undefined ? (
            <span className={styles.current}>{crumb.label}</span>
          ) : (
            <Link to={crumb.to}>{crumb.label}</Link>
          )}
        </span>
      ))}
    </nav>
  );
}
