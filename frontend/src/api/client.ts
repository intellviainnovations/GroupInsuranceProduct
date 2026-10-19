// Thin fetch wrapper for the staff API (docs/contracts/staff-api.md).
// - Session: HttpOnly cookie only (credentials: "same-origin"); nothing persisted in the browser.
// - CSRF: token held in memory, sent as X-CSRF-Token on every POST/PATCH.
// - Idempotency-Key: one UUID per user intent, supplied by the caller.
import type { ErrorBody, ErrorCode, FieldError } from "./model";

export const API_BASE = "/api/v1";

let csrfToken: string | null = null;
let onUnauthenticated: (() => void) | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function setUnauthenticatedHandler(handler: (() => void) | null): void {
  onUnauthenticated = handler;
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export type ClientErrorCode = ErrorCode | "NETWORK" | "UNEXPECTED";

export class ApiError extends Error {
  readonly status: number;
  readonly code: ClientErrorCode;
  readonly correlationId: string | null;
  readonly fields: FieldError[];

  constructor(status: number, code: ClientErrorCode, message: string, correlationId: string | null, fields: FieldError[]) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.correlationId = correlationId;
    this.fields = fields;
  }
}

type Query = Record<string, string | number | boolean | string[] | undefined | null>;

export interface RequestOptions {
  body?: unknown;
  query?: Query | undefined;
  idempotencyKey?: string | undefined;
}

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === "") continue;
      if (Array.isArray(v)) v.forEach((item) => params.append(k, item));
      else params.append(k, String(v));
    }
  }
  const qs = params.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ""}`;
}

function isErrorBody(value: unknown): value is ErrorBody {
  return typeof value === "object" && value !== null && "code" in value && "error" in value;
}

async function toApiError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  const headerCid = res.headers.get("X-Correlation-ID");
  if (isErrorBody(body)) {
    return new ApiError(res.status, body.code, body.error, body.correlation_id ?? headerCid, body.fields ?? []);
  }
  return new ApiError(res.status, "UNEXPECTED", res.statusText, headerCid, []);
}

async function send(method: string, path: string, opts: RequestOptions = {}): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const unsafe = method !== "GET";
  if (unsafe) {
    headers["Content-Type"] = "application/json";
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  }
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      ...(unsafe ? { body: JSON.stringify(opts.body ?? {}) } : {}),
    });
  } catch {
    throw new ApiError(0, "NETWORK", "Network error", null, []);
  }
  if (!res.ok) {
    const err = await toApiError(res);
    if (res.status === 401 && err.code === "UNAUTHENTICATED" && onUnauthenticated) onUnauthenticated();
    throw err;
  }
  return res;
}

export async function apiRequest<T>(method: "GET" | "POST" | "PATCH", path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await send(method, path, opts);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function apiBlob(path: string): Promise<{ blob: Blob; fileName: string | null }> {
  const res = await send("GET", path);
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  return { blob: await res.blob(), fileName: match?.[1] ?? null };
}
