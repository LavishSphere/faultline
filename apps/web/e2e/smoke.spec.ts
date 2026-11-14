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
// lib/format.ts `usd`: whole dollars, except a value on a half dollar (x.50) shows its cents (F20, #157).
const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const CENTS = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usd = (n: number) => (Math.abs((Math.abs(n) % 1) - 0.5) < 0.005 ? CENTS.format(n) : USD.format(Math.round(n) || 0));
/** lib/format.ts `usdCentsFloor`: dollars and cents, rounded down (a ceiling is never rounded up, F4). */
const usdCentsFloor = (n: number) => CENTS.format(Math.floor(n * 100 + 1e-9) / 100);

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
      items: { label: string; verdict: string; caveat: string | null; n_events: number }[];
      records: { agent_variant: string }[];
    };

    // F19 (#157): with no scorecard served the line says none is recorded instead of implying a recorded run exists.
    expect(api.provenance).toBe("RECORDED_RUN");
    const provenanceText = api.status === "NOT AVAILABLE" ? "RECORDED RUN (none recorded yet)" : api.provenance;
    expect(api.status === "NOT AVAILABLE", "NOT AVAILABLE exactly when no item is served").toBe(api.items.length === 0);
    await expect(page.getByText(`status: ${api.status} · provenance: ${provenanceText}`, { exact: true })).toBeVisible();
    for (const note of api.notes) await expect(page.getByText(note, { exact: true }).first()).toBeVisible();

    // #124: both variants side by side, each showing the FIRST item the API served for it, verbatim.
    const plain = [
      ["agent_only", "Agent only: the model saw evidence, no market price"],
      ["agent_plus_market", "Agent + market: the model also saw the market price at the cutoff"],
    ] as const;
    for (const [variant, line] of plain) {
      const card = page.getByTestId(`scorecard-${variant}`);
      await expect(card.getByTestId("scorecard-variant-line")).toHaveText(line);
      const i = api.records.findIndex((r) => r.agent_variant === variant);
      const item = i >= 0 ? api.items[i] : undefined;
      if (item) {
        await expect(card.getByTestId("scorecard-label")).toHaveText(item.label);
        await expect(card.getByTestId("scorecard-verdict")).toHaveText(item.verdict);
        if (item.caveat) await expect(card.getByTestId("scorecard-caveat")).toHaveText(item.caveat);
      } else {
        // No scorecard served: NOT AVAILABLE, never INSUFFICIENT DATA (that verdict belongs to a served card, #117).
        await expect(card.getByTestId("scorecard-label")).toHaveCount(0);
        await expect(card.getByTestId("scorecard-empty")).toHaveText("Not available");
        await expect(card.getByText("Insufficient data", { exact: true })).toHaveCount(0);
        if (api.items.length) {
          // The API's own note naming the missing variant is repeated on its card, verbatim.
          await expect(card.getByTestId("scorecard-empty-note")).toContainText(variant);
        }
      }
    }
    if (api.records.length >= 2) {
      // Wide screen: the two cards share a row.
      const a = await page.getByTestId("scorecard-agent_only").boundingBox();
      const b = await page.getByTestId("scorecard-agent_plus_market").boundingBox();
      expect(a && b && Math.abs(a.y - b.y) < 2 && b.x > a.x, "cards side by side at 1920 px").toBe(true);
    }
    // The outcome stays sealed until an explicit click, and nothing on the scorecard is marked as this forecast.
    await expect(page.getByText("Sealed", { exact: true })).toBeVisible();
    await expect(page.getByText("← this forecast")).toHaveCount(0);
    // Per-event outcomes (y of every scored event) start collapsed.
    for (const perEvent of await page.getByTestId("per-event-outcomes").all()) {
      await expect(perEvent).not.toHaveAttribute("open", /.*/);
    }

    await page.waitForTimeout(500);
    expect(apiCalls.filter((c) => c.startsWith("POST")), "no POST (reveal / compute) on page load").toEqual([]);
  });

  test("scorecards stack at 390 px with no horizontal page scroll", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const loaded = page.waitForResponse((r) => r.url() === BENCHMARK_URL);
    await page.goto("/reveal/");
    await loaded;
    const a = page.getByTestId("scorecard-agent_only");
    const b = page.getByTestId("scorecard-agent_plus_market");
    await expect(a.getByTestId("scorecard-variant-line")).toBeVisible();
    await expect(b.getByTestId("scorecard-variant-line")).toBeAttached();
    const boxA = await a.boundingBox();
    const boxB = await b.boundingBox();
    expect(boxA && boxB && boxB.y >= boxA.y + boxA.height, "agent + market card below agent only").toBe(true);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, "no horizontal page scroll at 390 px").toBeLessThanOrEqual(0);
  });
});

