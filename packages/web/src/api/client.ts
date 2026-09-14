import type {
  AppStatus,
  ProjectSummary,
  ProviderStatus,
  ResumeCommand,
  SearchResult,
  Session,
  SessionPage,
  SessionSummary,
  Stats,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const detail = await response
      .json()
      .then((body) => body?.detail ?? response.statusText)
      .catch(() => response.statusText);
    throw new ApiError(response.status, String(detail));
  }
  return response.json() as Promise<T>;
}

export interface SessionQuery {
  provider?: string[];
  project?: string | null;
  q?: string | null;
  kind?: "main" | "subagent" | null;
  sort?: "updated" | "created" | "messages" | "title";
  offset?: number;
  limit?: number;
}

function toSearchParams(query: SessionQuery): string {
  const params = new URLSearchParams();
  for (const provider of query.provider ?? []) params.append("provider", provider);
  if (query.project) params.set("project", query.project);
  if (query.q) params.set("q", query.q);
  if (query.kind) params.set("kind", query.kind);
  if (query.sort) params.set("sort", query.sort);
  if (query.offset) params.set("offset", String(query.offset));
  params.set("limit", String(query.limit ?? 100));
  return params.toString();
}

export const api = {
  status: () => request<AppStatus>("/api/status"),
  providers: () => request<ProviderStatus[]>("/api/providers"),
  projects: () => request<ProjectSummary[]>("/api/projects"),
  sessions: (query: SessionQuery) => request<SessionPage>(`/api/sessions?${toSearchParams(query)}`),
  session: (uid: string) => request<Session>(`/api/sessions/${encodeURIComponent(uid)}`),
  sessionChildren: (uid: string) =>
    request<SessionSummary[]>(`/api/sessions/${encodeURIComponent(uid)}/children`),
  sessionRaw: (uid: string) =>
    request<{ uid: string; records: unknown[]; truncated: boolean }>(
      `/api/sessions/${encodeURIComponent(uid)}/raw?limit=500`,
    ),
  resumeCommand: (uid: string) =>
    request<ResumeCommand>(`/api/sessions/${encodeURIComponent(uid)}/resume-command`),
  search: (q: string) => request<SearchResult>(`/api/search?q=${encodeURIComponent(q)}&limit=50`),
  stats: () => request<Stats>("/api/stats"),
  rescan: (force = false) =>
    request<{ ok: boolean; detail: string | null }>(`/api/index/rescan?force=${force}`, {
      method: "POST",
    }),
  bindWorkspace: (workspace_hash: string, path: string) =>
    request<{ ok: boolean; detail: string | null }>("/api/actions/bind-workspace", {
      method: "POST",
      body: JSON.stringify({ workspace_hash, path }),
    }),
  reveal: (path: string) =>
    request<{ ok: boolean; detail: string | null }>("/api/actions/reveal", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  exportUrl: (uid: string, format: "md" | "json", redact: boolean) =>
    `/api/sessions/${encodeURIComponent(uid)}/export?format=${format}&redact=${redact}`,
};
