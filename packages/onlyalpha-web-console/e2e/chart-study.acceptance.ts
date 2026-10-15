import { expect, test, type Page, type Response } from "@playwright/test";
import { readFileSync } from "node:fs";

// Each capability/evaluate exchange has the server's 10s cutoff. A workflow has
// several sequential exchanges, not a single-query 30s budget. HTTP status/body
// and 5s post-response render assertions remain unchanged. Setup/Market reads
// and presentation have a separate finite budget; this is not an SLO assertion.
const chartExchangeBudgetMs = 10_000;
const setupAndPresentationBudgetMs = 30_000;

function nativeBarsReply(page: Page): Promise<Response> {
    return page.waitForResponse((response) => {
        const url = new URL(response.url());
        if (
            !url.pathname.endsWith("/api/v2/market-data/bars") ||
            url.searchParams.get("anchor_kind") !== "LATEST_CLOSED"
        )
            return false;
        const semantic = JSON.parse(url.searchParams.get("bar_semantic") ?? "null") as {
            formation?: { kind?: string; window_minutes?: number };
        } | null;
        return (
            url.searchParams.get("instrument_id") === "BTCUSDT.BINANCE" &&
            semantic?.formation?.kind === "FIXED_DURATION" &&
            semantic.formation.window_minutes === 15
        );
    });
}

async function connectNativeChart(page: Page): Promise<void> {
    await page.goto("/");
    await page.getByText("本地只读访问", { exact: true }).click();
    await page.getByLabel("本地行情凭据").fill("ee".repeat(32));
    const bars = nativeBarsReply(page);
    await page.getByRole("button", { name: "连接只读行情" }).click();
    await expect(page.getByLabel("数据源").locator("option")).toHaveCount(2);
    await page.getByLabel("数据源").selectOption({ index: 1 });
    await expect(page.getByLabel("时间周期")).toBeEnabled();
    await page.getByLabel("时间周期").selectOption("15");
    expect((await bars).status()).toBe(200);
    await expect(page.getByTestId("market-data-status")).toHaveAttribute("data-status", "ready");
}

function evaluationReply(page: Page, period: number): Promise<Response> {
    return page.waitForResponse(
        (response) =>
            response.url().endsWith("/api/v2/chart/studies/evaluate") &&
            (
                response.request().postDataJSON() as {
                    calculation: { typed_parameters: { period: { value: number } } };
                }
            ).calculation.typed_parameters.period.value === period
    );
}

async function addSma(page: Page, period: number, color?: string): Promise<void> {
    await page.getByRole("button", { name: "指标", exact: true }).click();
    await page.getByRole("button", { name: "选择 SMA · 配置草稿" }).click();
    await expect(page.getByLabel("period", { exact: true })).toHaveValue("20");
    if (period !== 20) await page.getByLabel("period", { exact: true }).fill(String(period));
    if (color !== undefined) await page.getByRole("button", { name: color, exact: true }).click();
    await page.getByRole("button", { name: "添加", exact: true }).click();
}

async function disconnectChart(page: Page): Promise<void> {
    await page.getByText("本地只读访问", { exact: true }).click();
    await page.getByRole("button", { name: "清除凭据" }).click();
    await expect(page.getByTestId("chart-study-instance")).toHaveCount(0);
}

test("distinct SMA display instances admit both sequential owning HTTP replies without style or selection recompute", async ({
    page,
    request
}) => {
    // Two adds: picker/editor/consumer capabilities each plus three evaluations.
    test.setTimeout(9 * chartExchangeBudgetMs + setupAndPresentationBudgetMs);
    let evaluations = 0;
    page.on("request", (req) => {
        if (req.url().endsWith("/api/v2/chart/studies/evaluate")) ++evaluations;
    });
    await connectNativeChart(page);
    const first = evaluationReply(page, 30);
    await addSma(page, 30);
    expect((await first).status()).toBe(200);
    await expect(page.getByTestId("price-chart")).toHaveAttribute("data-study-series-count", "1");
    const both = Promise.all([evaluationReply(page, 30), evaluationReply(page, 20)]);
    await addSma(page, 20);
    for (const reply of await both) expect(reply.status()).toBe(200);
    await expect(page.getByTestId("chart-study-query-status")).toHaveAttribute(
        "data-query-status",
        "DISPLAYABLE"
    );
    await expect(page.getByTestId("chart-study-instance")).toHaveCount(2);
    await expect(page.getByTestId("price-chart")).toHaveAttribute("data-study-series-count", "2");
    expect(evaluations).toBe(3);
    const owners = await page
        .getByTestId("chart-study-instance")
        .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-instance-id")));
    expect(new Set(owners).size).toBe(2);
    await page.getByRole("button", { name: "选择 SMA", exact: true }).nth(1).click();
    await page.getByRole("button", { name: "隐藏 SMA", exact: true }).nth(1).click();
    await expect(page.getByTestId("price-chart")).toHaveAttribute("data-study-series-count", "1");
    await page.getByRole("button", { name: "显示 SMA", exact: true }).click();
    await expect(page.getByTestId("price-chart")).toHaveAttribute("data-study-series-count", "2");
    expect(evaluations).toBe(3);
    await disconnectChart(page);
    expect((await request.get("/health")).status()).toBe(200);
});