test.describe("DECISION · ACT / WAIT / HEDGE", () => {
  const DECISION_URL = `${E2E_API_BASE}/api/decision`;
  const FRAMES_URL = `${E2E_API_BASE}/api/decision/frames`;
  const isDecisionFor = (r: Request, frameId: string) =>
    r.method() === "POST" &&
    r.url() === DECISION_URL &&
    (r.postDataJSON() as { frame_id?: string } | null)?.frame_id === frameId;
  /** Same display formatting as components/decision/SplitView.tsx (whole dollars as on CASCADE, F13): no arithmetic. */
  const USD2 = { format: usd };

  test("payoffs equal the API for every policy; the forecast-insensitive caveat is shown verbatim", async ({ page }) => {
    await page.goto("/decision/");
    const select = page.locator("#decision-frame");
    await expect(select).toBeVisible();

    const answered = page.waitForResponse((r) => isDecisionFor(r.request(), "supply-disruption"));
    await select.selectOption("supply-disruption");
    const response = await answered;
    expect(response.status()).toBe(200);

    const direct = await page.request.post(DECISION_URL, { data: response.request().postDataJSON() });
    expect(direct.status(), "direct POST /api/decision").toBe(200);
    const body = (await direct.json()) as {
      provenance: string;
      policies: { name: string; value_if_yes: number; value_if_no: number }[];
    };
    expect(body.provenance).toBe("SIMULATED");
    expect(body.policies.map((p) => p.name)).toEqual(["ACT", "WAIT", "HEDGE"]);
    for (const p of body.policies) {
      const col = page.locator(`[data-policy="${p.name}"]`);
      await expect(col.getByText(USD2.format(p.value_if_yes), { exact: true }).first()).toBeVisible();
      await expect(col.getByText(USD2.format(p.value_if_no), { exact: true }).first()).toBeVisible();
      await expect(col.getByText(/^SIMULATED/).first()).toBeVisible();
    }

    const frames = (await (await page.request.get(FRAMES_URL)).json()) as {
      frames: { id: string; forecast_sensitive: boolean; caveat: string | null }[];
    };
    const insensitive = frames.frames.find((f) => !f.forecast_sensitive && f.caveat);
    expect(insensitive, "at least one frame carries a caveat").toBeTruthy();
    await select.selectOption(insensitive!.id);
    await expect(page.getByRole("note").getByText(insensitive!.caveat!, { exact: true })).toBeVisible();
  });

  test("no case: no frame is selected and no POST /api/decision is sent until the presenter picks", async ({ page }) => {
    const sent: Request[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url() === DECISION_URL) sent.push(r);
    });
    await page.goto("/decision/");
    await expect(page.locator("#decision-frame")).toHaveValue("");
    await expect(page.getByText("Choose a decision frame", { exact: true }).last()).toBeVisible();
    await expect(page.locator("[data-policy]")).toHaveCount(0);
    await page.waitForTimeout(500);
    expect(sent.length, "POST /api/decision before a frame is picked").toBe(0);
  });

  test("the SYNTHETIC distributor-depot case opens the supply-disruption frame", async ({ page }) => {
    await page.goto("/decision/");
    const answered = page.waitForResponse((r) => isDecisionFor(r.request(), "supply-disruption"));
    await page.locator("#decision-case").selectOption("synthetic_distributor-depot");
    await expect(page.locator("#decision-frame")).toHaveValue("supply-disruption");
    expect((await answered).status()).toBe(200);
  });

  test("no horizontal scroll at 390 px", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/decision/");
    await page.locator("#decision-frame").selectOption("supply-disruption");
    await expect(page.locator('[data-policy="HEDGE"]')).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});

