/**
 * The presenter flow (SPEC §2): five Blind Replay screens grouped under THEN / DECISION / REVEAL, then LIVE EXPLORE
 * (issue #61) under NOW. NOW is current web content, separate from the replay: nothing there feeds the screens before it.
 */

export type Phase = "THEN" | "DECISION" | "REVEAL" | "NOW";

export interface Step {
  slug: "rewind" | "decision" | "cascade" | "reveal" | "research" | "explore";
  index: number;
  label: string;
  short: string;
  phase: Phase;
  /** Display title: optional plain lead-in, then the italic emphasis word(s). */
  titlePre?: string;
  titleEm: string;
  lede: string;
}

export const PHASES: readonly Phase[] = ["THEN", "DECISION", "REVEAL", "NOW"] as const;

export const STEPS: readonly Step[] = [
  {
    slug: "rewind",
    index: 0,
    label: "Rewind",
    short: "Rewind",
    phase: "THEN",
    titleEm: "Rewind",
    lede: "Return to a resolved historical decision point. Only information available by the knowledge cutoff is shown; everything after it stays sealed.",
  },
  {
    slug: "decision",
    index: 1,
    label: "Decision",
    short: "Decide",
    phase: "DECISION",
    titlePre: "The",
    titleEm: "Decision",
    lede: "A local open-weight model chooses a path from point-in-time evidence, beside the market-implied probability at the same cutoff.",
  },
  {
    slug: "cascade",
    index: 2,
    label: "Cascade",
    short: "Cascade",
    phase: "DECISION",
    titlePre: "The",
    titleEm: "Cascade",
    lede: "A shock moves through the business: financing cost, liquidity, suppliers, payroll, cash. The deterministic optimizer recomputes feasible recovery plans.",
  },
  {
    slug: "reveal",
    index: 3,
    label: "Reveal",
    short: "Reveal",
    phase: "REVEAL",
    titleEm: "Reveal",
    lede: "Unseal the historical outcome and score the forecast against the market-only and naive baselines on the same cases. If the agent did not win, this screen says so.",
  },
  {
    slug: "research",
    index: 4,
    label: "Research Lens",
    short: "Lens",
    phase: "REVEAL",
    titlePre: "Research",
    titleEm: "Lens",
    lede: "Four dated, sourced public research perspectives: which theses bear on this decision, what was known by the cutoff, and where the model agreed or disagreed.",
  },
  {
    slug: "explore",
    index: 5,
    label: "Live Explore",
    short: "Explore",
    phase: "NOW",
    titlePre: "Live",
    titleEm: "Explore",
    lede: "Test a decision today. Tavily searches current news, the local model turns the results into cited evidence and suggests stress inputs, you confirm them, and the deterministic engine computes the cascade. Separate from the Blind Replay.",
  },
] as const;

export type StepSlug = Step["slug"];

export function findStep(slug: string): Step | undefined {
  return STEPS.find((s) => s.slug === slug);
}

/** Step for a pathname. `/` is the first screen (Rewind). */
export function stepFromPath(pathname: string): Step | undefined {
  const seg = pathname.replace(/^\/+/, "").split("/")[0] ?? "";
  return seg === "" ? STEPS[0] : findStep(seg);
}

export function stepHref(step: Step): string {
  return `/${step.slug}`;
}
