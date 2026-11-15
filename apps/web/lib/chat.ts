/**
 * "Ask the engine": client for the live engine-tool chat on /explore (issue #186).
 *
 * Contract (built in parallel on the backend branch `ash/live-chat-api`):
 * - GET  /api/explore/chat/models → {models: [{id, label, provider, available, note, context_length?, pricing?}],
 *                                     default, featured?: [ids]}: the full runtime catalogue (open-weight models via
 *                                     OpenRouter; OpenAI and Claude through their native APIs only)
 * - POST /api/explore/chat        → {status, provenance: "LIVE EXPLORE", label, model_id, provider, reply,
 *                                     tool_calls: [{name, input, result_status, result_summary, provenance}],
 *                                     usage: {input_tokens, output_tokens} | null, notes}
 *
 * Honesty rules (AGENTS.md §4): the reply is MODEL-WRITTEN text; every number it quotes came from an engine tool the
 * server ran. The browser never recomputes or edits those numbers. A body that does not match the contract is refused
 * as `malformed` (rendered NOT AVAILABLE), never coerced. The API is not streaming: nothing here imitates live tokens.
 *
 * TODO(presenter mode): when `components/PresenterToken.tsx` and the Authorization header in `lib/api.ts`
 * `requestJson` land on main, chat requests inherit that header automatically because they go through `requestJson`.
 * Until then chat requests carry no token, and a 401/403 renders "chat is disabled on the public demo right now".
 */
import { requestJson, type ApiFailure, type ApiResult } from "./api";

export const CHAT_MODELS_PATH = "/api/explore/chat/models";
export const CHAT_PATH = "/api/explore/chat";

/** Server limits: at most 20 messages per request, 4,000 characters each. */
export const CHAT_MAX_MESSAGES = 20;
export const CHAT_MAX_CHARS = 4000;

/** The wire provenance and label every chat reply carries. */
export const CHAT_PROVENANCE = "LIVE EXPLORE";
export const CHAT_LABEL = "MODEL-WRITTEN, numbers from engine tools";

export const CHAT_PROVIDERS = ["openrouter", "openai", "anthropic"] as const;
export type ChatProvider = (typeof CHAT_PROVIDERS)[number];
/** OpenAI and Claude models are served through their native APIs; OpenRouter carries the open-weight models. */
export const PROVIDER_LABEL: Record<ChatProvider, string> = {
  openrouter: "Open models via OpenRouter",
  openai: "OpenAI (direct)",
  anthropic: "Anthropic Claude (direct)",
};
export const PROVIDER_SHORT: Record<ChatProvider, string> = {
  openrouter: "OpenRouter",
  openai: "OpenAI",
  anthropic: "Anthropic",
};

/** USD per million tokens, as the server states it. Only fields whose name says "per million" are read. */
export interface ChatModelPricing {
  input_per_mtok?: number | null;
  output_per_mtok?: number | null;
}

export interface ChatModel {
  id: string;
  label: string;
  provider: ChatProvider;
  available: boolean;
  note: string | null;
  /** Context window in tokens, when the server reports it. */
  context_length?: number | null;
  pricing?: ChatModelPricing | null;
}

export interface ChatModelsResponse {
  models: ChatModel[];
  default: string | null;
  /** Model ids shown first as pills; ids not in `models` are ignored. Optional for older API builds. */
  featured?: string[];
}

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export interface ChatRequest {
  model_id: string;
  messages: ChatMessage[];
}

export interface ChatToolCall {
  name: string;
  input: Record<string, unknown>;
  result_status: string;
  /** What the model was shown, from the engine: an object on the #193 backend; a string or null is also accepted. */
  result_summary: Record<string, unknown> | string | null;
  provenance: string;
}

export interface ChatUsage {
  input_tokens: number;
  output_tokens: number;
}

export type ChatStatus = "ok" | "unavailable" | "error";

export interface ChatResponse {
  status: ChatStatus;
  provenance: typeof CHAT_PROVENANCE;
  label: string;
  model_id: string;
  provider: ChatProvider;
  reply: string;
  tool_calls: ChatToolCall[];
  usage: ChatUsage | null;
  notes: string[];
}

const STATUSES = new Set<string>(["ok", "unavailable", "error"]);
const PROVIDERS = new Set<string>(CHAT_PROVIDERS);

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const isCount = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 0;
const strOrNull = (v: unknown) => v === null || typeof v === "string";

