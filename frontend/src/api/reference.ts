// Session-scoped cache for reference data (codes and plans). Cleared on sign-in/out.
import { api } from "./endpoints";
import type { Plan, RefCodes } from "./types";

let codes: Promise<RefCodes> | null = null;
let plans: Promise<Plan[]> | null = null;

export function clearReferenceCache(): void {
  codes = null;
  plans = null;
}

export function loadRefCodes(): Promise<RefCodes> {
  codes ??= api.refCodes().catch((e: unknown) => {
    codes = null;
    throw e;
  });
  return codes;
}

export function loadPlans(): Promise<Plan[]> {
  plans ??= api
    .plans()
    .then((r) => r.items)
    .catch((e: unknown) => {
      plans = null;
      throw e;
    });
  return plans;
}

export function labelFor(list: { code: string; label: string }[] | undefined, code: string | null | undefined): string {
  if (!code) return "-";
  return list?.find((c) => c.code === code)?.label ?? code;
}
