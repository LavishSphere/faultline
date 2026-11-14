import { expect, test, type Locator, type Page, type Request } from "@playwright/test";
import { E2E_API_BASE } from "./ports";

/**
 * Golden-path smoke test (issue #53) against the real API and the static export.
 *
 * Honesty rule for this file: no expected figure is written here. Every expected number is fetched from the API
 * directly (same request body the browser sent) and compared with what the page displays. The one literal is the
 * RESEARCH cutoff fixture from the issue's acceptance criteria, which pins the curated dataset, not a computation.
 */

const SIMULATE_URL = `${E2E_API_BASE}/api/simulate`;
const VC_LENSES_URL = `${E2E_API_BASE}/api/vc-lenses`;
/** Issue #53 AC: at this cutoff the curated research dataset holds back 2 lenses as not yet public. */
const RESEARCH_CUTOFF = "2026-07-01T00:00:00Z";
const RESEARCH_EXPECTED_HELD_BACK = 2;

/** Same display formatting as components/FinancialReadout.tsx ("usd"): formatting only, no arithmetic. */
const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const usd = (n: number) => USD.format(Math.round(n) || 0);

const isSimulate = (r: Request) => r.method() === "POST" && r.url() === SIMULATE_URL;

/** The FinancialReadout block whose kicker is `label` (innermost div holding the kicker and the figure). */
function readout(page: Page, label: string): Locator {
  return page
    .locator("div")
    .filter({ has: page.getByText(label, { exact: true }) })
    .filter({ has: page.locator("p.num") })
    .last();
}

/** Screen-reader copy of a readout: the exact formatted API value, never an animation frame. */
function exactValue(block: Locator): Locator {
  return block.locator("p.num .sr-only");
}

async function minCashFromApi(page: Page, body: unknown): Promise<number> {
  const res = await page.request.post(SIMULATE_URL, { data: body });
  expect(res.status(), "direct POST /api/simulate").toBe(200);
  const json = (await res.json()) as { result: { min_cash: number } };
  expect(typeof json.result.min_cash).toBe("number");
  return json.result.min_cash;
}

test.describe("CASCADE", () => {
  test("baseline min cash equals the API; one slider move sends exactly one request and changes it", async ({ page }) => {
    const sent: Request[] = [];
    page.on("request", (r) => {
      if (isSimulate(r)) sent.push(r);
    });

    const firstResponse = page.waitForResponse((r) => isSimulate(r.request()));
    await page.goto("/cascade/");
    const first = await firstResponse;
    expect(first.status()).toBe(200);

    const baselineBody = first.request().postDataJSON() as unknown;
    const baselineMin = await minCashFromApi(page, baselineBody);
    const minCash = readout(page, "Minimum cash");
    await expect(exactValue(minCash)).toHaveText(usd(baselineMin));
    await expect(minCash.getByText("SIMULATED", { exact: true })).toBeVisible();

    // Controls unlock once the API has reported the horizon.
    const demand = page.locator("#cascade-demand-delta");
    await expect(demand).toBeEnabled();
    const before = sent.length;

    // One discrete slider move (a single input event): PageUp steps the range by a large increment.
    const moved = page.waitForResponse((r) => isSimulate(r.request()));
    await demand.focus();
    await demand.press("PageUp");
    const response = await moved;
    expect(response.status()).toBe(200);

    const movedBody = response.request().postDataJSON() as { shock?: { demand?: unknown } };
    expect(movedBody.shock?.demand, "the moved slider is in the request").toBeTruthy();
    const movedMin = await minCashFromApi(page, movedBody);
    await expect(exactValue(minCash)).toHaveText(usd(movedMin));
    expect(usd(movedMin), "a demand shock changes the displayed minimum cash").not.toBe(usd(baselineMin));

    // Well past the 150 ms debounce: no second request follows the single move.
    await page.waitForTimeout(1000);
    expect(sent.length - before, "POST /api/simulate requests after one slider move").toBe(1);
  });

  test("API down: readouts are NOT AVAILABLE and inputs are disabled", async ({ page }) => {
    // The browser cannot reach the API at all (connection refused), as when `make api` is not running.
    await page.route(`${E2E_API_BASE}/**`, (route) => route.abort("connectionrefused"));
    await page.goto("/cascade/");

    await expect(page.getByText(`API unreachable at ${E2E_API_BASE}`)).toBeVisible();
    const minCash = readout(page, "Minimum cash");
    await expect(minCash.getByText("Not available", { exact: true })).toBeVisible();
    await expect(minCash.getByText("NOT AVAILABLE", { exact: true })).toBeVisible();
    await expect(page.locator("#cascade-demand-delta")).toBeDisabled();
    // No dollar figure is carried over or invented.
    await expect(readout(page, "Ending cash").getByText("Not available", { exact: true })).toBeVisible();
  });
});

