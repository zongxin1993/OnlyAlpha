import { expect, test, type Page } from "@playwright/test";

const scenario = async (page: Page, value: string) => {
    const response = await page.request.put(`http://binance-probe-fixture:8080/scenario/${value}`);
    expect(response.ok(), await response.text()).toBeTruthy();
};

const inspectorValue = (page: Page, label: string) =>
    page
        .getByLabel("运行状态")
        .locator("dt", { hasText: new RegExp(`^${label}$`) })
        .locator("xpath=following-sibling::dd[1]");

const publish = async (page: Page) => {
    await page.getByRole("button", { name: "发布 Revision", exact: true }).click();
    await expect(page.getByRole("button", { name: "发布 Revision", exact: true })).toBeEnabled();
};

const probe = async (page: Page, expected: string) => {
    const action = page.getByRole("button", { name: "测试连接" });
    await action.click();
    await expect(action).toBeEnabled({ timeout: 30_000 });
    await expect(inspectorValue(page, "运行状态")).toContainText(expected, { timeout: 30_000 });
};

test("Binance Spot Data Source preserves exact-Revision probe evidence", async ({ page }) => {
    test.setTimeout(120_000);
    await scenario(page, "ALL_PASS");
    await page.goto("/data/sources/new");
    await page.getByRole("button", { name: /Binance Spot Market Data/ }).click();
    await page.getByLabel("显示名称").fill("Golden Binance Spot");
    const created = page.waitForResponse(
        (response) =>
            response.url().endsWith("/api/v2/integrations") &&
            response.request().method() === "POST"
    );
    await page.getByRole("button", { name: "创建数据源" }).click();
    const createdPayload = (await (await created).json()) as { integration_id: string };
    await expect(page.getByRole("heading", { name: "Golden Binance Spot" })).toBeVisible();
    const id = createdPayload.integration_id;

    await page.getByLabel("Request timeout").fill("10");
    await page.getByRole("button", { name: "保存草稿" }).click();
    await expect(page.getByRole("button", { name: "保存草稿" })).toBeEnabled();
    await publish(page);
    await expect(inspectorValue(page, "运行状态")).toContainText("UNKNOWN");
    const revision1 = await inspectorValue(page, "当前 Revision").textContent();
    expect(revision1).toMatch(/^[0-9a-f]{64}$/);

    await probe(page, "READY");
    await page.goto(`/data/sources/${id}`);
    await page.reload();
    await expect(inspectorValue(page, "当前 Revision")).toHaveText(revision1 ?? "");
    await expect(inspectorValue(page, "运行状态")).toContainText("READY");

    await page.getByLabel("Request timeout").fill("5");
    await page.getByRole("button", { name: "保存草稿" }).click();
    await expect(page.getByRole("button", { name: "保存草稿" })).toBeEnabled();
    await publish(page);
    await expect(inspectorValue(page, "运行状态")).toContainText("UNKNOWN");
    const revision2 = await inspectorValue(page, "当前 Revision").textContent();
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
