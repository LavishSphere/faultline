import { expect, test, type Page, type Route } from "@playwright/test";
import { E2E_API_BASE } from "./ports";

/**
 * "Ask the engine" live chat on /explore (#186), against the real API and the static export.
 *
 * Only the two chat routes are intercepted (the chat API is built on another branch and needs provider keys): their
 * bodies below are TEST FIXTURES shaped like the contract, never real model output. The page must render them as
 * served (reply text, tool chips, model, usage) and turn every failure into an honest message, never an answer.
 */

const MODELS_URL = `${E2E_API_BASE}/api/explore/chat/models`;
const CHAT_URL = `${E2E_API_BASE}/api/explore/chat`;
const STREAM_URL = `${CHAT_URL}/stream`;


// ---- TEST FIXTURES (chat contract shapes; never real model output) -------------------------------------------------

const fixtureModel = (id: string, provider: string, available = true, note: string | null = null, extra = {}) => ({
  id,
  label: `TEST FIXTURE ${id}`,
  provider,
  available,
  note,
  ...extra,
});

const OPEN_MODELS = Array.from({ length: 240 }, (_, i) =>
  fixtureModel(`open/fixture-${String(i).padStart(3, "0")}`, "openrouter", i !== 7, i === 7 ? "TEST FIXTURE: not served" : null, {
    context_length: 131072,
    pricing: { input_per_mtok: 0.2, output_per_mtok: 0.6 },
  }),
);

const MODELS = {
  models: [
    fixtureModel("claude-fixture", "anthropic", true, null, { context_length: 200000, pricing: { input_per_mtok: 3, output_per_mtok: 15 } }),
    fixtureModel("gpt-fixture", "openai"),
    fixtureModel("gpt-fixture-off", "openai", false, "TEST FIXTURE: OPENAI_API_KEY not set"),
    ...OPEN_MODELS,
  ],
  default: "claude-fixture",
  featured: ["claude-fixture", "gpt-fixture", "gpt-fixture-off", "open/fixture-001"],
};

function chatReply(over: Record<string, unknown> = {}) {
  return {
    status: "ok",
    provenance: "LIVE EXPLORE",
    label: "MODEL-WRITTEN, numbers from engine tools",
    model_id: "claude-fixture",
    provider: "anthropic",
    reply: "TEST FIXTURE reply.\n\n- first point\n- **second** point",
    tool_calls: [],
    usage: { input_tokens: 1234, output_tokens: 567 },
    notes: [],
    ...over,
  };
}

async function badQuarterShock(page: Page): Promise<Record<string, unknown>> {
  const res = await page.request.get(`${E2E_API_BASE}/api/scenarios`);
  const body = (await res.json()) as { items: { id: string; shock: Record<string, unknown> }[] };
  const item = body.items.find((s) => s.id === "bad-quarter");
  expect(item, "the API serves the bad-quarter scenario").toBeTruthy();
  return item!.shock;
}

async function mockModels(page: Page, body: unknown = MODELS, status = 200) {
  await page.route(MODELS_URL, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));
}

/** Fulfil POST /api/explore/chat with `respond(body)`; every request body is recorded. */
async function mockChat(page: Page, respond: (req: { model_id: string; messages: unknown[] }) => { status?: number; body: unknown; delayMs?: number }) {
  const bodies: { model_id: string; messages: { role: string; content: string }[] }[] = [];
  // These specs exercise the one-piece reply: the stream route (#222) answers 404, so the page falls back to it.
  await page.route(STREAM_URL, (route) => route.fulfill({ status: 404, contentType: "application/json", body: "{}" }));
  await page.route(CHAT_URL, async (route: Route) => {
    const req = route.request().postDataJSON() as { model_id: string; messages: { role: string; content: string }[] };
    bodies.push(req);
    const out = respond(req);
    if (out.delayMs) await new Promise((r) => setTimeout(r, out.delayMs));
    await route.fulfill({ status: out.status ?? 200, contentType: "application/json", body: JSON.stringify(out.body) });
  });
  return bodies;
}

async function ask(page: Page, text: string) {
  const input = page.locator("#chat-input");
  await input.fill(text);
  await input.press("Enter");
}

