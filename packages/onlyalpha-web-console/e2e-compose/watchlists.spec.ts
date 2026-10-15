import { expect, test } from "@playwright/test";

// Operates the actual Shipping UI and existing dev Authority; no API mocks/seeding.
test("Owner manages shared ordered Watchlists through Shipping UI", async ({
    page,
    browser
}, testInfo) => {
    await page.goto("/");
    const panel = page.getByRole("region", { name: "自选列表管理" });
    await expect(panel.getByLabel("新列表名称")).toBeVisible();
    // Explicitly stop the main chart while testing read-only list membership.
    await page.getByRole("combobox", { name: "数据源", exact: true }).selectOption("");
    const source = panel.getByLabel("列表行情来源");
    const option = source.getByRole("option").filter({ hasText: "Binance Spot" });
    await expect(option).toHaveCount(1);
    const sourceLabel = await option.innerText();
    const names = ["W4验收 日常20261015", "W4验收 趋势20261015"];
    let acquisitions = 0;
    page.on("request", (request) => {
        if (request.method() === "POST" && request.url().includes("/market-data/acquisitions"))
            acquisitions++;
    });
    for (const name of names) {
        await panel.getByLabel("新列表名称").fill(name);
        await source.selectOption({ label: sourceLabel });
        await panel.getByRole("button", { name: "创建列表", exact: true }).click();
        await expect(
            panel.getByLabel("自选列表").getByRole("option", { name, exact: true })
        ).toBeAttached();
    }
    const selected = panel.getByLabel("自选列表");
    await selected.selectOption({ label: names[0] });
    for (const symbol of ["BTCUSDT", "ETHUSDT"]) {
        await panel.getByLabel("搜索自选标的").fill(symbol);
        await panel.getByRole("button", { name: "查找标的", exact: true }).click();
        await panel.getByRole("button", { name: `加入 ${symbol}`, exact: true }).click();
        await expect(panel.getByRole("button", { name: "已加入", exact: true })).toBeDisabled();
    }
    await expect(panel.getByRole("row").filter({ hasText: "BTCUSDT.BINANCE" })).toHaveCount(1);
    await panel.getByRole("button", { name: "上移 ETHUSDT.BINANCE", exact: true }).click();
    await expect(panel.locator("tbody tr").first()).toContainText("ETHUSDT.BINANCE");
    await panel.getByLabel("列表新名称").fill("W4验收 已排序20261015");
    await panel.getByRole("button", { name: "重命名列表", exact: true }).click();
    await expect(
        selected.getByRole("option", { name: "W4验收 已排序20261015", exact: true })
    ).toBeAttached();
    // Removing our own membership and deleting our empty acceptance list uses the normal controls.
    await panel.getByRole("button", { name: "移除 BTCUSDT.BINANCE", exact: true }).click();
    await expect(panel.locator("tbody tr")).toHaveCount(1);
    await panel.getByLabel("搜索自选标的").fill("BTCUSDT");
    await panel.getByRole("button", { name: "查找标的", exact: true }).click();
    await panel.getByRole("button", { name: "加入 BTCUSDT", exact: true }).click();
    await expect(panel.locator("tbody tr")).toHaveCount(2);
    await selected.selectOption({ label: names[1] });
    page.once("dialog", (dialog) => void dialog.accept());
    await panel.getByRole("button", { name: "删除列表", exact: true }).click();
    await expect(selected.getByRole("option", { name: names[1], exact: true })).toHaveCount(0);
    await selected.selectOption({ label: "W4验收 已排序20261015" });
    expect(acquisitions).toBe(0);
    // A second authorized page reads the same committed server configuration.
    const otherContext = await browser.newContext();
    const other = await otherContext.newPage();
    await other.goto("/");
    const shared = other.getByRole("region", { name: "自选列表管理" });
    await shared.getByLabel("自选列表").selectOption({ label: "W4验收 已排序20261015" });
    await expect(shared.locator("tbody tr").first()).toContainText("ETHUSDT.BINANCE");
    await expect(shared.locator("tbody tr")).toHaveCount(2);
    await otherContext.close();
    await panel.locator("tbody tr").first().scrollIntoViewIfNeeded();
    await expect(panel.getByText(/已收盘历史|暂无已存历史|行情不可用/).first()).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("watchlists-shipping.png"), fullPage: true });
});

test("saved Watchlists and existing market history survive a real service restart", async ({
    page
}, testInfo) => {
    // Precondition: the preceding Shipping UI case created this book, then the operator
    // stopped and started the same dev service while retaining its existing stores.
    await page.goto("/");
    const panel = page.getByRole("region", { name: "自选列表管理" });
    await panel.getByLabel("自选列表").selectOption({ label: "W4验收 已排序20261015" });
    await expect(panel.locator("tbody tr")).toHaveCount(2);
    await expect(panel.locator("tbody tr").first()).toContainText("ETHUSDT.BINANCE");
    await expect(panel.locator("tbody tr").last()).toContainText("BTCUSDT.BINANCE");
    // Real dev trace: Source discovery + Instrument lookup + owning history proof take ~5 s.
    // Use the existing 10 s interaction budget for this sequential first-load pipeline.
    await expect(page.getByText(/历史投影 [0-9a-f]{12}/)).toBeVisible({ timeout: 10_000 });
    await panel.locator("tbody tr").first().scrollIntoViewIfNeeded();
    await expect(panel.getByText(/已收盘历史|暂无已存历史|行情不可用/).first()).toBeVisible();
    await page.screenshot({
        path: testInfo.outputPath("watchlists-after-restart.png"),
        fullPage: true
    });
});

