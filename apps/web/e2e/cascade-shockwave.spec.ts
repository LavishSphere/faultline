import { expect, test, type Page, type Request } from "@playwright/test";
import { E2E_API_BASE } from "./ports";

/**
 * CASCADE shockwave, payroll shield, plan on the graph, incoming-shock card and cash timeline (#165), against the
 * real API and the static export.
 *
 * Same honesty rule as smoke.spec.ts: no expected figure is written here. Every value is re-fetched from the API with
 * the exact body the browser sent, and compared with what the page shows once the animation has settled.
 */

const SIMULATE_URL = `${E2E_API_BASE}/api/simulate`;
const OPTIMIZE_URL = `${E2E_API_BASE}/api/optimize`;
const CHALLENGES_URL = `${E2E_API_BASE}/api/judge-challenges`;
const isSimulate = (r: Request) => r.method() === "POST" && r.url() === SIMULATE_URL;
const isOptimize = (r: Request) => r.method() === "POST" && r.url() === OPTIMIZE_URL;

// components/CascadeGraph.tsx `formatDelta` and lib/format.ts `usd` / `usdCentsFloor`: formatting only, no arithmetic.
const SIGNED = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0, signDisplay: "exceptZero" });
const INT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0, signDisplay: "exceptZero" });
const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const CENTS = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usd = (n: number) => (Math.abs((Math.abs(n) % 1) - 0.5) < 0.005 ? CENTS.format(n) : USD.format(Math.round(n) || 0));
const usdCentsFloor = (n: number) => CENTS.format(Math.floor(n * 100 + 1e-9) / 100);
const UNITS: Record<string, "usd" | "bp" | "pp"> = { Supplier: "pp", Rate: "bp" };
function formatDelta(v: number, node: string): string {
  const whole = (n: number) => Math.round(n) || 0;
  const unit = UNITS[node] ?? "usd";
  if (unit === "bp") return `${INT.format(whole(v * 10_000))} bp`;
  if (unit === "pp") return `${INT.format(whole(v * 100))} pp`;
  return SIGNED.format(whole(v));
}
/** The served per_week entry with the largest |Δ| (first on ties): the value the node displays. */
function peak(perWeek: number[]): number {
  let p = perWeek[0] ?? 0;
  for (const d of perWeek) if (Math.abs(d) > Math.abs(p)) p = d;
  return p;
}

interface Sim {
  min_cash_floor: number | null;
  first_week_below_floor: number | null;
  weeks_below_floor: number[];
  deltas: { nodes: Record<string, { per_week: number[]; max_abs: number }> };
}

async function directSim(page: Page, body: unknown): Promise<Sim> {
  const res = await page.request.post(SIMULATE_URL, { data: body });
  expect(res.status(), "direct POST /api/simulate").toBe(200);
  return (await res.json()) as Sim;
}

/** Every node's final value equals the API's peak Δ, and the floor callouts equal first_week_below_floor. */
async function expectGraphEqualsApi(page: Page, api: Sim) {
  await expect(page.locator('[data-testid^="graph-node-"][data-wave="running"]')).toHaveCount(0);
  for (const [name, node] of Object.entries(api.deltas.nodes)) {
    const value = page.getByTestId(`graph-value-${name}`);
    if (node.max_abs === 0) await expect(value).toHaveCount(0);
    else await expect(value, `${name} node shows the API value`).toHaveText(formatDelta(peak(node.per_week), name));
  }
  const first = api.first_week_below_floor;
  const timelineLine = page.getByTestId("timeline-floor-line");
  if (first !== null) {
    await expect(page.getByTestId("cash-node-floor")).toHaveText(`▼ below floor from week ${first}`);
    await expect(page.getByTestId("timeline-floor-callout")).toHaveText(`▼ below floor from week ${first}`);
    await expect(timelineLine).toHaveAttribute("data-breached", "true");
  } else {
    await expect(timelineLine).toHaveAttribute("data-breached", "false");
  }
  await expect(page.getByTestId("below-floor-band")).toHaveCount(api.weeks_below_floor.length);
}

test.describe("CASCADE shockwave (motion on)", () => {
  test.use({ reducedMotion: "no-preference" });

  test("a preset's pulse settles on exactly the API's values; the floor breach turns the cash node and line red", async ({ page }) => {
    await page.goto("/cascade/");
    await expect(page.locator("#cascade-preset")).toBeEnabled();
    const picked = page.waitForResponse((r) => isSimulate(r.request()) && r.request().postDataJSON()?.scenario_id === "bad-quarter");
    await page.locator("#cascade-preset").selectOption("bad-quarter");
    const res = await picked;
    // While the pulse runs, at least one node is still on its way (the wave is real, not a fixed delay).
    await expect(page.locator('[data-testid^="graph-node-"][data-wave="running"]').first()).toBeAttached();
    const api = await directSim(page, res.request().postDataJSON());
    expect(api.first_week_below_floor, "the bad quarter goes below the floor").not.toBeNull();
    await expectGraphEqualsApi(page, api);
    await expect(page.locator('[data-series="scenario"]')).toHaveCount(1);
    await expect(page.locator('[data-series="baseline"]')).toHaveCount(1);
  });

  test("a Judge's Challenge shows the API's name, description and range citation, then settles on the API values", async ({ page }) => {
    const list = (await (await page.request.get(CHALLENGES_URL)).json()) as {
      items: { id: string; name: string; description: string; range_citation: string }[];
    };
    const chosen = list.items[0];
    expect(chosen, "the API lists at least one challenge").toBeTruthy();
    if (!chosen) return;
    await page.goto("/cascade/");
    await expect(page.locator("#judge-challenge-select")).toBeEnabled();
    const picked = page.waitForResponse((r) => isSimulate(r.request()) && r.request().postDataJSON()?.scenario_id === chosen.id);
    await page.locator("#judge-challenge-select").selectOption(chosen.id);
    const card = page.getByTestId("incoming-shock");
    await expect(card).toBeVisible();
    await expect(card).toContainText(chosen.name);
    await expect(card).toContainText(chosen.description);
    await expect(card).toContainText(`Range: ${chosen.range_citation}`);
    const api = await directSim(page, (await picked).request().postDataJSON());
    await expectGraphEqualsApi(page, api);
    await expect(card).toBeHidden({ timeout: 8_000 });
  });
});

