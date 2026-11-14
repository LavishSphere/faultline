import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, devices } from "@playwright/test";
import { E2E_API_BASE, E2E_API_PORT, E2E_WEB_ORIGIN, E2E_WEB_PORT } from "./e2e/ports";

/**
 * End-to-end smoke test (issue #53): the real FastAPI app from services/api plus the static export of this app,
 * exactly as static hosting serves it. Nothing is mocked except the deliberate API-down case, which blocks the
 * browser's requests to the API (e2e/smoke.spec.ts).
 *
 * Ports (e2e/ports.ts) are unusual so a running `make dev` (8000/3000) is never reused by accident.
 * Python for uvicorn: FAULTLINE_E2E_PYTHON, else the services/api/.venv interpreter (Scripts/python.exe on Windows,
 * bin/python elsewhere), else `python` on Windows (where `python3` is usually the Microsoft Store stub) or `python3`.
 */
const apiDir = resolve(__dirname, "../../services/api");
const venvPythons = [resolve(apiDir, ".venv/Scripts/python.exe"), resolve(apiDir, ".venv/bin/python")];
const python =
  process.env.FAULTLINE_E2E_PYTHON ||
  venvPythons.find((candidate) => existsSync(candidate)) ||
  (process.platform === "win32" ? "python" : "python3");

const CI = !!process.env.CI;

export default defineConfig({
  testDir: "./e2e",
  // Outside the source tree's tracked paths (node_modules is git-ignored), so no .gitignore change is needed.
  outputDir: "./node_modules/.cache/faultline-e2e/test-results",
  fullyParallel: false,
  workers: 1,
  forbidOnly: CI,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: CI ? [["list"], ["github"]] : "list",
  use: {
    baseURL: E2E_WEB_ORIGIN,
    // Count-up animations are skipped, so the readout shows the API value as soon as the response lands.
    reducedMotion: "reduce",
    viewport: { width: 1920, height: 1080 },
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1920, height: 1080 } } }],
  webServer: [
    {
      name: "api",
      command: `"${python}" -m uvicorn main:app --host 127.0.0.1 --port ${E2E_API_PORT}`,
      cwd: apiDir,
      url: `${E2E_API_BASE}/api/health`,
      // The API allows CORS from exactly this origin (services/api/config.py).
      env: { FAULTLINE_WEB_ORIGIN: E2E_WEB_ORIGIN },
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      name: "web",
      // NEXT_PUBLIC_API_BASE is inlined at build time, so the export is rebuilt against the e2e API every run.
      command: `npm run build && node e2e/serve-static.mjs ${E2E_WEB_PORT} out`,
      cwd: __dirname,
      url: `${E2E_WEB_ORIGIN}/cascade/`,
      env: { FAULTLINE_STATIC_EXPORT: "1", NEXT_PUBLIC_API_BASE: E2E_API_BASE, NEXT_TELEMETRY_DISABLED: "1" },
      reuseExistingServer: false,
      timeout: 240_000,
      stdout: "ignore",
      stderr: "pipe",
    },
  ],
});
