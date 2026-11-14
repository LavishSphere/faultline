import { expect, test, type Request } from "@playwright/test";
import { E2E_API_BASE } from "./ports";

/**
 * Judge's Challenge (issue #123) against the real API and the static export.
 *
 * Same honesty rule as smoke.spec.ts: no expected figure is written here. The challenge list and every number are
 * fetched from the API and compared with what the page sends and displays.
 */

const SIMULATE_URL = `${E2E_API_BASE}/api/simulate`;
const CHALLENGES_URL = `${E2E_API_BASE}/api/judge-challenges`;

/** Same display formatting as components/FinancialReadout.tsx ("usd"): formatting only, no arithmetic. */
// lib/format.ts `usd`: whole dollars, except a value on a half dollar (x.50) shows its cents (F20, #157).
const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const CENTS = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usd = (n: number) => (Math.abs((Math.abs(n) % 1) - 0.5) < 0.005 ? CENTS.format(n) : USD.format(Math.round(n) || 0));
const isSimulate = (r: Request) => r.method() === "POST" && r.url() === SIMULATE_URL;

interface Challenge {
  id: string;
  name: string;
  range_citation: string;
  shock: Record<string, unknown>;
}

test("picking a challenge sends its exact shock; Surprise me follows the API's fixed order", async ({ page }) => {
  const direct = await page.request.get(CHALLENGES_URL);
  expect(direct.status(), "direct GET /api/judge-challenges").toBe(200);
  const api = (await direct.json()) as { status: string; items: Challenge[]; surprise_order: string[] };
  expect(api.status).toBe("AVAILABLE");
  const chosen = api.items[1] ?? api.items[0];
  expect(chosen, "the API lists at least one challenge").toBeTruthy();
  if (!chosen) return;

  const firstSim = page.waitForResponse((r) => isSimulate(r.request()));
  await page.goto("/cascade/");
  await firstSim;

  const panel = page.getByTestId("judge-challenge");
  // Badges: the shock is ILLUSTRATIVE, the results are SIMULATED (text + color, never color alone).
  await expect(panel.locator('[data-provenance="ILLUSTRATIVE"]')).toContainText("ILLUSTRATIVE");
  await expect(panel.locator('[data-provenance="SIMULATED"]')).toContainText("SIMULATED");
  const select = page.locator("#judge-challenge-select");
  await expect(select).toBeEnabled();

  // Keyboard path: focus the select and choose by value (a native <select> is keyboard operable).
  const picked = page.waitForResponse((r) => isSimulate(r.request()) && r.request().postData()?.includes(chosen.id) === true);
  await select.focus();
  await select.selectOption(chosen.id);
  const res = await picked;
  expect(res.status()).toBe(200);
  const body = res.request().postDataJSON() as { scenario_id?: string; shock: Record<string, unknown> };
  expect(body.scenario_id).toBe(chosen.id);
  expect(body.shock, "the challenge's ScenarioShock is sent exactly as served").toEqual(chosen.shock);

  const check = await page.request.post(SIMULATE_URL, { data: body });
  const minCash = ((await check.json()) as { result: { min_cash: number } }).result.min_cash;
  await expect(page.locator("p.num .sr-only").first()).toHaveText(usd(minCash));
  await expect(page.getByTestId("judge-challenge-citation")).toHaveText(`Range: ${chosen.range_citation}`);

  // Surprise me: pick 1 is surprise_order[0], deterministic.
  const firstSurprise = api.surprise_order[0];
  if (firstSurprise && firstSurprise !== chosen.id) {
    const surprised = page.waitForResponse((r) => isSimulate(r.request()) && r.request().postData()?.includes(firstSurprise) === true);
    await page.getByRole("button", { name: "Surprise me" }).click();
    expect((await surprised).status()).toBe(200);
    await expect(select).toHaveValue(firstSurprise);
    await expect(page.getByTestId("judge-challenge-active")).toContainText("Surprise pick 1");
  }
});

test("a pick drives one debounced /api/optimize with Protect payroll and drops a plan applied to the old shock", async ({ page }) => {
  const OPTIMIZE_URL = `${E2E_API_BASE}/api/optimize`;
  const isOptimize = (r: Request) => r.method() === "POST" && r.url() === OPTIMIZE_URL;
  const api = (await (await page.request.get(CHALLENGES_URL)).json()) as { items: Challenge[] };
  const chosen = api.items[0];
  expect(chosen, "the API lists at least one challenge").toBeTruthy();
  if (!chosen) return;

  const firstOpt = page.waitForResponse((r) => isOptimize(r.request()));
  await page.goto("/cascade/");
  await firstOpt;

  // Apply the baseline plan, so we can check it is not carried over to the challenge's shock.
  await expect(page.getByTestId("recovery-plan")).toHaveAttribute("data-status", "OPTIMAL");
  const planned = page.waitForResponse((r) => isSimulate(r.request()) && !!r.request().postDataJSON()?.plan);
  await page.getByRole("button", { name: "Apply plan" }).click();
  await planned;

  const sw = page.getByRole("switch", { name: "Protect payroll" });
  const protectedOpt = page.waitForResponse((r) => isOptimize(r.request()) && r.request().postDataJSON()?.protect_payroll === true);
  await sw.click();
  await protectedOpt;

  const optSent: Request[] = [];
  page.on("request", (r) => {
    if (isOptimize(r)) optSent.push(r);
  });
  const optPicked = page.waitForResponse(
    (r) => isOptimize(r.request()) && r.request().postDataJSON()?.scenario_id === chosen.id,
  );
  const simPicked = page.waitForResponse(
    (r) => isSimulate(r.request()) && r.request().postDataJSON()?.scenario_id === chosen.id,
  );
  await page.locator("#judge-challenge-select").selectOption(chosen.id);
  const [optRes, simRes] = await Promise.all([optPicked, simPicked]);
  expect(optRes.status()).toBe(200);
  const optBody = optRes.request().postDataJSON() as { shock: unknown; protect_payroll: boolean };
  expect(optBody.shock, "optimize gets the challenge's exact shock").toEqual(chosen.shock);
  expect(optBody.protect_payroll).toBe(true);
  expect((simRes.request().postDataJSON() as { plan?: unknown }).plan, "the old plan is not applied to the new shock").toBeUndefined();

  // The plan panel shows the API's answer for exactly this request.
  const again = await page.request.post(OPTIMIZE_URL, { data: optRes.request().postDataJSON() });
  const opt = (await again.json()) as { status: string; min_cash: number | null };
  await expect(page.getByTestId("recovery-plan")).toHaveAttribute("data-status", opt.status);
  if (opt.status === "OPTIMAL" && opt.min_cash !== null) await expect(page.getByTestId("plan-min-cash")).toHaveText(usd(opt.min_cash));

  await page.waitForTimeout(1000);
  expect(optSent.length, "POST /api/optimize requests after one pick").toBe(1);
});

test("Judge's Challenge fits a 390 px phone without horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/cascade/");
  await expect(page.locator("#judge-challenge-select")).toBeEnabled();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "horizontal overflow in px").toBeLessThanOrEqual(0);
});
