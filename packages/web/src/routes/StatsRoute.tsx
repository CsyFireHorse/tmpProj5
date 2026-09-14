import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Stats } from "../api/types";
import { compactNumber, money } from "../lib/format";
import { Spinner } from "../components/ui";

export function StatsRoute() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats });
  if (stats.isLoading) return <Spinner label="loading stats" />;
  if (!stats.data) return null;
  const data = stats.data;

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 p-10">
      <h1 className="text-xl font-semibold">Usage</h1>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="Sessions" value={compactNumber(data.total_sessions)} />
        <Metric label="Messages" value={compactNumber(data.total_messages)} />
        <Metric
          label="Tokens"
          value={`${compactNumber(data.tokens_input)} / ${compactNumber(data.tokens_output)}`}
        />
        <Metric label="Reported cost" value={money(data.cost)} />
      </div>

      <Table title="By provider" buckets={data.by_provider} />
      <Table title="By model" buckets={data.by_model.slice(0, 12)} />
      <Table title="By day" buckets={data.by_day.slice(0, 30)} />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg p-3 surface">
      <p className="text-[0.6875rem] uppercase tracking-wide muted">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function Table({ title, buckets }: { title: string; buckets: Stats["by_provider"] }) {
  if (buckets.length === 0) return null;
  const max = Math.max(...buckets.map((bucket) => bucket.sessions));
  return (
    <section>
      <h2 className="mb-2 text-xs font-medium uppercase tracking-wide muted">{title}</h2>
      <div className="overflow-hidden rounded-lg surface">
        <table className="w-full text-sm">
          <tbody>
            {buckets.map((bucket) => (
              <tr key={bucket.key} className="border-b border-stone-100 last:border-0 dark:border-stone-800">
                <td className="px-3 py-1.5 font-mono text-xs">{bucket.key}</td>
                <td className="w-1/2 px-3 py-1.5">
                  <div className="h-1.5 rounded-full bg-stone-100 dark:bg-stone-800">
                    <div
                      className="h-1.5 rounded-full bg-sky-500/70"
                      style={{ width: `${(bucket.sessions / max) * 100}%` }}
                    />
                  </div>
                </td>
                <td className="px-3 py-1.5 text-right text-xs tabular-nums">{bucket.sessions}</td>
                <td className="px-3 py-1.5 text-right text-xs tabular-nums muted">
                  {compactNumber(bucket.tokens_input + bucket.tokens_output)} tok
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
