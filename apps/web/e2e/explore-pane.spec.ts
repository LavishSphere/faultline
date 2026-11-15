import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { E2E_API_BASE } from "./ports";

/**
 * Explore right pane and starters (#220), against the static export. Only the chat routes (and, in one test, the
 * starters route) are intercepted. The Monte Carlo results are engine responses RECORDED in e2e/fixtures; the chat
 * reply and the news starters are TEST FIXTURES, never real model output or real news.
 */

const MODELS_URL = `${E2E_API_BASE}/api/explore/chat/models`;
const CHAT_URL = `${E2E_API_BASE}/api/explore/chat`;
const STARTERS_URL = `${E2E_API_BASE}/api/explore/chat/starters`;

const fixture = (name: string) =>
  JSON.parse(readFileSync(resolve(__dirname, "fixtures", `${name}.fixture.json`), "utf8")).result_summary as Record<string, unknown>;

const MODELS = {
  models: [{ id: "claude-fixture", label: "TEST FIXTURE claude-fixture", provider: "anthropic", available: true, note: null }],
  default: "claude-fixture",
  featured: ["claude-fixture"],
};

const reply = (calls: unknown[]) => ({
  status: "ok",
  provenance: "LIVE EXPLORE",
  label: "MODEL-WRITTEN, numbers from engine tools",
  model_id: "claude-fixture",
  provider: "anthropic",
  reply: "TEST FIXTURE reply.",
  tool_calls: calls,
  usage: { input_tokens: 10, output_tokens: 5 },
  notes: [],
});

async function mock(page: Page, calls: unknown[]) {
  await page.route(MODELS_URL, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MODELS) }));
  await page.route(`${CHAT_URL}/stream`, (r) => r.fulfill({ status: 404, contentType: "application/json", body: "{}" })); // one-piece path (#222)
  await page.route(CHAT_URL, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(reply(calls)) }));
}

async function ask(page: Page, text: string) {
  await expect(page.getByTestId("chat-model-current")).toHaveText("TEST FIXTURE claude-fixture");
  await page.locator("#chat-input").fill(text);
  await page.locator("#chat-input").press("Enter");
}

test("before any question: no cash graph, one line plus management starters in the right pane", async ({ page }) => {
  await mock(page, []);
  await page.goto("/explore/");
  const pane = page.getByTestId("chat-pane-empty");
  await expect(pane).toContainText("Ask a leadership or strategy decision. The odds appear here.");
  await expect(page.getByTestId("universe")).toHaveCount(0);
  // The real e2e API serves no starters route, so the four static management questions show, with no news line.
  await expect(page.getByTestId("chat-starters")).toHaveAttribute("data-source", "static");
  await expect(pane.getByTestId("chat-starter")).toHaveCount(4);
  await expect(page.getByTestId("starter-news")).toHaveCount(0);
  await expect(page.getByTestId("chat-panel")).not.toContainText(/cutting a single wage|cash floor|demo business/i);
  // Management decisions only: no starter is about cash, wages, payroll or a floor.
  for (const text of await page.getByTestId("chat-starter").allInnerTexts()) expect(text).not.toMatch(/cash|wage|payroll|floor/i);
});

test("a decision Monte Carlo answer fills the right pane large; the reply points to it", async ({ page }) => {
  await mock(page, [{ name: "monte_carlo_decision", input: {}, result_status: "ok", result_summary: fixture("mc-decision"), provenance: "SIMULATED" }]);
  await page.goto("/explore/");
  await ask(page, "Should Nvidia keep Jensen Huang as CEO? Give me the odds.");
  const pane = page.getByTestId("chat-mc-pane");
  await expect(pane.getByTestId("mc-decision")).toBeVisible();
  await expect(page.getByTestId("mc-decision")).toHaveCount(1);
  await expect(page.getByTestId("chat-cockpit")).toHaveAttribute("data-pane", "monte-carlo");
  await expect(page.getByTestId("chat-answer").getByTestId("chat-mc-on-pane")).toBeVisible();
  await expect(page.getByTestId("universe")).toHaveCount(0);
  await expect(pane.locator('[data-provenance="SIMULATED"]').first()).toBeVisible();
});

