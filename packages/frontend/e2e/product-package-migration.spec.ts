import { expect, test, type Page } from "@playwright/test";

// Real Shipping UI and canonical native owners; no mocked Product responses.
async function openSources(page: Page) {
    await page.getByLabel("设置", { exact: true }).click();
    await page
        .locator(".workspace-settings")
        .getByRole("button", { name: "管理数据源", exact: true })
        .click();
    return page.getByRole("dialog", { name: "管理数据源" });
}

test("native watchlist creation and rename survive a normal page reload", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    const watchlists = page.getByRole("region", { name: "自选行情" });
    await watchlists.getByLabel("管理自选列表").click();
    await watchlists.getByLabel("新列表名称").fill("迁移验收自选");
    await watchlists.getByRole("button", { name: "创建列表", exact: true }).click();
    await expect(watchlists.getByRole("status")).toHaveText("已保存");
    await page.reload();
    await expect(watchlists.getByLabel("自选列表", { exact: true })).toContainText("迁移验收自选");
    await watchlists
        .getByLabel("自选列表", { exact: true })
        .selectOption({ label: "迁移验收自选" });
    await watchlists.getByLabel("管理自选列表").click();
    await watchlists.getByLabel("列表新名称").fill("迁移验收已保存");
    await watchlists.getByRole("button", { name: "重命名列表", exact: true }).click();
    await expect(watchlists.getByRole("status")).toHaveText("已保存");
    await page.reload();
    await expect(watchlists.getByLabel("自选列表", { exact: true })).toContainText(
        "迁移验收已保存"
    );
});

test("native Source creation, draft save and publication survive reload without market access", async ({
    page
}) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    let manager = await openSources(page);
    await manager.getByRole("tab", { name: "添加数据源", exact: true }).click();
    await manager.getByRole("button", { name: /Binance Spot Market Data/ }).click();
    await manager.getByLabel("显示名称").fill("迁移验收数据源");
    await manager.getByRole("button", { name: "创建数据源", exact: true }).click();
    await expect(
        manager.getByRole("heading", { name: "迁移验收数据源", exact: true })
    ).toBeVisible();
    await manager.getByRole("button", { name: "保存草稿", exact: true }).click();
    await expect(manager.getByText(/草稿 v2/)).toBeVisible();
    await manager.getByRole("button", { name: "发布 Revision", exact: true }).click();
    await expect(manager.getByText(/^R1 ·/)).toBeVisible();
    await page.reload();
    manager = await openSources(page);
    await manager
        .getByRole("article", { name: "迁移验收数据源", exact: true })
        .getByRole("button", { name: "配置", exact: true })
        .click();
    await expect(
        manager.getByRole("heading", { name: "迁移验收数据源", exact: true })
    ).toBeVisible();
    await expect(manager.getByText(/^R1 ·/)).toBeVisible();
});