test("different periods of the same SMA retain independent colors, edits and visibility", async ({
    page
}, testInfo) => {
    test.setTimeout(70_000);
    const requests: { path: string; method: string }[] = [];
    page.on("request", (request) => {
        const path = new URL(request.url()).pathname;
        if (path.startsWith("/api/")) requests.push({ path, method: request.method() });
    });
    await connectNativeChart(page);

    const add = async (period: number, color: string) => {
        await page.getByRole("button", { name: "指标", exact: true }).click();
        await page.getByRole("button", { name: "选择 SMA · 配置草稿" }).click();
        await page.getByLabel("period", { exact: true }).fill(String(period));
        await page
            .getByRole("button", { name: color === "#c8332a" ? "红色" : "蓝色", exact: true })
            .click();
        await page.getByRole("combobox", { name: "位置" }).selectOption("PRICE_OVERLAY");
        const response = evaluationReply(page, period);
        await page.getByRole("button", { name: "添加", exact: true }).click();
        const reply = await response;
        expect(reply.status()).toBe(200);
        const result = (await reply.json()) as {
            input: { target_bar_count: number };
            series: { points: { readiness: string }[] }[];
        };
        expect(result.input.target_bar_count).toBe(2000);
        expect(result.series[0]?.points).toHaveLength(2000);
        expect(result.series[0]?.points[period - 1]?.readiness).toBe("READY");
        await expect(page.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "DISPLAYABLE"
        );
    };
    await add(20, "#c8332a");
    await add(30, "#2457c5");
    const instances = page.getByTestId("chart-study-instance");
    await expect(instances).toHaveCount(2);
    const sma20 = instances.filter({ hasText: "period=20" });
    const sma30 = instances.filter({ hasText: "period=30" });
    await expect(sma20).toBeVisible();
    await expect(sma30).toBeVisible();
    await expect(sma20).toContainText("主图 Overlay · 红色");
    await expect(sma30).toContainText("主图 Overlay · 蓝色");
    const firstId = await sma20.getAttribute("data-instance-id");
    const secondId = await sma30.getAttribute("data-instance-id");
    if (firstId === null || secondId === null) throw new Error("Missing Study instance identity");
    expect(firstId).not.toBe(secondId);
    const chart = page.getByTestId("price-chart");
    await expect(chart).toHaveAttribute("data-study-series-count", "2");
    await expect(page.getByTestId("study-hover")).toHaveCount(2);
    await page.getByRole("button", { name: "收起下方面板" }).click();
    expect((await chart.boundingBox())?.height).toBeGreaterThanOrEqual(220);
    await chart.screenshot({ path: testInfo.outputPath("sma20-and-sma30.png") });
    await page.setViewportSize({ width: 720, height: 900 });
    expect((await chart.boundingBox())?.height).toBeGreaterThanOrEqual(220);
    await expect(chart).toHaveAttribute("data-study-series-count", "2");
    await chart.screenshot({ path: testInfo.outputPath("sma20-and-sma30-narrow.png") });
    await page.setViewportSize({ width: 1280, height: 720 });

    const evaluations = requests.filter(({ path }) =>
        path.endsWith("/chart/studies/evaluate")
    ).length;
    await sma20.getByRole("button", { name: "隐藏 SMA", exact: true }).click();
    await expect(chart).toHaveAttribute("data-study-series-count", "1");
    await expect(sma30.getByRole("button", { name: "隐藏 SMA", exact: true })).toBeVisible();
    await expect(page.getByTestId("study-hover")).toHaveCount(1);
    await sma20.getByRole("button", { name: "显示 SMA", exact: true }).click();
    await expect(chart).toHaveAttribute("data-study-series-count", "2");
    expect(requests.filter(({ path }) => path.endsWith("/chart/studies/evaluate"))).toHaveLength(
        evaluations
    );

    await sma20.getByRole("button", { name: "编辑 SMA", exact: true }).click();
    await page.getByLabel("period", { exact: true }).fill("25");
    const changed = evaluationReply(page, 25);
    await page.getByRole("button", { name: "应用", exact: true }).click();
    expect((await changed).status()).toBe(200);
    await expect(page.getByTestId("chart-study-query-status")).toHaveAttribute(
        "data-query-status",
        "DISPLAYABLE"
    );
    const sma25 = instances.filter({ hasText: "period=25" });
    await expect(sma25).toHaveAttribute("data-instance-id", firstId);
    await expect(sma30).toHaveAttribute("data-instance-id", secondId);
    await expect(chart).toHaveAttribute("data-study-series-count", "2");
    const remaining = evaluationReply(page, 30);
    await sma25.getByRole("button", { name: "移除配置", exact: true }).click();
    await expect(instances).toHaveCount(1);
    await expect(sma30).toBeVisible();
    expect((await remaining).status()).toBe(200);
    await expect(page.getByTestId("chart-study-query-status")).toHaveAttribute(
        "data-query-status",
        "DISPLAYABLE"
    );
    await expect(chart).toHaveAttribute("data-study-series-count", "1");
    await expect(page.getByTestId("study-hover")).toHaveCount(1);
    expect(
        requests.filter(
            ({ method, path }) => method !== "GET" && path !== "/api/v2/chart/studies/evaluate"
        )
    ).toEqual([]);
});

