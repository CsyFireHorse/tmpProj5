import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { PROVIDER_LABELS, type ProviderId } from "../api/types";
import { Button, Callout, ProviderBadge, Spinner } from "../components/ui";
import { useIndexEvents } from "../hooks/useIndexEvents";

export function WelcomeRoute() {
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const liveIndex = useIndexEvents();
  const index = liveIndex ?? status.data?.index;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 p-10">
      <header>
        <h1 className="text-xl font-semibold">Agent chat history</h1>
        <p className="mt-1 text-sm muted">
          Everything is read from this machine and never leaves it. Pick a session on the left, or
          press <kbd className="rounded border border-stone-300 px-1 text-xs dark:border-stone-700">⌘K</kbd>{" "}
          to search across every provider.
        </p>
      </header>

      <section>
        <h2 className="mb-2 text-xs font-medium uppercase tracking-wide muted">Detected stores</h2>
        {providers.isLoading ? <Spinner label="probing" /> : null}
        <ul className="space-y-2">
          {(providers.data ?? []).map((provider) => (
            <li key={provider.id} className="rounded-lg p-3 surface">
              <div className="flex items-center gap-2">
                <ProviderBadge provider={provider.id as ProviderId} />
                <span className="text-sm font-medium">{PROVIDER_LABELS[provider.id as ProviderId]}</span>
                <span className="ml-auto text-xs muted">
                  {provider.detected ? `${provider.session_count ?? 0} sessions` : "not found"}
                </span>
              </div>
              <ul className="mt-1.5 space-y-0.5 font-mono text-[0.6875rem] muted">
                {provider.roots.map((root) => (
                  <li key={root}>{root}</li>
                ))}
              </ul>
              {provider.note ? <p className="mt-1 text-[0.6875rem] muted">{provider.note}</p> : null}
              {provider.error ? (
                <p className="mt-1 text-[0.6875rem] text-red-600 dark:text-red-400">{provider.error}</p>
              ) : null}
            </li>
          ))}
        </ul>
      </section>

      {providers.data?.every((provider) => !provider.detected) ? (
        <Callout tone="warn">
          No coding agent store was found under this home directory. Start the server with{" "}
          <code className="font-mono">--demo</code> to explore a synthetic history, or point it at
          another home with <code className="font-mono">ACV_HOME</code>.
        </Callout>
      ) : null}

      <section className="flex items-center gap-3">
        <Button onClick={() => api.rescan(true)}>Rebuild index</Button>
        <span className="text-xs muted">
          {index?.running
            ? `indexing ${index.scanned}/${index.total}`
            : `${index?.indexed_sessions ?? 0} sessions indexed`}
        </span>
      </section>
    </div>
  );
}
