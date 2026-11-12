import { expect, test } from "@playwright/test";
import {
    chart,
    controlledRealtime,
    hoverPreview,
    integrationId,
    minuteNs,
    openInspector,
    revision,
    semantic,
    source,
    status,
    windowEnd
} from "./support/temporaryMarketData";


test("default LIVE workspace subscribes at 15m and merges Temporary preview and closed Bars", async ({
    page
}) => {
    const providerTraffic: string[] = [];
    const nonChartRequests: string[] = [];
    page.on("request", (request) => {
        const url = new URL(request.url());
        if (/binance\.(com|vision)/.test(url.hostname)) providerTraffic.push(request.url());
        const path = url.pathname;
        if (
            path.startsWith("/api/v2/") &&
            path !== "/api/v2/chart/market-data/bars" &&
            path !== "/api/v2/chart/market-data/stream" &&
            path !== "/api/v2/market-data/sources" &&
            path !== "/api/v2/market/instruments" &&
            // Workspace bootstrap reads: saved layout restore and the watchlist panel.
            path !== "/api/v2/workspace" &&
            path !== "/api/v2/watchlists" &&
            !path.startsWith("/api/v2/chart/studies/") &&
            !path.startsWith("/api/v2/chart/temporary-studies/")
        )
            nonChartRequests.push(path);
    });
    const market = await controlledRealtime(page);
    await page.goto("/");
    await expect(status(page)).toContainText("● 实时");
    await expect.poll(() => market.steps).toEqual([15]);
    expect(market.subscriptions).toHaveLength(1);
    const subscription = market.subscriptions[0];
    expect(subscription.operation).toBe("SUBSCRIBE_TEMPORARY_BARS");
    expect(subscription.instrument_id).toBe("BTCUSDT.BINANCE");
    expect(subscription.source_reference).toEqual({
        integration_id: integrationId,
        integration_revision_fingerprint: revision,
        expected_type_id: source.type_id
    });
    expect(subscription.bar_semantic).toEqual(semantic(15));
    expect(subscription.before_ns).toBe(windowEnd);
    expect(subscription.target_bar_count).toBe(2000);
    expect(market.barQueries).toHaveLength(1);
    expect(market.barQueries[0]?.anchor).toBe("LATEST_CLOSED");
    expect(nonChartRequests).toEqual([]);

    await expect(status(page)).toHaveAttribute("data-loaded-bar-count", "2001");
    await expect(page.getByRole("tooltip", { name: "K 线信息" })).toHaveCount(0);

    const latency = await openInspector(page);
    await expect(latency.getByRole("row", { name: /^接收延迟/ }).getByRole("cell")).toHaveText(
        "1 ms"
    );
    await expect(latency.getByRole("row", { name: /^收盘到达延迟/ }).getByRole("cell")).toHaveText(
        "2 ms"
    );
    await expect(latency).toContainText("当前连接样本");
    market.emitPreview();
    await expect(latency.getByRole("row", { name: /^接收延迟/ }).getByRole("cell")).toHaveText(
        "-0.000001 ms（时钟偏差）"
    );
    await expect(latency.getByRole("row", { name: /^收盘到达延迟/ }).getByRole("cell")).toHaveText(
        "2 ms"
    );
    market.emitPreview(true);
    await expect(latency.getByRole("row", { name: /^接收延迟/ }).getByRole("cell")).toHaveText("—");
    await expect(latency.getByRole("row", { name: /^收盘到达延迟/ }).getByRole("cell")).toHaveText(
        "2 ms"
    );
    await hoverPreview(page);
    const observation = page.getByRole("tooltip", { name: "K 线信息" });
    await expect(observation).toContainText("实时预览");
    await expect(observation.locator('[data-observation-field="close"]')).toHaveText(
        "103.000000000000000002"
    );
    await expect(status(page)).toHaveAttribute("data-loaded-bar-count", "2001");
    await expect(page.getByRole("combobox", { name: "时间周期" })).toHaveValue("15");
    expect(providerTraffic).toEqual([]);
});