test.describe("Ask the engine: models", () => {
  test("models load grouped by provider, the default is selected, and an unavailable model cannot be selected", async ({ page }) => {
    await mockModels(page);
    await page.goto("/explore/");
    // The picker starts collapsed to one line naming the default; a click opens the galaxy.
    const toggle = page.getByTestId("chat-model-toggle");
    await expect(page.getByTestId("chat-model-current")).toHaveText("TEST FIXTURE claude-fixture");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    const picker = page.getByTestId("chat-model-picker");
    await expect(picker).toBeHidden();
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(picker).toBeVisible();
    // Provider order: open models via OpenRouter, OpenAI (direct), Anthropic Claude (direct).
    const groups = picker.locator('[data-testid^="chat-provider-"]');
    await expect(groups).toHaveCount(3);
    expect(await groups.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")))).toEqual([
      "chat-provider-openrouter",
      "chat-provider-openai",
      "chat-provider-anthropic",
    ]);
    await expect(groups.nth(0).locator(".kicker")).toHaveText("Via OpenRouter");
    await expect(groups.nth(1).locator(".kicker")).toHaveText("OpenAI (direct)");
    await expect(groups.nth(2).locator(".kicker")).toHaveText("Anthropic Claude (direct)");

    await expect(page.getByRole("radio", { name: /TEST FIXTURE claude-fixture/ })).toBeChecked();
    await expect(page.getByTestId("chat-selected-model")).toContainText("TEST FIXTURE claude-fixture");
    await expect(page.getByTestId("chat-selected-model")).toContainText("200K ctx");
    await expect(page.getByTestId("chat-selected-model")).toContainText("$3.00 in · $15.00 out /M tok");

    const off = page.getByRole("radio", { name: /TEST FIXTURE gpt-fixture-off/ });
    await expect(off).toBeDisabled();
    await expect(page.locator('[data-model="gpt-fixture-off"]')).toContainText("OPENAI_API_KEY not set");
    await page.locator('[data-model="gpt-fixture-off"]').click({ force: true });
    await expect(off).not.toBeChecked();
    await expect(page.getByRole("radio", { name: /TEST FIXTURE claude-fixture/ })).toBeChecked();

    await page.getByRole("radio", { name: /TEST FIXTURE gpt-fixture$/ }).check({ force: true });
    await expect(page.getByTestId("chat-selected-model")).toContainText("TEST FIXTURE gpt-fixture");
  });
});

