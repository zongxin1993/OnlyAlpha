import { expect, test } from "@playwright/test";

for (const width of [1381, 390]) {
    test(`native workspace toolbar and right icon navigation at ${String(width)}px`, async ({
        page
    }, testInfo) => {
        await page.setViewportSize({ width, height: 1187 });
        await page.goto("/");
        const toolbar = page
            .locator(".workspace-topbar")
            .getByRole("toolbar", { name: "图表工作条" });
        await expect(toolbar).toBeVisible();
        await expect(page.getByRole("link", { name: "OnlyAlpha 工作台" })).toHaveText("OA");
        const controls = toolbar.locator("button:visible, select:visible, summary:visible");
        await expect(controls).toHaveCount(8);
        expect(
            await controls.evaluateAll((nodes) =>
                nodes.map((node) => node.getAttribute("aria-label") ?? node.textContent)
            )
        ).toEqual([
            "搜索商品",
            "时间周期",
            "图表类型",
            "指标",
            "因子",
            "保存工作区",
            "载入工作区",
            "设置"
        ]);
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
        const navigation = page
            .locator(".global-workspace-rail")
            .getByRole("navigation", { name: "产品导航" });
        await expect(navigation.getByRole("link")).toHaveCount(6);
        await expect(page.locator(".workspace-save-state")).toHaveCount(0);
        // Native renderer geometry is presentation evidence, never market-data authority.
        await expect
            .poll(async () =>
                page.getByTestId("price-chart").evaluate((element) => {
                    const corner = element.querySelector("table tr:last-child td:last-child");
                    const timezone =
                        element.parentElement?.querySelector('[aria-label="显示时区"]');
                    if (!corner || !timezone) return Infinity;
                    const axis = corner.getBoundingClientRect(),
                        select = timezone.getBoundingClientRect();
                    return Math.max(
                        Math.abs(axis.x - select.x),
                        Math.abs(axis.y - select.y),
                        Math.abs(axis.width - select.width),
                        Math.abs(axis.height - select.height)
                    );
                })
            )
            .toBeLessThanOrEqual(1);
        const settingsBox = await toolbar.getByLabel("设置", { exact: true }).boundingBox();
        if (!settingsBox) throw new Error("Settings geometry required");
        expect(settingsBox.x + settingsBox.width).toBe(width);
        const periodBox = await toolbar.getByRole("combobox", { name: "时间周期" }).boundingBox();
        const typeBox = await toolbar.getByLabel("图表类型", { exact: true }).boundingBox();
        if (!periodBox || !typeBox) throw new Error("Independent control geometry required");
        expect(typeBox.x).toBeGreaterThan(periodBox.x + periodBox.width + 8);
        expect(
            Math.abs(settingsBox.y + settingsBox.height / 2 - (periodBox.y + periodBox.height / 2))
        ).toBeLessThanOrEqual(4);
        for (const type of ["收盘线", "蜡烛图"]) {
            await toolbar.getByLabel("图表类型", { exact: true }).click();
            const candleBox = await toolbar
                .getByRole("button", { name: "蜡烛图", exact: true })
                .boundingBox();
            const lineBox = await toolbar
                .getByRole("button", { name: "收盘线", exact: true })
                .boundingBox();
            if (!candleBox || !lineBox) throw new Error("Chart type list geometry required");
            expect(lineBox.y).toBeGreaterThanOrEqual(candleBox.y + candleBox.height);
            expect(lineBox.x).toBe(candleBox.x);
            const option = toolbar.getByRole("button", { name: type, exact: true });
            await expect(option).toHaveText("");
            await option.click();
            await expect(page.getByTestId("price-chart")).toHaveAttribute(
                "data-chart-type",
                type === "蜡烛图" ? "CANDLESTICK" : "LINE"
            );
            await expect(option).not.toBeVisible();
        }
        await toolbar.getByLabel("设置", { exact: true }).click();
        await toolbar.getByText("行情设置", { exact: true }).click();
        await expect(toolbar.getByRole("combobox", { name: "数据源", exact: true })).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(toolbar.getByLabel("设置", { exact: true })).toBeFocused();
        await toolbar.getByRole("button", { name: "载入工作区", exact: true }).click();
        await expect(page.getByRole("dialog", { name: "载入工作区" })).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(
            toolbar.getByRole("button", { name: "载入工作区", exact: true })
        ).toBeFocused();
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
        const right = await page.locator(".global-workspace-rail").boundingBox();
        const search = await toolbar
            .getByRole("button", { name: "搜索商品", exact: true })
            .boundingBox();
        if (!rail || !right || !search)
            throw new Error("Expected visible rail and search geometry");
        expect(rail.width).toBe(50);
        expect(right.width).toBe(50);
        expect(search.x).toBe(rail.x + rail.width);
        expect(
            await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
        ).toBe(true);
        await page.screenshot({
            path: testInfo.outputPath(`workspace-toolbar-${String(width)}.png`)
        });
    });
}
