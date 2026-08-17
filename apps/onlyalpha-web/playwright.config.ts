import { defineConfig } from "@playwright/test";

export default defineConfig({
    testDir: "./e2e",
    use: { baseURL: "http://127.0.0.1:4173", trace: "retain-on-failure" },
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