test.describe("Ask the engine: conversation", () => {
  test("sending shows the waiting state with elapsed time, then the reply with tool chips, badges, model and usage", async ({ page }) => {
    await mockModels(page);
    const shock = await badQuarterShock(page);
    const calls = [
      { name: "simulate", input: { scenario_id: "bad-quarter", shock }, result_status: "ok", result_summary: "TEST FIXTURE summary A", provenance: "SIMULATED" },
      { name: "optimize", input: { scenario_id: "bad-quarter", shock, protect_payroll: true }, result_status: "ok", result_summary: { fixture: "TEST FIXTURE summary B" }, provenance: "SIMULATED" },
      { name: "decision", input: { frame_id: "supply-disruption", p_yes: 0.4 }, result_status: "ok", result_summary: null, provenance: "SIMULATED" },
    ];
    const bodies = await mockChat(page, () => ({ body: chatReply({ tool_calls: calls }), delayMs: 1500 }));
    await page.goto("/explore/");
    await expect(page.getByTestId("chat-model-current")).toHaveText("TEST FIXTURE claude-fixture");

    const enginePosts: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().startsWith(E2E_API_BASE) && r.url() !== CHAT_URL && r.url() !== STREAM_URL) enginePosts.push(r.url());
    });
    await ask(page, "What if the supplier goes bust and we protect payroll?");
    const waitingCard = page.getByTestId("chat-waiting");
    await expect(waitingCard).toBeVisible();
    await expect(waitingCard).toContainText("Waiting for TEST FIXTURE claude-fixture");
    await expect(page.getByTestId("chat-elapsed")).toHaveText(/^\d+\.\d s$/);

    const answer = page.getByTestId("chat-answer");
    await expect(answer).toBeVisible();
    await expect(waitingCard).toHaveCount(0);
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toEqual({
      model_id: "claude-fixture",
      messages: [{ role: "user", content: "What if the supplier goes bust and we protect payroll?" }],
    });

    await expect(answer.getByTestId("chat-reply")).toContainText("TEST FIXTURE reply.");
    await expect(answer.locator("strong")).toHaveText("second");
    await expect(answer.locator('[data-provenance="LIVE EXPLORE"]')).toBeVisible();
    await expect(answer.locator('[data-provenance="MODEL-WRITTEN"]')).toBeVisible();
    await expect(answer.getByTestId("chat-model-id")).toHaveText("claude-fixture");
    await expect(answer.getByTestId("chat-model-line")).toContainText("Anthropic Claude (direct)");
    await expect(answer.getByTestId("chat-usage")).toHaveText("1,234 in · 567 out tokens");

    const chips = answer.getByTestId("chat-tool-chip");
    await expect(chips).toHaveCount(3);
    expect(await chips.evaluateAll((els) => els.map((e) => e.getAttribute("data-tool")))).toEqual(["simulate", "optimize", "decision"]);
    await expect(answer.getByText("steps the model took")).toBeVisible();
    await chips.nth(1).click();
    const detail = answer.getByTestId("chat-tool-detail");
    await expect(detail).toContainText('"protect_payroll": true');
    await expect(detail).toContainText(`"fixture": "TEST FIXTURE summary B"`);
    await chips.nth(2).click();
    await expect(detail).toContainText("Not available");

    // The browser recomputes nothing: the only engine calls on the reply's behalf are the universe's re-runs of the
    // exact simulate / optimize inputs (stage 2, #197; covered in detail in e2e/chat-cockpit.spec.ts).
    await expect(page.getByTestId("universe-body")).toHaveAttribute("data-status", "ok");
    expect([...new Set(enginePosts)].sort()).toEqual([`${E2E_API_BASE}/api/optimize`, `${E2E_API_BASE}/api/simulate`]);
  });

  test("the second question carries the conversation so far; Clear chat empties it", async ({ page }) => {
    await mockModels(page);
    let n = 0;
    const bodies = await mockChat(page, () => ({ body: chatReply({ reply: `TEST FIXTURE reply ${++n}` }) }));
    await page.goto("/explore/");
    await expect(page.getByTestId("chat-model-current")).toHaveText("TEST FIXTURE claude-fixture");
    await ask(page, "first question");
    await expect(page.getByTestId("chat-answer")).toHaveCount(1);
    // Shift+Enter inserts a newline instead of sending.
    await page.locator("#chat-input").fill("second");
    await page.locator("#chat-input").press("Shift+Enter");
    await page.locator("#chat-input").pressSequentially("line");
    expect(bodies).toHaveLength(1);
    await page.locator("#chat-input").press("Enter");
    await expect(page.getByTestId("chat-answer")).toHaveCount(2);
    expect(bodies[1]!.messages).toEqual([
      { role: "user", content: "first question" },
      { role: "assistant", content: "TEST FIXTURE reply 1" },
      { role: "user", content: "second\nline" },
    ]);
    await page.getByRole("button", { name: "Clear chat" }).click();
    await expect(page.getByTestId("chat-answer")).toHaveCount(0);
    await expect(page.getByTestId("chat-starter")).toHaveCount(4);
  });
});

