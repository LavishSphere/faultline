import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { E2E_API_BASE } from "./ports";

/**
 * REVEAL visual pass (#164): unsealing sequence, score race, results-by-event chart.
 *
 * Honesty rule for this file: no expected figure is written here. Expected values come from the API (the real e2e
 * API, or the route-mocked bodies below) and are compared with what the page draws, formatted as the UI formats them.
 *
 * `fixtures/committed-run.synthetic.json` is a TEST FIXTURE: real API bodies produced on a temporary data dir by the
 * official run script on 15 SYNTHETIC cases with a mocked model (pattern of services/api/tests/
 * test_routes_benchmark_committed.py). It is served only through page.route; the repo's data/ and var/ are untouched.
 */

const BENCHMARK_URL = `${E2E_API_BASE}/api/benchmark`;
const fixture = JSON.parse(readFileSync(resolve(__dirname, "fixtures/committed-run.synthetic.json"), "utf-8")) as {
  benchmark: Benchmark;
  reveal: Reveal;
  /** GET /api/replay/recorded bodies keyed "<case_id>|<agent_variant>". */
  recorded: Record<string, { items: { prediction_id: string; p_yes: number }[] }>;
};

interface EventRow {
  event_id: string;
  y: number;
  prediction_ids: string[];
  brier: Record<string, number>;
}
interface Card {
  label: string;
  caveat: string | null;
  agent_variant: string;
  per_event: EventRow[];
  summary: Record<string, { mean_brier: number; mean_log_loss: number }> | null;
  comparison: { mean_delta_brier: number } | null;
}
interface Benchmark {
  status: string;
  items: Card[];
  records: { origin: string; agent_variant: string }[];
}
interface Reveal {
  prediction: { prediction_id: string; prompt_sha256: string; snapshot_sha256: string };
  sealed: { outcome: string };
  persisted_before_outcome_revealed: boolean;
  scores: { brier: number };
  baselines: { market: { brier: number } | null; naive: { brier: number } };
}

/** components/reveal/ui.tsx: fmt4 and fmtPrecise (formatting only). */
const fmt4 = (x: number) => x.toFixed(4);
const fmtPrecise = (x: number) =>
  x === 0 ? "0.000000" : `${x < 0 ? "−" : "+"}${Math.abs(x) < 1e-4 ? String(Math.abs(x)) : Math.abs(x).toFixed(6)}`;
const short = (h: string) => (h.length > 28 ? `${h.slice(0, 16)}…${h.slice(-8)}` : h);

async function mockCommitted(page: Page, { recorded = true }: { recorded?: boolean } = {}) {
  await page.route(BENCHMARK_URL, (route) => route.fulfill({ json: fixture.benchmark }));
  if (!recorded) return;
  await page.route(`${E2E_API_BASE}/api/replay/recorded?**`, (route) => {
    const q = new URL(route.request().url()).searchParams;
    const body = fixture.recorded[`${q.get("case_id")}|${q.get("agent_variant")}`];
    return body ? route.fulfill({ json: body }) : route.fallback();
  });
}

async function mockReveal(page: Page) {
  const id = fixture.reveal.prediction.prediction_id;
  await page.route(`${E2E_API_BASE}/api/replay/${encodeURIComponent(id)}/reveal`, (route) =>
    route.request().method() === "POST" ? route.fulfill({ json: fixture.reveal }) : route.fallback(),
  );
  return id;
}

