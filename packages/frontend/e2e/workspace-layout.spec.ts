import { expect, test } from "@playwright/test";

// P1 工作台二分契约（docs/webui/design-brief-2026-11-10.md）：
// 桌面 = 280px 自选竖列 + 图表 + 图下"指标 / 因子"与"工作区"双卡并列；
// ≤880 单列，顺序 图表 → 指标行 → 自选；页面级零横向溢出。

test("1440 桌面二分：280px 自选竖列与图下双卡并列", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    const column = page.locator(".workspace-watch-column");
    await expect(column).toBeVisible();
    const columnBox = await column.boundingBox();
    expect(columnBox?.width).toBeCloseTo(280, 1);
    await expect(column.getByRole("region", { name: "自选行情" })).toBeVisible();
    const studiesCard = page.getByRole("region", { name: "指标", exact: true });
    const summaryCard = page.getByRole("region", {
        name: "工作区",
        exact: true
    });
    await expect(studiesCard).toBeVisible();
    await expect(summaryCard).toBeVisible();
    const studiesBox = await studiesCard.boundingBox();
    const summaryBox = await summaryCard.boundingBox();
    const chartBox = await page.getByRole("region", { name: "主图" }).boundingBox();
    expect(studiesBox).not.toBeNull();
    expect(summaryBox).not.toBeNull();
    expect(chartBox).not.toBeNull();
    // 双卡并列：顶边对齐；整体位于图表下方。
    expect(Math.abs((studiesBox?.y ?? 0) - (summaryBox?.y ?? 0))).toBeLessThan(4);
    expect((studiesBox?.y ?? 0) + 2).toBeGreaterThan((chartBox?.y ?? 0) + (chartBox?.height ?? 0));
    const toolsBox = await page.getByRole("toolbar", { name: "图表工具" }).boundingBox();
    expect(toolsBox).not.toBeNull();
    expect((columnBox?.x ?? 0) + (columnBox?.width ?? 0)).toBeLessThanOrEqual(toolsBox?.x ?? 0);
    expect((toolsBox?.x ?? 0) + (toolsBox?.width ?? 0)).toBeLessThanOrEqual(chartBox?.x ?? 0);
    await expect(page.getByRole("region", { name: "研究面板" })).toHaveCount(0);
    // 自选列在图表左侧。
    expect((columnBox?.x ?? 0) + (columnBox?.width ?? 0)).toBeLessThanOrEqual(chartBox?.x ?? 0);
    expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    ).toBe(true);
});

test("390 单列顺序：图表 → 指标行 → 自选，零横向溢出", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    const chartBox = await page.getByRole("region", { name: "主图" }).boundingBox();
    const studiesBox = await page.getByRole("region", { name: "指标", exact: true }).boundingBox();
    const summaryBox = await page
        .getByRole("region", { name: "工作区", exact: true })
        .boundingBox();
    const watchBox = await page.locator(".workspace-watch-column").boundingBox();
    expect(chartBox).not.toBeNull();
    expect(studiesBox).not.toBeNull();
    expect(summaryBox).not.toBeNull();
    expect(watchBox).not.toBeNull();
    expect((studiesBox?.y ?? 0) + 2).toBeGreaterThanOrEqual(
        (chartBox?.y ?? 0) + (chartBox?.height ?? 0)
    );
    // 单列下行序：指标行 → 工作区卡 → 自选。
    expect(summaryBox?.y ?? 0).toBeGreaterThanOrEqual(studiesBox?.y ?? 0);
    expect((watchBox?.y ?? 0) + 2).toBeGreaterThanOrEqual(
        (summaryBox?.y ?? 0) + (summaryBox?.height ?? 0)
    );
    await expect(page.getByRole("region", { name: "研究面板" })).toHaveCount(0);
    expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    ).toBe(true);
});

test("图下入口接既有目录与工作区 dialog", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await page
        .getByRole("region", { name: "指标", exact: true })
        .getByRole("button", { name: "目录" })
        .click();
    const catalog = page.getByRole("dialog", { name: "指标 / 因子目录" });
    await expect(catalog).toBeVisible();
    await expect(page.locator(".workspace-chart-toolbar .picker__trigger")).toHaveCount(0);
    await expect(catalog.getByRole("tab", { name: "指标", exact: true })).toHaveAttribute(
        "aria-selected",
        "true"
    );
    await expect(catalog.locator(".calculation-picker__entries > li")).toHaveCount(6);
    await catalog.getByRole("button", { name: "下一页" }).click();
    await expect(catalog.getByRole("button", { name: "上一页" })).toBeEnabled();
    await catalog.getByRole("button", { name: "下一页" }).click();
    await expect(catalog.getByRole("button", { name: "下一页" })).toBeDisabled();
    await catalog.getByRole("searchbox").fill("ATR");
    await expect(catalog.locator(".calculation-picker__entries > li")).toHaveCount(1);
    await expect(catalog.getByRole("button", { name: "上一页" })).toBeDisabled();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(catalog).toBeVisible();
    expect(await catalog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
        true
    );
    await page.getByRole("button", { name: "关闭目录" }).click();
    await expect(catalog).toHaveCount(0);
    // 本环境未配置行情来源：保存闸门诚实关闭（可保存 dialog 路径由单测覆盖）。
    await expect(
        page.getByRole("region", { name: "工作区" }).getByRole("button", { name: "保存副本" })
    ).toBeDisabled();
});

test("工作台响应式矩阵：控件不相交，页面无横向溢出", async ({ page }) => {
    await page.goto("/");
    for (const width of [390, 640, 768, 880, 1024, 1152, 1155, 1440]) {
        await page.setViewportSize({ width, height: 1240 });
        const watch = page.locator(".workspace-watch-column");
        const header = watch.locator(".watchlists__header");
        const add = header.getByRole("button", { name: "搜索并添加商品" });
        await expect(add).toBeVisible();
        const watchBox = await watch.boundingBox();
        const addBox = await add.boundingBox();
        expect(watchBox).not.toBeNull();
        expect(addBox).not.toBeNull();
        expect((addBox?.x ?? 0) + (addBox?.width ?? 0)).toBeLessThanOrEqual(
            (watchBox?.x ?? 0) + (watchBox?.width ?? 0)
        );
        expect(
            await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
        ).toBe(true);
        await expect(page.getByRole("region", { name: "研究面板" })).toHaveCount(0);
    }
});
