/**
 * Shapes come from the backend's OpenAPI document via `npm run gen:types`.
 * Nothing here is hand-written; these are just readable aliases.
 */
import type { components } from "./schema";

type S = components["schemas"];

export type ProviderStatus = S["ProviderStatus"];
export type ProviderId = ProviderStatus["id"];
export type SessionSummary = S["SessionSummary"];
export type SessionPage = S["SessionPage"];
export type Session = S["Session"];
export type Message = S["Message"];
export type ProjectSummary = S["ProjectSummary"];
export type SearchResult = S["SearchResult"];
export type SearchHit = S["SearchHit"];
export type Stats = S["Stats"];
export type IndexStatus = S["IndexStatus"];
export type AppStatus = S["AppStatus"];
export type ResumeCommand = S["ResumeCommand"];

export type Part = Message["parts"][number];
export type PartType = Part["type"];
export type TextPart = Extract<Part, { type: "text" }>;
export type ReasoningPart = Extract<Part, { type: "reasoning" }>;
export type ToolPart = Extract<Part, { type: "tool" }>;
export type FilePart = Extract<Part, { type: "file" }>;
export type PatchPart = Extract<Part, { type: "patch" }>;
export type SnapshotPart = Extract<Part, { type: "snapshot" }>;
export type StepPart = Extract<Part, { type: "step" }>;
export type TodoPart = Extract<Part, { type: "todo" }>;
export type SubtaskPart = Extract<Part, { type: "subtask" }>;
export type CompactionPart = Extract<Part, { type: "compaction" }>;
export type ErrorPart = Extract<Part, { type: "error" }>;
export type UnknownPart = Extract<Part, { type: "unknown" }>;

export const PROVIDER_LABELS: Record<ProviderId, string> = {
  codex: "Codex",
  "cursor-ide": "Cursor IDE",
  "cursor-cli": "Cursor CLI",
  opencode: "opencode",
};

export const PROVIDER_ACCENTS: Record<ProviderId, string> = {
  codex: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  "cursor-ide": "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  "cursor-cli": "bg-violet-500/15 text-violet-700 dark:text-violet-300",
  opencode: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
};
