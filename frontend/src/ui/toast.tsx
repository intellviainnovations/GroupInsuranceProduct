import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { strings } from "../strings";
import { correlationOf, errorText } from "./format";
import { IconAlert, IconCheck, IconInfo, IconX } from "./icons";

type Tone = "success" | "error" | "info" | "warning";
interface Toast {
  id: number;
  tone: Tone;
  title: string;
  body?: string | undefined;
  correlationId?: string | null | undefined;
}

interface ToastApi {
  push: (t: Omit<Toast, "id">) => void;
  error: (err: unknown, title?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);
  const dismiss = useCallback((id: number) => setToasts((ts) => ts.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (t: Omit<Toast, "id">) => {
      const id = next.current++;
      setToasts((ts) => [...ts.slice(-3), { ...t, id }]);
      window.setTimeout(() => dismiss(id), t.tone === "error" ? 10000 : 6000);
    },
    [dismiss],
  );
  const api = useMemo<ToastApi>(
    () => ({
      push,
      error: (err, title) => push({ tone: "error", title: title ?? errorText(err), body: title ? errorText(err) : undefined, correlationId: correlationOf(err) }),
    }),
    [push],
  );
  const tones: Record<Tone, string> = {
    success: "border-emerald-300 bg-emerald-50 text-emerald-900",
    error: "border-rose-300 bg-rose-50 text-rose-900",
    info: "border-brand-200 bg-brand-50 text-brand-900",
    warning: "border-amber-300 bg-amber-50 text-amber-900",
  };
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} role={t.tone === "error" ? "alert" : "status"} className={`pointer-events-auto flex gap-3 rounded-lg border p-3 text-sm shadow-lg ${tones[t.tone]}`}>
            {t.tone === "success" ? <IconCheck className="h-5 w-5 shrink-0" /> : t.tone === "info" ? <IconInfo className="h-5 w-5 shrink-0" /> : <IconAlert className="h-5 w-5 shrink-0" />}
            <div className="flex-1">
              <p className="font-medium">{t.title}</p>
              {t.body && <p className="mt-0.5">{t.body}</p>}
              {t.correlationId && (
                <p className="mt-1 text-xs opacity-80">
                  {strings.common.correlation}: <span className="font-mono">{t.correlationId}</span>
                </p>
              )}
            </div>
            <button type="button" className="self-start rounded p-0.5 opacity-70 hover:opacity-100" onClick={() => dismiss(t.id)} aria-label={strings.common.dismiss}>
              <IconX className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("ToastProvider missing");
  return ctx;
}
