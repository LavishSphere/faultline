import { expect, test } from "@playwright/test";

/**
 * Home and presenter navigation: `/` is Live Explore; the header is one compact row (Explore, then a small Blind
 * Replay link). The five-step replay timeline appears only on replay screens, which keep their own routes and the
 * presenter arrow keys. Navigation only: no figures are asserted here.
 */

test("`/` leads with Explore: compact header nav, no replay timeline", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Ask the engine" })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav.getByTestId("nav-live-explore")).toHaveAttribute("aria-current", "step");
  await expect(nav.getByRole("link", { name: "Blind Replay" })).toBeVisible();
  // The five replay steps belong to the replay screens, not the Explore page.
  await expect(page.getByRole("navigation", { name: "Presenter timeline" })).toHaveCount(0);
  // The replay case chip belongs to the replay screens, not the home screen.
  await expect(page.getByTestId("header-case")).toHaveCount(0);
});

test("the Blind Replay link opens Rewind with its timeline; Rewind → Research by arrow keys, and ← from Rewind returns to Explore", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Blind Replay" }).click();
  await expect(page).toHaveURL(/\/rewind\/?$/);
  await expect(page.getByRole("heading", { level: 1, name: "Rewind" })).toBeVisible();
  await expect(page.getByTestId("header-case")).toBeVisible();
  const timeline = page.getByRole("navigation", { name: "Presenter timeline" });
  await expect(timeline.getByText("Blind Replay: the honesty proof", { exact: true })).toBeVisible();
  await expect(timeline.getByRole("link", { name: /Rewind/ })).toHaveAttribute("aria-current", "step");
  await expect(page.getByTestId("nav-blind-replay")).toHaveAttribute("aria-current", "true");

  // Every replay step is still reachable from the timeline by link.
  await timeline.getByRole("link", { name: /Cascade/ }).click();
  await expect(page).toHaveURL(/\/cascade\/?$/);
  await page.goto("/rewind/");

  await page.locator("body").click({ position: { x: 5, y: 5 } });
  for (const slug of ["decision", "cascade", "reveal", "research"]) {
    await page.keyboard.press("ArrowRight");
    await expect(page).toHaveURL(new RegExp(`/${slug}/?$`));
  }
  await page.goto("/rewind/");
  await page.keyboard.press("ArrowLeft");
  await expect(page).toHaveURL(/\/explore\/?$/);
  await expect(page.getByTestId("nav-live-explore")).toHaveAttribute("aria-current", "step");
  await expect(page.getByRole("navigation", { name: "Presenter timeline" })).toHaveCount(0);
});

test("home at 390 px: no horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByTestId("nav-live-explore")).toBeVisible();
  await expect(page.getByTestId("nav-blind-replay")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "horizontal overflow in px").toBeLessThanOrEqual(0);
});
