/**
 * FAULTLINE API client.
 *
 * Rules (AGENTS.md §4, cascade-ui skill):
 * - The browser never computes authoritative numbers. Every figure shown comes from a response here.
 * - Anything not yet served by the API is listed in PENDING_ENDPOINTS and renders NOT AVAILABLE.
 *
 * Only `/api/health` is wired in this shell. Its response contract is being defined in issue #1
 * (services/api). `HealthResponse` below is a tolerant reading of that issue's acceptance criteria;
 * replace it with the generated Pydantic/OpenAPI type once `services/api/models.py` lands.
 */

// `||` (not `??`) so an empty NEXT_PUBLIC_API_BASE also falls back to the local default.
export const API_BASE: string = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000").replace(/\/+$/, "");

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string };

/** Raw `/api/health` payload as described by issue #1. All fields optional until the contract is fixed. */
export interface HealthResponse {
  status?: string;
  /** Issue #1: "ollama reachable (+ installed model tags)". Either a boolean or a nested object. */
  ollama?: boolean | { reachable?: boolean; models?: string[] };
  models?: string[];
  ollama_models?: string[];
  [key: string]: unknown;
}

export type ModelAvailability = "available" | "unavailable" | "unknown";

/** What the UI actually needs from `/api/health`. Derived only from fields the API returned. */
export interface HealthSummary {
  status: string | null;
  model: ModelAvailability;
  modelTags: string[];
  checkedAt: Date;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

export function summarizeHealth(raw: HealthResponse, checkedAt: Date = new Date()): HealthSummary {
  let reachable: boolean | undefined;
  let tags: string[] = [];

  if (typeof raw.ollama === "boolean") {
    reachable = raw.ollama;
  } else if (raw.ollama && typeof raw.ollama === "object") {
    if (typeof raw.ollama.reachable === "boolean") reachable = raw.ollama.reachable;
    tags = asStringArray(raw.ollama.models);
  }
  if (tags.length === 0) tags = asStringArray(raw.ollama_models);
  if (tags.length === 0) tags = asStringArray(raw.models);

  let model: ModelAvailability = "unknown";
  if (reachable === false) model = "unavailable";
  else if (reachable === true) model = tags.length > 0 ? "available" : "unavailable";

  return {
    status: typeof raw.status === "string" ? raw.status : null,
    model,
    modelTags: tags,
    checkedAt,
  };
}

async function getJson<T>(path: string, timeoutMs: number, signal?: AbortSignal): Promise<ApiResult<T>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);
  const onAbort = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", onAbort, { once: true });
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: controller.signal,
    });
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
    return { ok: true, data: (await res.json()) as T };
  } catch (err) {
    if (controller.signal.aborted) {
      const reason: unknown = controller.signal.reason;
      const timedOut = reason instanceof DOMException && reason.name === "TimeoutError";
      return { ok: false, error: timedOut ? "timed out" : "aborted" };
    }
    return { ok: false, error: err instanceof Error ? err.message : "request failed" };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

/** GET /api/health. Never throws; an unreachable API is a normal, displayed state. */
export async function getHealth(signal?: AbortSignal): Promise<ApiResult<HealthSummary>> {
  const res = await getJson<HealthResponse>("/api/health", 4000, signal);
  if (!res.ok) return res;
  if (!res.data || typeof res.data !== "object") return { ok: false, error: "malformed health payload" };
  return { ok: true, data: summarizeHealth(res.data) };
}

/**
 * Endpoints the screens need but that are not wired in this shell (SPEC §8 "Suggested API contract").
 * Panels reference these by key so the NOT AVAILABLE state names exactly what is missing.
 * No stub here returns data: there is nothing to return until the API serves it.
 */
export const PENDING_ENDPOINTS = {
  cases: "GET /api/cases",
  evidence: "GET /api/cases/{id}/evidence?as_of=",
  replayRun: "POST /api/replay/run",
  reveal: "POST /api/replay/{prediction_id}/reveal",
  simulate: "POST /api/simulate",
  optimize: "POST /api/optimize",
  benchmark: "GET /api/benchmark",
  vcLenses: "GET /api/vc-lenses",
} as const;

export type PendingEndpoint = keyof typeof PENDING_ENDPOINTS;