for (const change of ["timeframe", "source"] as const)
    test(`native ${change} A→B→A retains display intent and requires fresh owning evaluation`, async ({
        page,
        request
    }) => {
        test.setTimeout(8 * chartExchangeBudgetMs + setupAndPresentationBudgetMs);
        await connectNativeChart(page);
        const first = evaluationReply(page, 20);
        await addSma(page, 20);
        expect((await first).status()).toBe(200);
        await expect(page.getByTestId("price-chart")).toHaveAttribute(
            "data-study-series-count",
            "1"
        );
        const id = await page.getByTestId("chart-study-instance").getAttribute("data-instance-id");
        const config = await page
            .getByTestId("chart-study-instance")
            .getAttribute("data-configuration");
        if (change === "timeframe") {
            const native = evaluationReply(page, 20);
            await page.getByLabel("时间周期").selectOption("1");
            expect((await native).status()).toBe(200);
            await expect(page.getByTestId("price-chart")).toHaveAttribute(
                "data-study-series-count",
                "1"
            );
        } else {
            await page.getByLabel("数据源").selectOption("");
            await expect(page.getByTestId("price-chart")).toHaveAttribute(
                "data-study-series-count",
                "0"
            );
        }
        await expect(page.getByTestId("chart-study-instance")).toHaveCount(1);
        const restoredBars = nativeBarsReply(page);
        const restored = evaluationReply(page, 20);
        if (change === "timeframe") await page.getByLabel("时间周期").selectOption("15");
        else await page.getByLabel("数据源").selectOption({ index: 1 });
        expect((await restoredBars).status()).toBe(200);
        expect((await restored).status()).toBe(200);
        await expect(page.getByTestId("chart-study-instance")).toHaveAttribute(
            "data-instance-id",
            id ?? ""
        );
        await expect(page.getByTestId("chart-study-instance")).toHaveAttribute(
            "data-configuration",
            config ?? ""
        );
        await expect(page.getByTestId("price-chart")).toHaveAttribute(
            "data-study-series-count",
            "1"
        );
        await disconnectChart(page);
        expect((await request.get("/health")).status()).toBe(200);
    });

