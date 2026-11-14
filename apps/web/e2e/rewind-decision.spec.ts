import { expect, test, type Page } from "@playwright/test";
import { E2E_API_BASE } from "./ports";

/**
 * REWIND time machine, the local-model badge and the INTEGRITY scan (#163), against the real API and the static
 * export. Same honesty rule as smoke.spec.ts: every expected value (cutoff, counts, labels, statuses, model name) is
 * read from the API and compared with the page. Two tests reshape one real response (marked TEST FIXTURE) to reach
 * states the committed data does not have: excluded items, and a model that is not ready.
 */

const CASES_URL = `${E2E_API_BASE}/api/cases`;
const HEALTH_URL = `${E2E_API_BASE}/api/health`;
const INTEGRITY_URL = `${E2E_API_BASE}/api/integrity`;
const evidenceUrl = (id: string) => `${E2E_API_BASE}/api/cases/${encodeURIComponent(id)}/evidence`;
const CORS = { "access-control-allow-origin": "*", "access-control-expose-headers": "*" };

interface Case {
  event_id: string;
  title: string;
  as_of: string;
  provenance: "REAL_HISTORICAL" | "SYNTHETIC";
}
interface Evidence {
  items: { evidence_id: string }[];
  excluded_by_reason: Record<string, number>;
  market_at_cutoff: { status: string; label: string; p_yes: number | null; provenance: string | null };
}
interface Health {
  model_ready: boolean;
  ollama_status: { required_model: string };
}

