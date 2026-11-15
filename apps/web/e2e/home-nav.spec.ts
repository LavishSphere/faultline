import { expect, test } from "@playwright/test";

/**
 * Home and presenter navigation: `/` is Live Explore; the Blind Replay is a labelled second section whose screens keep
 * their own routes. Navigation only: no figures are asserted here.
 */

test("`/` leads with Live Explore and the nav highlights it", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Live Explore" })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Presenter timeline" });
  await expect(nav.getByText("Ask the engine", { exact: true })).toBeVisible();
  await expect(nav.getByText("Blind Replay: the honesty proof", { exact: true })).toBeVisible();
  await expect(page.getByTestId("nav-live-explore")).toHaveAttribute("aria-current", "step");
  // The replay case chip belongs to the replay screens, not the home screen.
  await expect(page.getByTestId("header-case")).toHaveCount(0);
});

test("the Blind Replay still runs Rewind → Research by link and arrow keys, and ← from Rewind returns to Explore", async ({
  page,
}) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Presenter timeline" });
  await nav.getByRole("link", { name: /Rewind/ }).click();
  await expect(page).toHaveURL(/\/rewind\/?$/);
  await expect(page.getByRole("heading", { level: 1, name: "Rewind" })).toBeVisible();
  await expect(page.getByTestId("header-case")).toBeVisible();

  await page.locator("body").click({ position: { x: 5, y: 5 } });
  for (const slug of ["decision", "cascade", "reveal", "research"]) {
    await page.keyboard.press("ArrowRight");
    await expect(page).toHaveURL(new RegExp(`/${slug}/?$`));
  }
  await page.goto("/rewind/");
  await page.keyboard.press("ArrowLeft");
  await expect(page).toHaveURL(/\/explore\/?$/);
  await expect(page.getByTestId("nav-live-explore")).toHaveAttribute("aria-current", "step");
});

test("home at 390 px: no horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByTestId("nav-live-explore")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "horizontal overflow in px").toBeLessThanOrEqual(0);
});
