export function relativeTime(value: string | null | undefined): string {
  if (!value) return "—";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  const units: [number, Intl.RelativeTimeFormatUnit][] = [
    [60, "minute"],
    [24, "hour"],
    [7, "day"],
    [4.348, "week"],
    [12, "month"],
    [Number.POSITIVE_INFINITY, "year"],
  ];
  let amount = seconds / 60;
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  for (const [size, unit] of units) {
    if (Math.abs(amount) < size) return formatter.format(-Math.round(amount), unit);
    amount /= size;
  }
  return "—";
}

export function absoluteTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

export function compactNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(
    value,
  );
}

export function money(value: number | null | undefined): string {
  if (!value) return "—";
  return `$${value < 0.01 ? value.toFixed(4) : value.toFixed(2)}`;
}

export function duration(from?: string | null, to?: string | null): string | null {
  if (!from || !to) return null;
  const ms = new Date(to).getTime() - new Date(from).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms / 60_000)}m`;
}

export function stringify(value: unknown, limit = 4000): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value.length > limit ? `${value.slice(0, limit)}…` : value;
  try {
    const text = JSON.stringify(value, null, 2);
    return text.length > limit ? `${text.slice(0, limit)}…` : text;
  } catch {
    return String(value);
  }
}

/** One-line preview of a tool's arguments for the collapsed header. */
export function summarizeInput(input: unknown): string {
  if (input === null || input === undefined) return "";
  if (typeof input === "string") return input.split("\n")[0].slice(0, 120);
  if (Array.isArray(input)) return input.map((item) => String(item)).join(" ").slice(0, 120);
  if (typeof input === "object") {
    const record = input as Record<string, unknown>;
    for (const key of ["command", "cmd", "path", "file_path", "pattern", "query", "filePath"]) {
      const value = record[key];
      if (typeof value === "string") return value.slice(0, 120);
      if (Array.isArray(value)) return value.join(" ").slice(0, 120);
    }
    return JSON.stringify(record).slice(0, 120);
  }
  return String(input);
}

export function highlight(text: string, query: string): string {
  if (!query.trim()) return escapeHtml(text);
  const terms = query.split(/\s+/).filter(Boolean).map(escapeRegex);
  if (terms.length === 0) return escapeHtml(text);
  const pattern = new RegExp(`(${terms.join("|")})`, "gi");
  return escapeHtml(text).replace(pattern, "<mark>$1</mark>");
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** The search endpoint marks hits with << >> so the payload stays plain text. */
export function renderSnippet(snippet: string): string {
  return escapeHtml(snippet).replace(/&lt;&lt;(.*?)&gt;&gt;/g, "<mark>$1</mark>");
}
