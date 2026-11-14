/** Shared by playwright.config.ts and the specs. Override with FAULTLINE_E2E_API_PORT / FAULTLINE_E2E_WEB_PORT. */
export const E2E_API_PORT = Number(process.env.FAULTLINE_E2E_API_PORT || "8799");
export const E2E_WEB_PORT = Number(process.env.FAULTLINE_E2E_WEB_PORT || "3799");
export const E2E_API_BASE = `http://127.0.0.1:${E2E_API_PORT}`;
export const E2E_WEB_ORIGIN = `http://127.0.0.1:${E2E_WEB_PORT}`;
