import clsx from "clsx";
import type { Part, ToolPart } from "../api/types";
import { compactNumber, duration, stringify, summarizeInput } from "../lib/format";
import { Collapsible } from "./Collapsible";
import { Diff } from "./Diff";
import { Markdown } from "./Markdown";

const TOOL_STATUS_DOT: Record<ToolPart["status"], string> = {
  completed: "bg-emerald-500",
  error: "bg-red-500",
  running: "bg-sky-500 animate-pulse",
  pending: "bg-stone-400",
};

export function PartView({
  part,
  expandAll,
  onSelect,
  selected,
}: {
  part: Part;
  expandAll?: boolean;
  onSelect?: (part: Part) => void;
  selected?: boolean;
}) {
  return (
    <div
      onClick={onSelect ? () => onSelect(part) : undefined}
      className={clsx(selected && "rounded-lg ring-2 ring-sky-400/60")}
    >
      <PartBody part={part} expandAll={expandAll} />
    </div>
  );
}

function PartBody({ part, expandAll }: { part: Part; expandAll?: boolean }) {
  switch (part.type) {
    case "text":
      return <Markdown>{part.text}</Markdown>;

    case "reasoning":
      return (
        <Collapsible
          tone="muted"
          open={expandAll}
          header={
            <span className="muted">
              Reasoning · {part.text.split(/\s+/).length} words
              {part.encrypted ? " · encrypted" : ""}
            </span>
          }
        >
          <div className="opacity-80">
            <Markdown>{part.text}</Markdown>
          </div>
        </Collapsible>
      );

    case "tool":
      return <ToolCall part={part} expandAll={expandAll} />;

    case "patch":
      return (
        <div className="space-y-2">
          {part.unified_diff ? <Diff text={part.unified_diff} /> : null}
          {part.files.map((file, index) => (
            <div key={index} className="space-y-1">
              <div className="flex items-center gap-2 font-mono text-xs">
                <span>{file.path}</span>
                {file.additions != null ? (
                  <span className="text-emerald-600 dark:text-emerald-400">+{file.additions}</span>
                ) : null}
                {file.deletions != null ? (
                  <span className="text-red-600 dark:text-red-400">−{file.deletions}</span>
                ) : null}
              </div>
              {file.diff ? <Diff text={file.diff} /> : null}
            </div>
          ))}
        </div>
      );

    case "file":
      return (
        <div className="flex items-center gap-2 rounded-md border border-dashed border-stone-300 px-3 py-2 text-xs dark:border-stone-700">
          <span className="muted">attachment</span>
          <span className="font-mono">{part.path ?? part.mime ?? "binary"}</span>
          {part.data_url ? (
            <img src={part.data_url} alt={part.path ?? "attachment"} className="max-h-40 rounded" />
          ) : null}
        </div>
      );

    case "snapshot":
      return (
        <p className="text-xs muted">
          Workspace snapshot <code className="font-mono">{part.ref ?? "—"}</code>
          {part.files_changed != null ? ` · ${part.files_changed} files` : ""}
        </p>
      );

    case "step": {
      const tokens = part.tokens;
      if (!tokens && part.cost == null) return null;
      return (
        <p className="text-xs muted">
          {part.phase === "start" ? "Step start" : "Step finish"}
          {tokens
            ? ` · ${compactNumber(tokens.input)} in / ${compactNumber(tokens.output)} out tokens`
            : ""}
          {part.cost != null ? ` · $${part.cost.toFixed(4)}` : ""}
        </p>
      );
    }

    case "todo":
      return (
        <ul className="space-y-1 text-sm">
          {part.items.map((item, index) => (
            <li key={index} className="flex gap-2">
              <span className="muted">{item.status === "completed" ? "✓" : "•"}</span>
              <span className={item.status === "completed" ? "line-through muted" : ""}>
                {item.content}
              </span>
            </li>
          ))}
        </ul>
      );

    case "subtask":
      return (
        <p className="text-xs">
          <span className="muted">Subtask</span> {part.title ?? part.agent ?? part.session_uid}
        </p>
      );

    case "compaction":
      return (
        <Collapsible tone="muted" open={expandAll} header={<span className="muted">Context compacted</span>}>
          <Markdown>{part.text ?? ""}</Markdown>
        </Collapsible>
      );

    case "error":
      return (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-200">
          {part.message}
        </div>
      );

    case "unknown":
      // Format drift lands here. Never silently dropped: the original payload
      // is shown so the record stays inspectable.
      return (
        <Collapsible
          tone="muted"
          open={expandAll}
          header={
            <span className="muted">
              Unrecognized record <code className="font-mono">{part.kind}</code> — shown as raw JSON
            </span>
          }
        >
          <pre className="overflow-x-auto font-mono text-[0.75rem]">{stringify(part.data, 20000)}</pre>
        </Collapsible>
      );

    default:
      return null;
  }
}

function ToolCall({ part, expandAll }: { part: ToolPart; expandAll?: boolean }) {
  const elapsed = duration(part.started_at, part.ended_at);
  return (
    <Collapsible
      open={expandAll}
      header={
        <span className="flex min-w-0 items-center gap-2">
          <span className={clsx("size-1.5 shrink-0 rounded-full", TOOL_STATUS_DOT[part.status])} />
          <span className="font-mono font-medium">{part.name}</span>
          <span className="truncate font-mono muted">{summarizeInput(part.input)}</span>
          {elapsed ? <span className="ml-auto shrink-0 muted">{elapsed}</span> : null}
        </span>
      }
    >
      <div className="space-y-3">
        {part.input != null ? (
          <section>
            <h4 className="mb-1 text-[0.6875rem] font-medium uppercase tracking-wide muted">Input</h4>
            <pre className="overflow-x-auto rounded bg-stone-50 p-2 font-mono text-[0.75rem] dark:bg-stone-950/60">
              {stringify(part.input, 8000)}
            </pre>
          </section>
        ) : null}
        {part.output ? (
          <section>
            <h4 className="mb-1 text-[0.6875rem] font-medium uppercase tracking-wide muted">Output</h4>
            <pre className="max-h-96 overflow-auto rounded bg-stone-50 p-2 font-mono text-[0.75rem] dark:bg-stone-950/60">
              {stringify(part.output, 20000)}
            </pre>
          </section>
        ) : null}
        {part.error ? (
          <p className="text-xs text-red-600 dark:text-red-400">error: {part.error}</p>
        ) : null}
      </div>
    </Collapsible>
  );
}
