import { defineConfig } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:4173";
const executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH;

export default defineConfig({
    testDir: "./e2e",
    use: {
        baseURL,
        trace: "retain-on-failure",
        launchOptions: executablePath === undefined ? {} : { executablePath }
    },
    webServer: [
        {
            command: "uv run --project ../.. python ../../scripts/serve_research_web_e2e.py",
            url: "http://127.0.0.1:8000/openapi.json",
            reuseExistingServer: !process.env.CI
        },
        {
            command: "npm run preview -- --host 127.0.0.1",
            url: "http://127.0.0.1:4173/research",
            reuseExistingServer: !process.env.CI
        }
    ]
});
