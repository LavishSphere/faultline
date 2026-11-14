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

const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const usd = (n: number) => USD.format(Math.round(n) || 0);

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

  test("severe drop with payroll protected reads NO FEASIBLE PLAN and the API's smallest feasible floor", async ({ page }) => {
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
    await expect(page.getByTestId("max-feasible-floor")).toHaveText(usd(api.max_feasible_cash_floor as number));

    // Switch off: payroll cuts are allowed again and the same shock has a plan.
    const unprotected = page.waitForResponse(
      (r) => isOptimize(r.request()) && r.request().postDataJSON()?.protect_payroll === false,
    );
    await sw.click();
    expect((await direct(page, await unprotected)).status).toBe("OPTIMAL");
    await expect(page.getByTestId("recovery-plan")).toHaveAttribute("data-status", "OPTIMAL");
  });
});