test.describe("RESEARCH LENS", () => {
  test(`cutoff ${RESEARCH_CUTOFF} shows the API's not-yet-public count`, async ({ page }) => {
    const initial = page.waitForResponse((r) => r.url().startsWith(VC_LENSES_URL));
    await page.goto("/research/");
    await initial;

    const input = page.locator("#thesis-as-of");
    // The first request pre-fills "now"; wait for it so it cannot overwrite the cutoff typed below.
    await expect(input).not.toHaveValue("");
    await input.fill(RESEARCH_CUTOFF);

    const query = `?as_of=${encodeURIComponent(RESEARCH_CUTOFF)}`;
    const atCutoff = page.waitForResponse((r) => r.url() === `${VC_LENSES_URL}${query}`);
    await page.getByRole("button", { name: "Apply cutoff" }).click();
    expect((await atCutoff).status()).toBe(200);

    const direct = await page.request.get(`${VC_LENSES_URL}${query}`);
    expect(direct.status(), "direct GET /api/vc-lenses").toBe(200);
    const api = (await direct.json()) as { as_of: string; items: unknown[]; excluded_not_yet_public: number };
    expect(api.excluded_not_yet_public, "curated dataset fixture (issue #53 AC)").toBe(RESEARCH_EXPECTED_HELD_BACK);

    const label = page.getByText(/not yet public at this cutoff/);
    await expect(label.locator("xpath=preceding-sibling::p[1]")).toHaveText(String(api.excluded_not_yet_public));
    await expect(page.getByText(/^API as_of/)).toHaveText(`API as_of ${api.as_of} · ${api.items.length} shown`);
  });
});

test.describe("REVEAL", () => {
  const BENCHMARK_URL = `${E2E_API_BASE}/api/benchmark`;

  test("loads the recorded benchmark read-only and shows what the API served; never reveals or computes", async ({ page }) => {
    const apiCalls: string[] = [];
    page.on("request", (r) => {
      if (r.url().startsWith(E2E_API_BASE)) apiCalls.push(`${r.method()} ${new URL(r.url()).pathname}`);
    });

    const loaded = page.waitForResponse((r) => r.url() === BENCHMARK_URL);
    await page.goto("/reveal/");
    expect((await loaded).status()).toBe(200);

    const direct = await page.request.get(BENCHMARK_URL);
    expect(direct.status(), "direct GET /api/benchmark").toBe(200);
    const api = (await direct.json()) as {
      status: string;
      provenance: string;
      notes: string[];
      items: { label: string; verdict: string }[];
    };

    await expect(page.getByText(`status: ${api.status} · provenance: ${api.provenance}`, { exact: true })).toBeVisible();
    for (const note of api.notes) await expect(page.getByText(note, { exact: true })).toBeVisible();

    const first = api.items[0];
    if (first) {
      // The default tab is the first variant the API served; its first item's strings are shown verbatim.
      await expect(page.getByTestId("scorecard-label")).toHaveText(first.label);
      await expect(page.getByTestId("scorecard-verdict")).toHaveText(first.verdict);
    } else {
      // No scorecard served: NOT AVAILABLE, never INSUFFICIENT DATA (that verdict belongs to a served card, #117).
      await expect(page.getByTestId("scorecard-label")).toHaveCount(0);
      await expect(page.getByTestId("scorecard-empty")).toHaveText("Not available");
      await expect(page.getByText("Insufficient data", { exact: true })).toHaveCount(0);
    }
    // The outcome stays sealed until an explicit click, and nothing on the scorecard is marked as this forecast.
    await expect(page.getByText("Sealed", { exact: true })).toBeVisible();
    await expect(page.getByText("← this forecast")).toHaveCount(0);
    // Per-event outcomes (y of every scored event) start collapsed.
    const perEvent = page.getByTestId("per-event-outcomes");
    if (await perEvent.count()) await expect(perEvent).not.toHaveAttribute("open", /.*/);

    await page.waitForTimeout(500);
    expect(apiCalls.filter((c) => c.startsWith("POST")), "no POST (reveal / compute) on page load").toEqual([]);
  });
});
