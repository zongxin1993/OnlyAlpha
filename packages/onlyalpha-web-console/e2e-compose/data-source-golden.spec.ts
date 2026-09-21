import { expect, test, type Page } from "@playwright/test";

const scenario = async (page: Page, value: string) => {
    const response = await page.request.put(`http://binance-probe-fixture:8080/scenario/${value}`);
    expect(response.ok(), await response.text()).toBeTruthy();
};

const inspectorValue = (page: Page, label: string) =>
    page
        .getByLabel("Operational inspector")
        .locator("dt", { hasText: new RegExp(`^${label}$`) })
        .locator("xpath=following-sibling::dd[1]");

const publish = async (page: Page) => {
    await page.getByRole("button", { name: "Publish", exact: true }).click();
    await expect(page.getByRole("button", { name: "Publish", exact: true })).toBeEnabled();
};

const probe = async (page: Page, expected: string) => {
    await page.getByRole("button", { name: "Test connection" }).click();
    await expect(inspectorValue(page, "Operational Status")).toHaveText(expected);
};

test("Binance Spot Data Source preserves exact-Revision probe evidence", async ({ page }) => {
    await scenario(page, "ALL_PASS");
    await page.goto("/data/sources/new");
    await page.getByLabel("Data Source type").selectOption("binance.spot.market_data");
    await page.getByLabel("Display name").fill("Golden Binance Spot");
    await page.getByRole("button", { name: "Create Data Source" }).click();
    await expect(page.getByRole("heading", { name: "Golden Binance Spot" })).toBeVisible();

    await page.getByText("Advanced settings").click();
    await page.getByLabel("Request timeout").fill("10");
    await page.getByRole("button", { name: "Save Draft" }).click();
    await expect(page.getByRole("button", { name: "Save Draft" })).toBeEnabled();
    await publish(page);
    await expect(inspectorValue(page, "Operational Status")).toHaveText("UNKNOWN");
    const revision1 = await inspectorValue(page, "Current Revision").textContent();
    expect(revision1).toMatch(/^[0-9a-f]{64}$/);

    await probe(page, "READY");
    await page.reload();
    await expect(inspectorValue(page, "Current Revision")).toHaveText(revision1 ?? "");
    await expect(inspectorValue(page, "Operational Status")).toHaveText("READY");

    await page.getByText("Advanced settings").click();
    await page.getByLabel("Request timeout").fill("5");
    await page.getByRole("button", { name: "Save Draft" }).click();
    await expect(page.getByRole("button", { name: "Save Draft" })).toBeEnabled();
    await publish(page);
    await expect(inspectorValue(page, "Operational Status")).toHaveText("UNKNOWN");
    const revision2 = await inspectorValue(page, "Current Revision").textContent();
    expect(revision2).toMatch(/^[0-9a-f]{64}$/);
    expect(revision2).not.toBe(revision1);
    await expect(page.getByRole("table").getByText("READY", { exact: true })).toBeVisible();

    await probe(page, "READY");
    await scenario(page, "REALTIME_FAIL");
    await probe(page, "DEGRADED");
    await scenario(page, "OFFLINE");
    await probe(page, "OFFLINE");
    await scenario(page, "INVALID_SCHEMA");
    await probe(page, "FAILED");
    await scenario(page, "ALL_PASS");
    await probe(page, "READY");
});
