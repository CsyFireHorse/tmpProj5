import clsx from "clsx";
import { useMemo } from "react";

type LineKind = "add" | "del" | "meta" | "hunk" | "context";

function classify(line: string): LineKind {
  if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ")) return "meta";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "del";
  return "context";
}

const LINE_STYLES: Record<LineKind, string> = {
  add: "bg-emerald-500/10 text-emerald-800 dark:text-emerald-300",
  del: "bg-red-500/10 text-red-800 dark:text-red-300",
  meta: "muted",
  hunk: "bg-sky-500/10 text-sky-800 dark:text-sky-300",
  context: "",
};

export function Diff({ text }: { text: string }) {
  const lines = useMemo(() => text.replace(/\n$/, "").split("\n"), [text]);
  const stats = useMemo(() => {
    let added = 0;
    let removed = 0;
    for (const line of lines) {
      const kind = classify(line);
      if (kind === "add") added += 1;
      if (kind === "del") removed += 1;
    }
    return { added, removed };
  }, [lines]);

  return (
    <div className="overflow-hidden rounded-lg border border-stone-200 dark:border-stone-800">
      <div className="flex items-center gap-3 border-b border-stone-200 bg-stone-50 px-3 py-1.5 text-[0.6875rem] dark:border-stone-800 dark:bg-stone-900/60">
        <span className="font-medium muted">diff</span>
        <span className="text-emerald-600 dark:text-emerald-400">+{stats.added}</span>
        <span className="text-red-600 dark:text-red-400">−{stats.removed}</span>
      </div>
      <pre className="overflow-x-auto bg-white py-1 font-mono text-[0.78125rem] leading-[1.45] dark:bg-stone-950/40">
        {lines.map((line, index) => (
          <div key={index} className={clsx("px-3", LINE_STYLES[classify(line)])}>
            {line === "" ? " " : line}
          </div>
        ))}
      </pre>
    </div>
  );
}