for (const width of [1440, 1024, 390]) {
    test(`Temporary catalog navigation preserves the BTCUSDT 15m market context at ${String(width)}px`, async ({
        page
    }) => {
        await page.setViewportSize({ width, height: 900 });
        const market = await controlledRealtime(page);
        const researchRequests: string[] = [];
        page.on("request", (request) => {
            const path = new URL(request.url()).pathname;
            if (path.startsWith("/api/v2/research/")) researchRequests.push(path);
        });
        await page.goto("/");
        await expect(status(page)).toContainText("● 实时");
        const context = await chart(page).getAttribute("data-chart-context-key");
        const baseline = { bars: market.barQueries.length };
        const trigger = page.getByRole("button", { name: "目录", exact: true });
        await trigger.focus();
        await page.keyboard.press("Enter");
        const dialog = page.getByRole("dialog", { name: "指标 / 因子目录" });
        await expect(
            dialog.getByText("CHART_STUDY_TRANSIENT · DISPLAY_ONLY · 不是 Research Result")
        ).toBeVisible();
        const search = dialog.getByRole("searchbox", { name: "搜索指标或因子" });
        await expect(search).toBeFocused();
        await page.getByRole("button", { name: "搜索商品" }).focus();
        await expect(search).toBeFocused();
        const box = await dialog.boundingBox();
        expect(box?.x).toBeGreaterThanOrEqual(0);
        expect((box?.x ?? width) + (box?.width ?? width)).toBeLessThanOrEqual(width);
        await search.fill("missing");
        await expect(dialog.getByText("没有匹配的指标。")).toBeVisible();
        await search.fill("sma");
        const choose = dialog.getByRole("button", { name: "选择 SMA · 配置草稿" });
        await expect(choose).toBeEnabled();
        const close = dialog.getByRole("button", { name: "关闭目录" });
        await close.focus();
        await page.keyboard.press("Shift+Tab");
        await expect(choose).toBeFocused();
        await page.keyboard.press("Tab");
        await expect(close).toBeFocused();
        await page.keyboard.press("Escape");
        await expect(dialog).toHaveCount(0);
        await expect(trigger).toBeFocused();
        await page.keyboard.press("Enter");
        await choose.click();
        const handoff = page.getByTestId("calculation-handoff");
        await expect(handoff).toHaveAttribute("data-registration-source", "CHART_STUDY_TRANSIENT");
        await expect(handoff).toHaveAttribute("data-type-id", "onlyalpha.indicator.sma");
        await expect(handoff).toContainText("仅配置草稿，尚未计算");
        await expect(handoff).not.toHaveAttribute("data-runtime-generation", /.+/);
        await expect(handoff).not.toHaveAttribute("data-backend", /.+/);
        await page.keyboard.press("Escape");
        await expect(page.getByRole("dialog", { name: "指标 / 因子参数配置" })).toHaveCount(0);
        await expect(chart(page)).toHaveAttribute("data-chart-context-key", context ?? "");
        market.emitPreview();
        await hoverPreview(page);
        await expect(page.getByRole("tooltip", { name: "K 线信息" })).toContainText("实时预览");
        expect(market.barQueries).toHaveLength(baseline.bars);
        // Escape bubbles through the settings drawer's cancel path, which re-reads
        // sources and may reopen the same stream; the market context itself must
        // not move: identical pin, page and semantic on every subscription.
        expect(
            market.subscriptions.every(
                (item) =>
                    item.before_ns === market.subscriptions[0]?.before_ns &&
                    item.page_id === market.subscriptions[0]?.page_id &&
                    item.bar_semantic.formation.window_minutes === 15
            )
        ).toBe(true);
        expect(market.olderRequests).toHaveLength(0);
        expect(researchRequests).toEqual([]);
        await expect(page.getByRole("combobox", { name: "时间周期" })).toHaveValue("15");
    });
}

