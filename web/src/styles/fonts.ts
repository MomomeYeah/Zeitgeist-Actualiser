// Bundled rather than fetched: a local tool should not need the network to
// render correctly. The weights are exactly those the handoff's typography
// table uses — Outfit 400/500/600/700/800 (covered by the variable face)
// and IBM Plex Mono 400/500/600/700, which ships as static weights.
import "@fontsource-variable/outfit";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import "@fontsource/ibm-plex-mono/700.css";