/** lib/replay.ts formatCutoffUtc: display formatting of the served instant, no arithmetic on it. */
function cutoffText(iso: string): string {
  const d = new Date(Date.parse(iso));
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`;
}

async function realCase(page: Page): Promise<Case> {
  const res = await page.request.get(CASES_URL);
  expect(res.status(), "direct GET /api/cases").toBe(200);
  const c = ((await res.json()) as { items: Case[] }).items.find((i) => i.provenance === "REAL_HISTORICAL");
  expect(c, "the API serves at least one REAL_HISTORICAL case").toBeTruthy();
  return c!;
}

async function pick(page: Page, c: Case) {
  await page.getByRole("list", { name: "Replay cases" }).getByRole("button").filter({ hasText: c.title }).click();
  await expect(page.getByTestId("header-case-id")).toHaveText(c.event_id);
}

test.describe("REWIND · time machine", () => {
  test("lands on the served cutoff; documents, not-yet-public count and market label are the API's", async ({ page }) => {
    const c = await realCase(page);
    const ev = (await (await page.request.get(evidenceUrl(c.event_id))).json()) as Evidence;
    await page.goto("/rewind/");
    await pick(page, c);

    const machine = page.getByTestId("time-machine");
    await expect(machine.getByTestId("time-machine-cutoff").locator(".sr-only")).toHaveText(cutoffText(c.as_of));
    // Reduced motion (playwright.config.ts): the visible frame is the final one at once.
    await expect(machine.getByTestId("time-machine-cutoff").locator('[aria-hidden="true"]')).toHaveText(cutoffText(c.as_of));
    await expect(machine.locator('[data-provenance="REAL HISTORICAL"]')).toBeVisible();

    // One card per admitted id, in served order.
    await expect(page.getByTestId("known-evidence").locator("li")).toHaveCount(ev.items.length);

    // Not yet public: the served counts for the two "after the cutoff" reasons, and nothing else.
    const notYet = (ev.excluded_by_reason.available_after_as_of ?? 0) + (ev.excluded_by_reason.published_after_as_of ?? 0);
    await expect(page.getByTestId("not-yet-public-count")).toHaveText(String(notYet));

    // Market at the cutoff: the API's label verbatim, badged with its own provenance.
    const market = page.getByTestId("market-at-cutoff");
    if (ev.market_at_cutoff.status === "AVAILABLE") {
      await expect(market.getByText(ev.market_at_cutoff.label, { exact: true })).toBeVisible();
      await expect(market.locator('[data-provenance="REAL HISTORICAL"]').first()).toBeVisible();
    } else {
      await expect(market).toHaveCount(0);
    }

    await expect(page.getByTestId("sealed-vault")).toContainText("Sealed: the outcome is locked until reveal");
  });

  test("excluded items show as sealed placeholders by count only (TEST FIXTURE counts on a real response)", async ({ page }) => {
    const c = await realCase(page);
    // TEST FIXTURE: the committed cases hold nothing dated after their cutoff, so the real body's counts are 0.
    // These counts are injected to exercise the placeholders; no excluded id or text exists to leak.
    const fixtureCounts = { available_after_as_of: 3, published_after_as_of: 1, retrospective_unverified: 2 };
    await page.route(evidenceUrl(c.event_id), async (route) => {
      const res = await route.fetch();
      const body = (await res.json()) as Evidence;
      route.fulfill({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify({ ...body, excluded_by_reason: fixtureCounts }) });
    });
    await page.goto("/rewind/");
    await pick(page, c);

    const box = page.getByTestId("not-yet-public");
    await expect(box.getByTestId("not-yet-public-count")).toHaveText("4");
    const cards = box.getByRole("list", { name: /Sealed placeholders/ }).locator("li");
    await expect(cards).toHaveCount(4);
    // A placeholder carries no id, title or text: only the glyph and "Sealed item".
    for (const card of await cards.all()) await expect(card).toHaveText(/^■\s*Sealed item$/);
    const reasons = box.getByTestId("excluded-by-reason");
    for (const [reason, n] of Object.entries(fixtureCounts)) await expect(reasons).toContainText(`${n} · ${reason}`);
  });

  test("390 px: the time machine and the documents fit with no horizontal scroll", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const c = await realCase(page);
    await page.goto("/rewind/");
    await pick(page, c);
    await expect(page.getByTestId("not-yet-public-count")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, "horizontal overflow on /rewind/ in px").toBeLessThanOrEqual(0);
  });
});

test.describe("DECISION · local-model badge and integrity scan", () => {
  test("badge and header chip say exactly what GET /api/health reports", async ({ page }) => {
    const health = (await (await page.request.get(HEALTH_URL)).json()) as Health;
    const model = health.ollama_status.required_model;
    await page.goto("/decision/");
    const badge = page.getByTestId("local-model-badge");
    await expect(badge.getByTestId("local-model-name")).toHaveText(model);
    await expect(badge).toHaveAttribute("data-ready", health.model_ready ? "available" : "unavailable");
    const chip = page.getByTestId("health-chip-model");
    if (health.model_ready) {
      await expect(badge.getByTestId("local-model-status")).toHaveText("runs locally, no cloud");
      await expect(chip).toHaveText(`Local model ready · ${model}`);
    } else {
      await expect(badge.getByTestId("local-model-status")).toContainText("not ready");
      await expect(badge).not.toContainText("runs locally");
      await expect(chip).toHaveText(`Local model unavailable · ${model}`);
    }
  });

  test("model_ready: false (TEST FIXTURE on the real health body) never reads as ready", async ({ page }) => {
    await page.route(HEALTH_URL, async (route) => {
      const real = (await (await route.fetch()).json()) as Health & { ollama_status: Record<string, unknown> };
      const body = { ...real, model_ready: false, ollama_status: { ...real.ollama_status, required_model_present: false } };
      route.fulfill({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify(body) });
    });
    await page.goto("/decision/");
    const badge = page.getByTestId("local-model-badge");
    await expect(badge).toHaveAttribute("data-ready", "unavailable");
    await expect(badge.getByTestId("local-model-status")).toContainText("not ready");
    await expect(page.getByTestId("health-chip-model")).toContainText("Local model unavailable");
  });

  test("each check shows the API's own status, and none before the response lands", async ({ page }) => {
    const c = await realCase(page);
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    // Hold every integrity request (with or without a case) until the assertions below have run.
    await page.route(
      (url) => url.href.startsWith(INTEGRITY_URL),
      async (route) => {
        await gate;
        await route.continue();
      },
    );
    await page.goto("/rewind/");
    await pick(page, c);
    await page.goto("/decision/");

    const panel = page.locator("section").filter({ hasText: "Integrity · what the AI could not see" });
    await expect(panel.getByTestId("integrity-scanning")).toBeVisible();
    await expect(panel.locator('[data-status="PASS"], [data-status="FAIL"]')).toHaveCount(0);

    const answered = page.waitForResponse((r) => r.url().startsWith(`${INTEGRITY_URL}?case_id=`));
    release();
    await answered;
    const direct = (await (await page.request.get(`${INTEGRITY_URL}?case_id=${encodeURIComponent(c.event_id)}`)).json()) as {
      checks: { id: string; status: string }[];
    };
    for (const check of direct.checks) {
      await expect(panel.locator(`[data-check="${check.id}"] [data-status]`)).toHaveAttribute("data-status", check.status);
    }
    // Facts are behind a disclosure, not dropped.
    await expect(panel.getByTestId("check-facts").first()).toBeAttached();
  });
});
