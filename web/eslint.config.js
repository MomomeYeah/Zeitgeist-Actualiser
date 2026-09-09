import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage", "src/api/schema.ts"] },
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // The three rules that enforce the Global Constraints' TypeScript
      // rule. Without them "no any, no !, no as" is a request rather than
      // a gate.
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-non-null-assertion": "error",
      "@typescript-eslint/consistent-type-assertions": [
        "error",
        { assertionStyle: "never" },
      ],
      "@typescript-eslint/consistent-type-imports": "error",
    },
  },
  {
    // The one file allowed to assert a type: `Response.json()` is
    // `Promise<any>` by definition, so the boundary between untyped JSON
    // and the generated contract types has to be asserted exactly once,
    // and `src/api/client.ts` is where. Scoping the exemption to the file
    // rather than sprinkling `eslint-disable` lines is what makes "the app
    // has one cast" a fact you can check by reading this config.
    files: ["src/api/client.ts"],
    rules: { "@typescript-eslint/consistent-type-assertions": "off" },
  },
  {
    // The generated schema and the node scripts are not part of the app's
    // type-checked project, and the drift checker is plain JS. `process`
    // and `console` are declared explicitly (rather than pulling in the
    // `globals` package for two identifiers) because
    // `js.configs.recommended`'s `no-undef` applies to every file and
    // Node's globals are otherwise unknown to it.
    files: ["scripts/**/*.mjs"],
    ...tseslint.configs.disableTypeChecked,
    languageOptions: {
      ...tseslint.configs.disableTypeChecked.languageOptions,
      globals: { process: "readonly", console: "readonly" },
    },
  },
  {
    // `recommendedTypeChecked`'s base config and rules carry no `files`
    // filter of their own, so without this block ESLint's own config file
    // — a plain `.js` file, never part of the app's type-checked project —
    // gets typed rules with no project service behind them, which crashes
    // linting rather than reporting a lint error. `tseslint.config()`
    // applies later entries after earlier ones, so this wins over the
    // `recommendedTypeChecked` spread above.
    files: ["eslint.config.js"],
    ...tseslint.configs.disableTypeChecked,
  },
);
