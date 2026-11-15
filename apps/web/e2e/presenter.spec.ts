import { expect, test, type Page } from "@playwright/test";

/**
 * Presenter mode (components/PresenterToken.tsx, lib/presenter.ts). Against the static export and the real API.
 *
 * - Without `?presenter=1` (and no stored token) nothing is rendered.
 * - With it, a pasted token goes to sessionStorage only: never localStorage, never the URL. The PRESENTER badge shows
 *   while it is stored; "clear" removes it from storage and the badge goes away.
 * The token below is a TEST value in the `openssl rand -hex 32` shape; no server holds it.
 */

const TOKEN = "e9".repeat(32);
const KEY = "faultline.presenterToken";

async function storage(page: Page) {
  return page.evaluate((key) => {
    const local: Record<string, string | null> = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)!;
      local[k] = localStorage.getItem(k);
    }
    return { local, session: sessionStorage.getItem(key) };
  }, KEY);
}

test("without ?presenter=1 the presenter control is not rendered", async ({ page }) => {
  await page.goto("/rewind/");
  await expect(page.getByText("FAULTLINE", { exact: true }).first()).toBeVisible();
  await expect(page.getByTestId("presenter-token")).toHaveCount(0);
  await expect(page.getByLabel("Presenter token")).toHaveCount(0);
});

test("?presenter=1: the token stays in sessionStorage only, never localStorage or the URL; clear removes it", async ({ page }) => {
  await page.goto("/rewind/?presenter=1");
  const input = page.getByLabel("Presenter token");
  await expect(input).toBeVisible();
  await expect(input).toHaveAttribute("type", "password");

  // A malformed value is refused and nothing is stored.
  await input.fill("not-a-token");
  await page.getByRole("button", { name: "save" }).click();
  await expect(page.getByTestId("presenter-token").getByRole("alert")).toBeVisible();
  expect((await storage(page)).session).toBeNull();

  await input.fill(TOKEN);
  await page.getByRole("button", { name: "save" }).click();
  await expect(page.getByTestId("presenter-badge")).toHaveText("PRESENTER");

  const after = await storage(page);
  expect(after.session).toBe(TOKEN);
  expect(JSON.stringify(after.local)).not.toContain(TOKEN);
  expect(page.url()).not.toContain(TOKEN);
  // The page never shows the token back.
  expect(await page.content()).not.toContain(TOKEN);

  // Still flagged after navigating away from ?presenter=1, because the token is still stored in this tab.
  await page.goto("/cascade/");
  await expect(page.getByTestId("presenter-badge")).toBeVisible();
  expect(page.url()).not.toContain(TOKEN);

  await page.getByRole("button", { name: "clear" }).click();
  await expect(page.getByTestId("presenter-badge")).toHaveCount(0);
  await expect(page.getByTestId("presenter-token")).toHaveCount(0);
  const cleared = await storage(page);
  expect(cleared.session).toBeNull();
  expect(JSON.stringify(cleared.local)).not.toContain(TOKEN);
});
