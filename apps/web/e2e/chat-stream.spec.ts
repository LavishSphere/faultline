import { expect, test, type Page } from "@playwright/test";
import { E2E_API_BASE } from "./ports";

/**
 * Live tool steps (#222): POST /api/explore/chat/stream, mocked in the browser with a chunked ReadableStream that the
 * test releases step by step, so the order is asserted (steps first, the reply only with `final`). Presenter mode is
 * checked on the same mock: the Authorization header is sent when a token is saved, absent when not, and the token
 * never reaches the DOM or the URL. Every body below is a TEST FIXTURE shaped like the contract, never model output.
 */

const MODELS_URL = `${E2E_API_BASE}/api/explore/chat/models`;
const MODELS = {
  models: [{ id: "claude-fixture", label: "TEST FIXTURE claude-fixture", provider: "anthropic", available: true, note: null }],
  default: "claude-fixture",
  featured: ["claude-fixture"],
};
const TOKEN = "e2e-presenter-fixture-token-7d1c";

const FINAL = {
  type: "final",
  response: {
    status: "ok",
    provenance: "LIVE EXPLORE",
    label: "MODEL-WRITTEN, numbers from engine tools",
    model_id: "claude-fixture",
    provider: "anthropic",
    reply: "TEST FIXTURE streamed reply.",
    tool_calls: [],
    usage: { input_tokens: 10, output_tokens: 5 },
    notes: [],
  },
};

const STEPS = [
  { type: "start", model_id: "claude-fixture", provider: "anthropic", started_at: "2026-11-15T00:00:00Z" },
  { type: "round", n: 1 },
  { type: "tool_call", id: "1.1", name: "web_search", input_preview: "Searching the web: “TEST FIXTURE query”" },
  { type: "tool_call", id: "1.2", name: "monte_carlo_decision", input_preview: "Running Monte Carlo · 20,000 paths · Keep vs Sell" },
  { type: "tool_result", id: "1.1", name: "web_search", result_status: "ok", preview: "TEST FIXTURE 8 sources: sec.gov, cnbc.com, …", provenance: "LIVE EXPLORE" },
  { type: "tool_result", id: "1.2", name: "monte_carlo_decision", result_status: "error", preview: "error: TEST FIXTURE refused", provenance: "SIMULATED" },
];

/** In the page: fetch to the stream route returns a chunked SSE body; `__release(n)` sends the next n events. */
async function mockStream(page: Page) {
  await page.route(MODELS_URL, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MODELS) }));
  await page.addInitScript(
    ({ events }) => {
      const w = window as unknown as Record<string, unknown>;
      const auth: (string | null)[] = [];
      w.__streamAuth = auth;
      let queue: string[] = [];
      let push: ((s: string) => void) | null = null;
      w.__release = (n: number) => {
        for (let i = 0; i < n && queue.length; i++) push?.(queue.shift()!);
      };
      const real = window.fetch.bind(window);
      window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        if (!url.endsWith("/api/explore/chat/stream")) return real(input, init);
        auth.push(new Headers(init?.headers).get("authorization"));
        queue = events.map((e: unknown) => `data: ${JSON.stringify(e)}\n\n`);
        const enc = new TextEncoder();
        const body = new ReadableStream<Uint8Array>({
          start(c) {
            push = (s) => (s === "CLOSE" ? c.close() : c.enqueue(enc.encode(s)));
            c.enqueue(enc.encode(": heartbeat\n\n"));
          },
        });
        return Promise.resolve(new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }));
      };
    },
    { events: [...STEPS, FINAL] },
  );
}

const release = (page: Page, n: number) => page.evaluate((k) => (window as unknown as { __release: (n: number) => void }).__release(k), n);

async function ask(page: Page, text: string) {
  const input = page.locator("#chat-input");
  await input.fill(text);
  await input.press("Enter");
}

test("tool steps appear live, before the reply, which arrives only with final", async ({ page }) => {
  await mockStream(page);
  await page.goto("/explore/");
  await expect(page.getByRole("radio", { name: /TEST FIXTURE claude-fixture/ })).toBeChecked();
  await ask(page, "TEST FIXTURE question");

  const waiting = page.getByTestId("chat-waiting");
  await expect(waiting).toBeVisible();
  await expect(waiting).toContainText("live steps · the reply is checked before it's shown");
  await expect(page.getByTestId("chat-live-empty")).toBeVisible();
  await expect(page.getByTestId("chat-elapsed")).toHaveText(/^\d+\.\d s$/);

  await release(page, 4); // start, round, two tool calls
  const steps = page.getByTestId("chat-live-step");
  await expect(steps).toHaveCount(2);
  await expect(steps.nth(0)).toHaveAttribute("data-status", "running");
  await expect(steps.nth(0)).toContainText("Searching the web: “TEST FIXTURE query”");
  await expect(steps.nth(1)).toContainText("Running Monte Carlo · 20,000 paths");
  await expect(page.getByTestId("chat-answer")).toHaveCount(0);

  await release(page, 2); // both results
  await expect(steps.nth(0)).toHaveAttribute("data-status", "ok");
  await expect(steps.nth(0)).toContainText("TEST FIXTURE 8 sources: sec.gov, cnbc.com, …");
  await expect(steps.nth(1)).toHaveAttribute("data-status", "error");
  await expect(steps.nth(1)).toContainText("error: TEST FIXTURE refused");
  await expect(page.getByText("TEST FIXTURE streamed reply.")).toHaveCount(0);

  await release(page, 1); // final
  const answer = page.getByTestId("chat-answer");
  await expect(answer).toBeVisible();
  await expect(answer.getByTestId("chat-reply")).toContainText("TEST FIXTURE streamed reply.");
  await expect(waiting).toHaveCount(0);
});

test("presenter mode: the token is sent as Authorization, never shown, and exit removes it", async ({ page }) => {
  await mockStream(page);
  await page.goto("/explore/#presenter");
  await expect(page.getByTestId("presenter-prompt")).toBeVisible();
  expect(page.url()).not.toContain("#presenter");
  await page.getByTestId("presenter-input").fill(TOKEN);
  await page.getByTestId("presenter-input").press("Enter");
  await expect(page.getByTestId("presenter-chip")).toBeVisible();
  expect(await page.content()).not.toContain(TOKEN);
  expect(page.url()).not.toContain(TOKEN);

  await ask(page, "TEST FIXTURE second");
  await release(page, 7);
  await expect(page.getByTestId("chat-answer")).toHaveCount(1);
  expect(await page.content()).not.toContain(TOKEN);

  await page.getByTestId("presenter-exit").click();
  await expect(page.getByTestId("presenter-chip")).toHaveCount(0);
  await ask(page, "TEST FIXTURE third");
  await release(page, 7);
  await expect(page.getByTestId("chat-answer")).toHaveCount(2);

  const sent = await page.evaluate(() => (window as unknown as { __streamAuth: (string | null)[] }).__streamAuth);
  expect(sent).toEqual([`Bearer ${TOKEN}`, null]);
});
