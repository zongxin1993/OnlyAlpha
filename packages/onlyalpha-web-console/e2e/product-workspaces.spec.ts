import { expect, test, type Page } from "@playwright/test";

const strategyId = "a".repeat(64);

test("preview forwards the health surface instead of returning the SPA document", async ({
    request
}) => {
    const backend = await request.get("http://127.0.0.1:8000/health/live");
    const proxied = await request.get("/health/live");
    expect(proxied.status()).toBe(backend.status());
    expect(proxied.headers()["content-type"]).toContain("application/json");
    const backendBody: unknown = await backend.json();
    const proxiedBody: unknown = await proxied.json();
    expect(proxiedBody).toEqual(backendBody);
});

const runId = "00000000-0000-4000-8000-000000000501";
const run = {
    schema_version: 1,
    run_id: runId,
    state: "COMPLETED",
    revision: 2,
    specification_fingerprint: "b".repeat(64),
    admission_resolution_fingerprint: "c".repeat(64),
    queued_at: "2026-08-21T00:00:00Z",
    started_at: "2026-08-21T00:00:01Z",
    cancel_requested_at: null,
    finished_at: "2026-08-21T00:00:02Z",
    failure: null,
    result_fingerprint: "d".repeat(64),
    evidence_fingerprint: "e".repeat(64),
    determinism_fingerprint: "f".repeat(64)
};
const evidence = {
    schema_version: 1,
    manifest: {
        schema_version: 1,
        backtest_run_id: runId,
        strategy_fingerprint: strategyId,
        specification_fingerprint: "b".repeat(64),
        admission_resolution_fingerprint: "c".repeat(64),
        result_fingerprint: "d".repeat(64),
        evidence_fingerprint: "e".repeat(64),
        determinism_fingerprint: "f".repeat(64),
        base_dataset_snapshot_fingerprint: "1".repeat(64),
        dataset_binding_fingerprint: "2".repeat(64),
        market_product_composition_fingerprint: "3".repeat(64),
        portfolio_profile_fingerprint: "4".repeat(64),
        risk_profile_fingerprint: "5".repeat(64),
        execution_profile_fingerprint: "6".repeat(64),
        implementation_fingerprints: ["7".repeat(64)],
        kernel_semantics_version: "v1",
        artifacts: [
            {
                name: "result.json",
                sha256: "8".repeat(64),
                size: 2048,
                media_type: "application/json"
            }
        ]
    }
};

async function mockProductReads(page: Page) {
    const strategy = {
        schema_version: 1,
        strategy_fingerprint: strategyId,
        current_stage: "BACKTEST",
        freeze_relation_fingerprints: ["9".repeat(64)],
        revision: {},
        promotion_records: []
    };
    for (const [path, body] of [
        [`/api/v2/strategies/${strategyId}`, strategy],
        [`/api/v2/backtest/runs/${runId}`, run],
        [`/api/v2/backtest/runs/${runId}/evidence`, evidence]
    ] as const) {
        await page.route(`**${path}`, (route) =>
            route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify(body)
            })
        );
    }
    const health = {
        live: { status: "LIVE", checks: { process: "ALIVE" } },
        ready: {
            status: "NOT_READY",
            checks: { postgres: "UNAVAILABLE" },
            reason: "Fixture database unavailable"
        },
        execution: {
            status: "DEGRADED",
            checks: { backtest_worker: "NO_READY_WORKER" },
            reason: "Fixture worker unavailable"
        }
    };
    for (const [name, body] of Object.entries(health)) {
        await page.route(`**/health/${name}`, (route) =>
            route.fulfill({
                status: name === "live" ? 200 : 503,
                contentType: "application/json",
                body: JSON.stringify(body)
            })
        );
    }
}

async function noOverflow(page: Page) {
    expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    ).toBe(true);
}

for (const width of [1440, 390]) {
    test(`Strategy Backtest and System read-only navigation at ${String(width)}px`, async ({
        page
    }, testInfo) => {
        await page.setViewportSize({ width, height: 900 });
        await mockProductReads(page);
        const commands: string[] = [];
        page.on("request", (request) => {
            if (request.url().includes("/api/") && request.method() !== "GET")
                commands.push(request.url());
        });
        await page.goto("/strategies");
        await page.getByLabel("Strategy fingerprint", { exact: true }).fill(strategyId);
        await page.getByRole("button", { name: "Open Strategy" }).click();
        await expect(page).toHaveURL(`/strategies/${strategyId}`);
        await expect(page.getByRole("heading", { name: "Strategy identity" })).toBeVisible();
        await expect(page.getByText("BACKTEST", { exact: true })).toBeVisible();
        await noOverflow(page);
        await page.screenshot({ path: testInfo.outputPath("strategy.png"), fullPage: true });
        await page.getByRole("link", { name: "Inspect a Backtest" }).click();
        await page.getByLabel("Backtest Run ID").fill(runId);
        await page.getByRole("button", { name: "Open Backtest" }).click();
        await expect(page).toHaveURL(`/backtest/runs/${runId}`);
        await expect(page.getByText("COMPLETED", { exact: true })).toBeVisible();
        await expect(
            page.getByText("Verified manifest linked to the exact completed Run.", { exact: true })
        ).toBeVisible();
        await expect(page.getByText("result.json", { exact: true })).toBeVisible();
        await noOverflow(page);
        await page.screenshot({ path: testInfo.outputPath("backtest.png"), fullPage: true });
        if (width < 1280) await page.getByRole("button", { name: "Toggle navigation" }).click();
        await page.getByRole("link", { name: "System Health", exact: true }).click();
        await expect(page.getByRole("heading", { name: "System Health" })).toBeVisible();
        await expect(page.getByText("LIVE", { exact: true })).toBeVisible();
        await expect(page.getByText("NOT_READY", { exact: true })).toBeVisible();
        await expect(page.getByText("DEGRADED", { exact: true })).toBeVisible();
        await expect(
            page.getByText(/These observations do not authorize LIVE trading/)
        ).toBeVisible();
        await noOverflow(page);
        await page.screenshot({ path: testInfo.outputPath("system-health.png"), fullPage: true });
        expect(commands).toEqual([]);
    });
}
