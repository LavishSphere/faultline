import { expect, test, type Request } from "@playwright/test";
import { E2E_API_BASE } from "./ports";

/**
 * On-screen fixes from docs/FINANCE_REVIEW.md (#157) against the real API and the static export.
 *
 * Same honesty rule as smoke.spec.ts: no expected figure, week or case id is written here. Each one is read from the
 * API and compared with what the page displays; only label wording is literal.
 */

const CASES_URL = `${E2E_API_BASE}/api/cases`;
const SIMULATE_URL = `${E2E_API_BASE}/api/simulate`;
const SCENARIOS_URL = `${E2E_API_BASE}/api/scenarios`;
const FRAMES_URL = `${E2E_API_BASE}/api/decision/frames`;
const VC_URL = `${E2E_API_BASE}/api/vc-lenses`;
const isSimulate = (r: Request) => r.method() === "POST" && r.url() === SIMULATE_URL;

const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

interface Case {
  event_id: string;
  title: string;
  as_of: string;
  provenance: "REAL_HISTORICAL" | "SYNTHETIC";
}

async function realCase(page: import("@playwright/test").Page): Promise<Case> {
  const res = await page.request.get(CASES_URL);
  expect(res.status(), "direct GET /api/cases").toBe(200);
  const items = ((await res.json()) as { items: Case[] }).items;
  const c = items.find((i) => i.provenance === "REAL_HISTORICAL");
  expect(c, "the API serves at least one REAL_HISTORICAL case").toBeTruthy();
  return c!;
}

test("F1: the header shows the selected case and its provenance on every screen, NOT AVAILABLE before a pick", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  const c = await realCase(page);
  await page.goto("/rewind/");
  const header = page.getByTestId("header-case");
  // Several cases are served and none is picked yet in this fresh tab.
  await expect(header).toContainText("NOT AVAILABLE");
  await expect(header).toContainText("No case selected");

  await page.getByRole("list", { name: "Replay cases" }).getByRole("button").filter({ hasText: c.title }).click();
  await expect(page.getByTestId("header-case-id")).toHaveText(c.event_id);
  await expect(header.locator('[data-provenance="REAL HISTORICAL"]')).toContainText("REAL HISTORICAL");
  await expect(header).not.toContainText("NOT AVAILABLE");

  // The selection is shared: still shown after moving to another screen, and D.3 checks that case.
  await page.goto("/reveal/");
  await expect(page.getByTestId("header-case-id")).toHaveText(c.event_id);
  await expect(page.getByText(`case ${c.event_id}`, { exact: false }).first()).toBeVisible();
  await expect(page.getByText("no case selected", { exact: true })).toHaveCount(0);
});

test("F9: Thesis Court defaults to the selected case's cutoff and labels the count with it", async ({ page }) => {
  const c = await realCase(page);
  await page.goto("/rewind/");
  await page.getByRole("list", { name: "Replay cases" }).getByRole("button").filter({ hasText: c.title }).click();
  await expect(page.getByTestId("header-case-id")).toHaveText(c.event_id);

  const first = page.waitForResponse((r) => r.url().startsWith(VC_URL));
  await page.goto("/research/");
  const res = await first;
  const url = new URL(res.url());
  const direct = (await (await page.request.get(res.url())).json()) as { as_of: string; items: { firm: string }[] };
  // The first request is at the case cutoff, normalized by the API; the input shows the case's as_of.
  expect(Date.parse(url.searchParams.get("as_of") ?? ""), "first request at the case cutoff").toBe(Date.parse(c.as_of));
  await expect(page.locator("#thesis-as-of")).toHaveValue(c.as_of);
  await expect(page.getByText(`Default: the selected case's cutoff (${c.event_id}).`, { exact: false })).toBeVisible();
  await expect(page.getByText(` public at ${direct.as_of}`, { exact: false }).first()).toBeVisible();
});

test("F2/F3: the bad quarter shows the API's floor and the weeks below it; 'Cash goes negative' is worded as a week", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  const scenarios = (await (await page.request.get(SCENARIOS_URL)).json()) as { items: { id: string }[] };
  const bad = scenarios.items.find((p) => p.id === "bad-quarter");
  expect(bad, "GET /api/scenarios serves bad-quarter").toBeTruthy();

  await page.goto("/cascade/");
  await expect(page.locator("#cascade-demand-delta")).toBeEnabled();
  await expect(page.getByText(/named scenarios? from GET \/api\/scenarios/)).toBeVisible();
  await expect(page.locator("#cascade-preset")).toBeEnabled();
  const picked = page.waitForResponse((r) => isSimulate(r.request()) && r.request().postDataJSON()?.scenario_id === "bad-quarter");
  await page.locator("#cascade-preset").selectOption("bad-quarter");
  const res = await picked;
  const api = (await (await page.request.post(SIMULATE_URL, { data: res.request().postDataJSON() })).json()) as {
    provenance: string;
    min_cash_floor: number;
    first_week_below_floor: number | null;
    weeks_below_floor: number[];
    result: { runway_week: number | null; horizon_weeks: number };
  };
  expect(api.provenance).toBe("SIMULATED");
  expect(api.first_week_below_floor, "the bad quarter goes below the floor").not.toBeNull();
  const ws = api.weeks_below_floor;
  const contiguous = ws.every((w, i) => i === 0 || w === ws[i - 1]! + 1);
  expect(contiguous, "this scenario's weeks below the floor are one run").toBe(true);
  const line = `floor ${USD.format(api.min_cash_floor)} · below it in week${ws.length === 1 ? "" : "s"} ${ws.length === 1 ? ws[0] : `${ws[0]}–${ws[ws.length - 1]}`}`;
  await expect(page.getByTestId("floor-line").first()).toHaveText(line);

  const negative = page.locator("div").filter({ has: page.getByText("Cash goes negative", { exact: true }) }).filter({ has: page.locator("p.num") }).last();
  await expect(negative.locator("p.num .sr-only")).toHaveText(
    api.result.runway_week === null ? `not within ${api.result.horizon_weeks} weeks` : `in week ${api.result.runway_week}`,
  );
  await expect(negative.getByText("first week C_t < 0 (MATH_MODEL §3)", { exact: false })).toBeVisible();
  await expect(page.getByText("Runway", { exact: true })).toHaveCount(0);

  // Baseline (Reset): the same API fields say cash stays above the floor.
  const reset = page.waitForResponse((r) => isSimulate(r.request()));
  await page.getByRole("button", { name: "Reset to baseline" }).click();
  const base = (await (await page.request.post(SIMULATE_URL, { data: (await reset).request().postDataJSON() })).json()) as {
    min_cash_floor: number;
    first_week_below_floor: number | null;
  };
  expect(base.first_week_below_floor).toBeNull();
  await expect(page.getByTestId("floor-line").first()).toHaveText(`stays above the ${USD.format(base.min_cash_floor)} floor`);
});

test("F21: DECISION shows the frames' status exactly as GET /api/decision/frames serves it", async ({ page }) => {
  const api = (await (await page.request.get(FRAMES_URL)).json()) as { status: string };
  expect(api.status.length).toBeGreaterThan(0);
  await page.goto("/decision/");
  const box = page.getByTestId("frames-status");
  await expect(box).toBeVisible();
  await box.locator("summary").click();
  await expect(box.getByText(api.status.trim(), { exact: true })).toBeVisible();
});

test("the new labels fit a 390 px phone without horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/cascade/", "/decision/", "/research/", "/reveal/"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `horizontal overflow on ${path} in px`).toBeLessThanOrEqual(0);
  }
});
