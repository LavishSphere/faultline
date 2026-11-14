/**
 * GET /api/integrity client (issue #81). Types mirror `services/api/routes/integrity.py` field for field.
 *
 * Honesty rules: every status shown in the INTEGRITY panel is the API's own `status` for that check, computed on
 * the server on this request. The browser never decides that a check passed. A body that does not match this
 * contract is reported as malformed and rendered NOT AVAILABLE, never coerced into a pass.
 */

import { API_BASE, describeErrorBody, type ApiResult } from "@/lib/api";

export type CheckStatus = "PASS" | "FAIL" | "NOT AVAILABLE";
export type CheckScope = "case" | "run" | "system";

export interface IntegrityFact {
  label: string;
  /** Counts, ids, flags or hashes as text; "NOT AVAILABLE" when unknown. */
  value: string;
}

export interface IntegrityCheck {
  id: string;
  scope: CheckScope;
  title: string;
  status: CheckStatus;
  explanation: string;
  facts: IntegrityFact[];
  enforced_by: string[];
}

export interface IntegrityExclusion {
  kind: "evidence" | "market";
  reason: string;
  count: number;
}

export interface IntegrityResponse {
  case_id: string | null;
  prediction_id: string | null;
  as_of: string | null;
  /** Wire provenance (e.g. "SYNTHETIC", "REAL_HISTORICAL"), or null without a case. */
  case_provenance: string | null;
  prediction_provenance: string | null;
  computed_at: string;
  checks: IntegrityCheck[];
  counts: { passed: number; failed: number; not_available: number };
  excluded: IntegrityExclusion[];
  limits: string[];
  notes: string[];
}

/** The subset of a `/api/cases` item the panel's case picker needs (models.ReplayCasePublic). */
export interface IntegrityCaseOption {
  event_id: string;
  title: string;
  as_of: string;
  provenance: string;
}

const STATUSES: readonly CheckStatus[] = ["PASS", "FAIL", "NOT AVAILABLE"];
const SCOPES: readonly CheckScope[] = ["case", "run", "system"];

const isStr = (v: unknown): v is string => typeof v === "string";
const isStrOrNull = (v: unknown): v is string | null => v === null || typeof v === "string";
const isCount = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 0;

function checkCheck(v: unknown): string | null {
  if (!v || typeof v !== "object") return "check missing";
  const c = v as Record<string, unknown>;
  if (!isStr(c.id) || !isStr(c.title) || !isStr(c.explanation)) return "check labels missing";
  if (!STATUSES.includes(c.status as CheckStatus)) return `check ${c.id}: unknown status`;
  if (!SCOPES.includes(c.scope as CheckScope)) return `check ${c.id}: unknown scope`;
  if (!Array.isArray(c.facts) || !c.facts.every((f) => f && isStr(f.label) && isStr(f.value))) {
    return `check ${c.id}: facts malformed`;
  }
  if (!Array.isArray(c.enforced_by) || !c.enforced_by.every(isStr)) return `check ${c.id}: enforced_by malformed`;
  return null;
}

/** Shape check on everything the panel reads. Exported for tests. */
export function checkIntegrityResponse(v: unknown): string | null {
  if (!v || typeof v !== "object") return "empty body";
  const r = v as Record<string, unknown>;
  for (const key of ["case_id", "prediction_id", "as_of", "case_provenance", "prediction_provenance"]) {
    if (!isStrOrNull(r[key])) return `${key} malformed`;
  }
  if (!isStr(r.computed_at)) return "computed_at missing";
  if (!Array.isArray(r.checks) || r.checks.length === 0) return "checks missing";
  for (const c of r.checks) {
    const problem = checkCheck(c);
    if (problem) return problem;
  }
  const counts = r.counts as Record<string, unknown> | undefined;
  if (!counts || !isCount(counts.passed) || !isCount(counts.failed) || !isCount(counts.not_available)) {
    return "counts malformed";
  }
  const statuses = (r.checks as IntegrityCheck[]).map((c) => c.status);
  const tally = (s: CheckStatus) => statuses.filter((x) => x === s).length;
  if (
    counts.passed !== tally("PASS") ||
    counts.failed !== tally("FAIL") ||
    counts.not_available !== tally("NOT AVAILABLE")
  ) {
    return "counts disagree with the checks' statuses";
  }
  if (!Array.isArray(r.excluded) || !r.excluded.every((x) => x && isStr(x.reason) && isCount(x.count))) {
    return "excluded malformed";
  }
  if (!Array.isArray(r.limits) || !r.limits.every(isStr)) return "limits malformed";
  if (!Array.isArray(r.notes) || !r.notes.every(isStr)) return "notes malformed";
  return null;
}

