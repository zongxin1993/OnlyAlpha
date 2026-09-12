import { expect, test, type Page } from "@playwright/test";

const runId = "00000000-0000-4000-8000-000000000401";
let result = "";

test.beforeAll(async ({ request }) => {
    const response = await request.get("http://127.0.0.1:8000/__onlyalpha_e2e__/fixture");
    expect(response.ok()).toBeTruthy();
    const identity = (await response.json()) as { readonly research_result_fingerprint: string };
    result = identity.research_result_fingerprint;
});

async function mockRunPage(page: Page, completed = false) {
    await page.route("**/api/v2/research/runs?**", (route) =>
        route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                schema_version: 2,
                runs: completed
                    ? [
                          {
                              schema_version: 2,
                              run_id: runId,
                              revision: "2",
                              state: "COMPLETED",
                              specification_schema_version: 2,
                              specification_fingerprint: "a".repeat(64),
                              admission_resolution_fingerprint: "b".repeat(64),
                              queued_at: "2026-08-21T00:00:00Z",
                              started_at: "2026-08-21T00:00:01Z",
                              cancel_requested_at: null,
                              finished_at: "2026-08-21T00:00:02Z",
                              result_ref: result,
                              artifact_ref: result,
                              failure: null
                          }
                      ]
                    : [],
                has_more: false,
                next_cursor: null
            })
        })
    );
}

async function noPageOverflow(page: Page) {
    const sizes = await page.evaluate(() => ({
        width: document.documentElement.scrollWidth,
        viewport: window.innerWidth
    }));
    expect(sizes.width).toBeLessThanOrEqual(sizes.viewport);
}

for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1920, height: 1080 }
]) {
    test(`analysis workstation composition at ${String(viewport.width)}px`, async ({
        page
    }, testInfo) => {
        await page.setViewportSize(viewport);
        await mockRunPage(page);
        const externalRequests: string[] = [];
        page.on("request", (request) => {
            const url = new URL(request.url());
            if (url.protocol.startsWith("http") && url.origin !== "http://127.0.0.1:4173")
                externalRequests.push(request.url());
        });
        await page.goto("/research/analysis");
        await expect(page.getByRole("link", { name: "OnlyAlpha Research" })).toBeVisible();
        await expect(page.getByRole("link", { name: "AI Analysis", exact: true })).toBeVisible();
        await expect(page.getByRole("heading", { name: "AI Opportunity Radar" })).toBeVisible();
        await expect(page.locator(".opportunity-card")).toHaveCount(4);
        await expect(page.getByRole("tab", { name: "Instant Analysis" })).toBeVisible();
        await expect(page.getByRole("region", { name: "Market ticker" })).toBeVisible();
        await expect(page.getByRole("heading", { name: "Market Pulse" })).toBeVisible();
        await expect(page.getByRole("heading", { name: "Economic Calendar" })).toBeVisible();
        await expect(page.getByRole("form", { name: "Analysis controls" })).toBeVisible();
        await expect(page.getByRole("region", { name: "Analysis canvas" })).toBeVisible();
        await expect(page.getByRole("complementary", { name: "Recent Research" })).toBeVisible();
        await expect(page.getByText("No Research Runs yet", { exact: true })).toBeVisible();
        await expect(page.getByRole("button", { name: "Open Analysis" })).toBeDisabled();
        await noPageOverflow(page);
        expect(externalRequests).toEqual([]);
        await page.screenshot({
            path: testInfo.outputPath("analysis-desktop.png"),
            fullPage: true
        });
        await page.getByRole("tab", { name: "Research", exact: true }).click();
        await expect(page.getByRole("heading", { name: "Your Research workflow" })).toBeVisible();
    });
}

test("completed Run opens real immutable Artifact and Statistics evidence", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockRunPage(page, true);
    await page.goto("/research/analysis");
    await expect(page.getByLabel("Completed Research Run")).toBeEnabled();
    await page.getByLabel("Completed Research Run").selectOption(runId);
    await page.getByRole("button", { name: "Open Analysis" }).click();
    await expect(page).toHaveURL(`/research/analysis?result=${result}`);
    await expect(
        page.getByRole("heading", { name: "Research evidence", exact: true })
    ).toBeVisible();
    await expect(page.getByTestId("scientific-chart")).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Exact value" })).toBeVisible();
    await noPageOverflow(page);
    await page.getByRole("link", { name: "Full workspace", exact: true }).click();
    await expect(page).toHaveURL(`/research/results/${result}`);
    await expect(page.getByRole("heading", { name: "Scientific Workstation" })).toBeVisible();
});

test("390px navigation, horizontal Radar and single-column evidence remain usable", async ({
    page
}, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockRunPage(page);
    await page.goto("/research/analysis");
    await expect(page.getByRole("heading", { name: "OnlyAlpha Analysis" })).toBeVisible();
    await expect(page.getByRole("link", { name: "AI Analysis", exact: true })).toBeHidden();
    await page.getByRole("button", { name: "Toggle navigation" }).click();
    await expect(page.getByRole("link", { name: "AI Analysis", exact: true })).toBeVisible();
    await page.getByRole("link", { name: "Runs", exact: true }).click();
    await expect(page).toHaveURL("/research/runs");
    await expect(page.getByRole("heading", { name: "Research Runs" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Toggle navigation" })).toHaveAttribute(
        "aria-expanded",
        "false"
    );
    await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page.getByRole("link", { name: "AI Analysis", exact: true }).click();
    await expect(page.getByRole("heading", { name: "OnlyAlpha Analysis" })).toBeVisible();
    await noPageOverflow(page);
    await page.screenshot({ path: testInfo.outputPath("analysis-mobile.png"), fullPage: true });
});

for (const width of [1024, 390]) {
    test(`Data and Library share a usable ${String(width)}px shell`, async ({ page }, testInfo) => {
        await page.setViewportSize({ width, height: 900 });
        const catalogs = {
            universes: { schema_version: 2, selection_kinds: [], registered_universes: [] },
            "dataset-fields": { schema_version: 2, dataset_fields: [] },
            calculations: { schema_version: 2, calculations: [] },
            statistics: { schema_version: 2, statistics: [] }
        };
        for (const [name, body] of Object.entries(catalogs)) {
            await page.route(`**/api/v2/research/catalog/${name}`, (route) =>
                route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify(body)
                })
            );
        }
        await page.goto("/data/inputs");
        await expect(
            page.getByRole("heading", { name: "Research Inputs", exact: true })
        ).toBeVisible();
        await expect(
            page.getByText("No registered universes are published.", { exact: true })
        ).toBeVisible();
        await noPageOverflow(page);
        await page.screenshot({ path: testInfo.outputPath("data-inputs.png"), fullPage: true });
        await page.getByRole("button", { name: "Toggle navigation" }).click();
        await page.getByRole("link", { name: "Research Library", exact: true }).click();
        await expect(page).toHaveURL("/research/library");
        await expect(
            page.getByRole("heading", { name: "Research Library", exact: true })
        ).toBeVisible();
        await expect(page.getByRole("button", { name: "Toggle navigation" })).toHaveAttribute(
            "aria-expanded",
            "false"
        );
        await noPageOverflow(page);
        await page.screenshot({
            path: testInfo.outputPath("research-library.png"),
            fullPage: true
        });
        await page.getByRole("button", { name: "Toggle navigation" }).click();
        await page.getByRole("link", { name: "Results", exact: true }).click();
        await expect(
            page.getByRole("heading", { name: "Open an exact Research result" })
        ).toBeVisible();
        await noPageOverflow(page);
    });
}
