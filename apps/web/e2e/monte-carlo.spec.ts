import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { E2E_API_BASE } from "./ports";

/**
 * Monte Carlo panels in a chat reply (#210), against the static export. Only the two chat routes are intercepted.
 * The tool results come from e2e/fixtures: mc-decision / mc-cash are engine responses RECORDED from POST
 * /api/montecarlo/{decision,cash} on the local API (request kept in the file); internal-data is a hand-built TEST
 * FIXTURE. The chat reply wrapping them is a TEST FIXTURE, never real model output. The page must draw them as served: the headline equals `best.prob_best`, the tornado follows
 * the served swings, unsafe links are dropped, every panel carries its provenance badge.
 *
 * Set MC_SHOTS=<dir> to also save screenshots (1920 dark and light, 390 wide).
 */

const MODELS_URL = `${E2E_API_BASE}/api/explore/chat/models`;
const CHAT_URL = `${E2E_API_BASE}/api/explore/chat`;
const SHOTS = process.env.MC_SHOTS;

const fixture = (name: string) =>
  JSON.parse(readFileSync(resolve(__dirname, "fixtures", `${name}.fixture.json`), "utf8")).result_summary as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

// The recorded decision run has no linked source, so a copy adds one safe and one javascript: link to test both paths.
const DECISION = fixture("mc-decision");
DECISION.monte_carlo.assumptions[0].source = { url: "https://example.com/test-fixture-source", title: "TEST FIXTURE source", note: "fixture link" };
DECISION.monte_carlo.assumptions[1].source = { url: "javascript:alert(1)", title: "TEST FIXTURE unsafe link", note: null };
const CASH = fixture("mc-cash");
const INTERNAL = fixture("internal-data");

const MODELS = {
  models: [{ id: "claude-fixture", label: "TEST FIXTURE claude-fixture", provider: "anthropic", available: true, note: null }],
  default: "claude-fixture",
  featured: ["claude-fixture"],
};

const toolCall = (name: string, result_summary: unknown) => ({ name, input: {}, result_status: "ok", result_summary, provenance: "SIMULATED" });

function reply(calls: unknown[]) {
  return {
    status: "ok",
    provenance: "LIVE EXPLORE",
    label: "MODEL-WRITTEN, numbers from engine tools",
    model_id: "claude-fixture",
    provider: "anthropic",
    reply: "TEST FIXTURE reply: the engine ran the paths.",
    tool_calls: calls,
    usage: { input_tokens: 100, output_tokens: 50 },
    notes: [],
  };
}

async function mock(page: Page, calls: unknown[]) {
  await page.route(MODELS_URL, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MODELS) }));
  await page.route(CHAT_URL, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(reply(calls)) }));
}

async function ask(page: Page, text: string) {
  const input = page.locator("#chat-input");
  await input.fill(text);
  await input.press("Enter");
}

const pct = (p: number) => `${(p * 100).toFixed(1)}%`;
const ci = (c: [number, number]) => `95% CI ${(c[0] * 100).toFixed(1)}–${pct(c[1])}`;
const n = (v: number) => v.toLocaleString("en-US");

const ALL = [
  toolCall("query_internal_data", INTERNAL),
  toolCall("monte_carlo_decision", DECISION),
  toolCall("monte_carlo_cash", CASH),
];

