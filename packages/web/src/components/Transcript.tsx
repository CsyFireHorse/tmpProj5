import clsx from "clsx";
import { useMemo, useState } from "react";
import type { Message, Part, Session } from "../api/types";
import { absoluteTime, compactNumber } from "../lib/format";
import { PartView } from "./Parts";
import { Callout } from "./ui";

const ROLE_STYLES: Record<Message["role"], { label: string; accent: string }> = {
  user: { label: "You", accent: "border-l-sky-400" },
  assistant: { label: "Assistant", accent: "border-l-stone-300 dark:border-l-stone-700" },
  system: { label: "System", accent: "border-l-amber-400" },
  tool: { label: "Tool", accent: "border-l-violet-400" },
};

export interface TranscriptFilters {
  roles: Set<Message["role"]>;
  query: string;
  onlyErrors: boolean;
}

export function Transcript({
  session,
  filters,
  expandAll,
  selectedPartId,
  onSelectPart,
}: {
  session: Session;
  filters: TranscriptFilters;
  expandAll?: boolean;
  selectedPartId?: string | null;
  onSelectPart: (part: Part, message: Message) => void;
}) {
  const messages = useMemo(
    () => session.messages.filter((message) => matches(message, filters)),
    [session.messages, filters],
  );

  if (messages.length === 0) {
    return (
      <div className="p-6">
        <Callout>No message matches the current filters.</Callout>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 px-6 py-6">
      {session.notes.length > 0 ? (
        <Callout tone="warn">
          <ul className="space-y-1">
            {session.notes.map((note, index) => (
              <li key={index}>{note}</li>
            ))}
          </ul>
        </Callout>
      ) : null}

      {messages.map((message) => (
        <MessageCard
          key={message.id}
          message={message}
          expandAll={expandAll}
          selectedPartId={selectedPartId}
          onSelectPart={onSelectPart}
        />
      ))}

      {session.warnings.length > 0 ? (
        <Callout tone="warn">
          <p className="mb-1 font-medium">
            {session.warnings.length} record(s) could not be parsed and were skipped
          </p>
          <ul className="space-y-0.5 font-mono text-[0.6875rem]">
            {session.warnings.slice(0, 20).map((warning, index) => (
              <li key={index}>{warning.message}</li>
            ))}
          </ul>
        </Callout>
      ) : null}
    </div>
  );
}

function MessageCard({
  message,
  expandAll,
  selectedPartId,
  onSelectPart,
}: {
  message: Message;
  expandAll?: boolean;
  selectedPartId?: string | null;
  onSelectPart: (part: Part, message: Message) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const role = ROLE_STYLES[message.role];

  return (
    <article id={`msg-${message.id}`} className={clsx("border-l-2 pl-4", role.accent)}>
      <header className="mb-2 flex items-center gap-2 text-xs">
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          className="font-semibold hover:underline"
        >
          {role.label}
        </button>
        {message.created_at ? (
          <time className="muted" dateTime={message.created_at} title={absoluteTime(message.created_at)}>
            {new Date(message.created_at).toLocaleTimeString()}
          </time>
        ) : null}
        {message.model ? <span className="muted">· {message.model}</span> : null}
        {message.tokens ? (
          <span className="muted">
            · {compactNumber(message.tokens.input)} in / {compactNumber(message.tokens.output)} out
          </span>
        ) : null}
        {message.error ? <span className="text-red-600 dark:text-red-400">· failed</span> : null}
      </header>

      {collapsed ? (
        <p className="text-xs italic muted">{message.parts.length} part(s) hidden</p>
      ) : (
        <div className="space-y-3">
          {message.parts.map((part) => (
            <PartView
              key={part.id}
              part={part}
              expandAll={expandAll}
              selected={selectedPartId === part.id}
              onSelect={(selected) => onSelectPart(selected, message)}
            />
          ))}
        </div>
      )}
    </article>
  );
}

function matches(message: Message, filters: TranscriptFilters): boolean {
  if (filters.roles.size > 0 && !filters.roles.has(message.role)) return false;
  if (filters.onlyErrors) {
    const hasError = message.error || message.parts.some((part) => part.type === "error");
    if (!hasError) return false;
  }
  if (filters.query.trim()) {
    const needle = filters.query.toLowerCase();
    const haystack = JSON.stringify(message.parts).toLowerCase();
    if (!haystack.includes(needle)) return false;
  }
  return true;
}
