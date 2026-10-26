import { defineConfig } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:4173";

export default defineConfig({
    testDir: "./e2e-compose",
    workers: 1,
    retries: 0,
    outputDir: "test-results/test-results",
    reporter: [
        ["list"],
        ["html", { outputFolder: "test-results/html-report", open: "never" }],
        ["json", { outputFile: "test-results/report.json" }]
    ],
    use: {
        baseURL,
        actionTimeout: 10_000,
        trace: "retain-on-failure",
        screenshot: "only-on-failure"
    }
});
