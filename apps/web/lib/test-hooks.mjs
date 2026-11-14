// Test-only module hook for `npm test` (node's built-in runner strips TypeScript types itself). The app's .ts files
// import siblings without an extension ("./api"), as the bundler allows; this resolves those to "./api.ts".
import { registerHooks } from "node:module";

registerHooks({
  resolve(specifier, context, nextResolve) {
    try {
      return nextResolve(specifier, context);
    } catch (err) {
      if (/^\.\.?\//.test(specifier) && !/\.[cm]?[jt]sx?$/.test(specifier)) return nextResolve(`${specifier}.ts`, context);
      throw err;
    }
  },
});
