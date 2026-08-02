import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // This repo's root is shared with the Python backend — without these,
    // ESLint's flat config walks .venv/ and finds every vendored JS asset
    // bundled inside site-packages (sklearn, torch, ...).
    ".venv/**",
    "alam/**",
    "tests/**",
    "scripts/**",
    "docs/**",
    "scratch/**",
  ]),
]);

export default eslintConfig;
