import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";

export default defineConfig({
    testDir: "./e2e",
    testMatch: "symbol-search.acceptance.ts",
    workers: 1,
    retries: 0,
    outputDir: "../../test-results/symbol-search-browser/artifacts",
    reporter: [
        ["list"],
        ["junit", { outputFile: "../../test-results/symbol-search-browser/junit.xml" }]
    ],
    use: { baseURL: "http://127.0.0.1:5173", trace: "retain-on-failure" },
    webServer: {
        command: "python -m tests.runtime_support.chart_study_browser --watchlist-slice",
        cwd: resolve(import.meta.dirname, "../.."),
        url: "http://127.0.0.1:5173/health/ready",
        reuseExistingServer: false
    }
});
