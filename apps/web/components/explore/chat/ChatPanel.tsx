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
  getChatStatus,
  initialModel,
  messageProblem,
  sendChat,
  type ChatFailureView,
  type ChatMessage,
  type ChatModel,
  type ChatModelsResponse,
  type ChatResponse,
} from "@/lib/chat";
import { costLabel, drivesUniverse, replyCostUsd } from "@/lib/universe";
import { usePrefersReducedMotion } from "../../CascadeGraph";
import { ProvenanceBadge } from "../../ProvenanceBadge";
import { ModelWrittenBadge } from "./ChatBadges";
import { FlightPath } from "./FlightPath";
import { ModelGalaxy } from "./ModelGalaxy";
import { ModelPalette } from "./ModelPalette";
import { ReplyText } from "./ReplyText";
import { StarterCards } from "./StarterCards";
import { EngineAgreement, Universe, type UniverseSource } from "./Universe";
import { EvidenceCards } from "./EvidenceCards";
import { VoiceButton } from "./VoiceButton";
import "./chat.css";

/**
 * "Mission control" (#186, stage 2 #197): the live engine-tool chat, the hero of /explore.
 *
 * Left: the conversation. A hosted model answers in words and calls FAULTLINE's engine tools on the server; every
 * number in its reply comes from those tools. Right: the business universe, which re-runs the exact simulate /
 * optimize inputs of the selected answer on the engine and draws the engine's responses (Universe.tsx).
 *
 * The chat API is not streaming. While a request is in flight the panel says so with the real elapsed time; it never
 * types out text or plays invented steps. The steps the model took are revealed after the reply lands. A race sends
 * the same question to two models as two parallel requests and shows facts side by side; it names no winner.
 * The conversation lives in React state only and is never persisted.
 */

type ModelsState = { kind: "loading" } | { kind: "done"; result: ApiResult<ChatModelsResponse> };

type Outcome =
  | { kind: "waiting"; startedAt: number }
  | { kind: "done"; response: ChatResponse; ms: number }
  | { kind: "failed"; failure: ChatFailureView; ms: number };

interface Lane {
  model: ChatModel;
  outcome: Outcome;
}

interface Turn {
  id: number;
  question: string;
  /** One lane, or two in a race (same question, two models, two requests). */
  lanes: Lane[];
}

const RACE_LETTERS = ["A", "B"] as const;

/**
 * The conversation sent for lane `lane`: each question with an "ok" reply in that lane (or, for a turn asked to one
 * model, its only lane), then that reply. In a race each model keeps its own thread.
 */
function historyOf(turns: readonly Turn[], lane = 0): ChatMessage[] {
  const out: ChatMessage[] = [];
  for (const t of turns) {
    const l = t.lanes[lane] ?? t.lanes[0];
    if (l && l.outcome.kind === "done" && l.outcome.response.status === "ok" && l.outcome.response.reply.trim()) {
      out.push({ role: "user", content: t.question }, { role: "assistant", content: l.outcome.response.reply });
    }
  }
  return out;
}

const laneDrives = (l: Lane) => l.outcome.kind === "done" && drivesUniverse(l.outcome.response.tool_calls);

function Elapsed({ since, testId = "chat-elapsed" }: { since: number; testId?: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, []);
  return (
    <span className="num" data-testid={testId}>
      {Math.max(0, (now - since) / 1000).toFixed(1)} s
    </span>
  );
}