/** Shape check for GET /api/explore/chat/models. Returns the problem, or null when the body matches. */
export function checkModelsResponse(v: unknown): string | null {
  if (!isObj(v) || !Array.isArray(v.models)) return "models list missing";
  const ids = new Set<string>();
  for (const [i, m] of v.models.entries()) {
    if (!isObj(m) || typeof m.id !== "string" || !m.id || typeof m.label !== "string") return `models[${i}] id or label`;
    if (typeof m.provider !== "string" || !PROVIDERS.has(m.provider)) return `models[${i}] unknown provider`;
    if (typeof m.available !== "boolean" || !strOrNull(m.note)) return `models[${i}] availability`;
    if (!(m.context_length === undefined || m.context_length === null || isCount(m.context_length))) {
      return `models[${i}] context_length`;
    }
    if (!(m.pricing === undefined || m.pricing === null || isObj(m.pricing))) return `models[${i}] pricing`;
    if (isObj(m.pricing)) {
      for (const k of ["input_per_mtok", "output_per_mtok"]) {
        const x = m.pricing[k];
        if (!(x === undefined || x === null || (typeof x === "number" && Number.isFinite(x) && x >= 0))) {
          return `models[${i}] pricing.${k}`;
        }
      }
    }
    if (ids.has(m.id)) return `models[${i}] duplicate id`;
    ids.add(m.id);
  }
  if (!strOrNull(v.default)) return "default malformed";
  if (!(v.featured === undefined || (Array.isArray(v.featured) && v.featured.every((f) => typeof f === "string")))) {
    return "featured malformed";
  }
  return null;
}

function checkToolCall(t: unknown, i: number): string | null {
  if (!isObj(t) || typeof t.name !== "string" || !t.name) return `tool_calls[${i}] name`;
  if (!isObj(t.input)) return `tool_calls[${i}] input`;
  if (typeof t.result_status !== "string" || !(strOrNull(t.result_summary) || isObj(t.result_summary))) return `tool_calls[${i}] result`;
  if (typeof t.provenance !== "string") return `tool_calls[${i}] provenance`;
  return null;
}

/** Shape check for POST /api/explore/chat. An unknown `status` is refused, never guessed. */
export function checkChatResponse(v: unknown): string | null {
  if (!isObj(v)) return "empty body";
  if (typeof v.status !== "string" || !STATUSES.has(v.status)) return "unknown status";
  if (v.provenance !== CHAT_PROVENANCE) return "provenance is not LIVE EXPLORE";
  if (typeof v.label !== "string") return "label missing";
  if (typeof v.model_id !== "string" || typeof v.provider !== "string" || !PROVIDERS.has(v.provider)) return "model or provider";
  if (typeof v.reply !== "string") return "reply missing";
  if (!Array.isArray(v.tool_calls)) return "tool_calls missing";
  for (const [i, t] of v.tool_calls.entries()) {
    const problem = checkToolCall(t, i);
    if (problem) return problem;
  }
  if (!(v.usage === null || (isObj(v.usage) && isCount(v.usage.input_tokens) && isCount(v.usage.output_tokens)))) {
    return "usage malformed";
  }
  if (!Array.isArray(v.notes) || !v.notes.every((n) => typeof n === "string")) return "notes malformed";
  return null;
}

/** Models grouped by provider in the fixed order OpenRouter, OpenAI, Anthropic; empty groups are dropped. */
export function groupModels(models: readonly ChatModel[]): { provider: ChatProvider; models: ChatModel[] }[] {
  return CHAT_PROVIDERS.map((provider) => ({ provider, models: models.filter((m) => m.provider === provider) })).filter(
    (g) => g.models.length > 0,
  );
}

/** The featured models that are listed, in provider order (OpenRouter, OpenAI, Anthropic), then the server's order. */
export function featuredModels(data: ChatModelsResponse): ChatModel[] {
  const byId = new Map(data.models.map((m) => [m.id, m]));
  const seen = new Set<string>();
  const picked: ChatModel[] = [];
  for (const id of data.featured ?? []) {
    const m = byId.get(id);
    if (m && !seen.has(id)) {
      seen.add(id);
      picked.push(m);
    }
  }
  return CHAT_PROVIDERS.flatMap((p) => picked.filter((m) => m.provider === p));
}

