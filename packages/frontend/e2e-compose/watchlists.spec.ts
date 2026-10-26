import { expect, test, type Locator, type Page } from "@playwright/test";

// Actual Shipping UI and existing dev Authority; no API mocks, seeding or data resets.
const savedName = "W4验收 已排序20261015";
const temporaryNames = ["W4验收 日常20261015", "W4验收 趋势20261015"];
const panelFor = (page: Page) => page.getByRole("region", { name: "自选行情" });
const rowFor = (page: Page, symbol: string) =>
    panelFor(page)
        .locator("tbody tr")
        .filter({
            has: page.getByRole("button", { name: symbol, exact: true })
        });

async function sourceControl(page: Page) {
    const control = page.getByRole("combobox", { name: "数据源", exact: true });
    if (!(await control.isVisible())) await page.getByText("行情设置", { exact: true }).click();
    return control;
}

async function listMenu(panel: Locator, open = true) {
    const menu = panel.locator("details.watchlists__manage");
    if (((await menu.getAttribute("open")) !== null) !== open)
        await menu.getByLabel("管理自选列表", { exact: true }).click();
}

async function rowAction(page: Page, symbol: string, action: string) {
    const row = rowFor(page, symbol);
    const control = row.getByRole("button", { name: action, exact: true });
    if (!(await control.isVisible()))
        await row.getByLabel(`管理 ${symbol}.BINANCE`, { exact: true }).click();
    await control.click();
    if (action !== "移出自选")
        await row.getByLabel(`管理 ${symbol}.BINANCE`, { exact: true }).click();
}

async function star(page: Page, symbol: string, sourceName: string) {
    await panelFor(page).getByRole("button", { name: "搜索并添加商品", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "商品搜索" });
    await dialog.getByRole("searchbox", { name: "商品代码或名称" }).fill(symbol);
    const result = dialog.getByRole("listitem").filter({
        has: page.getByRole("button", {
            name: `查看 ${symbol} · BINANCE · ${sourceName}`,
            exact: true
        })
    });
    await result.getByRole("button", { name: `加入自选 ${symbol}`, exact: true }).click();
    await expect(
        result.getByRole("button", { name: `移出自选 ${symbol}`, exact: true })
    ).toHaveAttribute("aria-pressed", "true");
    await dialog.getByRole("button", { name: "关闭商品搜索", exact: true }).click();
}

async function openInspector(page: Page) {
    await page
        .getByRole("toolbar", { name: "工作区面板" })
        .getByRole("button", { name: "检查器", exact: true })
        .click();
    return page.getByRole("table", { name: "行情检查器" });
}

async function openWatchlist(page: Page) {
    await page
        .getByRole("complementary", { name: "上下文面板" })
        .getByRole("button", { name: "自选", exact: true })
        .click();
    await panelFor(page).getByLabel("自选列表", { exact: true }).selectOption({ label: savedName });
}

