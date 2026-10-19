// Plain JS config/scripts use core rules; TypeScript sources use typescript-eslint's
// recommended type-checked rules (ADR-0001 Amendments 1 and 2).
// scripts/check-security.mjs still runs after ESLint (see `npm run lint`).
import tseslint from "typescript-eslint";

const coreRules = {
  "no-var": "error",
  "prefer-const": "error",
  eqeqeq: "error",
  "no-eval": "error",
  "no-implied-eval": "error",
  "no-new-func": "error",
};

export default tseslint.config(
  { ignores: ["dist/", "node_modules/"] },
  {
    files: ["**/*.js", "**/*.mjs"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { process: "readonly", console: "readonly" },
    },
    rules: { ...coreRules, "no-undef": "error", "no-unused-vars": "error" },
  },
  {
    files: ["src/**/*.{ts,tsx}", "vite.config.ts"],
    extends: [...tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    rules: coreRules,
  },
);