test("late genuine HTTP reply cannot revive an abandoned Study after logout and equal-token restoration", async ({
    page,
    request
}) => {
    test.setTimeout(4 * chartExchangeBudgetMs + setupAndPresentationBudgetMs);
    const token = "ee".repeat(32);
    let arrived!: () => void;
    let release!: () => void;
    let completed!: () => void;
    const responseArrived = new Promise<void>((resolve) => {
        arrived = resolve;
    });
    const releaseReply = new Promise<void>((resolve) => {
        release = resolve;
    });
    const replyCompleted = new Promise<void>((resolve) => {
        completed = resolve;
    });
    // Negative transport fault only: fetch the real protected HTTP/backend reply
    // intact, then delay delivery. The positive numeric acceptance below never
    // intercepts Shipping requests or manufactures a response/value.
    await page.route(
        "**/api/v2/chart/studies/evaluate",
        async (route) => {
            const response = await route.fetch();
            expect(response.status()).toBe(200);
            arrived();
            await releaseReply;
            await route.fulfill({ response });
            completed();
        },
        { times: 1 }
    );
    await connectNativeChart(page);
    await page.getByRole("button", { name: "指标", exact: true }).click();
    await page.getByRole("button", { name: "选择 SMA · 配置草稿" }).click();
    await page.getByRole("button", { name: "添加", exact: true }).click();
    await responseArrived;
    await expect(page.getByTestId("chart-study-query-status")).toHaveAttribute(
        "data-query-status",
        "QUERYING"
    );
    await page.getByText("本地只读访问", { exact: true }).click();
    const cancelled = page.waitForEvent("requestfailed", (req) =>
        req.url().endsWith("/api/v2/chart/studies/evaluate")
    );
    await page.getByRole("button", { name: "清除凭据" }).click();
    await cancelled;
    await page.getByText("本地只读访问", { exact: true }).click();
    await page.getByLabel("本地行情凭据").fill(token);
    const restoredBars = nativeBarsReply(page);
    await page.getByRole("button", { name: "连接只读行情" }).click();
    await expect(page.getByLabel("数据源").locator("option")).toHaveCount(2);
    await page.getByLabel("数据源").selectOption({ index: 1 });
    expect((await restoredBars).status()).toBe(200);
    await expect(page.getByTestId("market-data-status")).toHaveAttribute("data-status", "ready");
    release();
    await replyCompleted;
    await expect(page.getByTestId("chart-study-instance")).toHaveCount(0);
    await expect(page.getByTestId("price-chart")).toHaveAttribute("data-study-series-count", "0");
    // No Study has no Query status row. Whether absent or present, no late reply
    // may publish DISPLAYABLE; the independent zero-instance/series checks above
    // remain mandatory after actual delayed-reply delivery.
    await expect(
        page.locator('[data-testid="chart-study-query-status"][data-query-status="DISPLAYABLE"]')
    ).toHaveCount(0);
    await page.getByText("本地只读访问", { exact: true }).click();
    await page.getByRole("button", { name: "清除凭据" }).click();
    expect((await request.get("/health")).status()).toBe(200);
});

