import clsx from "clsx";
import { type ReactNode, useState } from "react";

export function Collapsible({
  header,
  children,
  open,
  defaultOpen = false,
  tone = "default",
}: {
  header: ReactNode;
  children: ReactNode;
  /** When provided, an ancestor (e.g. "expand all") controls the state. */
  open?: boolean;
  defaultOpen?: boolean;
  tone?: "default" | "muted";
}) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);

  // "Expand all" nudges every row, then each row is independent again.
  const [lastRequested, setLastRequested] = useState(open);
  if (open !== lastRequested) {
    setLastRequested(open);
    if (open !== undefined) setInternalOpen(open);
  }

  return (
    <div
      className={clsx(
        "overflow-hidden rounded-lg border",
        tone === "muted"
          ? "border-stone-200/70 bg-stone-50/60 dark:border-stone-800/70 dark:bg-stone-900/40"
          : "border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900/60",
      )}
    >
      <button
        type="button"
        onClick={() => setInternalOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-stone-100/70 dark:hover:bg-stone-800/60"
      >
        <span
          className={clsx(
            "select-none text-[0.625rem] muted transition-transform",
            internalOpen && "rotate-90",
          )}
        >
          ▶
        </span>
        <span className="min-w-0 flex-1">{header}</span>
      </button>
      {internalOpen ? <div className="border-t border-stone-200 p-3 dark:border-stone-800">{children}</div> : null}
    </div>
  );
}