test.describe("LIVE EXPLORE", () => {
  const ANALYZE_URL = `${E2E_API_BASE}/api/explore/analyze`;
  const HEALTH_URL = `${E2E_API_BASE}/api/health`;

  test("phone width: the screen fits 390 px with no horizontal scroll", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/explore/");
    await expect(page.locator("#explore-decision")).toBeVisible();
    await expect(page.getByText("Search powered by Tavily", { exact: true })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "horizontal overflow in px").toBeLessThanOrEqual(0);
  });

  test("without TAVILY_API_KEY the analysis is honestly unavailable and nothing is simulated", async ({ page }) => {
    const health = (await (await page.request.get(HEALTH_URL)).json()) as { optional_keys: { tavily_api_key: boolean } };
    test.skip(health.optional_keys.tavily_api_key, "a Tavily key is configured on the e2e API; this case needs none");

    const posts: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().startsWith(E2E_API_BASE)) posts.push(new URL(r.url()).pathname);
    });
    await page.goto("/explore/");
    await expect(page.getByText("No decision analyzed yet")).toBeVisible();
    await page.waitForTimeout(300);
    expect(posts, "nothing is sent on page load").toEqual([]);

    await page.locator("#explore-decision").fill("Should we open a third store while our loan resets?");
    const answered = page.waitForResponse((r) => r.url() === ANALYZE_URL);
    await page.getByRole("button", { name: "Research and analyze" }).click();
    const res = await answered;
    expect(res.status()).toBe(503);
    expect(((await res.json()) as { code: string }).code).toBe("LIVE_EXPLORE_UNAVAILABLE");

    await expect(page.getByText("Live Explore unavailable", { exact: true })).toBeVisible();
    await expect(page.getByText(/Set a valid TAVILY_API_KEY/)).toBeVisible();
    await expect(page.getByRole("button", { name: /Confirm inputs/ })).toHaveCount(0);
    expect(posts).toEqual(["/api/explore/analyze"]);
  });

  /**
   * A filled analysis, served by intercepting the analyze request (no Tavily key or model in e2e). TEST FIXTURE:
   * shaped like routes/explore.py `ExploreAnalysis`, with unbreakable URLs and hashes to provoke overflow. Its
   * numbers are scenario INPUTS; no result figure is asserted and Confirm is never clicked.
   */
  function filledAnalysis(fromModel: boolean) {
    const at = "2026-11-14T15:00:00Z";
    const long = (i: number) => `https://news${i}.example.test/${"averyveryverylongpathsegmentwithoutanybreaks".repeat(4)}`;
    const sources = [1, 2].map((i) => ({
      source_id: `S${i}`, title: `TEST FIXTURE headline ${"x".repeat(80)}`, url: long(i),
      snippet: `TEST FIXTURE snippet ${"y".repeat(150)}`, score: 0.5, published_at: null, published_at_raw: null,
      retrieved_at: at,
    }));
    const params = [
      { block: "rate", param: "delta_rate", unit: "Δr", integer: false, min: 0.0025, default: 0.005, max: 0.01, worse_when: "higher" },
      { block: "rate", param: "start_week", unit: "t", integer: true, min: 1, default: 1, max: 7, worse_when: "lower" },
    ];
    const suggested = params.map((p, i) => ({
      ...p,
      value: p.default,
      source: fromModel && i === 0 ? "model" : "guidance_default",
      model_value: fromModel && i === 0 ? p.default : null,
      rationale: fromModel && i === 0 ? `TEST FIXTURE rationale ${"z".repeat(120)}` : null,
      note: null,
    }));
    return {
      mode: "live_explore", label: "LIVE EXPLORE: current, not point-in-time", provider: "tavily",
      attribution: "Search powered by Tavily", decision_text: "TEST FIXTURE decision", retrieved_at: at, cached: false,
      status: "ok", status_message: null, sources,
      evidence: sources.map((s) => ({
        claim: `TEST FIXTURE claim ${"w".repeat(90)}`, source_id: s.source_id, source_url: s.url, source_title: s.title,
        snippet: s.snippet, published_at: null, published_at_raw: null, retrieved_at: at,
      })),
      rejected_claims: [{ claim: "TEST FIXTURE rejected", source_url: long(9), reason: "unknown_url", message: "not returned" }],
      suggestion: {
        label: fromModel ? "MODEL-SUGGESTED, HUMAN TO CONFIRM" : "GUIDANCE DEFAULTS, HUMAN TO CONFIRM",
        values_from_model: fromModel ? 1 : 0,
        category_id: "central-bank-rate-surprise", category_name: "Central-bank rate surprise", parameters: suggested,
        shock: { name: "fixture", rate: { delta_rate: 0.005, start_week: 1 }, demand: null, supplier: null },
        notes: fromModel ? [] : ["The model gave no usable numbers; these are guidance defaults."],
      },
      model: {
        agent_model: "ollama/fixture", model_tag: "fixture", model_digest: "d".repeat(64), temperature: 0, seed: 1,
        attempts: 1, prompt_sha256: "a".repeat(64), sources_sha256: "b".repeat(64), raw_output_sha256: "c".repeat(64),
        latency_ms: 1,
      },
      guidance: {
        provenance: "ILLUSTRATIVE", label: "ILLUSTRATIVE: modelling guidance, not forecasts", horizon_weeks: 26,
        categories: [{ id: "central-bank-rate-surprise", name: "Central-bank rate surprise", news_trigger: "t",
          timing_guidance: "g", rationale: "r", basis: "b", params }],
      },
      notes: [],
    };
  }

  test("Confirm sends exactly one simulate and one optimize; the plan shown is the API's; an edit withholds it", async ({ page }) => {
    const OPTIMIZE_URL = `${E2E_API_BASE}/api/optimize`;
    const sent: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" && (r.url() === SIMULATE_URL || r.url() === OPTIMIZE_URL)) sent.push(new URL(r.url()).pathname);
    });
    await page.route(ANALYZE_URL, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "access-control-allow-origin": "*" },
        body: JSON.stringify(filledAnalysis(true)),
      }),
    );
    await page.goto("/explore/");
    await page.locator("#explore-decision").fill("TEST FIXTURE decision");
    await page.getByRole("button", { name: "Research and analyze" }).click();
    await expect(page.locator("#explore-rate-delta_rate")).toBeVisible();

    // Every evidence card leads with its source host and the not-verified note.
    const hosts = page.getByTestId("evidence-host");
    await expect(hosts).toHaveCount(2);
    await expect(hosts.first()).toContainText("news1.example.test");
    await expect(page.getByText("Web source, not verified by FAULTLINE: check it before relying on it.")).toHaveCount(2);

    await page.waitForTimeout(300);
    expect(sent, "nothing is simulated or solved before Confirm").toEqual([]);
    await expect(page.getByTestId("explore-recovery-plan")).toHaveAttribute("data-status", "NOT AVAILABLE");

    const simDone = page.waitForResponse((r) => r.url() === SIMULATE_URL);
    const optDone = page.waitForResponse((r) => r.url() === OPTIMIZE_URL);
    await page.getByRole("button", { name: "Confirm inputs and run the engine" }).click();
    const [sim, opt] = await Promise.all([simDone, optDone]);
    expect(sim.status()).toBe(200);
    expect(opt.status()).toBe(200);
    const optBody = opt.request().postDataJSON() as { shock: unknown; protect_payroll: boolean };
    expect(optBody.shock, "the optimizer gets exactly the simulated shock").toEqual((sim.request().postDataJSON() as { shock: unknown }).shock);
    expect(optBody.protect_payroll).toBe(false);

    // The plan shown is what a direct call with the same body returns.
    const direct = (await (await page.request.post(OPTIMIZE_URL, { data: optBody })).json()) as {
      status: string;
      min_cash: number | null;
      max_feasible_cash_floor: number | null;
    };
    const plan = page.getByTestId("explore-recovery-plan");
    await expect(plan).toHaveAttribute("data-status", direct.status);
    if (direct.status === "OPTIMAL" && direct.min_cash !== null) {
      await expect(page.getByTestId("explore-plan-min-cash")).toHaveText(usd(direct.min_cash));
    } else if (direct.status === "NO FEASIBLE PLAN") {
      await expect(page.getByTestId("explore-max-feasible-floor")).toHaveText(
        direct.max_feasible_cash_floor === null ? "NOT AVAILABLE" : usdCentsFloor(direct.max_feasible_cash_floor),
      );
    }

    await page.waitForTimeout(500);
    expect(sent.sort(), "exactly one simulate and one optimize per Confirm").toEqual(["/api/optimize", "/api/simulate"]);

    // Flipping Protect payroll after Confirm withholds the plan and sends nothing until the next Confirm.
    await page.getByRole("switch", { name: "Protect payroll" }).click();
    await expect(plan).toHaveAttribute("data-status", "PENDING");
    await page.waitForTimeout(500);
    expect(sent.length, "no request after an edit").toBe(2);
  });

  for (const width of [390, 1920]) {
    for (const fromModel of [true, false]) {
      test(`filled analysis at ${width} px (${fromModel ? "model numbers" : "guidance defaults"}): no overflow, honest label`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await page.route(ANALYZE_URL, (route) =>
          route.fulfill({
            status: 200,
            contentType: "application/json",
            headers: { "access-control-allow-origin": "*" },
            body: JSON.stringify(filledAnalysis(fromModel)),
          }),
        );
        await page.goto("/explore/");
        await page.locator("#explore-decision").fill("TEST FIXTURE decision");
        await page.getByRole("button", { name: "Research and analyze" }).click();
        await expect(page.getByText("Scenario inputs · confirm before the engine runs")).toBeVisible();
        await expect(page.locator("#explore-rate-delta_rate")).toBeVisible();

        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow, "horizontal overflow in px").toBeLessThanOrEqual(0);

        const scenario = page.locator("section").filter({ hasText: "Scenario inputs · confirm before the engine runs" });
        if (fromModel) {
          await expect(scenario.locator('[data-provenance="MODEL-SUGGESTED"]')).toHaveCount(1);
          await expect(scenario.getByText(/The local model proposed 1 of these 2 numbers/)).toBeVisible();
        } else {
          await expect(scenario.locator('[data-provenance="MODEL-SUGGESTED"]')).toHaveCount(0);
          await expect(scenario.getByText(/MODEL-SUGGESTED/)).toHaveCount(0);
          await expect(scenario.getByText(/The model gave no usable numbers; these are guidance defaults\./).first()).toBeVisible();
        }
      });
    }
  }
});