test("native Watchlist preparation preserves chart settings", async ({ page }, testInfo) => {
    await page.goto("/");
    const panel = page.getByRole("region", { name: "自选列表管理" });
    await panel.getByLabel("自选列表").selectOption({ label: "W4验收 已排序20261015" });
    // Real dev trace: Source discovery + Instrument lookup + owning history proof take ~5 s.
    // Use the existing 10 s interaction budget for this sequential first-load pipeline.
    await expect(page.getByText(/历史投影 [0-9a-f]{12}/)).toBeVisible({ timeout: 10_000 });
    await page.getByRole("combobox", { name: "图表类型", exact: true }).selectOption("LINE");
    const ether = panel.locator("tbody tr").filter({ hasText: "ETHUSDT.BINANCE" });
    await ether.getByRole("button", { name: "准备 ETHUSDT.BINANCE 原生行情", exact: true }).click();
    // Measured real one-Bar acquisition takes 6.1 s; await its visible command outcome
    // under the existing 10 s interaction budget before asserting the read projection.
    await expect(
        ether.getByRole("button", { name: "准备 ETHUSDT.BINANCE 原生行情", exact: true })
    ).toBeEnabled({ timeout: 10_000 });
    await expect(ether).toContainText("原生准备请求已处理");
    await expect(ether).toContainText("已收盘历史 / 非实时成交价");
    await expect(ether.locator(".value")).not.toHaveText("—");
    await expect(page.getByRole("combobox", { name: "时间周期", exact: true })).toHaveValue("15");
    await expect(page.getByRole("combobox", { name: "图表类型", exact: true })).toHaveValue("LINE");
    await panel.getByRole("button", { name: "上移 BTCUSDT.BINANCE", exact: true }).click();
    await expect(panel.locator("tbody tr").first()).toContainText("BTCUSDT.BINANCE");
    await ether.getByRole("button", { name: "上移 ETHUSDT.BINANCE", exact: true }).click();
    await expect(panel.locator("tbody tr").first()).toContainText("ETHUSDT.BINANCE");
    await ether.scrollIntoViewIfNeeded();
    await page.screenshot({
        path: testInfo.outputPath("watchlists-native-preparation.png"),
        fullPage: true
    });
});

test("chart preparation remains explicit when a priced Watchlist member lacks chart history", async ({
    page
}, testInfo) => {
    // Measured preparation: exact lookup 2.3 s + planning 2.4 s + acquisition 8.4 s
    // + owning projection ~3 s. This is the real external acquisition interaction budget.
    test.setTimeout(40_000);
    await page.goto("/");
    const panel = page.getByRole("region", { name: "自选列表管理" });
    await panel.getByLabel("自选列表").selectOption({ label: "W4验收 已排序20261015" });
    await page.getByRole("combobox", { name: "图表类型", exact: true }).selectOption("LINE");
    const ether = panel.locator("tbody tr").filter({ hasText: "ETHUSDT.BINANCE" });
    let acquisitions = 0;
    page.on("request", (request) => {
        if (request.method() === "POST" && request.url().includes("/market-data/acquisitions"))
            acquisitions++;
    });
    await ether.getByRole("button", { name: "ETHUSDT.BINANCE", exact: true }).click();
    // The previous preparation now durably covers 15m. A normal period change after
    // read-only row selection establishes a new missing 30m chart window through UI.
    await expect(page.getByText("ETHUSDT · 15m", { exact: true })).toBeVisible();
    await page.getByRole("combobox", { name: "时间周期", exact: true }).selectOption("30");
    await expect(
        page.getByText("行情覆盖不足；请明确选择准备行情，本次选择不会自动采集").first()
    ).toBeVisible();
    expect(acquisitions).toBe(0);
    await ether.getByRole("button", { name: "准备 ETHUSDT.BINANCE 图表行情", exact: true }).click();
    // The measured explicit preparation pipeline is ~16 s, including owning reproof.
    await expect(page.getByText(/历史投影 [0-9a-f]{12}/)).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("combobox", { name: "时间周期", exact: true })).toHaveValue("30");
    await expect(page.getByRole("combobox", { name: "图表类型", exact: true })).toHaveValue("LINE");
    expect(acquisitions).toBeGreaterThan(0);
    await page.screenshot({
        path: testInfo.outputPath("watchlists-explicit-chart.png"),
        fullPage: true
    });
});
