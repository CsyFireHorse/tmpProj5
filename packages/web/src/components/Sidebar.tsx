import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import clsx from "clsx";
import { useMemo, useRef } from "react";
import { NavLink, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { PROVIDER_LABELS, type ProviderId, type SessionSummary } from "../api/types";
import { compactNumber, relativeTime } from "../lib/format";
import { Chip, ProviderBadge, Spinner } from "./ui";

const PROVIDERS: ProviderId[] = ["codex", "cursor-ide", "cursor-cli", "opencode"];

export function Sidebar({ indexing }: { indexing: boolean }) {
  const [params, setParams] = useSearchParams();
  const selectedProviders = params.getAll("provider");
  const project = params.get("project");
  const query = params.get("q") ?? "";
  const sort = (params.get("sort") ?? "updated") as "updated" | "created" | "messages" | "title";

  // Freshness comes from SSE-driven invalidation, not from polling.
  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  const projectsQuery = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const sessionsQuery = useQuery({
    queryKey: ["sessions", selectedProviders, project, query, sort],
    queryFn: () =>
      api.sessions({ provider: selectedProviders, project, q: query, sort, limit: 300 }),
  });

  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const status of providersQuery.data ?? []) map.set(status.id, status.session_count ?? 0);
    return map;
  }, [providersQuery.data]);

  function update(mutate: (next: URLSearchParams) => void) {
    const next = new URLSearchParams(params);
    mutate(next);
    setParams(next, { replace: true });
  }

  function toggleProvider(id: ProviderId) {
    update((next) => {
      const current = next.getAll("provider");
      next.delete("provider");
      const wanted = current.includes(id) ? current.filter((p) => p !== id) : [...current, id];
      for (const value of wanted) next.append("provider", value);
    });
  }

  const sessions = sessionsQuery.data?.items ?? [];

  return (
    <aside className="flex h-full w-80 shrink-0 flex-col border-r border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900/50">
      <div className="space-y-3 border-b border-stone-200 p-3 dark:border-stone-800">
        <input
          id="session-filter"
          name="session-filter"
          aria-label="Filter sessions"
          value={query}
          onChange={(event) =>
            update((next) => {
              const value = event.target.value;
              if (value) next.set("q", value);
              else next.delete("q");
            })
          }
          placeholder="Filter sessions…"
          className="w-full rounded-md border border-stone-300 bg-white px-2.5 py-1.5 text-sm outline-none placeholder:text-stone-400 focus:border-stone-500 dark:border-stone-700 dark:bg-stone-950"
        />

        <div className="flex flex-wrap gap-1.5">
          {PROVIDERS.map((id) => (
            <Chip
              key={id}
              active={selectedProviders.includes(id)}
              onClick={() => toggleProvider(id)}
              title={`${counts.get(id) ?? 0} sessions`}
            >
              {PROVIDER_LABELS[id]}
              <span className="ml-1 tabular-nums opacity-60">{counts.get(id) ?? 0}</span>
            </Chip>
          ))}
        </div>

        <div className="flex gap-2">
          <select
            id="project-filter"
            name="project-filter"
            aria-label="Filter by project"
            value={project ?? ""}
            onChange={(event) =>
              update((next) => {
                const value = event.target.value;
                if (value) next.set("project", value);
                else next.delete("project");
              })
            }
            className="min-w-0 flex-1 rounded-md border border-stone-300 bg-white px-2 py-1 text-xs dark:border-stone-700 dark:bg-stone-950"
          >
            <option value="">All projects</option>
            {(projectsQuery.data ?? []).map((entry) => (
              <option key={entry.cwd ?? entry.name} value={entry.cwd ?? entry.name}>
                {entry.name} ({entry.session_count})
              </option>
            ))}
          </select>
          <select
            id="sort-order"
            name="sort-order"
            aria-label="Sort order"
            value={sort}
            onChange={(event) => update((next) => next.set("sort", event.target.value))}
            className="rounded-md border border-stone-300 bg-white px-2 py-1 text-xs dark:border-stone-700 dark:bg-stone-950"
          >
            <option value="updated">Recent</option>
            <option value="created">Created</option>
            <option value="messages">Longest</option>
            <option value="title">Title</option>
          </select>
        </div>
      </div>

      <div className="flex items-center justify-between px-3 py-1.5 text-[0.6875rem] muted">
        <span>{sessionsQuery.data?.total ?? 0} sessions</span>
        {indexing ? <Spinner label="indexing" /> : null}
      </div>

      {sessionsQuery.isLoading ? (
        <div className="p-3">
          <Spinner label="loading" />
        </div>
      ) : (
        <SessionList sessions={sessions} />
      )}
    </aside>
  );
}

function SessionList({ sessions }: { sessions: SessionSummary[] }) {
  const parentRef = useRef<HTMLDivElement>(null);
  const { provider, id } = useParams();
  const activeUid = provider && id ? `${provider}:${id}` : null;
  const [params] = useSearchParams();

  const virtualizer = useVirtualizer({
    count: sessions.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 72,
    overscan: 12,
  });

  return (
    <div ref={parentRef} className="min-h-0 flex-1 overflow-y-auto">
      <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
        {virtualizer.getVirtualItems().map((row) => {
          const session = sessions[row.index];
          const [providerId, ...rest] = session.uid.split(":");
          const to = `/s/${providerId}/${encodeURIComponent(rest.join(":"))}?${params.toString()}`;
          return (
            <div
              key={session.uid}
              ref={virtualizer.measureElement}
              data-index={row.index}
              style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${row.start}px)` }}
            >
              <NavLink
                to={to}
                className={clsx(
                  "block border-b border-stone-100 px-3 py-2.5 transition dark:border-stone-800/60",
                  activeUid === session.uid
                    ? "bg-stone-100 dark:bg-stone-800/70"
                    : "hover:bg-stone-50 dark:hover:bg-stone-800/40",
                )}
              >
                <div className="flex items-start gap-2">
                  <ProviderBadge provider={session.provider} className="mt-0.5" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{session.title ?? session.id}</p>
                    <p className="mt-0.5 flex items-center gap-1.5 truncate text-[0.6875rem] muted">
                      <span className="truncate">{session.project ?? "unknown workspace"}</span>
                      <span>·</span>
                      <span className="shrink-0">{relativeTime(session.updated_at)}</span>
                      {session.message_count ? (
                        <>
                          <span>·</span>
                          <span className="shrink-0">{compactNumber(session.message_count)} msg</span>
                        </>
                      ) : null}
                      {session.kind === "subagent" ? (
                        <span className="shrink-0 rounded bg-stone-200 px-1 dark:bg-stone-700">sub</span>
                      ) : null}
                      {session.parse_status !== "ok" ? (
                        <span className="shrink-0 text-amber-600 dark:text-amber-400">⚠</span>
                      ) : null}
                    </p>
                  </div>
                </div>
              </NavLink>
            </div>
          );
        })}
      </div>
    </div>
  );
}
