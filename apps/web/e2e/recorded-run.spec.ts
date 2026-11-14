import { expect, test, type Page, type Route } from "@playwright/test";
import { E2E_API_BASE } from "./ports";

/**
 * DECISION · committed RECORDED RUN forecast (issue #116), GET /api/replay/recorded.
 *
 * 1. Real API: nothing is committed under data/recorded_runs/runs/, so the panel says NOT AVAILABLE with the API's
 *    own note (fetched directly and compared), never a placeholder.
 * 2. Public-demo path, mocked: the recorded route answers with a TEST FIXTURE row and the run route answers 401
 *    ADMIN_TOKEN_REQUIRED, as routes/replay.py does in public mode. The recorded panel becomes the primary view and
 *    shows the fixture verbatim; "Use recorded forecast" fills REVEAL's prediction id. Every expected value below is
 *    read from the fixture object, not retyped.
 */

const CASES_URL = `${E2E_API_BASE}/api/cases`;
const RUN_URL = `${E2E_API_BASE}/api/replay/run`;
const isRecorded = (url: URL) => url.pathname === "/api/replay/recorded";

async function firstCase(page: Page): Promise<{ event_id: string; as_of: string }> {
  const res = await page.request.get(CASES_URL);
  expect(res.status()).toBe(200);
  const body = (await res.json()) as { items: { event_id: string; as_of: string }[] };
  expect(body.items.length, "at least one committed case").toBeGreaterThan(0);
  return body.items[0]!;
}

function fixtureRow(caseId: string, asOf: string, variant: string) {
  return {
    provenance: "RECORDED_RUN",
    run_id: "e2e-fixture-run",
    prediction_id: `pred_e2e_fixture_${variant}`,
    case_id: caseId,
    agent_variant: variant,
    as_of: asOf,
    p_yes: 0.42,
    decision: "hedge",
    rationale: "TEST FIXTURE rationale, shown verbatim.",
    evidence_ids: ["evid_fixture_1"],
    cited_evidence: [
      {
        evidence_id: "evid_fixture_1",
        title: "TEST FIXTURE evidence title",
        available_at: asOf,
        source_url: null,
        provenance: "SYNTHETIC",
      },
    ],
    agent_model: "ollama/e2e-fixture",
    model_tag: "e2e-fixture",
    model_digest: null,
    temperature: 0,
    seed: 1,
    attempts: 1,
    prompt_sha256: "a".repeat(64),
    gated_prompt_sha256: "a".repeat(64),
    snapshot_sha256: "b".repeat(64),
    record_sha256: "c".repeat(64),
    row_sha256: "d".repeat(64),
    recorded_at: "2026-11-13T12:00:00Z",
    persisted_at: "2026-11-13T12:00:01Z",
    case_synthetic: true,
    contamination_flag: "unlikely",
    model_card_contamination_flag: "unlikely",
  };
}

async function mockPublicDemo(page: Page, asOf: string) {
  await page.route(isRecorded, (route: Route) => {
    const url = new URL(route.request().url());
    const caseId = url.searchParams.get("case_id") ?? "";
    const variant = url.searchParams.get("agent_variant") ?? "agent_only";
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify({
        status: "AVAILABLE",
        provenance: "RECORDED_RUN",
        case_id: caseId,
        items: [fixtureRow(caseId, asOf, variant)],
        notes: [],
      }),
    });
  });
  await page.route(RUN_URL, (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify({ code: "ADMIN_TOKEN_REQUIRED", message: "Admin only on the public demo (TEST FIXTURE)." }),
    }),
  );
}

test.describe("DECISION · recorded run", () => {
  test("real API with nothing committed: NOT AVAILABLE with the API's own note", async ({ page }) => {
    const c = await firstCase(page);
    const direct = await page.request.get(`${E2E_API_BASE}/api/replay/recorded`, {
      params: { case_id: c.event_id, agent_variant: "agent_only" },
    });
    expect(direct.status()).toBe(200);
    const body = (await direct.json()) as { status: string; items: unknown[]; notes: string[] };
    test.skip(body.status === "AVAILABLE", "a recorded run is committed on this checkout");
    expect(body.items).toEqual([]);

    await page.goto("/decision/");
    await page.locator("#decision-case").selectOption(c.event_id);
    const slot = page.getByTestId("recorded-slot");
    await expect(slot.getByTestId("recorded-not-available")).toBeVisible();
    await expect(slot.getByText("Recorded run: not available")).toBeVisible();
    for (const note of body.notes) await expect(slot.getByText(note, { exact: true })).toBeVisible();
    await expect(page.getByTestId("recorded-run")).toHaveCount(0);
  });

  for (const width of [1920, 390]) {
    test(`public demo at ${width} px: Run is admin-gated, the recorded forecast is primary and fills REVEAL`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1080 });
      const c = await firstCase(page);
      const row = fixtureRow(c.event_id, c.as_of, "agent_only");
      await mockPublicDemo(page, c.as_of);
      await page.goto("/decision/");
      await page.locator("#decision-case").selectOption(c.event_id);

      // Before the click it sits next to the Run button.
      const slot = page.getByTestId("recorded-slot");
      await expect(slot.getByTestId("recorded-run")).toBeVisible();
      await expect(slot.getByTestId("recorded-p")).toHaveText(row.p_yes.toFixed(3));

      await page.getByRole("button", { name: "Run sealed forecast" }).click();
      const primary = page.locator("section").filter({ has: page.getByText("B.R", { exact: true }) });
      const panel = primary.getByTestId("recorded-run");
      await expect(panel).toBeVisible();
      await expect(slot.getByTestId("recorded-run")).toHaveCount(0);
      await expect(primary.locator('[data-provenance="RECORDED RUN"]').first()).toBeVisible();
      await expect(panel.getByTestId("recorded-p")).toHaveText(row.p_yes.toFixed(3));
      await expect(panel.getByTestId("recorded-decision")).toHaveText("Hedge");
      await expect(panel.getByText(row.rationale, { exact: true })).toBeVisible();
      await expect(panel.getByText(row.cited_evidence[0]!.title, { exact: true })).toBeVisible();
      await expect(panel.getByText(row.run_id, { exact: true })).toBeVisible();
      await expect(panel.getByText(row.agent_model, { exact: true })).toBeVisible();
      await expect(panel.getByText("Reveal is disabled on the public demo", { exact: false })).toBeVisible();

      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `no horizontal page scroll at ${width} px`).toBeLessThanOrEqual(0);

      await panel.getByTestId("use-recorded").click();
      await expect(page).toHaveURL(/\/reveal\/?\?prediction_id=/);
      await expect(page.locator("#reveal-prediction-id")).toHaveValue(row.prediction_id);
    });
  }
});
