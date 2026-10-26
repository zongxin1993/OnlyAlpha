import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

const restricted = (patterns) => ({ "no-restricted-imports": ["error", { patterns }] });

export default tseslint.config(
    {
        ignores: [
            "dist",
            "playwright-report",
            "test-results",
            "coverage",
            "eslint.config.js",
            "src/api/research/generated.ts"
        ]
    },
    js.configs.recommended,
    ...tseslint.configs.strictTypeChecked,
    ...tseslint.configs.stylisticTypeChecked,
    {
        files: ["**/*.ts", "**/*.tsx"],
        languageOptions: {
            ecmaVersion: 2024,
            globals: globals.browser,
            parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname }
        },
        plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh },
        rules: {
            ...reactHooks.configs.flat.recommended.rules,
            "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
            "@typescript-eslint/no-explicit-any": "error",
            "@typescript-eslint/consistent-type-imports": "error"
        }
    },
    { files: ["src/app/providers.tsx"], rules: { "react-refresh/only-export-components": "off" } },
    {
        files: ["src/domain/research/**"],
        rules: restricted([
            "react",
            "react-*",
            "@tanstack/**",
            "lightweight-charts",
            "../../api/**",
            "**/api/**"
        ])
    },
    {
        files: ["src/api/research/**"],
        rules: restricted([
            "../../features/**",
            "**/features/**",
            "../../charts/**",
            "**/charts/**"
        ])
    },
    {
        files: ["src/charts/*.ts"],
        rules: restricted(["react", "react-*", "../../api/**", "**/api/**", "lightweight-charts"])
    }
);
