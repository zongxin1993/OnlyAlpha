import { defineConfig } from "@playwright/test";
import base from "./playwright.chart-study.config";

if (!Array.isArray(base.webServer))
    throw new Error("Expected shared Chart Study server configuration");

export default defineConfig({
    ...base,
    grep: /@preview-updates/,
    grepInvert: [],
    outputDir: "../../test-results/chart-study-preview-browser/artifacts",
    reporter: [
        ["list"],
        ["junit", { outputFile: "../../test-results/chart-study-preview-browser/junit.xml" }]
    ],
    webServer: base.webServer.map((server) => ({
        ...server,
        command:
            server.command === "python -m tests.runtime_support.chart_study_browser"
                ? `${server.command} --preview-updates`
                : server.command
    }))
});
