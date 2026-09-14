import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Part, Session } from "../api/types";
import { absoluteTime, compactNumber, money, stringify } from "../lib/format";
import { Button, Callout, Field, ProviderBadge } from "./ui";

type Tab = "info" | "raw";

export function DetailPanel({
  session,
  selectedPart,
  onClose,
}: {
  session: Session;
  selectedPart: Part | null;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("info");
  const summary = session.summary;

  return (
    <aside className="flex h-full w-96 shrink-0 flex-col border-l border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900/50">
      <div className="flex items-center gap-2 border-b border-stone-200 px-3 py-2 dark:border-stone-800">
        {(["info", "raw"] as Tab[]).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setTab(value)}
            className={
              tab === value
                ? "rounded px-2 py-1 text-xs font-medium bg-stone-200 dark:bg-stone-800"
                : "rounded px-2 py-1 text-xs muted hover:bg-stone-100 dark:hover:bg-stone-800/60"
            }
          >
            {value === "info" ? "Session" : "Raw records"}
          </button>
        ))}
        <button type="button" onClick={onClose} className="ml-auto text-xs muted hover:underline">
          hide
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {tab === "info" ? (
          <InfoTab session={session} selectedPart={selectedPart} />
        ) : (
          <RawTab uid={summary.uid} />
        )}
      </div>
    </aside>
  );
}

function InfoTab({ session, selectedPart }: { session: Session; selectedPart: Part | null }) {
  const summary = session.summary;
  const children = useQuery({
    queryKey: ["children", summary.uid],
    queryFn: () => api.sessionChildren(summary.uid),
  });
  const resume = useQuery({
    queryKey: ["resume", summary.uid],
    queryFn: () => api.resumeCommand(summary.uid),
    retry: false,
  });

  return (
    <div className="space-y-4">
      <section>
        <div className="mb-2 flex items-center gap-2">
          <ProviderBadge provider={summary.provider} />
          {summary.kind === "subagent" ? <span className="text-xs muted">subagent</span> : null}
        </div>
        <dl className="divide-y divide-stone-100 dark:divide-stone-800">
          <Field label="Session">{summary.id}</Field>
          <Field label="Workspace">{summary.cwd ?? "unknown"}</Field>
          <Field label="Model">{summary.model ?? "—"}</Field>
          {summary.git_branch ? <Field label="Branch">{summary.git_branch}</Field> : null}
          <Field label="Created">{absoluteTime(summary.created_at)}</Field>
          <Field label="Updated">{absoluteTime(summary.updated_at)}</Field>
          <Field label="Messages">{summary.message_count ?? session.messages.length}</Field>
          {summary.tokens ? (
            <Field label="Tokens">
              {compactNumber(summary.tokens.input)} in / {compactNumber(summary.tokens.output)} out
              {summary.tokens.cache_read
                ? ` · ${compactNumber(summary.tokens.cache_read)} cached`
                : ""}
            </Field>
          ) : null}
          {summary.cost ? <Field label="Cost">{money(summary.cost)}</Field> : null}
          <Field label="Source">{summary.source_path}</Field>
        </dl>
      </section>

      {Object.keys(session.metadata).length > 0 ? (
        <section>
          <h3 className="mb-1 text-[0.6875rem] font-medium uppercase tracking-wide muted">Metadata</h3>
          <dl className="divide-y divide-stone-100 dark:divide-stone-800">
            {Object.entries(session.metadata).map(([key, value]) => (
              <Field key={key} label={key}>
                {stringify(value, 400)}
              </Field>
            ))}
          </dl>
        </section>
      ) : null}

      <section className="space-y-2">
        <h3 className="text-[0.6875rem] font-medium uppercase tracking-wide muted">Export</h3>
        <div className="flex flex-wrap gap-2">
          <Button href={api.exportUrl(summary.uid, "md", false)} download>
            Markdown
          </Button>
          <Button href={api.exportUrl(summary.uid, "json", false)} download>
            JSON
          </Button>
          <Button href={api.exportUrl(summary.uid, "md", true)} download title="Mask secrets and $HOME">
            Markdown (redacted)
          </Button>
        </div>
      </section>

      {resume.data ? (
        <section className="space-y-1">
          <h3 className="text-[0.6875rem] font-medium uppercase tracking-wide muted">Resume</h3>
          <pre className="overflow-x-auto rounded bg-stone-100 p-2 font-mono text-[0.6875rem] dark:bg-stone-950/60">
            {resume.data.command}
          </pre>
          <p className="text-[0.6875rem] muted">{resume.data.note}</p>
          <Button onClick={() => navigator.clipboard?.writeText(resume.data.command)}>Copy</Button>
        </section>
      ) : null}

      {children.data && children.data.length > 0 ? (
        <section>
          <h3 className="mb-1 text-[0.6875rem] font-medium uppercase tracking-wide muted">
            Subagent sessions
          </h3>
          <ul className="space-y-1">
            {children.data.map((child) => {
              const [provider, ...rest] = child.uid.split(":");
              return (
                <li key={child.uid}>
                  <Link
                    to={`/s/${provider}/${encodeURIComponent(rest.join(":"))}`}
                    className="text-xs text-sky-700 hover:underline dark:text-sky-400"
                  >
                    {child.title ?? child.id}
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {selectedPart ? (
        <section>
          <h3 className="mb-1 text-[0.6875rem] font-medium uppercase tracking-wide muted">
            Selected part · {selectedPart.type}
          </h3>
          {selectedPart.locator ? (
            <p className="mb-1 break-all font-mono text-[0.6875rem] muted">
              {selectedPart.locator.source}
              {selectedPart.locator.line ? `:${selectedPart.locator.line}` : ""}
              {selectedPart.locator.key ? ` [${selectedPart.locator.key}]` : ""}
            </p>
          ) : null}
          <pre className="max-h-72 overflow-auto rounded bg-stone-100 p-2 font-mono text-[0.6875rem] dark:bg-stone-950/60">
            {stringify(selectedPart, 8000)}
          </pre>
        </section>
      ) : (
        <p className="text-xs muted">Click any part of the transcript to inspect it here.</p>
      )}
    </div>
  );
}

function RawTab({ uid }: { uid: string }) {
  const raw = useQuery({ queryKey: ["raw", uid], queryFn: () => api.sessionRaw(uid) });
  if (raw.isLoading) return <p className="text-xs muted">Loading original records…</p>;
  if (raw.error) return <Callout tone="error">{String(raw.error)}</Callout>;
  return (
    <div className="space-y-2">
      {raw.data?.truncated ? <Callout tone="warn">Showing the first 500 records.</Callout> : null}
      <pre className="overflow-x-auto font-mono text-[0.6875rem] leading-relaxed">
        {(raw.data?.records ?? []).map((record) => stringify(record, 4000)).join("\n\n")}
      </pre>
    </div>
  );
}
