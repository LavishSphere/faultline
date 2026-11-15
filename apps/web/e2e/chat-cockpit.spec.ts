import { expect, test, type Page, type Route } from "@playwright/test";
import { E2E_API_BASE } from "./ports";

/**
 * Mission-control cockpit on /explore (#197): the business universe, the model race, the paused state.
 *
 * The two chat routes are intercepted (they need provider keys): their bodies are TEST FIXTURES shaped like the
 * contract, never real model output. The engine routes are the REAL API: the universe must POST each tool call's
 * exact input to /api/simulate and /api/optimize and show the engine's own answer, equal to a direct call.
 */

const MODELS_URL = `${E2E_API_BASE}/api/explore/chat/models`;
const CHAT_URL = `${E2E_API_BASE}/api/explore/chat`;
const STATUS_URL = `${E2E_API_BASE}/api/explore/chat/status`;
const SIM_URL = `${E2E_API_BASE}/api/simulate`;
const OPT_URL = `${E2E_API_BASE}/api/optimize`;

// ---- TEST FIXTURES (chat contract shapes; never real model output) -------------------------------------------------

const MODELS = {
  models: [
    { id: "claude-fixture", label: "TEST FIXTURE claude-fixture", provider: "anthropic", available: true, note: null, context_length: 200000, pricing: { input_per_mtok: 3, output_per_mtok: 15 } },
    { id: "open-fixture", label: "TEST FIXTURE open-fixture", provider: "openrouter", available: true, note: null, context_length: 131072, pricing: null },
    { id: "gpt-fixture-off", label: "TEST FIXTURE gpt-fixture-off", provider: "openai", available: false, note: "TEST FIXTURE: OPENAI_API_KEY not set", context_length: null, pricing: null },
    ...Array.from({ length: 30 }, (_, i) => ({
      id: `open/fixture-${String(i).padStart(2, "0")}`,
      label: `TEST FIXTURE open ${String(i).padStart(2, "0")}`,
      provider: "openrouter",
      available: true,
      note: null,
      context_length: 32768,
      pricing: { input_per_mtok: 0.1, output_per_mtok: 0.2 },
    })),
  ],
  default: "claude-fixture",
  featured: ["open-fixture", "gpt-fixture-off", "claude-fixture"],
};

function chatReply(over: Record<string, unknown> = {}) {
  return {
    status: "ok",
    provenance: "LIVE EXPLORE",
    label: "MODEL-WRITTEN, numbers from engine tools",
    model_id: "claude-fixture",
    provider: "anthropic",
    reply: "TEST FIXTURE reply.",
    tool_calls: [],
    usage: { input_tokens: 1234, output_tokens: 567 },
    notes: [],
    ...over,
  };
}

type Scenario = { id: string; shock: Record<string, unknown> };

async function scenarios(page: Page): Promise<Scenario[]> {
  const res = await page.request.get(`${E2E_API_BASE}/api/scenarios`);
  return ((await res.json()) as { items: Scenario[] }).items;
}

function engineCalls(s: Scenario, protect: boolean) {
  return [
    { name: "simulate", input: { scenario_id: s.id, shock: s.shock }, result_status: "ok", result_summary: { fixture: "TEST FIXTURE" }, provenance: "SIMULATED" },
    { name: "optimize", input: { scenario_id: s.id, shock: s.shock, protect_payroll: protect }, result_status: "ok", result_summary: { fixture: "TEST FIXTURE" }, provenance: "SIMULATED" },
  ];
}

async function mockModels(page: Page) {
  await page.route(MODELS_URL, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MODELS) }));
}

type ChatBody = { model_id: string; messages: { role: string; content: string }[] };

