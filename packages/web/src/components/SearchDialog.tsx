import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { relativeTime, renderSnippet } from "../lib/format";
import { ProviderBadge, Spinner } from "./ui";

export function SearchDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [term, setTerm] = useState("");
  const [debounced, setDebounced] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(term), 200);
    return () => clearTimeout(timer);
  }, [term]);

  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (!open) setTerm("");
  }

  const results = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api.search(debounced),
    enabled: open && debounced.trim().length > 1,
  });

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-stone-900/30 p-16 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[70vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl surface shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <input
          autoFocus
          id="global-search"
          name="global-search"
          aria-label="Search all sessions"
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          onKeyDown={(event) => event.key === "Escape" && onClose()}
          placeholder="Search every message across all providers…"
          className="border-b border-stone-200 bg-transparent px-4 py-3 text-sm outline-none dark:border-stone-800"
        />
        <div className="min-h-0 flex-1 overflow-y-auto">
          {results.isFetching ? (
            <div className="p-4">
              <Spinner label="searching" />
            </div>
          ) : null}
          {results.data?.items.length === 0 && debounced.trim().length > 1 ? (
            <p className="p-4 text-sm muted">No match.</p>
          ) : null}
          {(results.data?.items ?? []).map((hit, index) => {
            const [provider, ...rest] = hit.uid.split(":");
            return (
              <button
                key={`${hit.uid}-${hit.message_id}-${index}`}
                type="button"
                onClick={() => {
                  navigate(
                    `/s/${provider}/${encodeURIComponent(rest.join(":"))}?msg=${hit.message_id ?? ""}`,
                  );
                  onClose();
                }}
                className="flex w-full flex-col gap-1 border-b border-stone-100 px-4 py-2.5 text-left hover:bg-stone-50 dark:border-stone-800/60 dark:hover:bg-stone-800/40"
              >
                <span className="flex items-center gap-2 text-xs">
                  <ProviderBadge provider={hit.provider} />
                  <span className="truncate font-medium">{hit.title ?? hit.uid}</span>
                  <span className="ml-auto shrink-0 muted">{relativeTime(hit.updated_at)}</span>
                </span>
                <span
                  className="line-clamp-2 text-xs muted"
                  // The snippet is server-escaped text with << >> markers.
                  dangerouslySetInnerHTML={{ __html: renderSnippet(hit.snippet) }}
                />
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
