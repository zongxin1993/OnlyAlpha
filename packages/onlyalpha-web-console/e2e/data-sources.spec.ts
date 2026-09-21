import { expect, test, type Page } from "@playwright/test";

const id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const revision = "a".repeat(64);
const integration = {
    schema_version: 1,
    integration_id: id,
    type_id: "test.market_data",
    display_name: "Local Market Data",
    lifecycle_state: "ACTIVE",
    current_revision_fingerprint: revision,
    created_at: "2026-09-21T00:00:00Z",
    updated_at: "2026-09-21T00:00:00Z"
};
const descriptor = {
    schema_version: 1,
    type_id: "test.market_data",
    category: "DATA_SOURCE",
    display_name: "Local Market Data",
    description: "Deterministic browser fixture",
    provider_id: "test",
    implementation_id: "test",
    implementation_version: "1",
    public_api_version: "1.1",
    capabilities: ["HISTORICAL_BARS"],
    fingerprint: "b".repeat(64),
    configuration_contract: {
        schema_version: 1,
        fingerprint: "c".repeat(64),
        fields: []
    },
    probe_contract: null
};

async function mockDataSources(page: Page) {
    await page.route("**/api/v2/integrations", (route) =>
        route.fulfill({
            contentType: "application/json",
            body: JSON.stringify({
                items: [
                    {
                        ...integration,
                        category: "DATA_SOURCE",
                        draft_version: 1,
                        pinned_type_descriptor_fingerprint: descriptor.fingerprint
                    }
                ]
            })
        })
    );
    await page.route(`**/api/v2/integrations/${id}/operational-status`, (route) =>
        route.fulfill({
            contentType: "application/json",
            body: JSON.stringify({
                schema_version: 1,
                integration_id: id,
                revision_fingerprint: revision,
                status: "UNKNOWN",
                probe_attempt_id: null,
                checked_at: null,
                probe_supported: false
            })
        })
    );
    await page.route("**/api/v2/integration-types?category=DATA_SOURCE", (route) =>
        route.fulfill({
            contentType: "application/json",
            body: JSON.stringify({ items: [descriptor] })
        })
    );
}

for (const width of [1440, 390]) {
    test(`Data Sources navigation and schema-driven Add page at ${String(width)}px`, async ({
        page
    }) => {
        await page.setViewportSize({ width, height: 900 });
        await mockDataSources(page);
        await page.goto("/data/sources");
        await expect(page.getByRole("heading", { name: "Data Sources" })).toBeVisible();
        await expect(page.getByRole("link", { name: "Local Market Data" })).toBeVisible();
        await expect(page.getByText("UNKNOWN", { exact: true })).toBeVisible();
        await expect
            .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
            .toBe(true);
        await page.getByRole("link", { name: "Add Data Source" }).click();
        await expect(page.getByRole("heading", { name: "Add Data Source" })).toBeVisible();
        await page.getByLabel("Data Source type").selectOption("test.market_data");
        await expect(page.getByLabel("Data Source type")).toHaveValue("test.market_data");
        if (width < 700) {
            await page.getByRole("button", { name: "Toggle navigation" }).click();
            await expect(page.getByRole("link", { name: "Data Sources" })).toBeVisible();
        }
    });
}