test("protected Shipping SMA20→30 uses owning PG/CH history and the registered backend without business writes", async ({
    page,
    request
}) => {
    // Initial add (4), style confirm (1), parameter confirm/consumer/evaluate (3).
    test.setTimeout(8 * chartExchangeBudgetMs + setupAndPresentationBudgetMs);
    const token = "ee".repeat(32);
    const writes: string[] = [];
    const leaks: string[] = [];
    const evaluations: unknown[] = [];
    const recordingPath = process.env.ONLYALPHA_CHART_STUDY_RECORDED_WIRE;
    const recorded = recordingPath
        ? (JSON.parse(readFileSync(recordingPath, "utf8")) as {
              expected: Record<string, { time_ns: string; value: string; readiness: string }[]>;
          })
        : null;
    page.on("request", (req) => {
        if (
            req.method() !== "GET" &&
            req.url().includes("/api/") &&
            !req.url().endsWith("/api/v2/chart/studies/evaluate")
        )
            writes.push(req.url());
        if (req.url().includes(token)) leaks.push("url");
    });
    page.on("console", (message) => {
        if (message.text().includes(token)) leaks.push("console");
    });
    page.on("response", (response) => {
        if (response.url().endsWith("/api/v2/chart/studies/evaluate") && response.status() === 200)
            void response.json().then((value) => {
                evaluations.push(value as unknown);
            });
    });
    expect((await request.get("/api/v2/chart/studies/capabilities")).status()).toBe(401);
    await connectNativeChart(page);
    await page.getByLabel("搜索标的").fill("BTCUSDT");
    await page.getByLabel("搜索标的").press("Enter");
    await page.getByRole("button", { name: /BTCUSDT.*BINANCE/ }).click();
    await expect(page.getByTestId("market-data-status")).toHaveAttribute("data-status", "ready");
    await page.getByRole("button", { name: "指标", exact: true }).click();
    await page.getByRole("button", { name: "选择 SMA · 配置草稿" }).click();
    await expect(page.getByLabel("period", { exact: true })).toHaveValue("20");
    const first = page.waitForResponse(
        (response) =>
            response.url().endsWith("/api/v2/chart/studies/evaluate") && response.status() === 200
    );
    await page.getByRole("button", { name: "添加", exact: true }).click();
    const response = await first;
    expect(response.headers()["cache-control"]).toBe("no-store");
    const value = (await response.json()) as {
        source_kind: string;
        authority: string;
        publication_status: string;
        input: {
            target_bar_count: number;
            resolution_mode: string;
            history_projection_fingerprint: string;
        };
        series: { points: { value: string; readiness: string; time_ns: string }[] }[];
    };
    expect([value.source_kind, value.authority, value.publication_status]).toEqual([
        "CHART_STUDY_TRANSIENT",
        "DISPLAY_ONLY",
        "NOT_A_RESEARCH_RESULT"
    ]);
    expect(value.input.target_bar_count).toBe(2000);
    expect(value.input.resolution_mode).toBe("PROVIDER_NATIVE");
    expect(value.input.history_projection_fingerprint).toMatch(/^[0-9a-f]{64}$/);
    expect(value.series[0]?.points).toHaveLength(2000);
    expect(value.series[0]?.points[0]?.value).toBe(
        recorded?.expected["20"]?.[0]?.value ?? "105.000000000000"
    );
    expect(value.series[0]?.points[0]?.readiness).toBe("PARTIAL");
    expect(value.series[0]?.points[19]?.readiness).toBe("READY");
    if (recorded !== null)
        expect(
            value.series[0]?.points.map((point) => ({
                time_ns: point.time_ns,
                value: point.value,
                readiness: point.readiness
            }))
        ).toEqual(recorded.expected["20"]);
    await expect(page.getByTestId("chart-study-query-status")).toHaveAttribute(
        "data-query-status",
        "DISPLAYABLE"
    );
    await expect(page.getByTestId("price-chart")).toHaveAttribute("data-study-series-count", "1");
    const statusBounds = await page.getByTestId("chart-study-query-status").boundingBox();
    const plot = await page.getByTestId("price-chart").boundingBox();
    if (plot === null || statusBounds === null)
        throw new Error("Expected native chart viewport and visible Query status");
    expect(plot.y).toBeGreaterThanOrEqual(statusBounds.y + statusBounds.height);
    expect(plot.height).toBeGreaterThan(80);
    await page.mouse.move(plot.x + plot.width * 0.7, plot.y + plot.height * 0.3);
    await expect(page.getByTestId("study-hover")).toContainText("UTC ns ");
    const hover = await page.getByTestId("study-hover").innerText();
    const hovered = value.series[0]?.points.find((point) =>
        hover.includes(`UTC ns ${point.time_ns}`)
    );
    expect(hovered).toBeDefined();
    expect(hover).toContain(hovered?.value ?? "missing");
    expect(hover).toContain(hovered?.readiness ?? "missing");
    await page.getByRole("button", { name: "隐藏 SMA", exact: true }).click();
    await page.getByRole("button", { name: "显示 SMA", exact: true }).click();
    expect(evaluations).toHaveLength(1);
    // Style-only confirmation rereads capability but never reevaluates values.
    await page.getByRole("button", { name: "编辑 SMA", exact: true }).click();
    await page.getByRole("button", { name: "青绿色", exact: true }).click();
    await page.getByRole("button", { name: "应用", exact: true }).click();
    await expect(page.getByTestId("chart-study-query-status")).toHaveAttribute(
        "data-query-status",
        "DISPLAYABLE"
    );
    expect(evaluations).toHaveLength(1);
    await expect(page.getByTestId("chart-study-instance")).toHaveAttribute(
        "data-presentation",
        expect.stringContaining('"color":"#008877"')
    );
    await page.getByRole("button", { name: "编辑 SMA", exact: true }).click();
    await page.getByLabel("period", { exact: true }).fill("30");
    const second = page.waitForResponse(
        (response) =>
            response.url().endsWith("/api/v2/chart/studies/evaluate") && response.status() === 200
    );
    await page.getByRole("button", { name: "应用", exact: true }).click();
    const changed = (await (await second).json()) as typeof value;
    expect(changed.series[0]?.points[19]?.readiness).toBe("PARTIAL");
    expect(changed.series[0]?.points[29]?.readiness).toBe("READY");
    if (recorded !== null)
        expect(
            changed.series[0]?.points.map((point) => ({
                time_ns: point.time_ns,
                value: point.value,
                readiness: point.readiness
            }))
        ).toEqual(recorded.expected["30"]);
    await expect(page.getByTestId("chart-study-query-status")).toHaveAttribute(
        "data-query-status",
        "DISPLAYABLE"
    );
    await page.screenshot({ path: "../../test-results/chart-study-browser/sma30.png" });
    await page.setViewportSize({ width: 720, height: 900 });
    await expect(page.getByTestId("price-chart")).toBeVisible();
    const narrowPlot = await page.getByTestId("price-chart").boundingBox();
    expect(narrowPlot?.height).toBeGreaterThan(80);
    expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    ).toBe(true);
    expect(evaluations).toHaveLength(2);
    await page.getByText("本地只读访问", { exact: true }).click();
    await page.getByRole("button", { name: "清除凭据" }).click();
    await expect(page.getByTestId("market-data-status")).toHaveAttribute(
        "data-loaded-bar-count",
        "0"
    );
    await expect(page.getByTestId("chart-study-instance")).toHaveCount(0);
    expect(writes).toEqual([]);
    expect(leaks).toEqual([]);
    expect(
        (
            await request.post("/api/v2/market-data/acquisitions", {
                headers: { Authorization: `Bearer ${token}` },
                data: {}
            })
        ).status()
    ).toBe(403);
    expect((await request.get("/health")).status()).toBe(200);
});