export function ChatPanel() {
  const reduce = usePrefersReducedMotion();
  const [models, setModels] = useState<ModelsState>({ kind: "loading" });
  const [modelsRetry, setModelsRetry] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const [pickedB, setPickedB] = useState<string | null>(null);
  const [race, setRace] = useState(false);
  const [palette, setPalette] = useState<null | "A" | "B">(null);
  const [galaxyOpen, setGalaxyOpen] = useState(true);
  const [paused, setPaused] = useState<{ until: string | null } | null>(null);
  const isPaused = paused !== null;
  const [turns, setTurns] = useState<Turn[]>([]);
  /** The answer shown on the universe; null follows the latest answer that called the engine. */
  const [shown, setShown] = useState<{ turn: number; lane: number } | null>(null);
  const [text, setText] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const aborts = useRef<Set<AbortController>>(new Set());
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

  // The presenter pause switch: a banner only (an admin caller may still chat while paused). Read on load, and every
  // 30 s while paused, so the banner clears when the presenter resumes (a successful send clears it too).
  useEffect(() => {
    const ctrl = new AbortController();
    const poll = () =>
      void getChatStatus(ctrl.signal).then((r) => {
        if (!ctrl.signal.aborted && r.ok) setPaused(r.data.paused ? { until: r.data.until } : null);
      });
    poll();
    const t = isPaused ? setInterval(poll, 30_000) : null;
    return () => {
      ctrl.abort();
      if (t) clearInterval(t);
    };
  }, [isPaused]);

  useEffect(() => {
    const set = aborts.current;
    return () => set.forEach((c) => c.abort());
  }, []);

  // ⌘K / Ctrl+K opens the full catalogue.
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => (p ? null : "A"));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const catalogue = models.kind === "done" && models.result.ok ? models.result.data : null;
  const selectedId = picked ?? (catalogue ? initialModel(catalogue) : null);
  const selected = catalogue?.models.find((m) => m.id === selectedId && m.available) ?? null;
  const featured = useMemo(() => (catalogue ? featuredModels(catalogue).filter((m) => m.available) : []), [catalogue]);
  const defaultB = featured.find((m) => m.id !== selected?.id) ?? catalogue?.models.find((m) => m.available && m.id !== selected?.id) ?? null;
  const selectedB =
    (pickedB && pickedB !== selected?.id ? catalogue?.models.find((m) => m.id === pickedB && m.available) : null) ?? defaultB;
  const waiting = turns.some((t) => t.lanes.some((l) => l.outcome.kind === "waiting"));
  const modelsFailure = models.kind === "done" && !models.result.ok ? describeChatFailure(models.result) : null;
  const history = useMemo(() => historyOf(turns), [turns]);

  const lastOutcome = turns[turns.length - 1]?.lanes.map((l) => l.outcome.kind).join();
  useEffect(() => {
    if (!lastRef.current || lastOutcome === undefined) return;
    lastRef.current.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
  }, [lastOutcome, turns.length, reduce]);

  const send = useCallback((question: string, lanesModels: (ChatModel | null)[], base: readonly Turn[]) => {
    if (lanesModels.some((m) => !m)) {
      setHint(lanesModels.length > 1 ? "Pick two different models to race." : "Pick a model first.");
      return;
    }
    const ms = lanesModels as ChatModel[];
    const hists = ms.map((_, i) => historyOf(base, i));
    const problem = hists.map((h) => messageProblem(question, h)).find((p) => p !== null) ?? null;
    if (problem) {
      setHint(problem);
      return;
    }
    setHint(null);
    aborts.current.forEach((c) => c.abort());
    aborts.current.clear();
    seq.current += 1;
    const id = seq.current;
    const startedAt = Date.now();
    setTurns([...base, { id, question, lanes: ms.map((model) => ({ model, outcome: { kind: "waiting", startedAt } })) }]);
    setShown(null);
    setText("");
    // One request per lane, in parallel: a race is exactly two POST /api/explore/chat calls.
    ms.forEach((model, lane) => {
      const ctrl = new AbortController();
      aborts.current.add(ctrl);
      void sendChat({ model_id: model.id, messages: [...hists[lane]!, { role: "user", content: question }] }, ctrl.signal).then((res) => {
        aborts.current.delete(ctrl);
        const ms2 = Date.now() - startedAt;
        const outcome: Outcome = res.ok
          ? { kind: "done", response: res.data, ms: ms2 }
          : { kind: "failed", failure: describeChatFailure(res), ms: ms2 };
        if (!res.ok && res.status === 503 && res.code === "PAUSED") setPaused((p) => p ?? { until: null });
        if (res.ok) setPaused(null);
        setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, lanes: t.lanes.map((l, i) => (i === lane ? { ...l, outcome } : l)) } : t)));
      });
    });
  }, []);

  const lanesToAsk = (): (ChatModel | null)[] => (race ? [selected, selectedB && selectedB.id !== selected?.id ? selectedB : null] : [selected]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (waiting) return;
    send(text, lanesToAsk(), turns);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };
  const clear = () => {
    aborts.current.forEach((c) => c.abort());
    aborts.current.clear();
    setTurns([]);
    setShown(null);
    setHint(null);
    inputRef.current?.focus();
  };
  const stop = () => aborts.current.forEach((c) => c.abort());
  const retryWith = (turn: Turn, model: ChatModel) => {
    setPicked(model.id);
    setRace(false);
    send(turn.question, [model], turns.filter((t) => t.id !== turn.id));
  };

  // The universe: the chosen answer, else the latest answer whose model called simulate or optimize.
  const shownTurn =
    (shown ? turns.find((t) => t.id === shown.turn) : undefined) ?? [...turns].reverse().find((t) => t.lanes.some(laneDrives));
  const sources: UniverseSource[] = shownTurn
    ? shownTurn.lanes.flatMap((l, i) =>
        l.outcome.kind === "done"
          ? [
              {
                key: `${shownTurn.id}:${i}`,
                title: `Answer ${turns.indexOf(shownTurn) + 1}${shownTurn.lanes.length > 1 ? ` · model ${RACE_LETTERS[i]}` : ""} · ${l.outcome.response.model_id}`,
                tab: `${RACE_LETTERS[i]} · ${l.model.label}`,
                calls: l.outcome.response.tool_calls,
              },
            ]
          : [],
      )
    : [];
  const focusKey = shown && shownTurn?.id === shown.turn ? `${shown.turn}:${shown.lane}` : undefined;

  const canSend = !!selected && !waiting && !!text.trim() && (!race || (!!selectedB && selectedB.id !== selected.id));

  return (
    <section
      aria-labelledby="chat-title"
      className="chat-hero-glow relative flex min-w-0 flex-col rounded-xl border border-line bg-elevated"
      data-testid="chat-panel"
    >
      <header className="flex flex-col gap-4 border-b border-line px-4 pb-5 pt-6 md:px-8 xl:flex-row xl:items-end xl:justify-between">
        <div className="flex min-w-0 flex-col gap-2">
          <p className="kicker">
            <span className="text-text-2">F.0</span> · mission control for business decisions · tools run on the server
          </p>
          <h2 id="chat-title" className="display text-[clamp(2.75rem,5.5vw,5.25rem)] leading-[0.95] text-text">
            Ask the <em>engine</em>
          </h2>
          <p className="max-w-3xl text-base leading-relaxed text-text-2 md:text-lg">
            Ask any business decision. The model answers in words and calls FAULTLINE&apos;s simulator and optimizer;
            when web search is switched on for this server it also cites current web sources. Every tool and source it
            used is listed, and the universe on the right re-runs the exact engine inputs it used.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 xl:justify-end">
          <ProvenanceBadge kind="LIVE EXPLORE" />
          <ModelWrittenBadge />
          <ProvenanceBadge kind="SIMULATED" detail="engine numbers" />
          <ProvenanceBadge kind="SYNTHETIC" detail="demo business" />
        </div>
      </header>

      {paused ? (
        <div className="chat-paused flex min-w-0 flex-wrap items-center gap-3 border-b border-info/50 px-4 py-4 md:px-8" role="status" data-testid="chat-paused">
          <span aria-hidden="true" className="chat-paused-dot size-2.5 shrink-0 rounded-full bg-info" />
          <p className="min-w-0 text-base font-medium text-text md:text-lg">The team is presenting right now.</p>
          <p className="min-w-0 text-sm text-text-2" data-testid="chat-paused-until">
            Public chat is paused by the presenter (PAUSED)
            {paused.until && !Number.isNaN(Date.parse(paused.until))
              ? ` until ${new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" }).format(Date.parse(paused.until))} UTC, as the API reports.`
              : "."}
          </p>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-col gap-3 border-b border-line px-4 py-4 md:px-8">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <p className="kicker">Models · pick one, or race two</p>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <button
              type="button"
              role="switch"
              aria-checked={race}
              onClick={() => setRace((r) => !r)}
              disabled={waiting || !catalogue}
              className={`flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                race ? "border-accent bg-accent-soft text-text" : "border-line-strong text-text-2 hover:bg-hover hover:text-text"
              }`}
              data-testid="chat-race-toggle"
            >
              <span aria-hidden="true" className={`relative h-3.5 w-6 rounded-full border ${race ? "border-accent bg-accent/40" : "border-line-strong"}`}>
                <span className={`absolute top-1/2 size-2.5 -translate-y-1/2 rounded-full transition-[left] ${race ? "left-[calc(100%-0.7rem)] bg-accent" : "left-0.5 bg-muted"}`} />
              </span>
              Race two models
            </button>
            {catalogue ? (
              <button
                type="button"
                onClick={() => setGalaxyOpen((o) => !o)}
                aria-expanded={galaxyOpen}
                aria-controls="chat-galaxy"
                className="rounded-full border border-line-strong px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-text-2 hover:bg-hover hover:text-text"
              >
                {galaxyOpen ? "Hide models" : "Show models"}
              </button>
            ) : null}
          </div>
        </div>
        {models.kind === "loading" ? (
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted" role="status">
            Loading GET {CHAT_MODELS_PATH}
          </p>
        ) : catalogue ? (
          catalogue.models.length === 0 ? (
            <p className="font-mono text-sm uppercase tracking-[0.08em] text-muted">No models served: NOT AVAILABLE</p>
          ) : (
            <>
              <div id="chat-galaxy" hidden={!galaxyOpen}>
                <ModelGalaxy data={catalogue} selected={selectedId} onSelect={setPicked} disabled={waiting} onBrowse={() => setPalette("A")} />
              </div>
              {!galaxyOpen ? (
                <p className="min-w-0 break-words font-mono text-[11px] text-muted">
                  Model{race ? " A" : ""}: <span className="text-text">{selected?.label ?? "none selected"}</span>
                </p>
              ) : null}
              {race ? (
                <div className="flex min-w-0 flex-wrap items-center gap-2 rounded-lg border border-accent/40 bg-accent-soft px-3 py-2" data-testid="chat-race-setup">
                  <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-text-2">Race</span>
                  <span className="min-w-0 break-words text-sm text-text">
                    A · {selected?.label ?? "pick a model"} <span className="text-muted">vs</span> B · {selectedB?.label ?? "pick a second model"}
                  </span>
                  <button
                    type="button"
                    onClick={() => setPalette("B")}
                    disabled={waiting}
                    className="rounded-md border border-line-strong px-2.5 py-1 font-mono text-[10.5px] uppercase tracking-[0.12em] text-text-2 hover:bg-hover hover:text-text disabled:opacity-50"
                    data-testid="chat-model-b"
                  >
                    Change model B
                  </button>
                  <span className="font-mono text-[10.5px] text-muted">Same question, two requests in parallel, same engine. Facts side by side; FAULTLINE ranks no one.</span>
                </div>
              ) : null}
            </>
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
            <button
              type="button"
              onClick={() => {
                setModels({ kind: "loading" });
                setModelsRetry((n) => n + 1);
              }}
              className="rounded-md border border-line-strong px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-text-2 hover:bg-hover hover:text-text"
            >
              Retry
            </button>
          </div>
        ) : null}
      </div>

      <div className="grid min-w-0 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.08fr)]" data-testid="chat-cockpit">
        <div className="flex min-w-0 flex-col xl:border-r xl:border-line">
          <div className="flex min-w-0 flex-1 flex-col gap-5 px-4 py-5 md:px-8 md:py-6">
            {turns.length === 0 ? (
              <div className="flex flex-col gap-3">
                <p className="kicker">Start with a decision or a stress test</p>
                <StarterCards onPick={(p) => send(p, lanesToAsk(), turns)} disabled={!selected || waiting || (race && !selectedB)} />
              </div>
            ) : (
              <ol role="log" aria-live="polite" aria-label="Conversation" className="flex min-w-0 flex-col gap-6" data-testid="chat-log">
                {turns.map((t, i) => {
                  const onUniverse = shownTurn?.id === t.id;
                  return (
                    <li key={t.id} ref={i === turns.length - 1 ? lastRef : undefined} className="flex min-w-0 scroll-mt-20 flex-col gap-3">
                      <UserBubble text={t.question} />
                      <div className={t.lanes.length > 1 ? "grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2" : "flex min-w-0 flex-col"} data-testid={t.lanes.length > 1 ? "chat-race" : undefined}>
                        {t.lanes.map((l, li) => (
                          <LaneView
                            key={li}
                            lane={l}
                            letter={t.lanes.length > 1 ? (RACE_LETTERS[li] ?? null) : null}
                            reduce={reduce}
                            featured={featured}
                            onStop={stop}
                            onRetryWith={(m) => retryWith(t, m)}
                            isLast={i === turns.length - 1}
                            busy={waiting}
                            onUniverse={onUniverse && (focusKey ? focusKey === `${t.id}:${li}` : li === 0)}
                            onShow={laneDrives(l) ? () => setShown({ turn: t.id, lane: li }) : null}
                            catalogue={catalogue}
                          />
                        ))}
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>

          <form onSubmit={submit} className="sticky bottom-0 z-10 flex min-w-0 flex-col gap-2 border-t border-line bg-elevated/95 px-4 py-4 backdrop-blur-[12px] md:px-8" data-testid="chat-composer">
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
                placeholder={
                  race
                    ? "Ask both models the same question…"
                    : selected
                      ? `Ask ${selected.label} any business decision…`
                      : "Pick a model, then ask any business decision…"
                }
                className="min-h-[3.25rem] w-full min-w-0 resize-y rounded-lg border border-line-strong bg-bg px-4 py-3 text-base leading-relaxed text-text placeholder:text-muted focus:border-accent focus:outline-none disabled:opacity-60 2xl:text-lg"
              />
              <div className="flex shrink-0 gap-2">
                <VoiceButton onTranscript={setText} disabled={waiting} />
                <button
                  type="submit"
                  disabled={!canSend}
                  className="flex-1 rounded-lg border border-accent bg-accent px-5 py-3 font-mono text-[12px] font-semibold uppercase tracking-[0.14em] text-bg transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:border-line-strong disabled:bg-transparent disabled:text-muted sm:flex-none"
                >
                  {race ? "Race" : "Ask"}
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
              <span>Enter to send · Shift+Enter for a new line · ⌘K all models · not saved: clearing or reloading erases it</span>
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
        </div>

        <div className="min-w-0 border-t border-line p-3 md:p-5 xl:border-t-0">
          <div className="xl:sticky xl:top-4">
            <Universe sources={sources} reduce={reduce} focusKey={focusKey} armed={turns.length > 0} />
          </div>
        </div>
      </div>

      {catalogue ? (
        <ModelPalette
          open={palette !== null}
          onClose={() => setPalette(null)}
          models={catalogue.models}
          selected={palette === "B" ? (selectedB?.id ?? null) : selectedId}
          title={palette === "B" ? "Pick model B for the race" : "All models"}
          onSelect={(id) => {
            if (palette === "B") setPickedB(id);
            else setPicked(id);
            setPalette(null);
          }}
        />
      ) : null}
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

function ModelLine({ model, response, ms, letter }: { model: ChatModel; response?: ChatResponse; ms?: number; letter: string | null }) {
  const provider = response ? response.provider : model.provider;
  return (
    <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] text-muted" data-testid="chat-model-line">
      {letter ? <span className="rounded-sm bg-accent px-1.5 py-0.5 font-semibold text-bg">{letter}</span> : null}
      <span className="min-w-0 break-all rounded-sm border border-line-strong px-1.5 py-0.5 text-text" data-testid="chat-model-id">
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

/** Race facts for one lane: time, steps, tokens and cost at catalogue price. Facts only; nobody is ranked. */
function LaneFacts({ lane, response, ms, catalogue }: { lane: Lane; response: ChatResponse | null; ms: number | null; catalogue: ChatModelsResponse | null }) {
  const model = catalogue?.models.find((m) => m.id === lane.model.id) ?? lane.model;
  const cost = response ? replyCostUsd(response.usage, model) : null;
  return (
    <dl className="grid min-w-0 grid-cols-3 gap-px overflow-hidden rounded-md border border-line bg-line/60 font-mono text-[11px]" data-testid="chat-race-facts">
      <div className="min-w-0 bg-elevated px-2.5 py-2">
        <dt className="text-[10px] uppercase tracking-[0.12em] text-muted">Time</dt>
        <dd className="num mt-0.5 text-sm text-text" data-testid="race-time">
          {lane.outcome.kind === "waiting" ? <Elapsed since={lane.outcome.startedAt} testId="race-elapsed" /> : ms !== null ? `${(ms / 1000).toFixed(1)} s` : "n/a"}
        </dd>
      </div>
      <div className="min-w-0 bg-elevated px-2.5 py-2">
        <dt className="text-[10px] uppercase tracking-[0.12em] text-muted">Tool steps</dt>
        <dd className="num mt-0.5 text-sm text-text" data-testid="race-steps">
          {response ? response.tool_calls.length : "…"}
        </dd>
      </div>
      <div className="min-w-0 bg-elevated px-2.5 py-2">
        <dt className="text-[10px] uppercase tracking-[0.12em] text-muted">Cost (est.)</dt>
        <dd className="num mt-0.5 break-words text-sm text-text" data-testid="chat-cost" title="usage × the catalogue's published $/M-token prices; not a bill">
          {response ? (cost === null ? "NOT AVAILABLE" : costLabel(cost)) : "…"}
        </dd>
      </div>
    </dl>
  );
}

function LaneView({
  lane,
  letter,
  reduce,
  featured,
  onStop,
  onRetryWith,
  isLast,
  busy,
  onUniverse,
  onShow,
  catalogue,
}: {
  lane: Lane;
  letter: string | null;
  reduce: boolean;
  featured: ChatModel[];
  onStop: () => void;
  onRetryWith: (m: ChatModel) => void;
  isLast: boolean;
  busy: boolean;
  onUniverse: boolean;
  onShow: (() => void) | null;
  catalogue: ChatModelsResponse | null;
}) {
  const o = lane.outcome;
  const racing = letter !== null;
  if (o.kind === "waiting") {
    return (
      <div className="chat-thinking flex min-w-0 flex-col gap-3 rounded-lg border border-line bg-bg/40 p-4 md:p-5" role="status" data-testid="chat-waiting">
        <ModelLine model={lane.model} letter={letter} />
        <div className="flex min-w-0 items-center gap-3">
          <span aria-hidden="true" className={`chat-orbit relative size-8 shrink-0 ${reduce ? "" : "chat-orbit-on"}`}>
            <span className="absolute inset-0 rounded-full border border-accent/40" />
            <span className="chat-orbit-dot absolute left-1/2 top-0 size-1.5 -translate-x-1/2 rounded-full bg-accent" />
          </span>
          <p className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-[15px] text-text-2">
            <span className="font-medium text-text">Waiting for {lane.model.label}</span>
            <span className="text-muted">· the model may be reading the engine…</span>
            <Elapsed since={o.startedAt} />
          </p>
        </div>
        {racing ? <LaneFacts lane={lane} response={null} ms={null} catalogue={catalogue} /> : null}
        <p className="font-mono text-[10.5px] text-muted">
          The reply arrives in one piece (POST {CHAT_PATH} is not streaming); the steps it took are shown once it lands.
        </p>
        <button type="button" onClick={onStop} className="w-fit rounded-md border border-line-strong px-3 py-1.5 font-mono text-[10.5px] uppercase tracking-[0.12em] text-text-2 hover:bg-hover hover:text-text">
          Stop waiting
        </button>
      </div>
    );
  }
  if (o.kind === "failed") {
    const isPaused = o.failure.kind === "paused";
    return (
      <div
        className={`flex min-w-0 flex-col gap-2 rounded-lg border p-4 ${
          isPaused ? "border-info/60 bg-[color-mix(in_srgb,var(--info)_6%,transparent)]" : "border-fail/50 bg-[color-mix(in_srgb,var(--fail)_5%,transparent)]"
        }`}
        role="alert"
        data-testid="chat-failure"
        data-kind={o.failure.kind}
      >
        <ModelLine model={lane.model} letter={letter} />
        <p className={`font-medium text-text ${isPaused ? "display text-3xl" : "text-[15px]"}`}>{o.failure.heading}</p>
        {o.failure.detail ? <p className="break-words font-mono text-[11px] text-text-2 [overflow-wrap:anywhere]">{o.failure.detail}</p> : null}
        <p className="font-mono text-[10.5px] text-muted">No answer is shown for this question.</p>
      </div>
    );
  }
  const r = o.response;
  const notOk = r.status !== "ok";
  const others = featured.filter((m) => m.id !== lane.model.id).slice(0, 4);
  return (
    <article
      className={`${reduce ? "" : "chat-enter"} flex min-w-0 flex-col gap-4 rounded-lg border bg-bg/40 p-4 transition-[border-color,box-shadow] md:p-6 ${
        notOk ? "border-fail/50" : onUniverse ? "chat-on-universe border-accent/70" : "border-line"
      }`}
      data-testid="chat-answer"
      data-status={r.status}
      data-on-universe={onUniverse ? "true" : "false"}
    >
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <ModelLine model={lane.model} response={r} ms={o.ms} letter={letter} />
        <span className="flex flex-wrap items-center gap-1.5">
          <ProvenanceBadge kind="LIVE EXPLORE" />
          {/* MODEL-WRITTEN only on a reply the model actually wrote (status ok). */}
          {!notOk ? <ModelWrittenBadge /> : null}
        </span>
      </div>

      {racing ? <LaneFacts lane={lane} response={r} ms={o.ms} catalogue={catalogue} /> : null}

      {notOk ? (
        <div className="flex flex-col gap-2" data-testid="chat-answer-problem">
          <p className="text-[15px] font-medium text-fail">
            {r.status === "unavailable" ? "This model is not available for chat right now." : "This model did not produce a usable answer."}
          </p>
          {r.notes.length ? (
            <ul className="flex flex-col gap-1">
              {r.notes.map((n, k) => (
                <li key={k} className="break-words font-mono text-[11.5px] text-text-2 [overflow-wrap:anywhere]">
                  {n}
                </li>
              ))}
            </ul>
          ) : (
            <p className="font-mono text-[11px] text-muted">The API sent no note.</p>
          )}
          {isLast && others.length && !racing ? (
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
      {!r.reply.trim() && !notOk ? (
        <p className="font-mono text-sm uppercase tracking-[0.08em] text-muted">Reply NOT AVAILABLE: the model returned no text.</p>
      ) : null}

      {r.status === "ok" && r.notes.length ? (
        <ul className="flex flex-col gap-0.5 border-l border-line-strong pl-3">
          {r.notes.map((n, k) => (
            <li key={k} className="break-words font-mono text-[10.5px] text-muted [overflow-wrap:anywhere]">
              {n}
            </li>
          ))}
        </ul>
      ) : null}

      {!notOk || r.tool_calls.length ? <FlightPath calls={r.tool_calls} reduce={reduce} /> : null}

      <EvidenceCards calls={r.tool_calls} />

      {drivesUniverse(r.tool_calls) ? <EngineAgreement calls={r.tool_calls} /> : null}

      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <p className="min-w-0 font-mono text-[10px] leading-snug text-muted">
          {r.label} · words by the model, numbers from the engine tools it called · not saved
        </p>
        {onShow ? (
          <button
            type="button"
            onClick={onShow}
            aria-pressed={onUniverse}
            className={`rounded-full border px-3 py-1 font-mono text-[10.5px] uppercase tracking-[0.12em] transition-colors ${
              onUniverse ? "border-accent bg-accent-soft text-text" : "border-line-strong text-text-2 hover:bg-hover hover:text-text"
            }`}
            data-testid="chat-replay"
          >
            {onUniverse ? "On the universe" : "Replay on the universe"}
          </button>
        ) : null}
      </div>
    </article>
  );
}