test.describe("Ask the engine: honest failures", () => {
  const cases = [
    { status: 429, code: "RATE_LIMITED", text: "Limit reached, try again in a few minutes." },
    { status: 503, code: "BUSY", text: "The engine chat is busy. Try again in a moment." },
    { status: 503, code: "LIVE_EXPLORE_UNAVAILABLE", text: "Live chat is not available on this server." },
    { status: 502, code: "UPSTREAM_ERROR", text: "The model provider returned an error." },
    { status: 403, code: "ADMIN_REQUIRED", text: "Chat is disabled on the public demo right now." },
    { status: 401, code: "ADMIN_REQUIRED", text: "Chat is disabled on the public demo right now." },
    { status: 503, code: "PAUSED", text: "The team is presenting right now. Public chat is paused by the presenter." },
  ];
  for (const c of cases) {
    test(`HTTP ${c.status} ${c.code} shows an honest message and no answer`, async ({ page }) => {
      await mockModels(page);
      await mockChat(page, () => ({ status: c.status, body: { code: c.code, message: "TEST FIXTURE server message" } }));
      await page.goto("/explore/");
      await expect(page.getByTestId("chat-model-current")).toHaveText("TEST FIXTURE claude-fixture");
      await ask(page, "hello");
      const failure = page.getByTestId("chat-failure");
      await expect(failure).toContainText(c.text);
      await expect(page.getByTestId("chat-answer")).toHaveCount(0);
      await expect(page.getByTestId("chat-reply")).toHaveCount(0);
    });
  }

  test("status error shows the API's note and one click switches to a featured model", async ({ page }) => {
    await mockModels(page);
    const bodies = await mockChat(page, (req) =>
      req.model_id === "claude-fixture"
        ? { body: chatReply({ status: "error", reply: "", notes: ["TEST FIXTURE: the model did not call the tools correctly."] }) }
        : { body: chatReply({ model_id: req.model_id, provider: "openai", reply: "TEST FIXTURE second model reply" }) },
    );
    await page.goto("/explore/");
    await expect(page.getByTestId("chat-model-current")).toHaveText("TEST FIXTURE claude-fixture");
    await ask(page, "hello");
    const answer = page.getByTestId("chat-answer");
    await expect(answer).toHaveAttribute("data-status", "error");
    await expect(answer).toContainText("TEST FIXTURE: the model did not call the tools correctly.");
    await expect(answer.getByTestId("chat-reply")).toHaveCount(0);
    const switchTo = answer.getByTestId("chat-switch-model").filter({ hasText: "TEST FIXTURE gpt-fixture" });
    await expect(answer.getByTestId("chat-switch-model").filter({ hasText: "gpt-fixture-off" })).toHaveCount(0);
    await switchTo.click();
    await expect(page.getByTestId("chat-answer")).toHaveAttribute("data-status", "ok");
    await expect(page.getByTestId("chat-reply")).toContainText("TEST FIXTURE second model reply");
    expect(bodies[1]).toEqual({ model_id: "gpt-fixture", messages: [{ role: "user", content: "hello" }] });
    await expect(page.getByTestId("chat-model-current")).toHaveText("TEST FIXTURE gpt-fixture");
  });

  test("a reply with an unknown status is refused, not shown", async ({ page }) => {
    await mockModels(page);
    await mockChat(page, () => ({ body: chatReply({ status: "streaming" }) }));
    await page.goto("/explore/");
    await expect(page.getByTestId("chat-model-current")).toHaveText("TEST FIXTURE claude-fixture");
    await ask(page, "hello");
    await expect(page.getByTestId("chat-failure")).toHaveAttribute("data-kind", "malformed");
    await expect(page.getByTestId("chat-reply")).toHaveCount(0);
  });

  test("the real API with no provider keys: every model is shown unavailable and nothing can be sent", async ({ page }) => {
    // Since #193 the e2e API serves the chat catalogue; CI configures no provider key, so no model is available.
    await page.goto("/explore/");
    await page.getByTestId("chat-model-toggle").click();
    const pills = page.getByTestId("chat-model-pill");
    await expect(pills.first()).toBeVisible();
    expect(await pills.evaluateAll((els) => els.map((e) => e.getAttribute("data-available")))).not.toContain("true");
    await expect(page.getByTestId("chat-selected-model")).toContainText("No model selected");
    await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeDisabled();
  });

  test("when the models route fails the picker says NOT AVAILABLE", async ({ page }) => {
    await mockModels(page, { code: "TEST", message: "TEST FIXTURE down" }, 500);
    await page.goto("/explore/");
    await expect(page.getByTestId("chat-models-failed")).toContainText("Models NOT AVAILABLE");
    await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeDisabled();
  });
});

test.describe("Ask the engine: phone width", () => {
  test("a long reply and its tool chips wrap with no horizontal scroll at 390 px", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockModels(page);
    const long = `TEST FIXTURE ${"verylongunbrokenwordwithoutanyspaces".repeat(12)} and ${"word ".repeat(400)}`;
    await mockChat(page, () => ({
      body: chatReply({
        reply: long,
        tool_calls: [{ name: "simulate_with_a_very_long_tool_name_for_wrapping", input: { shock: {} }, result_status: "ok", result_summary: "y".repeat(500), provenance: "SIMULATED" }],
      }),
    }));
    await page.goto("/explore/");
    await expect(page.getByTestId("chat-model-current")).toHaveText("TEST FIXTURE claude-fixture");
    await ask(page, "x".repeat(300));
    await expect(page.getByTestId("chat-reply")).toBeVisible();
    await page.getByTestId("chat-tool-chip").click();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, "horizontal overflow in px").toBeLessThanOrEqual(0);
  });
});