test.describe("CASCADE payroll shield and plan on the graph", () => {
  test("reduced motion: final values at once; shield, solving state, then the plan's API amounts on Purchases", async ({ page }) => {
    await page.goto("/cascade/");
    await expect(page.locator("#cascade-preset")).toBeEnabled();
    const picked = page.waitForResponse((r) => isSimulate(r.request()) && r.request().postDataJSON()?.scenario_id === "bad-quarter");
    await page.locator("#cascade-preset").selectOption("bad-quarter");
    const api = await directSim(page, (await picked).request().postDataJSON());
    // Reduced motion (playwright.config.ts): no wave is ever running.
    await expect(page.locator('[data-wave="running"]')).toHaveCount(0);
    await expectGraphEqualsApi(page, api);

    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(OPTIMIZE_URL, async (route) => {
      if (route.request().postDataJSON()?.protect_payroll === true) await held;
      await route.continue();
    });
    const sw = page.getByRole("switch", { name: "Protect payroll" });
    const sent = page.waitForRequest((r) => isOptimize(r) && r.postDataJSON()?.protect_payroll === true);
    await sw.click();
    await expect(page.getByTestId("payroll-shield")).toBeVisible();
    const optReq = await sent;
    // While the solver has not answered: the solving state, and no plan on the graph.
    await expect(page.getByTestId("optimizer-chip")).toHaveAttribute("data-state", "solving");
    await expect(page.getByTestId("graph-plan-chip")).toHaveCount(0);
    release();

    const again = await page.request.post(OPTIMIZE_URL, { data: optReq.postDataJSON() });
    const opt = (await again.json()) as { status: string; actions: { action: string; amount: number | null }[] | null; max_feasible_cash_floor: number | null };
    await expect(page.getByTestId("recovery-plan")).toHaveAttribute("data-status", opt.status);
    if (opt.status === "OPTIMAL") {
      await expect(page.getByTestId("optimizer-chip")).toHaveAttribute("data-state", "optimal");
      const cuts = (opt.actions ?? []).filter((a) => a.action === "purchase_cut");
      const firstCut = cuts[0];
      if (firstCut && firstCut.amount !== null) {
        const chip = page.getByTestId("graph-node-Purchases").locator("..").getByTestId("graph-plan-chip");
        await expect(chip).toContainText(`×${cuts.length}`);
        await expect(chip.getByTestId("graph-plan-amount").first()).toHaveText(usd(firstCut.amount));
      }
      await expect(page.locator('[data-series="plan"]')).toHaveCount(1);
    } else if (opt.status === "NO FEASIBLE PLAN") {
      await expect(page.getByTestId("optimizer-chip")).toHaveAttribute("data-state", "infeasible");
    }
  });

  test("plant closure with payroll protected: the graph's red state carries the API's highest feasible floor", async ({ page }) => {
    await page.goto("/cascade/");
    await expect(page.locator("#judge-challenge-select")).toBeEnabled();
    const sw = page.getByRole("switch", { name: "Protect payroll" });
    await sw.click();
    const optRes = page.waitForResponse(
      (r) => isOptimize(r.request()) && r.request().postDataJSON()?.protect_payroll === true && r.request().postDataJSON()?.scenario_id === "judge-plant-closure",
    );
    await page.locator("#judge-challenge-select").selectOption("judge-plant-closure");
    const res = await optRes;
    const opt = (await (await page.request.post(OPTIMIZE_URL, { data: res.request().postDataJSON() })).json()) as {
      status: string;
      max_feasible_cash_floor: number | null;
    };
    await expect(page.getByTestId("recovery-plan")).toHaveAttribute("data-status", opt.status);
    if (opt.status !== "NO FEASIBLE PLAN") return;
    const chip = page.getByTestId("optimizer-chip");
    await expect(chip).toHaveAttribute("data-state", "infeasible");
    if (opt.max_feasible_cash_floor !== null) await expect(chip).toContainText(usdCentsFloor(opt.max_feasible_cash_floor));
    await expect(page.locator('[data-series="plan"]')).toHaveCount(0);
  });

  test("CASCADE at 390 px: no horizontal scroll with the timeline and the network", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/cascade/");
    await expect(page.locator("#cascade-preset")).toBeEnabled();
    await page.locator("#cascade-preset").selectOption("bad-quarter");
    await expect(page.getByTestId("timeline-floor-callout")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, "horizontal overflow in px").toBeLessThanOrEqual(0);
  });
});