/** "128K ctx" / "1M ctx" from the served context length; null when it is not served. Formatting only. */
export function contextLabel(m: ChatModel): string | null {
  const n = m.context_length;
  if (n === undefined || n === null) return null;
  if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(2)}M ctx`;
  if (n >= 1000) return `${Math.round(n / 1000)}K ctx`;
  return `${n} ctx`;
}

const PRICE = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 3 });

/** "$3.00 in · $15.00 out /M tok" from the served prices; null when neither is served. Formatting only. */
export function priceLabel(m: ChatModel): string | null {
  const p = m.pricing;
  if (!p) return null;
  const inp = typeof p.input_per_mtok === "number" ? PRICE.format(p.input_per_mtok) : null;
  const out = typeof p.output_per_mtok === "number" ? PRICE.format(p.output_per_mtok) : null;
  if (inp === null && out === null) return null;
  return `${inp ?? "n/a"} in · ${out ?? "n/a"} out /M tok`;
}

/** The preselected model: the server's `default` when it is available; otherwise nothing (the presenter picks). */
export function initialModel(data: ChatModelsResponse): string | null {
  const d = data.models.find((m) => m.id === data.default);
  return d && d.available ? d.id : null;
}

/** Why a message cannot be sent as it stands, or null. Mirrors the server's limits; the server still checks. */
export function messageProblem(text: string, history: readonly ChatMessage[]): string | null {
  if (!text.trim()) return "Type a question first.";
  if (text.length > CHAT_MAX_CHARS) return `Messages are limited to ${CHAT_MAX_CHARS.toLocaleString("en-US")} characters.`;
  if (history.length + 1 > CHAT_MAX_MESSAGES) {
    return `This conversation has reached the ${CHAT_MAX_MESSAGES}-message limit. Clear the chat to start a new one.`;
  }
  return null;
}

/** GET /api/explore/chat/models. Never throws. */
export async function getChatModels(signal?: AbortSignal): Promise<ApiResult<ChatModelsResponse>> {
  const res = await requestJson<ChatModelsResponse>("GET", CHAT_MODELS_PATH, 6000, signal);
  if (!res.ok) return res;
  const problem = checkModelsResponse(res.data);
  return problem ? { ok: false, kind: "malformed", error: `malformed chat models payload: ${problem}` } : res;
}

/** POST /api/explore/chat. Never throws. Tool-calling turns can take a while, so the timeout is generous. */
export async function sendChat(req: ChatRequest, signal?: AbortSignal): Promise<ApiResult<ChatResponse>> {
  const res = await requestJson<ChatResponse>("POST", CHAT_PATH, 120_000, signal, req);
  if (!res.ok) return res;
  const problem = checkChatResponse(res.data);
  return problem ? { ok: false, kind: "malformed", error: `malformed chat payload: ${problem}` } : res;
}

export type ChatFailureKind =
  | "paused"
  | "rate_limited"
  | "busy"
  | "unavailable"
  | "upstream"
  | "admin"
  | "validation"
  | "not_served"
  | "unreachable"
  | "aborted"
  | "malformed"
  | "http";

export interface ChatFailureView {
  kind: ChatFailureKind;
  heading: string;
  /** The server's own message where one was sent; shown verbatim under the heading. */
  detail: string | null;
}

/** Translate a failed chat request into an honest, human message. The server's text is kept, never replaced. */
export function describeChatFailure(f: ApiFailure): ChatFailureView {
  const detail = f.error && !/^HTTP \d+$/.test(f.error) ? f.error : null;
  if (f.kind === "aborted") return { kind: "aborted", heading: "Stopped waiting for this reply.", detail: null };
  if (f.kind === "network" || f.kind === "timeout") {
    return {
      kind: "unreachable",
      heading: f.kind === "timeout" ? "The API did not answer in time." : "The API could not be reached.",
      detail,
    };
  }
  if (f.kind === "malformed") {
    return { kind: "malformed", heading: "The reply did not match the chat contract, so none of it is shown.", detail };
  }
  if (f.status === 503 && f.code === "PAUSED") {
    return { kind: "paused", heading: "The team is presenting right now. Chat is back in a few minutes.", detail: null };
  }
  if (f.status === 429) return { kind: "rate_limited", heading: "Limit reached, try again in a few minutes.", detail };
  if (f.status === 401 || f.status === 403) {
    return { kind: "admin", heading: "Chat is disabled on the public demo right now.", detail: null };
  }
  if (f.status === 503 && f.code === "BUSY") {
    return { kind: "busy", heading: "The engine chat is busy. Try again in a moment.", detail };
  }
  if (f.status === 503) return { kind: "unavailable", heading: "Live chat is not available on this server.", detail };
  if (f.status === 502) return { kind: "upstream", heading: "The model provider returned an error.", detail };
  if (f.status === 404) {
    return { kind: "not_served", heading: `This API build does not serve ${CHAT_PATH} yet.`, detail: null };
  }
  if (f.kind === "validation") return { kind: "validation", heading: "The server rejected this message.", detail };
  return { kind: "http", heading: `The chat request failed${f.status ? ` (HTTP ${f.status})` : ""}.`, detail };
}

export const CHAT_STATUS_PATH = "/api/explore/chat/status";

/** GET /api/explore/chat/status: the presenter pause switch (routes/explore_chat.py `ChatStatus`). */
export interface ChatPauseStatus {
  paused: boolean;
  until: string | null;
}

/** GET /api/explore/chat/status. Never throws; a body that does not match is `malformed` (no banner is shown). */
export async function getChatStatus(signal?: AbortSignal): Promise<ApiResult<ChatPauseStatus>> {
  const res = await requestJson<ChatPauseStatus>("GET", CHAT_STATUS_PATH, 6000, signal);
  if (!res.ok) return res;
  const v: unknown = res.data;
  if (!isObj(v) || typeof v.paused !== "boolean" || !strOrNull(v.until)) {
    return { ok: false, kind: "malformed", error: "malformed chat status payload" };
  }
  return res;
}