test("chart study configuration, presentation and removal run over the live Temporary stream", async ({
    page
}) => {
    const market = await controlledRealtime(page);
    await page.goto("/");
    await expect(status(page)).toContainText("● 实时");
    await expect(chart(page)).toHaveAttribute("data-volume-point-count", "2001");
    await expect(chart(page)).toHaveAttribute("data-study-series-count", "0");
    const context = await chart(page).getAttribute("data-chart-context-key");
    const trigger = page.getByRole("button", { name: "目录", exact: true });
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: "指标 / 因子目录" });
    await dialog.getByRole("searchbox", { name: "搜索指标或因子" }).fill("sma");
    const editor = page.getByRole("dialog", { name: "指标 / 因子参数配置" });
    await dialog.getByRole("button", { name: "选择 SMA · 配置草稿" }).click();
    await expect(editor).toBeVisible();
    const period = editor.getByRole("textbox", { name: "period" });
    await expect(period).toBeFocused();
    await expect(period).toHaveValue("20");
    await expect(editor.getByText("按收盘价计算")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(editor).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await expect(page.getByTestId("chart-study-instance")).toHaveCount(0);

    await trigger.press("Enter");
    await dialog.getByRole("button", { name: "选择 SMA · 配置草稿" }).click();
    await editor.getByRole("button", { name: "添加", exact: true }).click();
    const first = page.getByTestId("chart-study-instance").first();
    await expect(first).toHaveCount(1);
    await expect(first).toHaveAttribute("data-chart-context-key", context ?? "");
    // The chart re-reads its own BEFORE_TIME window and admits the official batch proof.
    await expect
        .poll(() => market.evaluateReads.length, { timeout: 15_000 })
        .toBeGreaterThan(0);
    const evaluated = market.evaluateReads[0] as { window: { before_ns: string } };
    expect(BigInt(evaluated.window.before_ns) >= BigInt(windowEnd)).toBe(true);
    await expect(chart(page)).toHaveAttribute("data-study-series-count", "1", {
        timeout: 15_000
    });

    await first.getByRole("button", { name: "编辑 SMA" }).click();
    await editor.getByRole("button", { name: "SMA 红色", exact: true }).click();
    await editor.getByRole("button", { name: "应用", exact: true }).click();
    await expect(editor).toHaveCount(0);
    expect(JSON.parse((await first.getAttribute("data-presentation")) ?? "null")).toMatchObject({
        seriesStyles: { value: { color: "#c8332a" } }
    });
    await expect(first).toHaveAttribute("data-chart-context-key", context ?? "");

    await trigger.click();
    await dialog.getByRole("searchbox", { name: "搜索指标或因子" }).fill("sma");
    await dialog.getByRole("button", { name: "选择 SMA · 配置草稿" }).click();
    await editor.getByRole("button", { name: "添加", exact: true }).click();
    await expect(page.getByTestId("chart-study-instance")).toHaveCount(2);

    await first.getByRole("button", { name: "选择 SMA", exact: true }).click();
    await expect(first).toHaveAttribute("data-selected", "true");
    // Two instances are configured; hiding the first leaves the sibling's series.
    await first.getByRole("button", { name: "隐藏 SMA", exact: true }).press("Enter");
    await expect(chart(page)).toHaveAttribute("data-study-series-count", "1", {
        timeout: 15_000
    });
    await first.getByRole("button", { name: "显示 SMA", exact: true }).press("Enter");
    await expect(chart(page)).toHaveAttribute("data-study-series-count", "2", {
        timeout: 15_000
    });

    const baseline = {
        bars: market.barQueries.length,
        subscriptions: market.subscriptions.length
    };
    await first.getByRole("button", { name: "移除配置", exact: true }).press("Enter");
    await expect(page.getByTestId("chart-study-instance")).toHaveCount(1);
    await expect(chart(page)).toHaveAttribute("data-study-series-count", "1", {
        timeout: 15_000
    });
    expect(market.subscriptions).toHaveLength(baseline.subscriptions);
    expect(market.olderRequests).toHaveLength(0);
    await expect(status(page)).toContainText("● 实时");
    await expect(page.getByRole("combobox", { name: "时间周期" })).toHaveValue("15");
});

for (const width of [1024, 390]) {
    test(`one configured study keeps its pane ownership at ${String(width)}px`, async ({
        page
    }) => {
        await page.setViewportSize({ width, height: 900 });
        await controlledRealtime(page);
        await page.goto("/");
        await expect(status(page)).toContainText("● 实时");
        const renderedChart = chart(page);
        await expect(renderedChart).toBeVisible();
        const box = await renderedChart.boundingBox();
        expect(box?.height ?? 0).toBeGreaterThanOrEqual(160);
        await page.getByRole("button", { name: "目录", exact: true }).click();
        const dialog = page.getByRole("dialog", { name: "指标 / 因子目录" });
        await dialog.getByRole("searchbox", { name: "搜索指标或因子" }).fill("sma");
        await dialog.getByRole("button", { name: "选择 SMA · 配置草稿" }).click();
        await page
            .getByRole("dialog", { name: "指标 / 因子参数配置" })
            .getByRole("button", { name: "添加", exact: true })
            .click();
        await expect(page.getByTestId("chart-study-instance")).toHaveCount(1);
        await expect(renderedChart).toHaveAttribute("data-study-series-count", "1", {
            timeout: 15_000
        });
        await expect(page.getByRole("dialog")).toHaveCount(0);
        expect(
            await page.evaluate(() => document.documentElement.scrollWidth)
        ).toBeLessThanOrEqual(width);
        await test.info().attach(`study-live-${String(width)}`, {
            contentType: "image/png",
            body: await page.screenshot()
        });
    });
}