// The named lists are created only by this case. Existing names cause an explicit
// precondition failure; they are never silently adopted, overwritten or deleted.
test("Owner manages shared ordered Watchlists through Shipping UI", async ({
    page,
    browser
}, testInfo) => {
    await page.goto("/");
    const panel = panelFor(page);
    await listMenu(panel);
    await expect(panel.getByLabel("新列表名称")).toBeEnabled();
    for (const name of [...temporaryNames, savedName])
        await expect(panel.getByRole("option", { name, exact: true })).toHaveCount(0);
    const source = await sourceControl(page);
    const option = source.getByRole("option").filter({ hasText: "Binance Spot" });
    await expect(option).toHaveCount(1);
    const sourceLabel = await option.innerText();
    const sourceName = sourceLabel.split(" · ").slice(0, -1).join(" · ");
    expect(sourceName).not.toBe("");
    // Stop the main chart before observing that stars/quotes acquire no K-line history.
    await source.selectOption("");
    await expect(page.getByTestId("market-data-status")).toHaveAttribute(
        "data-loaded-bar-count",
        "0"
    );
    let acquisitions = 0;
    page.on("request", (request) => {
        if (request.method() === "POST" && request.url().includes("/market-data/acquisitions"))
            acquisitions++;
    });
    for (const name of temporaryNames) {
        await panel.getByLabel("新列表名称").fill(name);
        await panel.getByRole("button", { name: "创建列表", exact: true }).click();
        await expect(
            panel.getByLabel("自选列表").getByRole("option", { name, exact: true })
        ).toBeAttached();
    }
    await listMenu(panel, false);
    const selected = panel.getByLabel("自选列表");
    await selected.selectOption({ label: temporaryNames[0] });
    for (const symbol of ["BTCUSDT", "ETHUSDT"]) await star(page, symbol, sourceName);
    await expect(rowFor(page, "BTCUSDT")).toHaveCount(1);
    await rowAction(page, "ETHUSDT", "上移");
    await expect(
        panel.locator("tbody tr").first().getByRole("button", { name: "ETHUSDT", exact: true })
    ).toBeVisible();
    await listMenu(panel);
    await panel.getByLabel("列表新名称").fill(savedName);
    await panel.getByRole("button", { name: "重命名列表", exact: true }).click();
    await expect(selected.getByRole("option", { name: savedName, exact: true })).toBeAttached();
    await listMenu(panel, false);
    await rowAction(page, "BTCUSDT", "移出自选");
    await expect(panel.locator("tbody tr")).toHaveCount(1);
    await star(page, "BTCUSDT", sourceName);
    await expect(panel.locator("tbody tr")).toHaveCount(2);
    await selected.selectOption({ label: temporaryNames[1] });
    await listMenu(panel);
    page.once("dialog", (dialog) => void dialog.accept());
    await panel.getByRole("button", { name: "删除列表", exact: true }).click();
    await expect(
        selected.getByRole("option", { name: temporaryNames[1], exact: true })
    ).toHaveCount(0);
    await selected.selectOption({ label: savedName });
    await listMenu(panel, false);
    expect(acquisitions).toBe(0);
    await expect(panel.getByRole("columnheader")).toHaveText(["商品", "最新价", "涨跌幅"]);
    const otherContext = await browser.newContext();
    try {
        const other = await otherContext.newPage();
        await other.goto("/");
        const shared = panelFor(other);
        await shared.getByLabel("自选列表").selectOption({ label: savedName });
        await expect(
            shared.locator("tbody tr").first().getByRole("button", { name: "ETHUSDT", exact: true })
        ).toBeVisible();
        await expect(shared.locator("tbody tr")).toHaveCount(2);
    } finally {
        await otherContext.close();
    }
    await page.screenshot({ path: testInfo.outputPath("watchlists-shipping.png"), fullPage: true });
});

test("saved Watchlists and existing history remain readable after an externally performed service restart", async ({
    page
}, testInfo) => {
    // Required external precondition: the prior case saved this exact list, then
    // the operator stopped/started the same dev services retaining their stores.
    // This browser case proves the reader; it cannot alone certify that restart.
    let acquisitions = 0;
    page.on("request", (request) => {
        if (request.method() === "POST" && request.url().includes("/market-data/acquisitions"))
            acquisitions++;
    });
    const existingHistory = page.waitForResponse(
        (response) =>
            new URL(response.url()).pathname === "/api/v2/market-data/bars" &&
            response.request().method() === "GET"
    );
    await page.goto("/");
    await panelFor(page).getByLabel("自选列表").selectOption({ label: savedName });
    await expect(panelFor(page).locator("tbody tr")).toHaveCount(2);
    await expect(
        panelFor(page)
            .locator("tbody tr")
            .first()
            .getByRole("button", { name: "ETHUSDT", exact: true })
    ).toBeVisible();
    await expect(
        panelFor(page)
            .locator("tbody tr")
            .last()
            .getByRole("button", { name: "BTCUSDT", exact: true })
    ).toBeVisible();
    const response = await existingHistory;
    expect(response.ok()).toBe(true);
    const history = (await response.json()) as {
        coverage: { status: string };
        bars: unknown[];
        revision_evidence: unknown[];
        history_projection_fingerprint: string;
    };
    expect(history.coverage.status).toBe("COMPLETE");
    expect(history.bars.length).toBeGreaterThan(0);
    expect(history.revision_evidence.length).toBeGreaterThan(0);
    expect(acquisitions).toBe(0);
    const inspector = await openInspector(page);
    await expect(
        inspector.getByRole("cell", { name: history.history_projection_fingerprint, exact: true })
    ).toBeVisible({ timeout: 10_000 });
    await testInfo.attach("existing-owning-history-after-restart", {
        contentType: "application/json",
        body: JSON.stringify(history)
    });
    await page.screenshot({
        path: testInfo.outputPath("watchlists-after-restart.png"),
        fullPage: true
    });
});