async function mockChat(page: Page, respond: (req: ChatBody, n: number) => { status?: number; body: unknown; delayMs?: number }) {
  const bodies: ChatBody[] = [];
  await page.route(CHAT_URL, async (route: Route) => {
    const req = route.request().postDataJSON() as ChatBody;
    bodies.push(req);
    const out = respond(req, bodies.length);
    if (out.delayMs) await new Promise((r) => setTimeout(r, out.delayMs));
    await route.fulfill({ status: out.status ?? 200, contentType: "application/json", body: JSON.stringify(out.body) });
  });
  return bodies;
}

/** Every POST body the page sends to an engine route, in order. */
function recordEngine(page: Page) {
  const sent: { url: string; body: unknown }[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && (r.url() === SIM_URL || r.url() === OPT_URL)) sent.push({ url: r.url(), body: r.postDataJSON() });
  });
  return sent;
}

async function open(page: Page) {
  await page.goto("/explore/");
  await expect(page.getByRole("radio", { name: /TEST FIXTURE claude-fixture/ })).toBeChecked();
}

async function ask(page: Page, text: string) {
  await page.locator("#chat-input").fill(text);
  await page.locator("#chat-input").press("Enter");
}

const WHOLE = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

test.describe("Cockpit: the business universe", () => {
  test("re-runs the exact tool inputs on the real engine; its values equal a direct /api/simulate call", async ({ page }) => {
    await mockModels(page);
    const s = (await scenarios(page)).find((x) => x.id === "bad-quarter")!;
    const calls = engineCalls(s, true);
    await mockChat(page, () => ({ body: chatReply({ tool_calls: calls }) }));
    const sent = recordEngine(page);
    await open(page);

    await ask(page, "What if the supplier goes bust and we protect payroll?");
    const body = page.getByTestId("universe-body");
    await expect(body).toHaveAttribute("data-status", "ok");

    // The browser POSTed each tool call's input exactly, and nothing else on the reply's behalf.
    const nonBaseline = sent.filter((x) => JSON.stringify(x.body) !== JSON.stringify({ shock: {} }));
    expect(nonBaseline).toHaveLength(2);
    expect(nonBaseline).toEqual(
      expect.arrayContaining([
        { url: SIM_URL, body: calls[0]!.input },
        { url: OPT_URL, body: calls[1]!.input },
      ]),
    );

    // The same input sent directly to the engine gives exactly the values the universe shows.
    const direct = (await (await page.request.post(SIM_URL, { data: calls[0]!.input })).json()) as {
      result: { min_cash: number };
      min_cash_floor: number;
      first_week_below_floor: number | null;
    };
    await expect(body).toHaveAttribute("data-engine-min-cash", String(direct.result.min_cash));
    await expect(body).toHaveAttribute("data-engine-first-below", String(direct.first_week_below_floor ?? "none"));
    await expect(page.getByTestId("universe-readouts")).toContainText(WHOLE.format(Math.round(direct.result.min_cash)));
    await expect(page.getByTestId("universe-floor")).toHaveText(WHOLE.format(direct.min_cash_floor));

    const directOpt = (await (await page.request.post(OPT_URL, { data: calls[1]!.input })).json()) as { status: string };
    await expect(page.getByTestId("universe-plan")).toHaveAttribute("data-status", directOpt.status);
    // protect_payroll: true in the optimize input → the payroll shield locks on the network.
    await expect(page.getByTestId("payroll-shield")).toBeVisible();
    await expect(page.getByTestId("universe")).toContainText("Engine re-ran this exact input");
    await expect(page.getByTestId("universe").locator('[data-provenance="SIMULATED"]').first()).toBeVisible();
    await expect(page.getByTestId("universe").locator('[data-provenance="SYNTHETIC"]').first()).toBeVisible();

    // The flight path names the steps from the tool names and inputs.
    await expect(page.getByTestId("chat-flight-narrative")).toContainText("simulate");
    await expect(page.getByTestId("chat-flight-narrative")).toContainText("with payroll protected");
    // The test fixture summary has no comparable fields, so the agreement check says NOT AVAILABLE, not "same".
    await expect(page.getByTestId("engine-agreement")).toHaveAttribute("data-verdict", "na");
  });

  test("clicking an earlier answer replays its engine state on the universe", async ({ page }) => {
    await mockModels(page);
    const all = await scenarios(page);
    const first = all.find((x) => x.id === "supplier-outage-3wk")!;
    const second = all.find((x) => x.id === "rate-plus-200bp")!;
    await mockChat(page, (_req, n) => ({ body: chatReply({ tool_calls: engineCalls(n === 1 ? first : second, n === 1) }) }));
    await open(page);
    const minOf = async (s: Scenario) =>
      String(((await (await page.request.post(SIM_URL, { data: { scenario_id: s.id, shock: s.shock } })).json()) as { result: { min_cash: number } }).result.min_cash);

    await ask(page, "first");
    await expect(page.getByTestId("universe-body")).toHaveAttribute("data-engine-min-cash", await minOf(first));
    await expect(page.getByTestId("payroll-shield")).toBeVisible();
    await ask(page, "second");
    await expect(page.getByTestId("chat-answer")).toHaveCount(2);
    await expect(page.getByTestId("universe-body")).toHaveAttribute("data-engine-min-cash", await minOf(second));
    await expect(page.getByTestId("payroll-shield")).toHaveCount(0);
    await expect(page.getByTestId("chat-answer").nth(1)).toHaveAttribute("data-on-universe", "true");

    await page.getByTestId("chat-replay").first().click();
    await expect(page.getByTestId("universe-body")).toHaveAttribute("data-engine-min-cash", await minOf(first));
    await expect(page.getByTestId("chat-answer").nth(0)).toHaveAttribute("data-on-universe", "true");
    await expect(page.getByTestId("payroll-shield")).toBeVisible();
    await expect(page.getByTestId("universe-caption")).toContainText("Answer 1");
  });

  test("a failed engine re-run shows NOT AVAILABLE, never a guess", async ({ page }) => {
    await mockModels(page);
    const s = (await scenarios(page)).find((x) => x.id === "bad-quarter")!;
    await mockChat(page, () => ({ body: chatReply({ tool_calls: engineCalls(s, true).slice(0, 1) }) }));
    await page.route(SIM_URL, async (route) => {
      const b = route.request().postDataJSON() as { scenario_id?: string };
      if (b.scenario_id) await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ code: "TEST", message: "TEST FIXTURE engine down" }) });
      else await route.continue();
    });
    await open(page);
    await ask(page, "hello");
    await expect(page.getByTestId("universe-failed")).toContainText("Not available");
    await expect(page.getByTestId("universe-body")).not.toHaveAttribute("data-engine-min-cash", /.+/);
    await expect(page.getByTestId("universe-readouts")).toContainText("Not available");
  });
});

