/**
 * The presenter flow. LIVE EXPLORE (issue #61, the engine-tool chat #186) leads: it is the home screen `/` under NOW.
 * Then the five Blind Replay screens (SPEC §2), grouped under THEN / DECISION / REVEAL: the honesty proof.
 * NOW is current web content, separate from the replay: nothing there feeds the replay screens.
 */

export type Phase = "NOW" | "THEN" | "DECISION" | "REVEAL";

/** Top-level navigation sections: Live Explore first, then the Blind Replay. */
export type Section = "live" | "replay";

export interface Step {
  slug: "rewind" | "decision" | "cascade" | "reveal" | "research" | "explore";
  index: number;
  label: string;
  short: string;
  phase: Phase;
  section: Section;
  /** Display title: optional plain lead-in, then the italic emphasis word(s). */
  titlePre?: string;
  titleEm: string;
  lede: string;
}

export const PHASES: readonly Phase[] = ["NOW", "THEN", "DECISION", "REVEAL"] as const;

export const SECTION_LABEL: Record<Section, string> = {
  live: "Ask the engine",
  replay: "Blind Replay: the honesty proof",
};

export const STEPS: readonly Step[] = [
  {
    slug: "explore",
    index: 0,
    label: "Live Explore",
    short: "Explore",
    phase: "NOW",
    section: "live",
    titlePre: "Live",
    titleEm: "Explore",
    lede: "Ask a leadership or strategy decision; the engine returns Monte Carlo odds with cited sources.",
  },
  {
    slug: "rewind",
    index: 1,
    label: "Rewind",
    short: "Rewind",
    phase: "THEN",
    section: "replay",
    titleEm: "Rewind",
    lede: "Return to a resolved historical decision point. Only information available by the knowledge cutoff is shown; everything after it stays sealed.",
  },
  {
    slug: "decision",
    index: 2,
    label: "Decision",
    short: "Decide",
    phase: "DECISION",
    section: "replay",
    titlePre: "The",
    titleEm: "Decision",
    lede: "A local open-weight model chooses a path from point-in-time evidence, beside the market-implied probability at the same cutoff.",
  },
  {
    slug: "cascade",
    index: 3,
    label: "Cascade",
    short: "Cascade",
    phase: "DECISION",
    section: "replay",
    titlePre: "The",
    titleEm: "Cascade",
    lede: "A shock moves through the business: financing cost, liquidity, suppliers, payroll, cash. The deterministic optimizer recomputes feasible recovery plans.",
  },
  {
    slug: "reveal",
    index: 4,
    label: "Reveal",
    short: "Reveal",
    phase: "REVEAL",
    section: "replay",
    titleEm: "Reveal",
    lede: "Unseal the historical outcome and score the forecast against the market-only and naive baselines on the same cases. If the agent did not win, this screen says so.",
  },
  {
    slug: "research",
    index: 5,
    label: "Research Lens",
    short: "Lens",
    phase: "REVEAL",
    section: "replay",
    titlePre: "Research",
    titleEm: "Lens",
    lede: "Four dated, sourced public research perspectives: which theses bear on this decision, what was known by the cutoff, and where the model agreed or disagreed.",
  },
] as const;

export type StepSlug = Step["slug"];

export function findStep(slug: string): Step | undefined {
  return STEPS.find((s) => s.slug === slug);
}

/** The home screen `/`: Live Explore (rendered directly, not redirected, so it works as a static export). */
export const HOME_STEP: Step = STEPS[0]!;

/** Step for a pathname. `/` is the home screen (Live Explore). */
export function stepFromPath(pathname: string): Step | undefined {
  const seg = pathname.replace(/^\/+/, "").split("/")[0] ?? "";
  return seg === "" ? HOME_STEP : findStep(seg);
}

/** Steps in one navigation section, in presenter order. */
export function sectionSteps(section: Section): readonly Step[] {
  return STEPS.filter((s) => s.section === section);
}

export function stepHref(step: Step): string {
  return `/${step.slug}`;
}