async function getJson(path: string, timeoutMs: number, signal?: AbortSignal): Promise<ApiResult<unknown>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);
  const onAbort = () => controller.abort(signal?.reason);
  if (signal?.aborted) onAbort();
  signal?.addEventListener("abort", onAbort, { once: true });
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: controller.signal,
    });
    if (!res.ok) {
      let body: unknown = null;
      try {
        body = await res.json();
      } catch {
        body = null;
      }
      const { message, code } = describeErrorBody(body);
      return {
        ok: false,
        kind: res.status === 422 ? "validation" : "http",
        status: res.status,
        code,
        error: message ?? `HTTP ${res.status}`,
      };
    }
    try {
      return { ok: true, data: (await res.json()) as unknown };
    } catch {
      return { ok: false, kind: "malformed", status: res.status, error: "response was not JSON" };
    }
  } catch (err) {
    if (controller.signal.aborted) {
      const reason: unknown = controller.signal.reason;
      const timedOut = reason instanceof DOMException && reason.name === "TimeoutError";
      return timedOut ? { ok: false, kind: "timeout", error: "timed out" } : { ok: false, kind: "aborted", error: "aborted" };
    }
    return { ok: false, kind: "network", error: err instanceof Error ? err.message : "request failed" };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

export const INTEGRITY_REQUEST = "GET /api/integrity";

/** GET /api/integrity?case_id=&prediction_id=. Never throws. */
export async function getIntegrity(
  params: { caseId?: string | null; predictionId?: string | null },
  signal?: AbortSignal,
): Promise<ApiResult<IntegrityResponse>> {
  const q = new URLSearchParams();
  if (params.caseId) q.set("case_id", params.caseId);
  if (params.predictionId) q.set("prediction_id", params.predictionId);
  const qs = q.toString();
  // The import scan and (once merged) the optimizer probe run server-side on each request: allow a little time.
  const res = await getJson(`/api/integrity${qs ? `?${qs}` : ""}`, 15000, signal);
  if (!res.ok) return res;
  const problem = checkIntegrityResponse(res.data);
  if (problem) return { ok: false, kind: "malformed", error: `integrity response: ${problem}` };
  return { ok: true, data: res.data as IntegrityResponse };
}

/** GET /api/cases, reduced to what the case picker shows. An empty list is a real, displayed state. */
export async function getIntegrityCases(signal?: AbortSignal): Promise<ApiResult<IntegrityCaseOption[]>> {
  const res = await getJson("/api/cases", 6000, signal);
  if (!res.ok) return res;
  const items = (res.data as { items?: unknown } | null)?.items;
  if (!Array.isArray(items)) return { ok: false, kind: "malformed", error: "cases response: items missing" };
  const out: IntegrityCaseOption[] = [];
  for (const it of items) {
    const c = it as Record<string, unknown> | null;
    if (!c || !isStr(c.event_id) || !isStr(c.title) || !isStr(c.as_of) || !isStr(c.provenance)) {
      return { ok: false, kind: "malformed", error: "cases response: item malformed" };
    }
    out.push({ event_id: c.event_id, title: c.title, as_of: c.as_of, provenance: c.provenance });
  }
  return { ok: true, data: out };
}