test.describe("REVEAL · results by event", () => {
  test("NOT AVAILABLE with no committed scorecard (real API)", async ({ page }) => {
    const direct = (await (await page.request.get(BENCHMARK_URL)).json()) as Benchmark;
    test.skip(direct.records.some((r) => r.origin === "committed"), "the API serves a committed run; covered below");
    const loaded = page.waitForResponse((r) => r.url() === BENCHMARK_URL);
    await page.goto("/reveal/");
    await loaded;
    const empty = page.getByTestId("results-chart-empty");
    await expect(empty).toBeVisible();
    await expect(empty.getByText("Not available", { exact: true })).toBeVisible();
    await expect(page.getByTestId("results-chart-empty-note")).toHaveText("Appears after the official recorded run.");
    await expect(page.getByTestId("results-chart-event")).toHaveCount(0);
  });

  test("committed run: one point per per_event row, outcomes sealed until clicked, tooltip = API values", async ({ page }) => {
    await mockCommitted(page);
    await page.goto("/reveal/");
    const i = fixture.benchmark.records.findIndex((r) => r.origin === "committed");
    const card = fixture.benchmark.items[i]!;
    const chart = page.getByTestId("results-chart");
    await expect(chart).toBeVisible();
    await expect(page.getByTestId("results-chart-label")).toHaveText(card.label);
    if (card.caveat) await expect(page.getByTestId("results-chart-caveat")).toHaveText(card.caveat);
    await expect(page.getByTestId("results-chart-event")).toHaveCount(card.per_event.length);

    // #117: the y of every scored event is not drawn until the explicit click.
    await expect(page.getByTestId("results-chart-y")).toHaveCount(0);
    await page.getByTestId("results-chart-toggle-y").click();
    await expect(page.getByTestId("results-chart-y")).toHaveCount(card.per_event.length);

    // Hover events: id, Brier as the API sent them, p (model) from the matched recorded forecast, p (market) not available.
    const events = page.getByTestId("results-chart-event");
    const tooltip = page.getByTestId("results-chart-tooltip");
    for (let k = 0; k < card.per_event.length; k += 7) {
      await events.nth(k).hover();
      const id = (await page.getByTestId("results-chart-tooltip-id").textContent())?.split("←")[0]?.trim();
      const row = card.per_event.find((e) => e.event_id === id);
      expect(row, `tooltip names a served event (${id})`).toBeTruthy();
      await expect(tooltip).toContainText(`Brier agent${fmt4(row!.brier[card.agent_variant]!)}`);
      await expect(tooltip).toContainText(`Brier market${fmt4(row!.brier.market!)}`);
      await expect(tooltip).toContainText(`y${row!.y}`);
      const rec = fixture.recorded[`${row!.event_id}|${card.agent_variant}`]!;
      const p = rec.items.filter((f) => row!.prediction_ids.includes(f.prediction_id)).map((f) => fmt4(f.p_yes));
      expect(p.length, "fixture has the scored forecast").toBeGreaterThan(0);
      await expect(page.getByTestId("results-chart-tooltip-p")).toHaveText(p.join(" · "));
      await expect(tooltip).toContainText("p (market)Not available");
    }
  });

  test("p (model) is NOT AVAILABLE where the recorded-forecast route serves nothing for the event (real API)", async ({ page }) => {
    await mockCommitted(page, { recorded: false });
    await page.goto("/reveal/");
    await expect(page.getByTestId("results-chart")).toBeVisible();
    await page.getByTestId("results-chart-event").first().hover();
    await expect(page.getByTestId("results-chart-tooltip-p")).toHaveText("Not available");
  });

  test("score race lands on the card's means and Δ", async ({ page }) => {
    await mockCommitted(page);
    await page.goto("/reveal/");
    for (const [i, rec] of fixture.benchmark.records.entries()) {
      const card = fixture.benchmark.items[i]!;
      const scope = page.getByTestId(`scorecard-${rec.agent_variant}`);
      const race = scope.getByTestId("score-race");
      await race.scrollIntoViewIfNeeded();
      const s = card.summary!;
      const agent = s[card.agent_variant]!;
      await expect(race.getByTestId("race-brier-agent")).toHaveText(fmt4(agent.mean_brier));
      await expect(race.getByTestId("race-brier-market")).toHaveText(fmt4(s.market!.mean_brier));
      await expect(race.getByTestId("race-brier-naive")).toHaveText(fmt4(s.naive!.mean_brier));
      await expect(race.getByTestId("race-logloss-agent")).toHaveText(fmt4(agent.mean_log_loss));
      await expect(race.getByTestId("race-delta-mean")).toHaveText(fmtPrecise(card.comparison!.mean_delta_brier));
    }
  });

  test("390 px: no horizontal page scroll with a committed run", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockCommitted(page);
    await page.goto("/reveal/");
    await expect(page.getByTestId("results-chart")).toBeAttached();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, "no horizontal page scroll at 390 px").toBeLessThanOrEqual(0);
  });
});

test.describe("REVEAL · unsealing sequence", () => {
  async function revealAndCheck(page: Page) {
    const id = await mockReveal(page);
    await page.goto(`/reveal/?prediction_id=${encodeURIComponent(id)}`);
    // Nothing about the outcome before the click.
    await expect(page.getByTestId("unseal-sequence")).toHaveCount(0);
    await expect(page.getByText("Sealed", { exact: true }).first()).toBeVisible();
    await page.getByRole("button", { name: "Reveal outcome" }).click();
    const seq = page.getByTestId("unseal-sequence");
    await expect(seq).toHaveAttribute("data-done", "true", { timeout: 6000 });
    const r = fixture.reveal;
    await expect(seq.getByTestId("unseal-line-prompt")).toContainText(short(r.prediction.prompt_sha256));
    await expect(seq.getByTestId("unseal-line-snapshot")).toContainText(short(r.prediction.snapshot_sha256));
    // The reveal response has no case hash: its slot says so instead of being skipped.
    await expect(seq.getByTestId("unseal-line-case")).toContainText("Not available");
    await expect(seq.getByTestId("unseal-line-before")).toHaveAttribute(
      "data-state",
      String(r.persisted_before_outcome_revealed),
    );
    await expect(seq.getByTestId("unseal-outcome")).toContainText(r.sealed.outcome);
    await expect(seq.getByTestId("unseal-brier-agent")).toHaveText(fmt4(r.scores.brier));
    if (r.baselines.market) await expect(seq.getByTestId("unseal-brier-market")).toHaveText(fmt4(r.baselines.market.brier));
    await expect(seq.getByTestId("unseal-brier-naive")).toHaveText(fmt4(r.baselines.naive.brier));
  }

  test("reduced motion: the final state at once, values = the API's", async ({ page }) => {
    await revealAndCheck(page);
  });

  test.describe("with motion", () => {
    test.use({ reducedMotion: "no-preference" });
    test("plays, then ends on exactly the API's values", async ({ page }) => {
      await revealAndCheck(page);
    });
  });
});
