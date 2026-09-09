import "react";

declare module "react" {
  interface CSSProperties {
    /** StageBar's hard-edged gradient stop. */
    "--fill"?: string;
    /** MemeTile's square edge length. */
    "--tile"?: string;
    /** MoodBar's segment share. */
    "--share"?: string;
  }
}