test("visible Watchlist quotes are read-only and row selection preserves chart settings", async ({
    page
}, testInfo) => {
    await page.goto("/");
    await (await sourceControl(page)).selectOption("");
    await expect(page.getByTestId("market-data-status")).toHaveAttribute(
        "data-loaded-bar-count",
        "0"
    );
    let acquisitions = 0;
    page.on("request", (request) => {
        if (request.method() === "POST" && request.url().includes("/market-data/acquisitions"))
            acquisitions++;
    });
    await openInspector(page);
    const quoteReply = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return (
            url.pathname === "/api/v2/market-data/quotes" &&
            url.searchParams.getAll("instrument_ids").includes("ETHUSDT.BINANCE")
        );
    });
    await openWatchlist(page);
    const ether = rowFor(page, "ETHUSDT");
    await ether.scrollIntoViewIfNeeded();
    const response = await quoteReply;
    expect(response.ok()).toBe(true);
    const quotes = (await response.json()) as {
        quotes: {
            instrument_id: string;
            status: string;
            last_price: string | null;
            change_pct: string | null;
            change_basis: string | null;
        }[];
    };
    const quote = quotes.quotes.find((item) => item.instrument_id === "ETHUSDT.BINANCE");
    if (quote === undefined) throw new Error("Missing exact ETHUSDT quote");
    expect(quote.status).toBe("AVAILABLE");
    expect(quote.last_price).not.toBeNull();
    expect(quote.change_basis).toBe("ROLLING_24H");
    await expect(ether.locator(".value")).not.toHaveText("—");
    expect(await ether.getAttribute("title")).toContain(
        `原始报价 ${quote.last_price ?? "missing"}`
    );
    const displayed = await ether.locator(".value").innerText();
    if (quote.last_price === null) throw new Error("Missing exact quote price");
    if (/[eE]/.test(quote.last_price)) expect(displayed).toBe(quote.last_price);
    else {
        expect(displayed).toMatch(/^-?\d+\.\d{2,}$/);
        const [integer, fraction = ""] = quote.last_price.split(".");
        const [shownInteger, shownFraction = ""] = displayed.split(".");
        expect(shownInteger).toBe(integer);
        const precision = Math.max(fraction.length, shownFraction.length);
        expect(shownFraction.padEnd(precision, "0")).toBe(fraction.padEnd(precision, "0"));
    }
    if (quote.change_pct === null) throw new Error("Missing Binance 24h change percentage");
    await expect(ether.getByRole("cell").last()).toHaveText(`${quote.change_pct}%`);
    await expect(ether).toHaveAttribute("title", /24小时变动/);
    expect(acquisitions).toBe(0);
    await expect(ether.getByRole("cell")).toHaveCount(3);
    await page.getByRole("combobox", { name: "图表类型", exact: true }).selectOption("LINE");
    await ether.getByRole("button", { name: "ETHUSDT", exact: true }).click();
    await expect(page.getByTestId("market-data-status")).toHaveAttribute("data-status", "ready", {
        timeout: 20_000
    });
    await expect(page.getByRole("combobox", { name: "时间周期", exact: true })).toHaveValue("15");
    await expect(page.getByRole("combobox", { name: "图表类型", exact: true })).toHaveValue("LINE");
    await rowAction(page, "BTCUSDT", "上移");
    await expect(
        panelFor(page)
            .locator("tbody tr")
            .first()
            .getByRole("button", { name: "BTCUSDT", exact: true })
    ).toBeVisible();
    await rowAction(page, "ETHUSDT", "上移");
    await expect(
        panelFor(page)
            .locator("tbody tr")
            .first()
            .getByRole("button", { name: "ETHUSDT", exact: true })
    ).toBeVisible();
    await page.screenshot({
        path: testInfo.outputPath("watchlists-quotes-and-chart.png"),
        fullPage: true
    });
});