test("two SMA instances preserve parameters and colors across native 15m to 1m to 15m with fresh values", async ({
    page
}) => {
    test.setTimeout(12 * chartExchangeBudgetMs + setupAndPresentationBudgetMs);
    await connectNativeChart(page);
    const first = evaluationReply(page, 20);
    await addSma(page, 20);
    expect((await first).status()).toBe(200);
    const second = evaluationReply(page, 10);
    await addSma(page, 10, "红色");
    expect((await second).status()).toBe(200);
    const chart = page.getByTestId("price-chart");
    await expect(chart).toHaveAttribute("data-study-series-count", "2");
    const instances = page.getByTestId("chart-study-instance");
    const intent = () =>
        instances.evaluateAll((nodes) =>
            nodes.map((node) => ({
                id: node.getAttribute("data-instance-id"),
                configuration: node.getAttribute("data-configuration"),
                presentation: node.getAttribute("data-presentation")
            }))
        );
    const original = await intent();
    expect(original).toHaveLength(2);
    await page.getByRole("button", { name: "收起下方面板" }).click();
    const plot = await chart.locator("canvas").first().boundingBox();
    if (plot === null) throw new Error("Missing native price canvas");
    await page.mouse.move(plot.x + plot.width * 0.45, plot.y + plot.height * 0.5);
    await page.mouse.down();
    await page.mouse.move(plot.x + plot.width * 0.65, plot.y + plot.height * 0.5, { steps: 8 });
    await page.mouse.up();
    await page.mouse.wheel(0, -120);
    await expect(chart).toHaveAttribute("data-study-series-count", "2");
    const readStarts: string[] = [];
    for (const minutes of [1, 15]) {
        const replies = Promise.all([evaluationReply(page, 20), evaluationReply(page, 10)]);
        await page.getByLabel("时间周期").selectOption(String(minutes));
        await expect(instances).toHaveCount(2);
        for (const reply of await replies) {
            expect(reply.status()).toBe(200);
            const body = (await reply.json()) as {
                bar_semantic: { formation: { window_minutes: number } };
                input: {
                    resolved_start_ns: string;
                    resolved_end_ns: string;
                };
                series: { points: { time_ns: string; value: string | null }[] }[];
            };
            expect(body.bar_semantic.formation.window_minutes).toBe(minutes);
            expect(BigInt(body.input.resolved_end_ns) - BigInt(body.input.resolved_start_ns)).toBe(
                BigInt(2000 * minutes) * 60_000_000_000n
            );
            expect(body.series[0]?.points).toHaveLength(2000);
            expect(body.series[0]?.points[0]?.time_ns).toBe(body.input.resolved_start_ns);
            expect(body.series[0]?.points[1999]?.value).toEqual(expect.any(String));
            readStarts.push(body.input.resolved_start_ns);
        }
        await expect(chart).toHaveAttribute("data-study-series-count", "2");
        await expect(page.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "DISPLAYABLE"
        );
        expect(await intent()).toEqual(original);
    }
    expect(readStarts[0]).not.toBe(readStarts[2]);
    await disconnectChart(page);
});