test("a re-fingerprinted Capability fails closed at confirmation without an instance", async ({
    page
}) => {
    const market = await controlledRealtime(page, { staleCapabilityOnConfirm: true });
    await page.goto("/");
    await expect(status(page)).toContainText("● 实时");
    await page.getByRole("button", { name: "目录", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "指标 / 因子目录" });
    await dialog.getByRole("searchbox", { name: "搜索指标或因子" }).fill("sma");
    await dialog.getByRole("button", { name: "选择 SMA · 配置草稿" }).click();
    const editor = page.getByRole("dialog", { name: "指标 / 因子参数配置" });
    await expect(editor.getByRole("button", { name: "添加", exact: true })).toBeEnabled();
    market.armStaleVerify();
    await editor.getByRole("button", { name: "添加", exact: true }).click();
    await expect(editor.getByRole("alert")).toContainText("STALE");
    await expect(page.getByTestId("chart-study-instance")).toHaveCount(0);
    await editor.getByRole("button", { name: "取消配置" }).click();
    await expect(editor).toHaveCount(0);
    expect(market.evaluateReads).toHaveLength(0);
});

test("chart type keeps the realtime subscription and exact preview readout", async ({
    page
}) => {
    const market = await controlledRealtime(page);
    await page.goto("/");
    await expect(status(page)).toContainText("● 实时");
    await page.getByRole("combobox", { name: "时间周期" }).selectOption("1");
    await expect.poll(() => market.steps.at(-1)).toBe(1);
    await expect(status(page)).toContainText("● 实时");
    const observation = page.getByRole("tooltip", { name: "K 线信息" });
    await expect(observation).toHaveCount(0);
    market.emitPreview();
    await hoverPreview(page);
    await expect(observation).toContainText("实时预览");
    await expect(observation.locator('[data-observation-field="close"]')).toHaveText(
        "103.000000000000000001"
    );
    await expect(observation.locator('[data-observation-field="volume"]')).toHaveText(
        "3.000000000000000001"
    );
    const bars = market.barQueries.length;
    const subscriptions = market.subscriptions.length;
    for (const type of ["LINE", "CANDLESTICK"]) {
        await page.getByLabel("图表类型", { exact: true }).click();
        await page
            .getByRole("menuitem", { name: type === "LINE" ? "收盘线" : "蜡烛图", exact: true })
            .click();
        await expect(chart(page)).toHaveAttribute("data-chart-type", type);
        await hoverPreview(page);
        await expect(observation).toContainText("实时预览");
        await expect(observation.locator('[data-observation-field="close"]')).toHaveText(
            "103.000000000000000001"
        );
        expect(market.barQueries).toHaveLength(bars);
        expect(market.subscriptions).toHaveLength(subscriptions);
        await expect(status(page)).toContainText("● 实时");
    }
});

test("realtime reconnect repins at the admitted close without older-history reads — CONTROLLED_TEST_EVIDENCE", async ({
    page
}) => {
    const market = await controlledRealtime(page, { holdRecovery: true });
    await page.goto("/");
    await expect(status(page)).toContainText("● 实时");
    expect(market.olderRequests).toHaveLength(0);
    await expect(status(page)).toHaveAttribute("data-older-history-status", "idle");

    const latency = await openInspector(page);
    await expect(latency).toContainText("当前连接样本");
    await market.disconnect();
    await expect(status(page)).toContainText("● 行情中断");
    await expect(latency).toContainText("最后样本 · 非当前");
    await expect(status(page)).toContainText("● 恢复中");
    market.releaseRecovery();
    await expect(status(page)).toContainText("● 实时");
    await expect(latency).toContainText("最后样本 · 非当前");

    // The refresh repins the Temporary window at the last admitted closed end,
    // then re-subscribes there: no gap and no older 240-Bar paging.
    const repin = market.pinQueries().at(-1);
    expect(repin?.before).toBe((BigInt(windowEnd) + BigInt(15) * minuteNs).toString());
    expect(repin?.target).toBe(2000);
    expect(market.subscriptions[1]?.before_ns).toBe(repin?.before);
    market.emitPreview();
    await expect(latency).toContainText("当前连接样本");
    await expect.poll(() => market.subscriptions.length).toBe(2);
    expect(market.olderRequests).toHaveLength(0);
});