test.describe("Cockpit: evidence the model fetched", () => {
  test("web_search results render as source cards and market results as quote cards, each labelled", async ({ page }) => {
    await mockModels(page);
    const calls = [
      {
        name: "web_search",
        input: { query: "TEST FIXTURE meta ceo" },
        result_status: "ok",
        result_summary: {
          provenance: "REAL (web, retrieved 2026-11-14T18:00:00Z)",
          label: "LIVE EXPLORE: current, not point-in-time",
          attribution: "Search powered by Tavily",
          note: "TEST FIXTURE note: current web pages, not point-in-time evidence",
          retrieved_at: "2026-11-14T18:00:00Z",
          query: "TEST FIXTURE meta ceo",
          results: [
            { title: "TEST FIXTURE source one", url: "https://www.example.com/a", domain: "example.com", published_date: "2026-11-10", snippet: "TEST FIXTURE snippet" },
            { title: "TEST FIXTURE unsafe link", url: "javascript:alert(1)", domain: null, published_date: null, snippet: null },
          ],
        },
        provenance: "LIVE EXPLORE",
      },
      {
        name: "prediction_markets",
        input: { query: "TEST FIXTURE" },
        result_status: "ok",
        result_summary: {
          provenance: "LIVE MARKET QUOTE",
          fetched_at: "2026-11-14T18:01:00Z",
          markets: [
            { venue: "kalshi", question: "TEST FIXTURE market A?", price: 0.62, volume: 15000, url: "https://kalshi.example/a", market_id: "TEST-A" },
            { venue: "polymarket", question: "TEST FIXTURE market B?", price: null, volume: null, url: null, market_id: "TEST-B" },
          ],
        },
        provenance: "LIVE MARKET QUOTE",
      },
    ];
    await mockChat(page, () => ({ body: chatReply({ tool_calls: calls }) }));
    await open(page);
    await ask(page, "Should Meta keep Zuckerberg as CEO?");
    const answer = page.getByTestId("chat-answer");
    const sources = answer.getByTestId("chat-source-card");
    await expect(sources).toHaveCount(2);
    await expect(sources.nth(0).getByTestId("source-domain")).toHaveText("example.com");
    await expect(sources.nth(0).getByTestId("source-date")).toHaveText("Nov 10, 2026");
    await expect(sources.nth(0).getByTestId("source-link")).toHaveAttribute("href", "https://www.example.com/a");
    // The server's provenance string is shown as-is; the label, Tavily credit and note sit with the cards.
    await expect(sources.nth(0).locator('[data-provenance="REAL (web, retrieved 2026-11-14T18:00:00Z)"]')).toBeVisible();
    await expect(answer.getByTestId("source-label")).toHaveText("LIVE EXPLORE: current, not point-in-time");
    await expect(answer.getByTestId("source-credit")).toContainText("Search powered by Tavily");
    await expect(answer.getByTestId("source-credit")).toContainText("TEST FIXTURE note");
    // A non-http(s) URL never becomes a link; missing fields say so.
    await expect(sources.nth(1).getByTestId("source-link")).toHaveCount(0);
    await expect(sources.nth(1)).toContainText("date not available");

    const quotes = answer.getByTestId("chat-quote-card");
    await expect(quotes).toHaveCount(2);
    await expect(quotes.nth(0).getByTestId("quote-price")).toHaveText("0.62");
    await expect(quotes.nth(0).getByTestId("quote-price-unit")).toHaveText("units as served");
    await expect(quotes.nth(0).getByTestId("quote-volume")).toHaveText("15,000");
    await expect(quotes.nth(0)).toContainText("market-implied (price-derived)");
    await expect(quotes.nth(0).locator('[data-provenance="LIVE MARKET QUOTE"]')).toBeVisible();
    await expect(quotes.nth(1).getByTestId("quote-price")).toHaveText(/not available/i);
    await expect(answer.getByTestId("chat-market-quotes")).toContainText("fetched Nov 14");
    await expect(page.getByTestId("chat-flight-narrative")).toContainText("checked prediction markets");
  });
});