for (const collapsed of [false, true]) {
    test(`chart plot, native time axis and timezone remain reachable in 1280x720 shell with research dock ${collapsed ? "collapsed" : "expanded"}`, async ({
        page
    }, testInfo) => {
        test.setTimeout(9 * chartExchangeBudgetMs + setupAndPresentationBudgetMs);
        await page.setViewportSize({ width: 1280, height: 720 });
        await connectNativeChart(page);
        const first = evaluationReply(page, 20);
        await addSma(page, 20, "深蓝色");
        expect((await first).status()).toBe(200);
        const both = Promise.all([evaluationReply(page, 20), evaluationReply(page, 10)]);
        await addSma(page, 10, "红色");
        for (const reply of await both) expect(reply.status()).toBe(200);
        const chart = page.getByTestId("price-chart");
        await expect(chart).toHaveAttribute("data-study-series-count", "2");
        await expect(page.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "DISPLAYABLE"
        );
        if (collapsed) await page.getByRole("button", { name: "收起下方面板" }).click();
        const main = page.getByRole("region", { name: "主图", exact: true });
        // Scroll the existing owning region from its text surface. Wheel input on
        // the financial canvas intentionally zooms; it is not a page-scroll path.
        const bounds = await main.boundingBox();
        if (bounds === null) throw new Error("Missing main chart region");
        await page.mouse.move(bounds.x + 8, bounds.y + 8);
        await page.mouse.wheel(0, 2000);
        const timezone = page.getByRole("combobox", { name: "显示时区" });
        await timezone.focus();
        const geometry = await chart.evaluate((element) => {
            const main = element.closest(".chart-region");
            const surface = element.closest(".price-chart-surface");
            if (main === null || surface === null) throw new Error("Missing owning chart layout");
            const clip = main.getBoundingClientRect(),
                plot = element.getBoundingClientRect();
            const footer = surface
                .querySelector(".chart-display-controls")
                ?.getBoundingClientRect();
            return {
                clip: { top: clip.top, bottom: clip.bottom },
                plot: { top: plot.top, bottom: plot.bottom, height: plot.height },
                footer: footer === undefined ? null : { top: footer.top, bottom: footer.bottom },
                scrollTop: main.scrollTop,
                scrollHeight: main.scrollHeight,
                clientHeight: main.clientHeight
            };
        });
        await testInfo.attach("constrained-chart-layout", {
            body: JSON.stringify(geometry),
            contentType: "application/json"
        });
        expect(geometry.plot.height).toBeGreaterThanOrEqual(220);
        expect(geometry.plot.top).toBeGreaterThanOrEqual(geometry.clip.top);
        expect(geometry.plot.bottom).toBeLessThanOrEqual(geometry.clip.bottom);
        expect(geometry.footer?.bottom).toBeLessThanOrEqual(geometry.clip.bottom);
        await expect(timezone).toBeInViewport({ ratio: 1 });
        await timezone.selectOption("Asia/Shanghai");
        await expect(timezone).toHaveValue("Asia/Shanghai");
        await page.getByRole("button", { name: "编辑 SMA", exact: true }).first().click();
        await expect(page.getByRole("dialog", { name: "指标 / 因子参数配置" })).toBeVisible();
        await page.getByRole("button", { name: "取消配置" }).click();
        await expect(chart).toHaveAttribute("data-study-series-count", "2");
    });
}
