/**
 * Named aliases over the generated schema.
 *
 * `schema.ts` addresses every model as `components["schemas"]["RunPage"]`.
 * Letting screens reach into that shape would spread the generator's own
 * layout through the app, so a future switch of generator — or a `$ref` that
 * resolves differently — would touch every file that names a type. This
 * module is the only one that knows the shape.
 */
import type { components } from "@/api/schema";

type Schemas = components["schemas"];

export type RunConfig = Schemas["RunConfig"];
export type RunError = Schemas["RunError"];
export type RunRecordRow = Schemas["RunRecordRow"];
export type RunStatus = RunRecordRow["status"];
export type RunSummary = Schemas["RunSummary"];
export type RunPage = Schemas["RunPage"];
export type RunDetail = Schemas["RunDetail"];
export type StageRecord = Schemas["StageRecord"];
export type Stage = StageRecord["stage"];
export type StageStatus = StageRecord["status"];

export type TopicRow = Schemas["TopicRow"];
export type TrendStatus = TopicRow["trend_status"];
export type RankedTopic = Schemas["RankedTopic"];
export type TopicDetail = Schemas["TopicDetail"];
export type ReplyOut = Schemas["ReplyOut"];
export type TopicRecurrence = Schemas["TopicRecurrence"];
export type Dossier = Schemas["Dossier"];
export type Phrase = Schemas["Phrase"];
export type IndexedTopic = Schemas["IndexedTopic"];
export type TopicIndex = Schemas["TopicIndex"];

export type RenderRecord = Schemas["RenderRecord"];
export type Origin = RenderRecord["origin"];
export type RenderStatus = RenderRecord["status"];
export type LogLine = Schemas["LogLine"];
export type SettingField = Schemas["SettingField"];

export type ActiveRuns = Schemas["ActiveRuns"];
export type QueuedRun = Schemas["QueuedRun"];
export type RunActionAck = Schemas["RunActionAck"];
export type StartRunBody = Schemas["StartRunBody"];
export type ResumeBody = Schemas["ResumeBody"];
export type SettingsUpdate = Schemas["SettingsUpdate"];
export type SettingSource = SettingField["source"];
export type ConfigOptions = Schemas["ConfigOptions"];
export type PlatformOption = Schemas["PlatformOption"];
export type TemplateOption = Schemas["TemplateOption"];

/** The four stages in the order they run — the order the stage cards draw. */
export const STAGES: readonly Stage[] = ["ingest", "analyse", "evaluate", "generate"];

/**
 * What each stage's checkpoint is called on screen.
 *
 * The spec drops the extensions the design drew (`evidence.json`) because
 * these are database rows now, and a filename for a row is a small lie on a
 * screen whose whole job is telling you what a run actually did. The names
 * themselves are the pipeline's own vocabulary and stay.
 */
export const ARTIFACT_NAMES: Readonly<Record<Stage, string>> = {
  ingest: "evidence",
  analyse: "topics",
  evaluate: "ranked",
  generate: "briefs",
};
