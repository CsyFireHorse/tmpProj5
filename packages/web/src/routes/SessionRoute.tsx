import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Message, Part } from "../api/types";
import { DetailPanel } from "../components/DetailPanel";
import { Transcript, type TranscriptFilters } from "../components/Transcript";
import { Button, Callout, Chip, EmptyState, Spinner } from "../components/ui";

const ROLES: Message["role"][] = ["user", "assistant", "system", "tool"];

export function SessionRoute() {
  const { provider, id } = useParams();
  const uid = `${provider}:${id}`;
  const [params] = useSearchParams();

  const [roles, setRoles] = useState<Set<Message["role"]>>(new Set());
  const [query, setQuery] = useState("");
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [expandAll, setExpandAll] = useState<boolean | undefined>(undefined);
  const [selectedPart, setSelectedPart] = useState<Part | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);

  const session = useQuery({ queryKey: ["session", uid], queryFn: () => api.session(uid) });

  // Switching sessions clears the per-session view state.
  const [lastUid, setLastUid] = useState(uid);
  if (uid !== lastUid) {
    setLastUid(uid);
    setSelectedPart(null);
    setQuery("");
  }

  // Deep links from search land on a specific message.
  useEffect(() => {
    const target = params.get("msg");
    if (!target || !session.data) return;
    const element = document.getElementById(`msg-${target}`);
    element?.scrollIntoView({ block: "center" });
  }, [params, session.data]);

  const filters: TranscriptFilters = useMemo(
    () => ({ roles, query, onlyErrors }),
    [roles, query, onlyErrors],
  );

  if (session.isLoading) {
    return (
      <div className="p-6">
        <Spinner label="loading session" />
      </div>
    );
  }
  if (session.error) {
    return (
      <div className="p-6">
        <Callout tone="error">{String(session.error)}</Callout>
      </div>
    );
  }
  if (!session.data) return <EmptyState title="Session not found" />;

  const summary = session.data.summary;

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-b border-stone-200 bg-white/80 px-6 py-3 backdrop-blur dark:border-stone-800 dark:bg-stone-900/50">
          <h1 className="truncate text-base font-semibold">{summary.title ?? summary.id}</h1>
          <p className="mt-0.5 truncate text-xs muted">
            {summary.cwd ?? "unknown workspace"}
            {summary.model ? ` · ${summary.model}` : ""}
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <input
              id="in-session-search"
              name="in-session-search"
              aria-label="Find in this session"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Find in this session…"
              className="w-56 rounded-md border border-stone-300 bg-white px-2 py-1 text-xs outline-none focus:border-stone-500 dark:border-stone-700 dark:bg-stone-950"
            />
            {ROLES.map((role) => (
              <Chip
                key={role}
                active={roles.has(role)}
                onClick={() =>
                  setRoles((current) => {
                    const next = new Set(current);
                    if (next.has(role)) next.delete(role);
                    else next.add(role);
                    return next;
                  })
                }
              >
                {role}
              </Chip>
            ))}
            <Chip active={onlyErrors} onClick={() => setOnlyErrors((value) => !value)}>
              errors
            </Chip>
            <div className="ml-auto flex gap-2">
              <Button variant="ghost" onClick={() => setExpandAll((value) => !value)}>
                {expandAll ? "Collapse all" : "Expand all"}
              </Button>
              <Button variant="ghost" onClick={() => setPanelOpen((value) => !value)}>
                {panelOpen ? "Hide details" : "Details"}
              </Button>
            </div>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <Transcript
            session={session.data}
            filters={filters}
            expandAll={expandAll}
            selectedPartId={selectedPart?.id ?? null}
            onSelectPart={(part) => setSelectedPart(part)}
          />
        </div>
      </div>

      {panelOpen ? (
        <DetailPanel
          session={session.data}
          selectedPart={selectedPart}
          onClose={() => setPanelOpen(false)}
        />
      ) : null}
    </div>
  );
}
