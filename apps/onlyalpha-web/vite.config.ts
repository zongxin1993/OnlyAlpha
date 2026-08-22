import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const proxy = { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } };

export default defineConfig({
    plugins: [react()],
    server: { proxy },
    preview: { proxy },
    test: {
        environment: "jsdom",
        globals: true,
        exclude: ["e2e/**", "e2e-real/**", "node_modules/**", "dist/**"],
        setupFiles: "./src/test/setup.ts",
        coverage: {
            provider: "v8",
            include: ["src/api/**/*.ts", "src/domain/**/*.ts", "src/charts/**/*.ts"],
            exclude: ["src/api/research/generated.ts", "src/charts/lightweight/**"],
            thresholds: { lines: 95, branches: 90, functions: 95, statements: 95 }
        }
    }
});
