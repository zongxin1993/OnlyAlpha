import { expect, test, type Page } from "@playwright/test";

async function search(page: Page, symbol: string) {
    await page.getByRole("button", { name: "搜索商品", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "商品搜索", exact: true });
    await dialog.getByRole("searchbox", { name: "商品代码或名称" }).fill(symbol);
    return dialog;
}

// Actual Shipping dist, Owner cookie ingress, Product services, PG/CH and Binance
// parsers. Only external wire payloads and realtime delivery are controlled inputs.
// The fixture creates configured Sources, never Watchlists or market history.
test("search stars mixed Sources, quotes automatically, opens missing K lines and simplifies SMA", async ({
    page
}, testInfo) => {
    // Two searches/quote reads, three server-planned cold-history ranges and SMA/readback.
    test.setTimeout(60_000);
    const acquisitions: string[] = [];
    page.on("request", (request) => {
        if (request.method() === "POST" && request.url().includes("/market-data/acquisitions"))
            acquisitions.push(request.url());
    });
    await page.goto("/");
    const panel = page.getByRole("region", { name: "自选行情", exact: true });
    await expect(panel.getByText("还没有自选，在搜索结果中点 ☆ 添加。")).toBeVisible();
    await expect(panel.getByLabel("新列表名称")).not.toBeVisible();

    let dialog = await search(page, "BTC");
    const primary = dialog
        .getByRole("listitem")
        .filter({ hasText: "Chart acceptance Binance Spot" });
    await expect(primary).toHaveCount(1);
    await primary.getByRole("button", { name: "加入自选 BTCUSDT", exact: true }).click();
    await expect(
        primary.getByRole("button", { name: "移出自选 BTCUSDT", exact: true })
    ).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("Escape");
    const bitcoin = panel
        .getByRole("row")
        .filter({ has: page.getByRole("button", { name: "BTCUSDT", exact: true }) });
    await expect(bitcoin).toContainText("105.00");
    await expect(bitcoin).toContainText("2.50%");
    await expect(bitcoin).toHaveAttribute("title", /24小时变动/);
    expect(acquisitions).toHaveLength(0);
    await expect(panel.getByRole("columnheader")).toHaveText(["商品", "最新价", "涨跌幅"]);

    dialog = await search(page, "SOL");
    const alternate = dialog.getByRole("listitem").filter({ hasText: "Other Binance Spot" });
    await expect(alternate).toHaveCount(1);
    await alternate.getByRole("button", { name: "加入自选 SOLUSDT", exact: true }).click();
    await expect(
        alternate.getByRole("button", { name: "移出自选 SOLUSDT", exact: true })
    ).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("Escape");
    await expect(panel.getByRole("row").filter({ hasText: "Other Binance Spot" })).toContainText(
        "105.00"
    );
    expect(acquisitions).toHaveLength(0);

    await bitcoin.getByRole("button", { name: "BTCUSDT", exact: true }).click();
    // The initial 2000 x 15m viewport spans three acquisition ranges; the recorded first range
    // completes in about 3.3s. Wait for the final owning proof within a 20s cold-load budget.
    await expect(page.getByTestId("market-data-status")).toHaveAttribute("data-status", "ready", {
        timeout: 20_000
    });
    await expect(page.getByTestId("market-data-status")).toContainText("行情已加载");
    expect(acquisitions.length).toBeGreaterThan(0);
    await expect(page.getByRole("button", { name: /获取行情|准备.*行情/ })).toHaveCount(0);

    await page.getByRole("button", { name: "指标", exact: true }).click();
    await page.getByRole("button", { name: "选择 SMA · 配置草稿", exact: true }).click();
    const editor = page.getByRole("dialog", { name: "指标 / 因子参数配置", exact: true });
    await expect(editor.getByLabel("period", { exact: true })).toHaveValue("20");
    await expect(editor.getByLabel("线宽", { exact: true })).not.toBeVisible();
    await editor.getByText("高级选项", { exact: true }).click();
    await expect(editor.getByLabel("线宽", { exact: true })).toBeVisible();
    await editor.getByLabel("线宽", { exact: true }).fill("3");
    // Existing Chart Study contract permits a 10s evaluate exchange; rendering keeps its 5s limit.
    const evaluation = page.waitForResponse(
        (response) => response.url().endsWith("/api/v2/chart/studies/evaluate"),
        { timeout: 10_000 }
    );
    await editor.getByRole("button", { name: "添加", exact: true }).click();
    expect((await evaluation).status()).toBe(200);
    await expect(page.getByTestId("price-chart")).toHaveAttribute("data-study-series-count", "1");
    const chip = page.getByTestId("chart-study-instance");
    await expect(chip.getByRole("button", { name: "选择 SMA", exact: true })).toHaveText("SMA(20)");
    await expect(chip.getByText(/period=20/)).not.toBeVisible();
    await chip.getByLabel("配置详情 SMA", { exact: true }).click();
    await expect(chip.getByText(/period=20/)).toBeVisible();
    await chip.getByLabel("配置详情 SMA", { exact: true }).click();
    const queryStatus = page.getByTestId("chart-study-query-status");
    await expect(queryStatus.getByText(/DISPLAY_ONLY/)).not.toBeVisible();
    await queryStatus.getByText("指标查询详情", { exact: true }).click();
    await expect(queryStatus.getByText(/DISPLAY_ONLY/)).toBeVisible();
    await queryStatus.getByText("指标查询详情", { exact: true }).click();
    const hover = page.getByTestId("study-hover");
    await expect(hover.getByText(/onlyalpha.indicator.sma/)).not.toBeVisible();
    await hover.getByLabel("指标点详情 SMA", { exact: true }).click();
    await expect(hover.getByText(/onlyalpha.indicator.sma/)).toBeVisible();
    await hover.getByLabel("指标点详情 SMA", { exact: true }).click();
    await page.screenshot({
        path: testInfo.outputPath("symbol-search-watchlist-sma.png"),
        fullPage: true
    });

    await page.reload();
    await expect(panel.getByRole("button", { name: "BTCUSDT", exact: true })).toBeVisible();
    await expect(panel.getByRole("button", { name: "SOLUSDT", exact: true })).toBeVisible();
    await expect(panel.getByRole("row").filter({ hasText: "Other Binance Spot" })).toContainText(
        "105.00"
    );
    dialog = await search(page, "BTC");
    const retained = dialog
        .getByRole("listitem")
        .filter({ hasText: "Chart acceptance Binance Spot" });
    await retained.getByRole("button", { name: "移出自选 BTCUSDT", exact: true }).click();
    await expect(
        retained.getByRole("button", { name: "加入自选 BTCUSDT", exact: true })
    ).toHaveAttribute("aria-pressed", "false");
    await page.keyboard.press("Escape");
    await expect(panel.getByRole("button", { name: "BTCUSDT", exact: true })).toHaveCount(0);
    await page.reload();
    await expect(panel.getByRole("button", { name: "BTCUSDT", exact: true })).toHaveCount(0);
    await expect(panel.getByRole("button", { name: "SOLUSDT", exact: true })).toBeVisible();
});
