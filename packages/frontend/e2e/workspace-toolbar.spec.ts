import { expect, test } from "@playwright/test";

// 壳迁移 + e14e22c8 工具条整合后的真实契约：
// 工作条固定六控件；设置走侧栏"全局设置"抽屉；保存/载入走"工作区"下拉；
// 顶栏不再整幅占满，右栏成为可空面板宿主。
for (const width of [1381, 390]) {
    test(`native workspace toolbar and left rail navigation at ${String(width)}px`, async ({
        page
    }, testInfo) => {
        await page.setViewportSize({ width, height: 1187 });
        await page.goto("/");
        const toolbar = page
            .locator(".workspace-topbar")
            .getByRole("toolbar", { name: "图表工作条" });
        await expect(toolbar).toBeVisible();
        await expect(page.getByRole("link", { name: "OnlyAlpha 工作台" })).toContainText("OA");
        // e14e22c8 起保存/载入合并进"工作区"下拉、图表设置移入全局设置抽屉；工作条固定六个控件。
        const controls = toolbar.locator("button:visible, select:visible, summary:visible");
        await expect(controls).toHaveCount(6);
        expect(
            await controls.evaluateAll((nodes) =>
                nodes.map((node) => node.getAttribute("aria-label") ?? node.textContent)
            )
        ).toEqual(["搜索商品", "时间周期", "图表类型", "指标", "因子", "工作区"]);
        await expect(toolbar.getByRole("option", { name: "1 分钟", exact: true })).toHaveAttribute(
            "value",
            "1"
        );
        await expect(toolbar.getByRole("option", { name: "1 小时", exact: true })).toHaveAttribute(
            "value",
            "60"
        );
        await expect(page.getByRole("button", { name: /展开工具条|收起工具条/ })).toHaveCount(0);
        await expect(page.getByText("Control + Presentation", { exact: true })).toHaveCount(0);
        await expect(page.getByText("临时行情 · 仅内存", { exact: true })).toHaveCount(0);
        await expect(page.locator(".data-source-entry")).toHaveCount(0);
        const navigation = page.locator(".side-rail").getByRole("navigation", { name: "产品导航" });
        await expect(navigation.getByRole("link")).toHaveCount(7);
        await expect(page.locator(".workspace-save-state")).toHaveCount(0);
        // 时区控件与纵轴同列对齐（水平契约；垂直由控件高度自适应）。
        await expect
            .poll(async () =>
                page.getByTestId("price-chart").evaluate((element) => {
                    const corner = element.querySelector("table tr:last-child td:last-child");
                    const timezone =
                        element.parentElement?.querySelector('[aria-label="显示时区"]');
                    if (!corner || !timezone) return Infinity;
                    const axis = corner.getBoundingClientRect();
                    const select = timezone.getBoundingClientRect();
                    return Math.max(
                        Math.abs(axis.x - select.x),
                        Math.abs(axis.width - select.width)
                    );
                })
            )
            .toBeLessThanOrEqual(1);
        for (const type of ["蜡烛图", "收盘线"]) {
            await toolbar.getByLabel("图表类型", { exact: true }).click();
            const option = page.getByRole("menuitem", { name: type, exact: true });
            await expect(option).toBeVisible();
            await option.click();
            await expect(page.getByTestId("price-chart")).toHaveAttribute(
                "data-chart-type",
                type === "蜡烛图" ? "CANDLESTICK" : "LINE"
            );
        }
        // 图表设置与数据源管理都在全局设置抽屉内（左侧栏入口；窄屏先开导航抽屉）。
        const drawer = width <= 900;
        if (drawer) {
            await page.getByRole("button", { name: "开启导航" }).click();
        }
        await page.getByRole("button", { name: "全局设置" }).click();
        const settings = page.getByRole("dialog");
        await expect(settings.getByRole("tab", { name: "图表", exact: true })).toHaveAttribute(
            "aria-selected",
            "true"
        );
        await settings.getByRole("tab", { name: "数据源", exact: true }).click();
        await expect(settings.getByRole("heading", { name: "管理数据源" })).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(settings).toHaveCount(0);
        if (drawer) {
            // 关闭设置后导航抽屉仍在，收起后才可操作工作条。
            await page.keyboard.press("Escape");
            await expect(page.locator("body")).not.toHaveClass(/rail-open/);
        }
        // 载入工作区走"工作区"下拉。
        await toolbar.getByRole("button", { name: "工作区", exact: true }).click();
        await page.getByRole("menuitem", { name: "载入工作区" }).click();
        const loadDialog = page.getByRole("dialog", { name: "载入工作区" });
        await expect(loadDialog).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(loadDialog).toHaveCount(0);
        for (const name of ["搜索商品", "指标", "因子"]) {
            await toolbar.getByRole("button", { name, exact: true }).click();
            await expect(
                page.getByRole("dialog", {
                    name: name === "搜索商品" ? "商品搜索" : "指标 / 因子目录"
                })
            ).toBeVisible();
            await page.keyboard.press("Escape");
            await expect(toolbar.getByRole("button", { name, exact: true })).toBeFocused();
        }
        const rail = await page.getByRole("toolbar", { name: "图表工具" }).boundingBox();
        if (!rail) throw new Error("Expected visible chart tool rail");
        expect(rail.width).toBe(50);
        // 新壳右侧栏是工作区面板宿主：收纳图表工具托盘后为固定细栏，不侵占工作区。
        const right = await page.locator(".global-workspace-rail").boundingBox();
        if (!right) throw new Error("Expected workspace rail host");
        expect(right.width).toBeLessThanOrEqual(38);
        expect(
            await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
        ).toBe(true);
        await page.screenshot({
            path: testInfo.outputPath(`workspace-toolbar-${String(width)}.png`)
        });
    });
}