test.describe("Cockpit: model race", () => {
  test("sends exactly two requests in parallel and renders both side by side with facts, no winner", async ({ page }) => {
    await mockModels(page);
    const s = (await scenarios(page)).find((x) => x.id === "bad-quarter")!;
    // Lane A's simulate summary carries the engine's own figures (to the cent); lane B's is off by $1,000.
    const direct = (await (await page.request.post(SIM_URL, { data: { scenario_id: s.id, shock: s.shock } })).json()) as {
      result: { min_cash: number };
      first_week_below_floor: number | null;
    };
    const cents = Math.round(direct.result.min_cash * 100) / 100;
    const withSummary = (calls: ReturnType<typeof engineCalls>, min: number) =>
      calls.map((c, i) => (i === 0 ? { ...c, result_summary: { min_cash: min, first_week_below_floor: direct.first_week_below_floor } } : c));
    const bodies = await mockChat(page, (req) =>
      req.model_id === "claude-fixture"
        ? { body: chatReply({ tool_calls: withSummary(engineCalls(s, true), cents) }), delayMs: 900 }
        : {
            body: chatReply({
              model_id: req.model_id,
              provider: "openrouter",
              reply: "TEST FIXTURE open reply",
              tool_calls: withSummary(engineCalls(s, false).slice(0, 1), cents + 1000),
              usage: null,
            }),
            delayMs: 300,
          },
    );
    await open(page);
    await page.getByTestId("chat-race-toggle").click();
    await expect(page.getByTestId("chat-race-toggle")).toHaveAttribute("aria-checked", "true");
    await expect(page.getByTestId("chat-race-setup")).toContainText("TEST FIXTURE open-fixture");
    await ask(page, "race question");

    // Both lanes wait at once, each with its own timer.
    await expect(page.getByTestId("race-elapsed")).toHaveCount(2);
    const race = page.getByTestId("chat-race");
    await expect(race.getByTestId("chat-answer")).toHaveCount(2);
    expect(bodies).toHaveLength(2);
    expect(bodies.map((b) => b.model_id).sort()).toEqual(["claude-fixture", "open-fixture"]);
    expect(bodies[0]!.messages).toEqual([{ role: "user", content: "race question" }]);
    expect(bodies[1]!.messages).toEqual([{ role: "user", content: "race question" }]);

    const facts = race.getByTestId("chat-race-facts");
    await expect(facts).toHaveCount(2);
    // usage × catalogue price: (1234 × $3 + 567 × $15) / 10^6 = $0.012207 → "$0.0122"; no usage → NOT AVAILABLE.
    await expect(race.getByTestId("chat-answer").nth(0).getByTestId("chat-cost")).toHaveText("$0.0122");
    await expect(race.getByTestId("chat-answer").nth(1).getByTestId("chat-cost")).toHaveText("NOT AVAILABLE");
    await expect(race.getByTestId("chat-answer").nth(0).getByTestId("race-steps")).toHaveText("2");
    await expect(race.getByTestId("chat-answer").nth(1).getByTestId("race-steps")).toHaveText("1");
    // Whether each model's numbers match the engine: a fact per lane, nobody ranked.
    await expect(race.getByTestId("chat-answer").nth(0).getByTestId("engine-agreement")).toHaveAttribute("data-verdict", "same");
    await expect(race.getByTestId("chat-answer").nth(1).getByTestId("engine-agreement")).toHaveAttribute("data-verdict", "differs");

    // The universe shows each model's engine run, same engine, one tab each.
    const tabs = page.getByTestId("universe-tab");
    await expect(tabs).toHaveCount(2);
    await expect(page.getByTestId("payroll-shield")).toBeVisible();
    await tabs.nth(1).click();
    await expect(page.getByTestId("universe-body")).toHaveAttribute("data-status", "ok");
    await expect(page.getByTestId("payroll-shield")).toHaveCount(0);

    const text = (await page.getByTestId("chat-panel").innerText()).toLowerCase();
    expect(text).not.toMatch(/\bwinner\b|\bbeats\b|real-time/);
  });
});

