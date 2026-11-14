import { expect, test, type Page, type Request, type Response } from "@playwright/test";
import { E2E_API_BASE } from "./ports";

/**
 * CASCADE Protect payroll / recovery plan (issue #56) against the real API and the static export.
 *
 * Honesty rule (as smoke.spec.ts): no expected dollar figure is written here. Each one is fetched from the API with
 * the exact body the browser sent and compared with what the page displays. The infeasible case is the scenario the
 * finance tests pin (test_optimizer.py: 50% drop weeks 5-10, 4-week recovery, payroll protected).
 */

const OPTIMIZE_URL = `${E2E_API_BASE}/api/optimize`;
const SIMULATE_URL = `${E2E_API_BASE}/api/simulate`;

// lib/format.ts `usd`: whole dollars, except a value on a half dollar (x.50) shows its cents (F20, #157).
const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const CENTS = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usd = (n: number) => (Math.abs((Math.abs(n) % 1) - 0.5) < 0.005 ? CENTS.format(n) : USD.format(Math.round(n) || 0));
/** lib/format.ts `usdCentsFloor`: dollars and cents, rounded down, so a ceiling is never shown above itself (F4). */
const usdCentsFloor = (n: number) => CENTS.format(Math.floor(n * 100 + 1e-9) / 100);

const isOptimize = (r: Request) => r.method() === "POST" && r.url() === OPTIMIZE_URL;
const isSimulate = (r: Request) => r.method() === "POST" && r.url() === SIMULATE_URL;

type Opt = { status: string; min_cash: number | null; max_feasible_cash_floor: number | null; protect_payroll: boolean };

async function direct(page: Page, res: Response): Promise<Opt> {
  const again = await page.request.post(OPTIMIZE_URL, { data: res.request().postDataJSON() });
  expect(again.status(), "direct POST /api/optimize").toBe(200);
  return (await again.json()) as Opt;
}

test.describe("CASCADE recovery plan", () => {
  test("feasible baseline plan shows the API's min cash; Apply plan re-simulates with recovery plan", async ({ page }) => {
    const first = page.waitForResponse((r) => isOptimize(r.request()));
    await page.goto("/cascade/");
    const res = await first;
    expect(res.status()).toBe(200);
    const api = await direct(page, res);
    expect(api.status).toBe("OPTIMAL");

    const plan = page.getByTestId("recovery-plan");
    await expect(plan).toHaveAttribute("data-status", "OPTIMAL");
    await expect(page.getByTestId("plan-min-cash")).toHaveText(usd(api.min_cash as number));

    const withPlan = page.waitForResponse((r) => isSimulate(r.request()) && !!r.request().postDataJSON()?.plan);
    await page.getByRole("button", { name: "Apply plan" }).click();
    expect((await withPlan).status()).toBe(200);
    await expect(page.getByText("with recovery plan", { exact: false }).first()).toBeVisible();
  });

  test("severe drop with payroll protected reads NO FEASIBLE PLAN and the API's highest floor a plan can hold", async ({ page }) => {
    await page.goto("/cascade/");
    await expect(page.locator("#cascade-demand-delta")).toBeEnabled();
    await page.locator("#cascade-demand-end").fill("10");
    await page.locator("#cascade-demand-start").fill("5");
    await page.locator("#cascade-demand-recovery").fill("4");
    await page.locator("#cascade-demand-delta").fill("50");

    const sw = page.getByRole("switch", { name: "Protect payroll" });
    await expect(sw).toBeEnabled();
    const protectedRes = page.waitForResponse(
      (r) => isOptimize(r.request()) && r.request().postDataJSON()?.protect_payroll === true,
    );
    await sw.click();
    await expect(sw).toHaveAttribute("aria-checked", "true");
    const res = await protectedRes;
    const body = res.request().postDataJSON() as { shock: { demand: Record<string, number> } };
    expect(body.shock.demand).toMatchObject({ delta: 0.5, start_week: 5, end_week: 10, recovery_weeks: 4 });
    const api = await direct(page, res);
    expect(api.status).toBe("NO FEASIBLE PLAN");

    await expect(page.getByTestId("recovery-plan")).toHaveAttribute("data-status", "NO FEASIBLE PLAN");
    await expect(page.getByText("NO FEASIBLE PLAN", { exact: true })).toBeVisible();
    const floor = api.max_feasible_cash_floor as number;
    await expect(page.getByTestId("max-feasible-floor")).toHaveText(usdCentsFloor(floor));
    const shown = Number((await page.getByTestId("max-feasible-floor").textContent())!.replace(/[$,]/g, ""));
    expect(shown, "the highest feasible floor is shown with cents and never rounded up").toBeLessThanOrEqual(floor);
    expect(floor - shown).toBeLessThan(0.01);

    // Switch off: payroll cuts are allowed again and the same shock has a plan.
    const unprotected = page.waitForResponse(
      (r) => isOptimize(r.request()) && r.request().postDataJSON()?.protect_payroll === false,
    );
    await sw.click();
    expect((await direct(page, await unprotected)).status).toBe("OPTIMAL");
    await expect(page.getByTestId("recovery-plan")).toHaveAttribute("data-status", "OPTIMAL");
  });

  test("flipping Protect payroll on never shows the old plan's payroll cuts while the new answer is pending", async ({ page }) => {
    await page.goto("/cascade/");
    await expect(page.locator("#cascade-demand-delta")).toBeEnabled();
    await page.locator("#cascade-demand-end").fill("10");
    await page.locator("#cascade-demand-start").fill("5");
    await page.locator("#cascade-demand-recovery").fill("4");
    await page.locator("#cascade-demand-delta").fill("50");

    // Protect off: the API's plan for this shock uses payroll cuts (test_optimizer.py pins that), so they are listed.
    const plan = page.getByTestId("recovery-plan");
    await expect(plan).toHaveAttribute("data-status", "OPTIMAL");
    await expect(page.getByTestId("chosen-actions").getByText(/^Payroll cut/).first()).toBeVisible();

    // Hold the protect-on request at the network until the assertions below have run.
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
    // During the debounce and while the request is held: no plan rows at all, only the pending state.
    await expect(plan).toHaveAttribute("data-status", "PENDING");
    await expect(page.getByText(/^Payroll cut/)).toHaveCount(0);
    await sent;
    await expect(plan).toHaveAttribute("data-status", "PENDING");
    await expect(page.getByText(/^Payroll cut/)).toHaveCount(0);
    await expect(page.getByText("Solving for the current inputs", { exact: false })).toBeVisible();

    release();
    await expect(plan).toHaveAttribute("data-status", "NO FEASIBLE PLAN");
    await expect(page.getByText(/^Payroll cut/)).toHaveCount(0);
  });
});