test.describe("Monte Carlo panels", () => {
  test("decision: headline is best.prob_best, tornado follows the served swings, sources are safe, the run is stamped", async ({ page }) => {
    await mock(page, ALL);
    await page.goto("/explore/");
    await ask(page, "Should Nvidia keep Jensen Huang as CEO? Give me the odds.");
    const panel = page.getByTestId("mc-decision");
    await expect(panel).toBeVisible();
    const mc = DECISION.monte_carlo;

    await expect(panel.getByTestId("mc-headline-prob")).toHaveText(pct(mc.best.prob_best));
    const bestLabel = mc.options.find((o: { id: string }) => o.id === mc.best.id).label;
    await expect(panel.getByTestId("mc-headline-text")).toHaveText(`${bestLabel} · best in ${pct(mc.best.prob_best)} of ${n(mc.n_paths)} paths`);
    await expect(panel.getByTestId("mc-headline-ci")).toHaveText(ci(mc.best.ci95));
    await expect(panel.locator('[data-provenance="SIMULATED"]').first()).toBeVisible();

    // One ridge per option, every bin drawn with its served count.
    await expect(panel.getByTestId("mc-ridge")).toHaveCount(mc.options.length);
    const counts = await panel.locator('[data-option="replace"] rect').evaluateAll((els) => els.map((e) => Number(e.getAttribute("data-count"))));
    expect(counts).toEqual(mc.options[1].histogram.counts);

    await expect(panel.getByTestId("mc-pair-prob")).toHaveText(mc.pairwise.map((p: { prob_a_better: number }) => pct(p.prob_a_better)));

    const expected = [...mc.sensitivity].sort((a: { swing: number }, b: { swing: number }) => b.swing - a.swing).map((s: { driver: string }) => s.driver);
    expect(expected.length).toBeGreaterThan(1);
    const order = await panel.getByTestId("mc-tornado-row").evaluateAll((els) => els.map((e) => e.getAttribute("data-driver")));
    expect(order).toEqual(expected);

    // http(s) source is linked safely; the javascript: one is not rendered as a link; no source reads model-estimated.
    const links = panel.getByTestId("mc-source-link");
    await expect(links).toHaveCount(1);
    await expect(links).toHaveAttribute("href", "https://example.com/test-fixture-source");
    await expect(links).toHaveAttribute("rel", "noopener noreferrer");
    await expect(panel.getByTestId("mc-model-estimated")).toHaveCount(mc.assumptions.length - 1);
    // Grouped by option, in the served order.
    const groups = await panel.getByTestId("mc-assumption-group").evaluateAll((els) => els.map((e) => e.getAttribute("data-option")));
    expect(groups).toEqual([...new Set(mc.assumptions.map((a: { option_id: string }) => a.option_id))]);
    await expect(panel.locator('a[href^="javascript:"]')).toHaveCount(0);

    await expect(panel.getByTestId("mc-n-paths")).toHaveText(n(mc.n_paths));
    await expect(panel.getByTestId("mc-seed")).toHaveText(String(mc.seed));
    await expect(panel.getByTestId("mc-sha")).toContainText(mc.input_sha256.slice(0, 12));
    await expect(panel.getByTestId("mc-runtime")).toHaveText(`${mc.runtime_ms.toLocaleString("en-US", { maximumFractionDigits: 1 })} ms`);
    await expect(panel.getByTestId("mc-computed-by")).toContainText("Computed by FAULTLINE in Python, not by the language model.");
  });

  test("cash: breach tiles, fan bands, the view toggle and the per-week strip come from the served run", async ({ page }) => {
    await mock(page, ALL);
    await page.goto("/explore/");
    await ask(page, "What's the probability we breach the cash floor if our biggest supplier fails?");
    const panel = page.getByTestId("mc-cash");
    await expect(panel).toBeVisible();
    const mc = CASH.monte_carlo;
    await expect(panel.getByTestId("mc-breach-no-plan")).toHaveText(pct(mc.no_plan.prob_below_floor_any));
    await expect(panel.getByTestId("mc-breach-with-plan")).toHaveText(pct(mc.with_plan.prob_below_floor_any));
    await expect(panel.getByTestId("mc-breach")).toContainText(`no plan ${ci(mc.no_plan.prob_below_floor_ci95)} · with plan ${ci(mc.with_plan.prob_below_floor_ci95)}`);
    await expect(panel.getByTestId("mc-plan-status")).toHaveText(mc.plan.status);
    await expect(panel.getByTestId("mc-plan-action")).toHaveCount(mc.plan.actions.length);
    for (const kind of ["SIMULATED", "SYNTHETIC", "ILLUSTRATIVE"]) await expect(panel.locator(`[data-provenance="${kind}"]`).first()).toBeVisible();

    await expect(panel.getByTestId("mc-fan-no-plan")).toHaveCount(1);
    await expect(panel.getByTestId("mc-fan-with-plan")).toHaveCount(1);
    await panel.getByTestId("mc-view-no_plan").click();
    await expect(panel.getByTestId("mc-fan-with-plan")).toHaveCount(0);
    await panel.getByTestId("mc-view-with_plan").click();
    await expect(panel.getByTestId("mc-fan-no-plan")).toHaveCount(0);
    await expect(panel.getByTestId("mc-fan-with-plan")).toHaveCount(1);

    await expect(panel.getByTestId("mc-heat-no-plan").getByTestId("mc-heat-cell")).toHaveCount(mc.weeks);
    await expect(panel.getByTestId("mc-heat-no-plan").getByTestId("mc-heat-cell").nth(25)).toHaveAttribute(
      "title",
      `Week 26: ${pct(mc.no_plan.prob_below_floor_by_week[25])} of paths below the floor`,
    );
    await expect(panel.getByTestId("mc-how-made")).toContainText("Computed by FAULTLINE in Python");
  });

  test("internal data: a compact table with the SYNTHETIC mock-data badge; a missing cell reads NOT AVAILABLE", async ({ page }) => {
    await mock(page, ALL);
    await page.goto("/explore/");
    await ask(page, "Who are our suppliers?");
    const card = page.getByTestId("mc-internal-data");
    await expect(card).toBeVisible();
    await expect(card.locator('[data-provenance="SYNTHETIC"]')).toBeVisible();
    await expect(card.locator('[data-provenance="SYNTHETIC (mock internal data)"]')).toBeVisible();
    await expect(card.getByTestId("mc-internal-row")).toHaveCount(3);
    await expect(card.getByTestId("mc-internal-row").nth(2)).toContainText("NOT AVAILABLE");
  });

  test("a malformed Monte Carlo body draws no chart and says NOT AVAILABLE", async ({ page }) => {
    await mock(page, [toolCall("monte_carlo_decision", { monte_carlo: { provenance: "SIMULATED" } })]);
    await page.goto("/explore/");
    await ask(page, "TEST FIXTURE malformed");
    await expect(page.getByTestId("mc-unreadable")).toBeVisible();
    await expect(page.getByTestId("mc-decision")).toHaveCount(0);
  });

  test("390 px wide: no horizontal page scroll", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mock(page, ALL);
    await page.goto("/explore/");
    await ask(page, "Should Nvidia keep Jensen Huang as CEO? Give me the odds.");
    await expect(page.getByTestId("chat-answer")).toBeVisible();
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(over).toBeLessThanOrEqual(0);
    if (SHOTS) {
      await page.getByTestId("mc-decision").screenshot({ path: `${SHOTS}/mc-390-decision.png` });
      await page.getByTestId("mc-cash").screenshot({ path: `${SHOTS}/mc-390-cash.png` });
    }
  });

  test("reduced motion: nothing animates and the bars are at their final size", async ({ page }) => {
    await mock(page, ALL);
    await page.goto("/explore/");
    await ask(page, "TEST FIXTURE reduced motion");
    const panel = page.getByTestId("mc-decision");
    await expect(panel).toBeVisible();
    const animated = await page.locator('[data-testid="chat-monte-carlo"] *').evaluateAll((els) =>
      els.filter((e) => getComputedStyle(e).animationName !== "none").length,
    );
    expect(animated).toBe(0);
  });

  test("with motion: the reveal ends exactly on the data", async ({ browser }) => {
    const context = await browser.newContext({ reducedMotion: "no-preference", viewport: { width: 1920, height: 1080 } });
    const page = await context.newPage();
    await mock(page, ALL);
    await page.goto("/explore/");
    await ask(page, "TEST FIXTURE motion");
    const grow = page.locator('[data-testid="mc-decision"] .mc-grow').first();
    await expect(grow).toBeVisible();
    await expect
      .poll(() => grow.evaluate((e) => getComputedStyle(e).transform), { timeout: 5000 })
      .toMatch(/^(none|matrix\(1, 0, 0, 1, 0, 0\))$/);
    await context.close();
  });

  for (const theme of ["dark", "light"] as const) {
    test(`screenshots at 1920 (${theme})`, async ({ browser }) => {
      test.skip(!SHOTS, "MC_SHOTS not set");
      const context = await browser.newContext({ colorScheme: theme, reducedMotion: "reduce", viewport: { width: 1920, height: 1080 } });
      await context.addInitScript((t) => {
        try {
          localStorage.setItem("faultline-theme", t);
        } catch {}
      }, theme);
      const page = await context.newPage();
      await mock(page, ALL);
      await page.goto("/explore/");
      await ask(page, "Should Nvidia keep Jensen Huang as CEO? Give me the odds.");
      await expect(page.getByTestId("mc-cash")).toBeVisible();
      await page.getByTestId("mc-decision").scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${SHOTS}/mc-1920-${theme}-viewport.png` });
      await page.getByTestId("mc-fan").scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${SHOTS}/mc-1920-${theme}-viewport-cash.png` });
      await page.getByTestId("mc-decision").screenshot({ path: `${SHOTS}/mc-1920-${theme}-decision.png` });
      await page.getByTestId("mc-cash").screenshot({ path: `${SHOTS}/mc-1920-${theme}-cash.png` });
      await page.getByTestId("mc-internal-data").screenshot({ path: `${SHOTS}/mc-1920-${theme}-internal.png` });
      await context.close();
    });
  }
});