test.describe("Cockpit: states", () => {
  test("reduced motion renders the final state with no running animation", async ({ page }) => {
    await mockModels(page);
    const s = (await scenarios(page)).find((x) => x.id === "bad-quarter")!;
    await mockChat(page, () => ({ body: chatReply({ tool_calls: engineCalls(s, true) }) }));
    await open(page);
    await ask(page, "hello");
    await expect(page.getByTestId("universe-body")).toHaveAttribute("data-status", "ok");
    await expect(page.getByTestId("chat-tool-chip")).toHaveCount(2);
    // Every node is settled at once and shows its value; nothing on the panel is animating.
    await expect(page.locator('[data-testid^="graph-node-"][data-wave="running"]')).toHaveCount(0);
    await expect(page.getByTestId("graph-value-Cash")).toBeVisible();
    const animating = await page.getByTestId("chat-panel").evaluate((root) =>
      [root, ...root.querySelectorAll("*")].filter((el) => {
        const cs = getComputedStyle(el);
        const pseudo = getComputedStyle(el, "::before");
        return (cs.animationName !== "none" && cs.animationName !== "") || (pseudo.animationName !== "none" && pseudo.animationName !== "");
      }).length,
    );
    expect(animating, "elements with a running CSS animation under reduced motion").toBe(0);
  });

  test("at 390 px the universe stacks under the chat with no horizontal scroll", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockModels(page);
    const s = (await scenarios(page)).find((x) => x.id === "bad-quarter")!;
    await mockChat(page, () => ({ body: chatReply({ tool_calls: engineCalls(s, true), reply: `TEST FIXTURE ${"word ".repeat(200)}` }) }));
    await open(page);
    await page.getByTestId("chat-race-toggle").click();
    await ask(page, "hello");
    await expect(page.getByTestId("universe-body")).toHaveAttribute("data-status", "ok");
    await page.getByTestId("chat-tool-chip").first().click();
    const composer = await page.getByTestId("chat-composer").boundingBox();
    const universe = await page.getByTestId("universe").boundingBox();
    expect(universe!.y).toBeGreaterThan(composer!.y);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, "horizontal overflow in px").toBeLessThanOrEqual(0);
  });

  test("paused by the presenter: the banner shows, and a send that gets PAUSED says so", async ({ page }) => {
    await mockModels(page);
    await page.route(STATUS_URL, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ paused: true, until: null, note: "TEST FIXTURE" }) }),
    );
    await mockChat(page, () => ({ status: 503, body: { code: "PAUSED", message: "TEST FIXTURE paused" } }));
    await open(page);
    await expect(page.getByTestId("chat-paused")).toContainText("The team is presenting right now");
    await ask(page, "hello");
    await expect(page.getByTestId("chat-failure")).toHaveAttribute("data-kind", "paused");
    await expect(page.getByTestId("chat-failure")).toContainText("The team is presenting right now");
    await expect(page.getByTestId("chat-answer")).toHaveCount(0);
  });

  test("the paused banner clears once a send succeeds; an error reply carries no MODEL-WRITTEN badge", async ({ page }) => {
    await mockModels(page);
    let paused = true;
    await page.route(STATUS_URL, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ paused, until: null, note: "TEST FIXTURE" }) }),
    );
    await mockChat(page, (_req, n) =>
      n === 1
        ? { body: chatReply({ status: "error", reply: "", notes: ["TEST FIXTURE: no usable answer"] }) }
        : { body: chatReply() },
    );
    await open(page);
    await expect(page.getByTestId("chat-paused")).toBeVisible();
    await expect(page.getByTestId("chat-paused-until")).not.toContainText("few minutes");
    paused = false;
    await ask(page, "first");
    const err = page.getByTestId("chat-answer").first();
    await expect(err).toHaveAttribute("data-status", "error");
    await expect(err.locator('[data-provenance="MODEL-WRITTEN"]')).toHaveCount(0);
    await expect(page.getByTestId("chat-paused")).toHaveCount(0);
    await ask(page, "second");
    await expect(page.getByTestId("chat-answer").nth(1).locator('[data-provenance="MODEL-WRITTEN"]')).toBeVisible();
  });

  test("⌘K opens the full catalogue; search and Enter pick a model", async ({ page }) => {
    await mockModels(page);
    await open(page);
    await page.keyboard.press("ControlOrMeta+k");
    const palette = page.getByTestId("chat-palette");
    await expect(palette).toBeVisible();
    await page.getByTestId("chat-palette-search").fill("open 17");
    await expect(palette.getByTestId("chat-palette-item")).toHaveCount(1);
    await page.keyboard.press("Enter");
    await expect(palette).toHaveCount(0);
    await expect(page.getByTestId("chat-selected-model")).toContainText("TEST FIXTURE open 17");
  });
});
