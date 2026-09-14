import clsx from "clsx";
import type { ReactNode } from "react";
import { PROVIDER_ACCENTS, PROVIDER_LABELS, type ProviderId } from "../api/types";

export function ProviderBadge({ provider, className }: { provider: ProviderId; className?: string }) {
  return (
    <span
      className={clsx(
        "inline-flex shrink-0 items-center rounded px-1.5 py-0.5 text-[0.6875rem] font-medium",
        PROVIDER_ACCENTS[provider],
        className,
      )}
    >
      {PROVIDER_LABELS[provider]}
    </span>
  );
}

export function Chip({
  active,
  onClick,
  children,
  title,
}: {
  active?: boolean;
  onClick?: () => void;
  children: ReactNode;
  title?: string;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={clsx(
        "rounded-full border px-2.5 py-1 text-xs transition",
        active
          ? "border-stone-900 bg-stone-900 text-white dark:border-stone-100 dark:bg-stone-100 dark:text-stone-900"
          : "border-stone-300 text-stone-600 hover:border-stone-400 dark:border-stone-700 dark:text-stone-300 dark:hover:border-stone-600",
      )}
    >
      {children}
    </button>
  );
}

export function Button({
  children,
  onClick,
  href,
  download,
  variant = "default",
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  href?: string;
  download?: boolean;
  variant?: "default" | "ghost";
  title?: string;
}) {
  const className = clsx(
    "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition",
    variant === "default"
      ? "border border-stone-300 bg-white hover:bg-stone-100 dark:border-stone-700 dark:bg-stone-900 dark:hover:bg-stone-800"
      : "text-stone-600 hover:bg-stone-200/60 dark:text-stone-300 dark:hover:bg-stone-800",
  );
  if (href) {
    return (
      <a className={className} href={href} download={download} title={title}>
        {children}
      </a>
    );
  }
  return (
    <button type="button" className={className} onClick={onClick} title={title}>
      {children}
    </button>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[6.5rem_1fr] gap-2 py-1 text-xs">
      <dt className="muted">{label}</dt>
      <dd className="break-words font-mono text-[0.6875rem] leading-relaxed">{children}</dd>
    </div>
  );
}

export function Callout({
  tone = "info",
  children,
}: {
  tone?: "info" | "warn" | "error";
  children: ReactNode;
}) {
  return (
    <div
      className={clsx(
        "rounded-md border px-3 py-2 text-xs leading-relaxed",
        tone === "info" &&
          "border-sky-200 bg-sky-50 text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-200",
        tone === "warn" &&
          "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200",
        tone === "error" &&
          "border-red-200 bg-red-50 text-red-900 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-200",
      )}
    >
      {children}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-xs muted">
      <span className="size-3 animate-spin rounded-full border-2 border-stone-400 border-t-transparent" />
      {label}
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail?: ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-10 text-center">
      <p className="text-sm font-medium">{title}</p>
      {detail ? <p className="max-w-md text-xs leading-relaxed muted">{detail}</p> : null}
    </div>
  );
}