test("preset and custom periods resubscribe to matching temporary streams — CONTROLLED_TEST_EVIDENCE", async ({
    page
}) => {
    const market = await controlledRealtime(page);
    await page.goto("/");
    await expect(status(page)).toContainText("● 实时");
    await page.getByRole("combobox", { name: "时间周期" }).selectOption("1");
    await expect.poll(() => market.steps.at(-1)).toBe(1);
    await expect(status(page)).toContainText("● 实时");

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("15");
    await expect.poll(() => market.steps.at(-1)).toBe(15);
    await expect(status(page)).toContainText("● 实时");

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("60");
    await expect.poll(() => market.steps.at(-1)).toBe(60);
    await expect(status(page)).toContainText("● 实时");

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("custom");
    await page.getByRole("spinbutton", { name: "自定义周期分钟数" }).fill("7");
    await page.getByRole("button", { name: "应用" }).click();
    await expect.poll(() => market.steps.at(-1)).toBe(7);
    await expect(status(page)).toContainText("● 实时");

    await page.getByRole("spinbutton", { name: "自定义周期分钟数" }).fill("37");
    await page.getByRole("button", { name: "应用" }).click();
    await expect.poll(() => market.steps.at(-1)).toBe(37);
    await expect(status(page)).toContainText("● 实时");

    // Derived 37m carries no Provider-native timing after the fresh SUBSCRIBED reset.
    const latency = await openInspector(page);
    await expect(latency.getByRole("row", { name: /^接收延迟/ }).getByRole("cell")).toHaveText("—");
    await expect(
        latency.getByRole("row", { name: /^收盘到达延迟/ }).getByRole("cell")
    ).toHaveText("—");
    await expect(latency).toContainText("暂无实时样本");
    expect(market.steps).toEqual([15, 1, 15, 60, 7, 37]);
});

test("a stale realtime preview cannot crash the chart — CONTROLLED_TEST_EVIDENCE", async ({
    page
}) => {
    const market = await controlledRealtime(page);
    await page.goto("/");
    await expect(status(page)).toContainText("● 实时");
    market.emitStalePreview();
    await expect(status(page)).toContainText("● 恢复中");
    await expect(chart(page).locator("canvas").first()).toBeVisible();
});

for (const width of [1381, 390]) {
    test(`CONTROLLED_TEST_EVIDENCE search result text contrasts with its surface at ${String(width)}px`, async ({
        page
    }) => {
        await page.setViewportSize({ width, height: 1187 });
        await controlledRealtime(page);
        await page.goto("/");
        await page.getByRole("button", { name: "搜索商品", exact: true }).click();
        const dialog = page.getByRole("dialog", { name: "商品搜索" });
        await dialog.getByRole("searchbox", { name: "商品代码或名称" }).fill("BTCUSDT");
        const choice = dialog.getByRole("button", {
            name: "查看 BTCUSDT · BINANCE · Binance Spot US",
            exact: true
        });
        await expect(choice).toBeVisible();
        const colors = await choice.evaluate((element) => {
            const surface = element.closest("dialog");
            const star = element.nextElementSibling;
            if (!surface || !star) throw new Error("Search dialog and star required");
            return {
                surface: getComputedStyle(surface).backgroundColor,
                text: [...element.children].map((child) => getComputedStyle(child).color),
                star: getComputedStyle(star).color
            };
        });
        expect(colors.text).not.toContain(colors.surface);
        expect(colors.star).not.toBe(colors.surface);
        await choice.click();
        await expect(dialog).not.toBeVisible();
        await expect(page.getByRole("button", { name: "搜索商品", exact: true })).toHaveText(
            /BTCUSDT/
        );
    });
}
