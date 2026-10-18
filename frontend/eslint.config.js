// ESLint in the ADR-0001 baseline cannot parse TypeScript on its own
// (needs typescript-eslint, a needs-human request in task T-003). Until then it
// lints the plain JavaScript config and script files only; TypeScript is checked
// by `npm run typecheck`, and scripts/check-security.mjs scans the TS sources.
export default [
  { ignores: ["dist/", "node_modules/", "src/", "vite.config.ts"] },
  {
    files: ["**/*.js", "**/*.mjs"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { process: "readonly", console: "readonly" },
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": "error",
      "no-var": "error",
      "prefer-const": "error",
      eqeqeq: "error",
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
    },
  },
];
