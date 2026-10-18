// Display-only formatting. Money stays a decimal string end to end: it is
// regrouped as text (Indian grouping), never parsed into a floating number.
import { ApiError } from "../api/client";
import { strings } from "../strings";

export function formatInr(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return strings.common.notAvailable;
  const m = /^(\d+)(\.\d+)?$/.exec(value);
  if (!m) return value;
  const int = m[1] ?? "";
  const dec = m[2] ?? "";
  let grouped = int;
  if (int.length > 3) {
    const last3 = int.slice(-3);
    const rest = int.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
    grouped = `${rest},${last3}`;
  }
  return `₹${grouped}${dec}`;
}

const dateTimeFmt = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const dateFmt = new Intl.DateTimeFormat("en-IN", { timeZone: "UTC", day: "2-digit", month: "short", year: "numeric" });

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return strings.common.notAvailable;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : dateTimeFmt.format(d);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return strings.common.notAvailable;
  const d = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? value : dateFmt.format(d);
}

export function show(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === "" ? strings.common.notAvailable : String(value);
}

export function errorText(err: unknown): string {
  if (!(err instanceof ApiError)) return strings.errors.generic;
  const e = strings.errors;
  switch (err.code) {
    case "NETWORK":
      return e.network;
    case "FORBIDDEN":
      return e.forbidden;
    case "NOT_FOUND":
      return e.notFound;
    case "VERSION_CONFLICT":
      return e.versionConflict;
    case "VALIDATION_FAILED":
      return e.validation;
    case "CUSTOMER_NOT_FOUND":
      return e.customerNotFound;
    case "CBS_UNAVAILABLE":
      return e.cbsUnavailable;
    case "PREMIUM_MISMATCH":
      return e.premiumMismatch;
    case "CONSENT_REQUIRED":
      return e.consentRequired;
    case "ACCOUNT_NOT_ELIGIBLE":
      return e.accountNotEligible;
    case "POSTING_UNRESOLVED":
      return e.postingUnresolved;
    case "MAKER_CANNOT_CHECK":
      return e.makerCannotCheck;
    case "INVALID_STATE":
      return e.invalidState;
    case "IDEMPOTENCY_IN_PROGRESS":
      return e.idempotencyInProgress;
    case "RATE_LIMITED":
      return e.rateLimited;
    case "LOGIN_FAILED":
      return strings.signIn.failed;
    case "AUTH_UNAVAILABLE":
      return strings.signIn.unavailable;
    default:
      return e.generic;
  }
}

export function correlationOf(err: unknown): string | null {
  return err instanceof ApiError ? err.correlationId : null;
}
