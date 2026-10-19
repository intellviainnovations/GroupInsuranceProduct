import { useRef, useState } from "react";
import { ApiError, newIdempotencyKey } from "../api/client";
import type { ActionResult } from "../api/model";
import { strings } from "../strings";
import { useToast } from "./toast";

/**
 * Runs a user intent. Each intent name keeps one Idempotency-Key until the
 * server answers (so a retry after a network failure reuses it), then a new
 * key is used for the next intent.
 */
export function useAction(onConflict?: () => void) {
  const toast = useToast();
  const keys = useRef(new Map<string, string>());
  const [busy, setBusy] = useState<string | null>(null);

  async function run<T>(intent: string, fn: (idempotencyKey: string) => Promise<T>): Promise<T | null> {
    let key = keys.current.get(intent);
    if (!key) {
      key = newIdempotencyKey();
      keys.current.set(intent, key);
    }
    setBusy(intent);
    try {
      const r = await fn(key);
      keys.current.delete(intent);
      return r;
    } catch (err) {
      if (!(err instanceof ApiError && (err.code === "NETWORK" || err.code === "IDEMPOTENCY_IN_PROGRESS"))) {
        keys.current.delete(intent);
      }
      toast.error(err);
      if (err instanceof ApiError && err.code === "VERSION_CONFLICT") onConflict?.();
      return null;
    } finally {
      setBusy(null);
    }
  }

  function outcomeToast(r: ActionResult, title: string) {
    const o = r.outcome;
    const tone = o.result === "DONE" ? "success" : o.result === "REJECTED" ? "error" : o.result === "NEEDS_ATTENTION" ? "warning" : "info";
    const parts = [strings.outcome[o.result], o.message ?? "", o.replayed ? strings.replayed : ""].filter(Boolean);
    toast.push({ tone, title, body: parts.join(" - ") });
  }

  return { run, busy, outcomeToast, toast };
}
