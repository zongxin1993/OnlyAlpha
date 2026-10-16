import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";

export default defineConfig({
    testDir: "./e2e",
    testMatch: "chart-study.acceptance.ts",
    grepInvert: /@preview-updates/,
    workers: 1,
    retries: 0,
    outputDir: "../../test-results/chart-study-browser/artifacts",
    reporter: [
        ["list"],
        ["junit", { outputFile: "../../test-results/chart-study-browser/junit.xml" }]
    ],
    use: { baseURL: "http://127.0.0.1:4173", trace: "off" },
    webServer: [
        {
            command: "python -m tests.runtime_support.chart_study_browser",
            cwd: resolve(import.meta.dirname, "../.."),
            url: "http://127.0.0.1:8000/health/ready",
            reuseExistingServer: false
        },
        {
            command: "npm run preview -- --host 127.0.0.1 --strictPort",
            url: "http://127.0.0.1:4173",
            reuseExistingServer: false
        }
    ]
});
