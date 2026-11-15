"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { API_BASE, type ApiResult } from "@/lib/api";
import {
  CHAT_MAX_CHARS,
  CHAT_MAX_MESSAGES,
  CHAT_MODELS_PATH,
  CHAT_PATH,
  PROVIDER_LABEL,
  describeChatFailure,
  featuredModels,
  getChatModels,
  initialModel,
  messageProblem,
  sendChat,
  type ChatFailureView,
  type ChatMessage,
  type ChatModel,
  type ChatModelsResponse,
  type ChatResponse,
} from "@/lib/chat";
import { usePrefersReducedMotion } from "../../CascadeGraph";
import { ProvenanceBadge } from "../../ProvenanceBadge";
import { ModelWrittenBadge } from "./ChatBadges";
import { ModelPicker } from "./ModelPicker";
import { ReplyText } from "./ReplyText";
import { ToolSteps } from "./ToolSteps";
import "./chat.css";

/**
 * "Ask the engine" (#186): the live engine-tool chat, the hero of /explore.
 *
 * A hosted model (picked by the presenter or a judge) answers in words and calls FAULTLINE's engine tools on the
 * server; every number in its reply comes from those tools. This panel only sends the conversation and renders the
 * answer: the reply verbatim (minimal safe markdown, no HTML) and the steps the model took (tool name, status,
 * provenance, input and the server's result summary). The browser recomputes nothing.
 *
 * The API is not streaming. While a request is in flight the panel says so with the real elapsed time; it never
 * types out text or plays invented steps. The conversation lives in React state only and is never persisted.
 */

const STARTERS = [
  { title: "Supplier failure", prompt: "What if the supplier goes bust and we protect payroll?" },
  { title: "Judge's Challenge", prompt: "Which Judge's Challenge hurts cash the most?" },
  { title: "Rate shock", prompt: "How long is our runway if rates rise 200 bp from week 1?" },
];

type ModelsState = { kind: "loading" } | { kind: "done"; result: ApiResult<ChatModelsResponse> };

type Outcome =
  | { kind: "waiting"; startedAt: number }
  | { kind: "done"; response: ChatResponse; ms: number }
  | { kind: "failed"; failure: ChatFailureView };

interface Turn {
  id: number;
  question: string;
  model: ChatModel;
  outcome: Outcome;
}

/** The conversation sent to the server: each question that got an "ok" reply, then that reply. */
function historyOf(turns: readonly Turn[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  for (const t of turns) {
    if (t.outcome.kind === "done" && t.outcome.response.status === "ok" && t.outcome.response.reply.trim()) {
      out.push({ role: "user", content: t.question }, { role: "assistant", content: t.outcome.response.reply });
    }
  }
  return out;
}

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, []);
  return <span className="num" data-testid="chat-elapsed">{Math.max(0, (now - since) / 1000).toFixed(1)} s</span>;
}