test("Watchlist row and period selection automatically load history without preparation controls", async ({
    page
}, testInfo) => {
    test.setTimeout(40_000);
    await page.goto("/");
    await openWatchlist(page);
    await page.getByRole("combobox", { name: "图表类型", exact: true }).selectOption("LINE");
    await rowFor(page, "ETHUSDT").getByRole("button", { name: "ETHUSDT", exact: true }).click();
    await expect(page.getByTestId("market-data-status")).toHaveAttribute("data-status", "ready", {
        timeout: 20_000
    });
    const acquisitionRequests: {
        instrument_id: string;
        start_ns: string;
        end_ns: string;
        bar_semantic: unknown;
    }[] = [];
    page.on("request", (request) => {
        if (
            request.method() === "POST" &&
            new URL(request.url()).pathname === "/api/v2/market-data/acquisitions"
        )
            acquisitionRequests.push(
                request.postDataJSON() as (typeof acquisitionRequests)[number]
            );
    });
    const initialWindow = page.waitForResponse((response) => {
        const url = new URL(response.url());
        const raw = url.searchParams.get("bar_semantic");
        return (
            url.pathname === "/api/v2/market-data/bars" &&
            raw !== null &&
            (JSON.parse(raw) as { formation: { window_minutes: number } }).formation
                .window_minutes === 30
        );
    });
    await page.getByRole("combobox", { name: "时间周期", exact: true }).selectOption("30");
    const response = await initialWindow;
    expect(response.ok()).toBe(true);
    const planned = (await response.json()) as {
        bar_semantic: unknown;
        coverage: {
            status: string;
            planned_acquisition_ranges: { start_ns: string; end_ns: string }[];
        };
    };
    await expect(page.getByTestId("market-data-status")).toHaveAttribute("data-status", "ready", {
        timeout: 20_000
    });
    if (planned.coverage.status === "INCOMPLETE") {
        expect(planned.coverage.planned_acquisition_ranges.length).toBeGreaterThan(0);
        expect(acquisitionRequests.map(({ start_ns, end_ns }) => ({ start_ns, end_ns }))).toEqual(
            planned.coverage.planned_acquisition_ranges
        );
        for (const request of acquisitionRequests) {
            expect(request.instrument_id).toBe("ETHUSDT.BINANCE");
            expect(request.bar_semantic).toEqual(planned.bar_semantic);
        }
    } else {
        // Existing dev data may already cover 30m; do not clear history to force a gap.
        expect(planned.coverage.status).toBe("COMPLETE");
        expect(acquisitionRequests).toHaveLength(0);
    }
    await expect(page.getByRole("button", { name: /准备 .*行情/ })).toHaveCount(0);
    await expect(page.getByRole("combobox", { name: "时间周期", exact: true })).toHaveValue("30");
    await expect(page.getByRole("combobox", { name: "图表类型", exact: true })).toHaveValue("LINE");
    await testInfo.attach("automatic-chart-loading-existing-or-missing-history", {
        contentType: "application/json",
        body: JSON.stringify({ initialCoverage: planned.coverage, acquisitionRequests })
    });
    await page.screenshot({
        path: testInfo.outputPath("watchlists-automatic-chart.png"),
        fullPage: true
    });
});
