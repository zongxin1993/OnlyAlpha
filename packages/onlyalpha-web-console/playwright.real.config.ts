import { defineConfig } from "@playwright/test";

export default defineConfig({
    testDir: "./e2e-real",
    timeout: 90_000,
    expect: { timeout: 10_000 },
    workers: 1,
    retries: 0,
    use: {
        baseURL: "http://127.0.0.1:4173",
        actionTimeout: 10_000,
        trace: "retain-on-failure"
    }
});
