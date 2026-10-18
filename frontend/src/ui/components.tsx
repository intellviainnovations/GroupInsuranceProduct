import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { EnrolmentStatus } from "../api/types";
import { strings } from "../strings";
import { correlationOf, errorText } from "./format";
import { IconAlert, IconX } from "./icons";

const statusTone: Record<EnrolmentStatus, string> = {
  DRAFT: "bg-slate-100 text-slate-700 ring-slate-300",
  PENDING_CHECK: "bg-amber-50 text-amber-800 ring-amber-300",
  REJECTED: "bg-rose-50 text-rose-700 ring-rose-300",
  APPROVED: "bg-sky-50 text-sky-800 ring-sky-300",
  PROPOSAL_CREATED: "bg-indigo-50 text-indigo-700 ring-indigo-300",
  PAYMENT_PENDING: "bg-violet-50 text-violet-700 ring-violet-300",
  PAYMENT_FAILED: "bg-red-100 text-red-800 ring-red-400",
  PAID: "bg-teal-50 text-teal-700 ring-teal-300",
  ISSUED: "bg-emerald-50 text-emerald-700 ring-emerald-300",
  PROPOSAL_REJECTED: "bg-pink-50 text-pink-700 ring-pink-300",
  PROPOSAL_CANCELLED: "bg-stone-100 text-stone-600 ring-stone-300",
  NEEDS_ATTENTION: "bg-orange-100 text-orange-800 ring-orange-400",
  CANCELLATION_PENDING: "bg-yellow-50 text-yellow-800 ring-yellow-300",
  CANCELLED: "bg-zinc-200 text-zinc-700 ring-zinc-400",
};

export function StatusBadge({ status }: { status: EnrolmentStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset ${statusTone[status]}`}
    >
      {strings.status[status]}
    </span>
  );
}

export function Pill({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "amber" | "green" | "red" | "blue" }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700",
    amber: "bg-amber-100 text-amber-800",
    green: "bg-emerald-100 text-emerald-800",
    red: "bg-rose-100 text-rose-800",
    blue: "bg-brand-50 text-brand-700",
  };
  return <span className={`inline-flex rounded px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>{children}</span>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 p-6 text-sm text-slate-500">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
      {label ?? strings.common.loading}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: (() => void) | undefined }) {
  const cid = correlationOf(error);
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
      <IconAlert className="mt-0.5 h-5 w-5 shrink-0" />
      <div className="flex-1">
        <p className="font-medium">{errorText(error)}</p>
        {cid && (
          <p className="mt-1 text-xs text-rose-700">
            {strings.common.correlation}: <span className="font-mono">{cid}</span>
          </p>
        )}
      </div>
      {onRetry && (
        <button type="button" className="btn-secondary" onClick={onRetry}>
          {strings.common.retry}
        </button>
      )}
    </div>
  );
}

export function EmptyState({ text }: { text: string }) {
  return <p className="p-6 text-center text-sm text-slate-500">{text}</p>;
}

export function Card({
  title,
  actions,
  children,
  className,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className ?? ""}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          {actions}
        </header>
      )}
      <div>{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function DefList({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 p-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
      {items.map(([k, v]) => (
        <div key={k}>
          <dt className="text-xs font-medium text-slate-500">{k}</dt>
          <dd className="mt-0.5 text-slate-900">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input, select, textarea, button")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus();
    };
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4">
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} className="card w-full max-w-lg">
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h2 className="font-semibold text-slate-900">{title}</h2>
          <button type="button" className="btn-ghost px-2" onClick={onClose} aria-label={strings.common.close}>
            <IconX className="h-4 w-4" />
          </button>
        </header>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string | undefined;
  error?: string | undefined;
  children: ReactNode;
}) {
  return (
    <div>
      <label htmlFor={id} className="field-label">
        {label}
      </label>
      {children}
      {hint && !error && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs text-rose-700">
          {error}
        </p>
      )}
    </div>
  );
}

export interface AsyncState<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
  setData: (d: T) => void;
}

/** Load data on mount and whenever deps change. */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const loader = useCallback(load, deps);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    loader().then(
      (d) => {
        if (alive) {
          setData(d);
          setLoading(false);
        }
      },
      (e: unknown) => {
        if (alive) {
          setError(e);
          setLoading(false);
        }
      },
    );
    return () => {
      alive = false;
    };
  }, [loader, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1), setData };
}
