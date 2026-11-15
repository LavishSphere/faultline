import { expect, test, type Page } from "@playwright/test";
import { E2E_API_BASE } from "./ports";

/**
 * Header status chip (#236): on Explore (`/`) the second half reports the live chat's own routes, never the Blind
 * Replay "RECORDED RUNS" status; the replay pages keep that wording. Every body below is a TEST FIXTURE shaped like the
 * contract, never real API output.
 */

const HEALTH_URL = `${E2E_API_BASE}/api/health`;
const MODELS_URL = `${E2E_API_BASE}/api/explore/chat/models`;
const STATUS_URL = `${E2E_API_BASE}/api/explore/chat/status`;
const CORS = { "access-control-allow-origin": "*", "access-control-expose-headers": "*" };

const fixtureModel = (id: string, available = true) => ({
  id,
  label: `TEST FIXTURE ${id}`,
  provider: "openrouter",
  available,
  note: available ? null : "TEST FIXTURE: not served",
});
const MODELS = {
  models: [fixtureModel("fx/a"), fixtureModel("fx/b"), fixtureModel("fx/c"), fixtureModel("fx/off", false)],
  default: "fx/a",
  featured: ["fx/a"],
};

/** The public server's health shape (FAULTLINE_MODE=public), so the replay pages would say RECORDED RUNS. */
async function publicHealth(page: Page) {
  await page.route(HEALTH_URL, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { ...CORS, "x-faultline-mode": "public" },
      body: JSON.stringify({ status: "ok", model_ready: false, ollama_reachable: false, tavily_configured: false }),
    }),
  );
}

async function chatRoutes(page: Page, paused: boolean, modelsStatus = 200) {
  await page.route(MODELS_URL, (route) =>
    route.fulfill({
      status: modelsStatus,
      contentType: "application/json",
      headers: CORS,
      body: modelsStatus === 200 ? JSON.stringify(MODELS) : JSON.stringify({ detail: "TEST FIXTURE: chat not configured" }),
    }),
  );
  await page.route(STATUS_URL, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify({ paused, until: null }) }),
  );
}

test("on / the chip says CHAT LIVE · N models from the chat's models route; /rewind/ still says RECORDED RUNS", async ({ page }) => {
  await publicHealth(page);
  await chatRoutes(page, false);
  await page.goto("/");
  const chip = page.getByTestId("health-chip-model");
  await expect(chip).toHaveText("CHAT LIVE · 3 models");
  const button = page.locator("button", { has: chip });
  await expect(button).toHaveAttribute("title", /\/api\/explore\/chat\/models: 3 models available of 4 listed/);
  await expect(page.getByText("PUBLIC DEMO · RECORDED RUNS", { exact: true })).toHaveCount(0);

  await page.goto("/rewind/");
  await expect(chip).toHaveText("PUBLIC DEMO · RECORDED RUNS");
  await expect(button).toHaveAttribute("title", /This public server runs no model\. Forecasts shown are committed RECORDED RUNs/);
});

test("on / a paused chat adds PAUSED; a failing models route reads CHAT NOT AVAILABLE, never live", async ({ page }) => {
  await publicHealth(page);
  await chatRoutes(page, true);
  await page.goto("/");
  await expect(page.getByTestId("health-chip-model")).toHaveText("CHAT LIVE · 3 models · PAUSED");

  await page.unrouteAll();
  await publicHealth(page);
  await chatRoutes(page, false, 503);
  await page.reload();
  const chip = page.getByTestId("health-chip-model");
  await expect(chip).toHaveText("CHAT NOT AVAILABLE");
  await expect(chip).not.toContainText("LIVE");
});