export function ChatPanel() {
  const reduce = usePrefersReducedMotion();
  const [models, setModels] = useState<ModelsState>({ kind: "loading" });
  const [modelsRetry, setModelsRetry] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const seq = useRef(0);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const lastRef = useRef<HTMLLIElement | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    void getChatModels(ctrl.signal).then((result) => {
      if (!ctrl.signal.aborted) setModels({ kind: "done", result });
    });
    return () => ctrl.abort();
  }, [modelsRetry]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const catalogue = models.kind === "done" && models.result.ok ? models.result.data : null;
  // The presenter's pick wins; until then the server's default (when it is available).
  const selectedId = picked ?? (catalogue ? initialModel(catalogue) : null);
  const selected = catalogue?.models.find((m) => m.id === selectedId && m.available) ?? null;
  const waiting = turns.some((t) => t.outcome.kind === "waiting");
  const modelsFailure = models.kind === "done" && !models.result.ok ? describeChatFailure(models.result) : null;
  const history = useMemo(() => historyOf(turns), [turns]);
  const featured = useMemo(() => (catalogue ? featuredModels(catalogue).filter((m) => m.available) : []), [catalogue]);

  const lastOutcome = turns[turns.length - 1]?.outcome.kind;
  useEffect(() => {
    if (!lastRef.current || lastOutcome === undefined) return;
    lastRef.current.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
  }, [lastOutcome, turns.length, reduce]);

  const send = useCallback(
    (question: string, model: ChatModel | null, base: readonly Turn[]) => {
      if (!model) {
        setHint("Pick a model first.");
        return;
      }
      const hist = historyOf(base);
      const problem = messageProblem(question, hist);
      if (problem) {
        setHint(problem);
        return;
      }
      setHint(null);
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      seq.current += 1;
      const id = seq.current;
      const startedAt = Date.now();
      setTurns([...base, { id, question, model, outcome: { kind: "waiting", startedAt } }]);
      setText("");
      void sendChat({ model_id: model.id, messages: [...hist, { role: "user", content: question }] }, ctrl.signal).then((res) => {
        if (abortRef.current === ctrl) abortRef.current = null;
        const outcome: Outcome = res.ok
          ? { kind: "done", response: res.data, ms: Date.now() - startedAt }
          : { kind: "failed", failure: describeChatFailure(res) };
        setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, outcome } : t)));
      });
    },
    [],
  );

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (waiting) return;
    send(text, selected, turns);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };
  const clear = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setTurns([]);
    setHint(null);
    inputRef.current?.focus();
  };
  const stop = () => abortRef.current?.abort();
  /** "Try another model": switch to a featured model and ask the same question again. */
  const retryWith = (turn: Turn, model: ChatModel) => {
    setPicked(model.id);
    send(turn.question, model, turns.filter((t) => t.id !== turn.id));
  };

  const canSend = !!selected && !waiting && !!text.trim();

  return (
    <section
      aria-labelledby="chat-title"
      className="chat-hero-glow relative flex min-w-0 flex-col overflow-hidden rounded-xl border border-line bg-elevated"
      data-testid="chat-panel"
    >
      <header className="flex flex-col gap-5 border-b border-line px-4 pb-5 pt-6 md:px-8 md:pt-8 xl:flex-row xl:items-end xl:justify-between">
        <div className="flex min-w-0 flex-col gap-3">
          <p className="kicker">
            <span className="text-text-2">F.0</span> · live chat · engine tools on the server
          </p>
          <h2 id="chat-title" className="display text-[clamp(3rem,7vw,6.5rem)] text-text">
            Ask the <em>engine</em>
          </h2>
          <p className="max-w-3xl text-base leading-relaxed text-text-2 md:text-lg">
            Pick any model. It answers in words and calls FAULTLINE&apos;s simulator, optimizer and decision tools; every
            number in a reply comes from those tools, and every tool call it made is listed under the reply.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 xl:justify-end">
          <ProvenanceBadge kind="LIVE EXPLORE" />
          <ModelWrittenBadge />
          <ProvenanceBadge kind="SIMULATED" detail="engine numbers" />
          <ProvenanceBadge kind="SYNTHETIC" detail="demo business" />
        </div>
      </header>

      <div className="border-b border-line px-4 py-4 md:px-8">
        {models.kind === "loading" ? (
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted" role="status">
            Loading GET {CHAT_MODELS_PATH}
          </p>
        ) : catalogue ? (
          catalogue.models.length === 0 ? (
            <p className="font-mono text-sm uppercase tracking-[0.08em] text-muted">No models served: NOT AVAILABLE</p>
          ) : (
            <ModelPicker data={catalogue} selected={selectedId} onSelect={setPicked} disabled={waiting} />
          )
        ) : modelsFailure ? (
          <div className="flex flex-wrap items-center justify-between gap-3" data-testid="chat-models-failed">
            <div className="min-w-0">
              <p className="font-mono text-sm font-medium uppercase tracking-[0.08em] text-muted">Models NOT AVAILABLE</p>
              <p className="mt-1 break-words text-xs text-muted">
                {modelsFailure.heading}
                {modelsFailure.detail ? ` ${modelsFailure.detail}` : ""}
                {modelsFailure.kind === "unreachable" ? ` (${API_BASE})` : ""}
              </p>
            </div>
            <button type="button" onClick={() => { setModels({ kind: "loading" }); setModelsRetry((n) => n + 1); }} className="rounded-md border border-line-strong px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-text-2 hover:bg-hover hover:text-text">
              Retry
            </button>
          </div>
        ) : null}
      </div>

      <div className="flex min-w-0 flex-col gap-5 px-4 py-5 md:px-8 md:py-6">
        {turns.length === 0 ? (
          <div className="flex flex-col gap-3">
            <p className="kicker">Try one of these</p>
            <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {STARTERS.map((s) => (
                <li key={s.prompt} className="min-w-0">
                  <button
                    type="button"
                    onClick={() => send(s.prompt, selected, turns)}
                    disabled={!selected || waiting}
                    className="group flex h-full w-full min-w-0 flex-col gap-2 rounded-lg border border-line bg-bg/40 p-4 text-left transition-[border-color,background-color,transform] hover:-translate-y-px hover:border-accent/60 hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
                    data-testid="chat-starter"
                  >
                    <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-accent">{s.title}</span>
                    <span className="text-[15px] leading-snug text-text 2xl:text-base">{s.prompt}</span>
                    <span className="mt-auto font-mono text-[10px] uppercase tracking-[0.12em] text-muted group-hover:text-text-2">
                      Ask →
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {turns.length > 0 ? (
          <ol role="log" aria-live="polite" aria-label="Conversation" className="flex min-w-0 flex-col gap-6" data-testid="chat-log">
            {turns.map((t, i) => (
              <li key={t.id} ref={i === turns.length - 1 ? lastRef : undefined} className="flex min-w-0 scroll-mt-20 flex-col gap-3">
                <UserBubble text={t.question} />
                <AssistantTurn
                  turn={t}
                  reduce={reduce}
                  featured={featured}
                  onStop={stop}
                  onRetryWith={(m) => retryWith(t, m)}
                  isLast={i === turns.length - 1}
                  busy={waiting}
                />
              </li>
            ))}
          </ol>
        ) : null}

      </div>

      <form onSubmit={submit} className="sticky bottom-0 flex min-w-0 flex-col gap-2 border-t border-line bg-elevated/95 px-4 py-4 backdrop-blur-[12px] md:px-8" data-testid="chat-composer">
        <label htmlFor="chat-input" className="sr-only">
          Ask the engine a question
        </label>
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end">
          <textarea
            id="chat-input"
            ref={inputRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            rows={2}
            maxLength={CHAT_MAX_CHARS}
            placeholder={selected ? `Ask ${selected.label} about the demo business…` : "Pick a model, then ask a question…"}
            className="min-h-[3.25rem] w-full min-w-0 resize-y rounded-lg border border-line-strong bg-bg px-4 py-3 text-base leading-relaxed text-text placeholder:text-muted focus:border-accent focus:outline-none disabled:opacity-60 2xl:text-lg"
          />
          <div className="flex shrink-0 gap-2">
            <button
              type="submit"
              disabled={!canSend}
              className="flex-1 rounded-lg border border-accent bg-accent px-5 py-3 font-mono text-[12px] font-semibold uppercase tracking-[0.14em] text-bg transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:border-line-strong disabled:bg-transparent disabled:text-muted sm:flex-none"
            >
              Ask
            </button>
            <button
              type="button"
              onClick={clear}
              disabled={turns.length === 0}
              className="rounded-lg border border-line-strong px-4 py-3 font-mono text-[11px] uppercase tracking-[0.12em] text-text-2 hover:bg-hover hover:text-text disabled:cursor-not-allowed disabled:opacity-40"
            >
              Clear chat
            </button>
          </div>
        </div>
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 font-mono text-[10.5px] text-muted">
          <span>Enter to send · Shift+Enter for a new line · not saved: clearing or reloading erases it</span>
          <span className="num">
            {text.length.toLocaleString("en-US")} / {CHAT_MAX_CHARS.toLocaleString("en-US")} chars · {history.length} / {CHAT_MAX_MESSAGES} messages
          </span>
        </div>
        {hint ? (
          <p className="text-xs text-risk" role="alert" data-testid="chat-hint">
            {hint}
          </p>
        ) : null}
      </form>
    </section>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="chat-enter flex min-w-0 justify-end">
      <div className="min-w-0 max-w-[min(100%,48rem)] rounded-lg rounded-br-sm border border-accent/40 bg-accent-soft px-4 py-2.5">
        <p className="mb-0.5 text-right font-mono text-[10px] uppercase tracking-[0.14em] text-muted">You</p>
        <p className="whitespace-pre-wrap break-words text-[15px] leading-relaxed text-text [overflow-wrap:anywhere] md:text-base">{text}</p>
      </div>
    </div>
  );
}

function ModelLine({ model, response, ms }: { model: ChatModel; response?: ChatResponse; ms?: number }) {
  const provider = response ? response.provider : model.provider;
  return (
    <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] text-muted" data-testid="chat-model-line">
      <span className="rounded-sm border border-line-strong px-1.5 py-0.5 text-text" data-testid="chat-model-id">
        {response ? response.model_id : model.id}
      </span>
      <span>{PROVIDER_LABEL[provider]}</span>
      {response ? (
        <span className="num" data-testid="chat-usage">
          {response.usage
            ? `${response.usage.input_tokens.toLocaleString("en-US")} in · ${response.usage.output_tokens.toLocaleString("en-US")} out tokens`
            : "token usage NOT AVAILABLE"}
        </span>
      ) : null}
      {ms !== undefined ? <span className="num">· answered in {(ms / 1000).toFixed(1)} s</span> : null}
    </p>
  );
}

function AssistantTurn({
  turn,
  reduce,
  featured,
  onStop,
  onRetryWith,
  isLast,
  busy,
}: {
  turn: Turn;
  reduce: boolean;
  featured: ChatModel[];
  onStop: () => void;
  onRetryWith: (m: ChatModel) => void;
  isLast: boolean;
  busy: boolean;
}) {
  const o = turn.outcome;
  if (o.kind === "waiting") {
    return (
      <div className="flex min-w-0 flex-col gap-3 rounded-lg border border-line bg-bg/40 p-4 md:p-5" role="status" data-testid="chat-waiting">
        <ModelLine model={turn.model} />
        <p className="flex flex-wrap items-baseline gap-x-2 text-[15px] text-text-2">
          <span className="font-medium text-text">Waiting for {turn.model.label}</span>
          <span className="text-muted">· it may call the engine tools on the server before it answers ·</span>
          <Elapsed since={o.startedAt} />
        </p>
        <div className="relative h-[3px] max-w-xl overflow-hidden rounded-full bg-line" aria-hidden="true">
          <div className={`absolute inset-y-0 left-0 w-1/3 rounded-full bg-accent ${reduce ? "" : "chat-waiting-bar"}`} />
        </div>
        <p className="font-mono text-[10.5px] text-muted">
          The reply arrives in one piece (POST {CHAT_PATH} is not streaming); the tools it used are listed once it lands.
        </p>
        <button type="button" onClick={onStop} className="w-fit rounded-md border border-line-strong px-3 py-1.5 font-mono text-[10.5px] uppercase tracking-[0.12em] text-text-2 hover:bg-hover hover:text-text">
          Stop waiting
        </button>
      </div>
    );
  }
  if (o.kind === "failed") {
    return (
      <div className="flex min-w-0 flex-col gap-2 rounded-lg border border-fail/50 bg-[color-mix(in_srgb,var(--fail)_5%,transparent)] p-4" role="alert" data-testid="chat-failure" data-kind={o.failure.kind}>
        <ModelLine model={turn.model} />
        <p className="text-[15px] font-medium text-text">{o.failure.heading}</p>
        {o.failure.detail ? <p className="break-words font-mono text-[11px] text-text-2 [overflow-wrap:anywhere]">{o.failure.detail}</p> : null}
        <p className="font-mono text-[10.5px] text-muted">No answer is shown for this question.</p>
      </div>
    );
  }
  const r = o.response;
  const notOk = r.status !== "ok";
  const others = featured.filter((m) => m.id !== turn.model.id).slice(0, 4);
  return (
    <article
      className={`${reduce ? "" : "chat-enter"} flex min-w-0 flex-col gap-4 rounded-lg border bg-bg/40 p-4 md:p-6 ${notOk ? "border-fail/50" : "border-line"}`}
      data-testid="chat-answer"
      data-status={r.status}
    >
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <ModelLine model={turn.model} response={r} ms={o.ms} />
        <span className="flex flex-wrap items-center gap-1.5">
          <ProvenanceBadge kind="LIVE EXPLORE" />
          <ModelWrittenBadge />
        </span>
      </div>

      {notOk ? (
        <div className="flex flex-col gap-2" data-testid="chat-answer-problem">
          <p className="text-[15px] font-medium text-fail">
            {r.status === "unavailable" ? "This model is not available for chat right now." : "This model did not produce a usable answer."}
          </p>
          {r.notes.length ? (
            <ul className="flex flex-col gap-1">
              {r.notes.map((n, k) => (
                <li key={k} className="break-words font-mono text-[11.5px] text-text-2 [overflow-wrap:anywhere]">{n}</li>
              ))}
            </ul>
          ) : (
            <p className="font-mono text-[11px] text-muted">The API sent no note.</p>
          )}
          {isLast && others.length ? (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-muted">Try another model:</span>
              {others.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => onRetryWith(m)}
                  disabled={busy}
                  className="rounded-full border border-accent/60 px-3 py-1 text-[13px] text-text hover:bg-accent-soft disabled:opacity-50"
                  data-testid="chat-switch-model"
                >
                  {m.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {r.reply.trim() && !notOk ? <ReplyText text={r.reply} className="max-w-[80ch]" /> : null}
      {!r.reply.trim() && !notOk ? <p className="font-mono text-sm uppercase tracking-[0.08em] text-muted">Reply NOT AVAILABLE: the model returned no text.</p> : null}

      {r.status === "ok" && r.notes.length ? (
        <ul className="flex flex-col gap-0.5 border-l border-line-strong pl-3">
          {r.notes.map((n, k) => (
            <li key={k} className="break-words font-mono text-[10.5px] text-muted [overflow-wrap:anywhere]">{n}</li>
          ))}
        </ul>
      ) : null}

      {!notOk || r.tool_calls.length ? <ToolSteps calls={r.tool_calls} reduce={reduce} /> : null}


      <p className="font-mono text-[10px] leading-snug text-muted">
        {r.label} · words by the model, numbers from the engine tools it called · not saved
      </p>
    </article>
  );
}

