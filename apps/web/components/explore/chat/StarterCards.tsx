"use client";

import "./flight.css";

/**
 * Starter prompts (stage 2): four cinematic cards, two real-world decisions and two stress tests of the SYNTHETIC demo
 * business, that send a question to the selected model. They carry questions
 * only: no results, no figures. The model's answer and the engine's numbers arrive through the chat API.
 */

type Tone = "risk" | "info" | "viable" | "accent";

export const STARTERS: { kicker: string; title: string; prompt: string; tone: Tone }[] = [
  {
    kicker: "Governance · Monte Carlo",
    title: "Should Nvidia keep Jensen Huang as CEO?",
    prompt: "Should Nvidia keep Jensen Huang as CEO? Give me the odds.",
    tone: "accent",
  },
  {
    kicker: "Strategy · current web",
    title: "Should Nvidia keep betting on AI data centers?",
    prompt: "Should Nvidia keep betting on AI data centers? Give me a decision brief with current sources and the main risks.",
    tone: "info",
  },
  {
    kicker: "Cash risk · Monte Carlo",
    title: "What are the odds we breach the cash floor?",
    prompt: "What's the probability we breach the cash floor if our biggest supplier fails?",
    tone: "risk",
  },
  {
    kicker: "Stress test · engine",
    title: "Can we survive without cutting a single wage?",
    prompt: "Can we survive the worst stress scenario without cutting a single wage? Protect payroll and find a plan.",
    tone: "viable",
  },
];

const TONE_CLASS: Record<Tone, string> = {
  risk: "starter-tone-risk",
  info: "starter-tone-info",
  viable: "starter-tone-viable",
  accent: "starter-tone-accent",
};

const TONE_TEXT: Record<Tone, string> = {
  risk: "text-risk",
  info: "text-info",
  viable: "text-viable",
  accent: "text-accent",
};

export function StarterCards({ onPick, disabled }: { onPick: (prompt: string) => void; disabled: boolean }) {
  return (
    <ul className="grid grid-cols-1 gap-3 md:grid-cols-2" aria-label="Starter questions">
      {STARTERS.map((s) => (
        <li key={s.title} className="min-w-0">
          <button
            type="button"
            onClick={() => onPick(s.prompt)}
            disabled={disabled}
            title={s.prompt}
            data-testid="chat-starter"
            className={`starter-card ${TONE_CLASS[s.tone]} group relative isolate flex h-full min-h-[9.5rem] w-full min-w-0 flex-col gap-3 overflow-hidden rounded-xl border border-line p-5 text-left disabled:cursor-not-allowed disabled:opacity-50 md:min-h-[11rem] md:p-6`}
          >
            <span className="flex items-center gap-3">
              <span className={`font-mono text-[10.5px] uppercase tracking-[0.16em] ${TONE_TEXT[s.tone]}`}>{s.kicker}</span>
            </span>
            <span className="starter-rule h-px w-12" aria-hidden="true" />
            <span className="display min-w-0 break-words text-[1.6rem] leading-[1.08] text-text md:text-[1.9rem] 2xl:text-[2.05rem]">
              {s.title}
            </span>
            <span className="mt-auto flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted transition-colors duration-150 group-hover:text-text-2">
              Ask the engine <span aria-hidden="true">→</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