// The giant headline percentage is gradient text (background-clip: text): its box must hold every glyph, "%" included.
for (const [w, h] of [
  [1920, 1080],
  [1512, 982],
  [1440, 900],
  [390, 844],
] as const) {
  test(`the headline percentage is not clipped at ${w}×${h}`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await mock(page, [{ name: "monte_carlo_decision", input: {}, result_status: "ok", result_summary: fixture("mc-decision"), provenance: "SIMULATED" }]);
    await page.goto("/explore/");
    await ask(page, "TEST FIXTURE headline");
    const num = page.getByTestId("mc-headline-prob");
    await expect(num).toHaveText(/%$/);
    const m = await num.evaluate((el) => {
      const r = el.getBoundingClientRect();
      const range = document.createRange();
      range.selectNodeContents(el);
      const t = range.getBoundingClientRect();
      const panel = el.closest('[data-testid="mc-decision"]')!.getBoundingClientRect();
      return { scroll: el.scrollWidth, client: el.clientWidth, textRight: t.right, boxRight: r.right, panelRight: panel.right };
    });
    expect(m.scroll, "headline scrollWidth vs clientWidth").toBeLessThanOrEqual(m.client);
    expect(m.textRight, "last glyph inside the painted box").toBeLessThanOrEqual(m.boxRight);
    expect(m.boxRight, "headline inside its panel").toBeLessThanOrEqual(m.panelRight);
  });
}

test("at 390 px the Monte Carlo panel stays inline in the reply", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mock(page, [{ name: "monte_carlo_decision", input: {}, result_status: "ok", result_summary: fixture("mc-decision"), provenance: "SIMULATED" }]);
  await page.goto("/explore/");
  await ask(page, "TEST FIXTURE narrow");
  await expect(page.getByTestId("chat-answer").getByTestId("mc-decision")).toBeVisible();
  await expect(page.getByTestId("chat-mc-pane")).toHaveCount(0);
});

test("news starters: question, 'In the news' line with an http(s)-only link, and the server's provenance", async ({ page }) => {
  const at = "2026-11-14T12:00:00Z";
  const starter = (q: string, url: string, date: string | null) => ({
    question: q,
    headline: `TEST FIXTURE headline for ${q}`,
    source_title: "TEST FIXTURE source",
    source_url: url,
    domain: "example.com",
    published_date: date,
    tag: "Leadership",
  });
  await page.route(STARTERS_URL, (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        provenance: `REAL (web, retrieved ${at})`,
        generated_at: at,
        label: "TEST FIXTURE",
        starters: [starter("TEST FIXTURE question one?", "https://example.com/a", "2026-11-13"), starter("TEST FIXTURE question two?", "javascript:alert(1)", null)],
      }),
    }),
  );
  await mock(page, []);
  await page.goto("/explore/");
  await expect(page.getByTestId("chat-starters")).toHaveAttribute("data-source", "news");
  await expect(page.getByTestId("chat-starter")).toHaveCount(2);
  await expect(page.getByTestId("chat-starters").locator(`[data-provenance="REAL (web, retrieved ${at})"]`)).toBeVisible();
  const news = page.getByTestId("starter-news");
  await expect(news.nth(0)).toContainText("In the news: TEST FIXTURE headline for TEST FIXTURE question one? · example.com · Nov 13, 2026");
  const link = news.nth(0).getByRole("link");
  await expect(link).toHaveAttribute("href", "https://example.com/a");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  // The javascript: url is dropped: the headline shows as text, with no link, and the missing date says so.
  await expect(news.nth(1).getByRole("link")).toHaveCount(0);
  await expect(news.nth(1)).toContainText("date not available");
});

test("starters route down (503): static management questions, no news line", async ({ page }) => {
  await page.route(STARTERS_URL, (r) =>
    r.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ code: "STARTERS_UNAVAILABLE", message: "TEST FIXTURE" }) }),
  );
  await mock(page, []);
  await page.goto("/explore/");
  await expect(page.getByTestId("chat-starters")).toHaveAttribute("data-source", "static");
  await expect(page.getByTestId("starter-news")).toHaveCount(0);
});

test("the Provenance popover closes on an outside click and on Esc", async ({ page }) => {
  await mock(page, []);
  await page.goto("/explore/");
  const key = page.getByTestId("chat-provenance-key");
  await key.locator("summary").click();
  await expect(key).toHaveAttribute("open", "");
  await page.locator("h1").click();
  await expect(key).not.toHaveAttribute("open", "");
  await key.locator("summary").click();
  await expect(key).toHaveAttribute("open", "");
  await page.keyboard.press("Escape");
  await expect(key).not.toHaveAttribute("open", "");
});
