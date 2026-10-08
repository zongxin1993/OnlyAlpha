import { expect, test, type Page, type Route, type WebSocketRoute } from "@playwright/test";

const integrationId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const integrationRevision = "a".repeat(64);
const historicalRevision = "d".repeat(64);
const historyFingerprint = "8".repeat(64);
const sourceId = "binance.spot.market_data.us";
const minuteNs = BigInt("60000000000");
const historyStart = BigInt("1767225600000000000");
const historyEnd = historyStart + BigInt(1_440) * minuteNs;
const planFingerprint = (durationMinutes: number) => durationMinutes.toString(16).padStart(64, "0");
const nativeSteps = new Set([1, 3, 5, 15, 30, 60, 120, 240]);
const semantic = (durationMinutes: number) => ({
    schema_version: 2,
    formation: {
        schema_version: 1,
        kind: "FIXED_DURATION",
        window_minutes: durationMinutes,
        stride_minutes: durationMinutes,
        alignment: "SESSION_START"
    },
    price_type: "LAST",
    adjustment_policy: "RAW"
});

const source = {
    integration_id: integrationId,
    integration_revision_fingerprint: integrationRevision,
    display_name: "Binance Spot US",
    type_id: "binance.spot.market_data",
    source_id: sourceId,
    environment: "US",
    time_bar_capability: {
        provider_base_semantic: semantic(1),
        derived_algorithm: "TIME_BAR@1",
        minimum_window_minutes: 1,
        maximum_window_minutes: 240
    }
};
const instrument = {
    instrument_id: "BTCUSDT.BINANCE",
    display_symbol: "BTCUSDT",
    venue: "BINANCE",
    market: "SPOT",
    asset_class: "CRYPTOCURRENCY",
    instrument_type: "CRYPTO_SPOT",
    status: "ACTIVE",
    market_data_capabilities: ["BAR_1M_EXTERNAL_RAW"]
};

const json = (route: Route, body: unknown) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });

async function controlledRealtime(
    page: Page,
    holdRecovery = false,
    acquireHistory = false,
    defaultGlobal = false
) {
    const environment = defaultGlobal ? "GLOBAL" : "US";
    let socket: WebSocketRoute | null = null;
    let connections = 0;
    const completedSteps = new Set<number>();
    let acquisitions = 0;
    const acquisitionSteps: number[] = [];
    let releaseRecovery: (() => void) | null = null;
    let emitStalePreview: (() => void) | null = null;
    let emitPreview: (() => void) | null = null;
    const cursors: string[] = [];
    const steps: number[] = [];
    const historyAnchors: string[] = [];
    const historySteps: number[] = [];
    const subscriptions: object[] = [];
    const olderRequests: URL[] = [];
    await page.route("**/api/v2/**", (route) => {
        const url = new URL(route.request().url());
        if (url.pathname === "/api/v2/market-data/sources")
            return json(route, { schema_version: 1, sources: [{ ...source, environment }] });
        if (url.pathname === "/api/v2/market/instruments")
            return json(route, {
                schema_version: 1,
                source_selection: {
                    integration_id: integrationId,
                    integration_revision_fingerprint: integrationRevision,
                    type_id: source.type_id,
                    source_id: sourceId,
                    environment
                },
                instruments: [instrument]
            });
        if (url.pathname === "/api/v2/market-data/bars") {
            const anchor = url.searchParams.get("anchor_kind");
            expect(anchor === "LATEST_CLOSED" || anchor === "BEFORE_TIME").toBe(true);
            historyAnchors.push(anchor ?? "");
            const targetCount = Number(url.searchParams.get("target_bar_count"));
            expect([1440, 240]).toContain(targetCount);
            expect(url.searchParams.has("start_ns")).toBe(false);
            const requested = JSON.parse(
                url.searchParams.get("bar_semantic") ?? "null"
            ) as ReturnType<typeof semantic>;
            const step = requested.formation.window_minutes;
            historySteps.push(step);
            const older = targetCount === 240;
            const before = url.searchParams.get("before_ns");
            if (older && before === null) throw new Error("older query requires before_ns");
            const end = older ? BigInt(before ?? "0") : historyEnd;
            const start = older ? end - BigInt(240 * step) * minuteNs : historyStart;
            if (older) {
                expect(anchor).toBe("BEFORE_TIME");
                olderRequests.push(url);
            } else {
                expect(targetCount).toBe(1440);
                if (anchor === "BEFORE_TIME")
                    expect(url.searchParams.get("before_ns")).toBe(end.toString());
            }
            const native = nativeSteps.has(step);
            const historyComplete = !acquireHistory || completedSteps.has(step);
            const duration = BigInt(step) * minuteNs;
            const bar = (offset: bigint, close: string) => ({
                bar_start_ns: (start + offset).toString(),
                bar_end_ns: (start + offset + duration).toString(),
                open: "100",
                high: "103",
                low: "99",
                close,
                volume: "2",
                closed: true
            });
            return json(route, {
                schema_version: 1,
                source_selection: {
                    integration_id: integrationId,
                    integration_revision_fingerprint: integrationRevision,
                    type_id: source.type_id,
                    source_id: sourceId,
                    environment
                },
                instrument_id: instrument.instrument_id,
                display_symbol: instrument.display_symbol,
                venue: instrument.venue,
                market: instrument.market,
                bar_semantic: semantic(step),
                closed_only: true,
                anchor_kind: anchor,
                requested_before_ns: anchor === "BEFORE_TIME" ? end.toString() : null,
                requested_bar_count: targetCount,
                resolved_start_ns: start.toString(),
                resolved_end_ns: end.toString(),
                coverage: {
                    status: historyComplete ? "COMPLETE" : "INCOMPLETE",
                    manifest_id: "manifest",
                    manifest_fingerprint: "c".repeat(64),
                    expected_bar_count: 1440,
                    actual_bar_count: historyComplete ? 1440 : 0,
                    issues: historyComplete ? [] : ["BAR_GRID_INCOMPLETE"],
                    gaps: historyComplete ? [] : [{ start_ns: String(start), end_ns: String(end) }],
                    planned_acquisition_ranges: historyComplete
                        ? []
                        : [{ start_ns: String(start), end_ns: String(end) }]
                },
                revision_evidence: historyComplete
                    ? [
                          {
                              revision_id: "revision",
                              revision_fingerprint: historicalRevision,
                              manifest_id: "manifest",
                              manifest_fingerprint: "c".repeat(64),
                              seal_id: "seal",
                              covered_start_ns: start.toString(),
                              covered_end_ns: end.toString()
                          }
                      ]
                    : [],
                history_projection_fingerprint: historyComplete ? historyFingerprint : null,
                derived_projection_fingerprint: historyComplete && !native ? "9".repeat(64) : null,
                aggregation_semantics_version: native ? null : "TIME_BAR_V1",
                calendar_fingerprint: native ? null : "a".repeat(64),
                resolution_mode: native ? "PROVIDER_NATIVE" : "DERIVED",
                resolution_plan_fingerprint: planFingerprint(step),
                resume_after_sequence: historyComplete
                    ? (
                          end / (step === 15 ? BigInt(15) * minuteNs : minuteNs) -
                          BigInt(1)
                      ).toString()
                    : null,
                resume_plan_fingerprint: historyComplete ? planFingerprint(step) : null,
                bars: historyComplete ? [bar(BigInt(0), "101"), bar(duration, "102")] : []
            });
        }
        if (
            url.pathname === "/api/v2/market-data/acquisitions" &&
            route.request().method() === "POST"
        ) {
            acquisitions += 1;
            const request = route.request().postDataJSON() as {
                start_ns: string;
                end_ns: string;
                bar_semantic: ReturnType<typeof semantic>;
            };
            acquisitionSteps.push(request.bar_semantic.formation.window_minutes);
            completedSteps.add(request.bar_semantic.formation.window_minutes);
            return json(route, {
                schema_version: 1,
                acquisition_id: `acquisition:${"b".repeat(64)}`,
                status: "COMPLETE",
                source_id: sourceId,
                integration_binding_fingerprint: "f".repeat(64),
                instrument_id: instrument.instrument_id,
                bar_semantic: request.bar_semantic,
                start_ns: request.start_ns,
                end_ns: request.end_ns,
                provenance: "REST_BACKFILL",
                coverage: {
                    status: "COMPLETE",
                    manifest_id: "manifest",
                    manifest_fingerprint: "c".repeat(64),
                    expected_bar_count: 1440,
                    actual_bar_count: 1440,
                    issues: [],
                    gaps: [],
                    planned_acquisition_ranges: []
                },
                revision_id: "revision",
                revision_fingerprint: historicalRevision,
                seal_id: "seal",
                failure_detail: null
            });
        }
        return route.fallback();
    });
    await page.routeWebSocket("**/api/v2/market-data/stream", (ws) => {
        socket = ws;
        const connection = ++connections;
        ws.onMessage((message) => {
            const request = JSON.parse(String(message)) as {
                resume_after_sequence: string;
                resume_plan_fingerprint: string;
                bar_semantic: ReturnType<typeof semantic>;
            };
            subscriptions.push(request);
            cursors.push(request.resume_after_sequence);
            const step = request.bar_semantic.formation.window_minutes;
            steps.push(step);
            const send = (event: object) => {
                ws.send(JSON.stringify({ schema_version: 2, ...event }));
            };
            send({
                event: "SUBSCRIBED",
                stream_id: `stream-${String(connection)}`,
                source_id: sourceId,
                instrument_id: instrument.instrument_id,
                resolution_mode: nativeSteps.has(step) ? "PROVIDER_NATIVE" : "DERIVED",
                resolution_plan_fingerprint: planFingerprint(step),
                cursor_bar_stride_minutes: nativeSteps.has(step) ? step : 1
            });
            send({ event: "STATE", state: "RECOVERING" });
            const sequence = (BigInt(request.resume_after_sequence) + BigInt(1)).toString();
            const cursorStride = step === 15 ? BigInt(15) : BigInt(1);
            const derivedBar = {
                bar_start_ns: (BigInt(sequence) * cursorStride * minuteNs).toString(),
                bar_end_ns: (
                    (BigInt(sequence) * cursorStride + BigInt(step)) *
                    minuteNs
                ).toString(),
                open: "102",
                high: "104",
                low: "101",
                close: "103",
                volume: "3",
                closed: false
            };
            send({
                event: "BAR_PREVIEW",
                source_id: sourceId,
                instrument_id: instrument.instrument_id,
                bar_semantic: request.bar_semantic,
                bar: derivedBar
            });
            send({
                event: "BAR_CLOSED",
                source_id: sourceId,
                instrument_id: instrument.instrument_id,
                bar_semantic: request.bar_semantic,
                sequence,
                bar: { ...derivedBar, closed: true }
            });
            emitStalePreview = () => {
                send({
                    event: "BAR_PREVIEW",
                    source_id: sourceId,
                    instrument_id: instrument.instrument_id,
                    bar_semantic: request.bar_semantic,
                    bar: {
                        ...derivedBar,
                        bar_start_ns: (
                            (BigInt(sequence) - BigInt(1)) *
                            cursorStride *
                            minuteNs
                        ).toString(),
                        bar_end_ns: (BigInt(sequence) * cursorStride * minuteNs).toString()
                    }
                });
                send({ event: "STATE", state: "RECOVERING" });
            };
            emitPreview = () => {
                send({
                    event: "BAR_PREVIEW",
                    source_id: sourceId,
                    instrument_id: instrument.instrument_id,
                    bar_semantic: request.bar_semantic,
                    bar: {
                        ...derivedBar,
                        bar_start_ns: BigInt(derivedBar.bar_end_ns).toString(),
                        bar_end_ns: (
                            BigInt(derivedBar.bar_end_ns) +
                            BigInt(step) * minuteNs
                        ).toString(),
                        close: "103.000000000000000001",
                        volume: "3.000000000000000001"
                    }
                });
            };
            if (connection === 1 || !holdRecovery) send({ event: "STATE", state: "READY" });
            else
                releaseRecovery = () => {
                    send({ event: "STATE", state: "READY" });
                };
        });
    });
    return {
        cursors,
        steps,
        acquisitions: () => acquisitions,
        acquisitionSteps,
        historyAnchors,
        historySteps,
        subscriptions,
        olderRequests,
        releaseRecovery: () => releaseRecovery?.(),
        emitStalePreview: () => emitStalePreview?.(),
        emitPreview: () => emitPreview?.(),
        disconnect: async () => {
            await socket?.close({ code: 1012, reason: "controlled disconnect" });
        }
    };
}

test("default LIVE workspace first subscribes at 15m and merges Product preview and closed Bars", async ({
    page
}) => {
    const providerTraffic: string[] = [];
    page.on("request", (request) => {
        if (/binance\.(com|vision)/.test(new URL(request.url()).hostname))
            providerTraffic.push(request.url());
    });
    page.on("websocket", (socket) => {
        if (/binance\.(com|vision)/.test(new URL(socket.url()).hostname))
            providerTraffic.push(socket.url());
    });
    const fixture = await controlledRealtime(page, false, false, true);
    await page.goto("/");
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    expect(fixture.historySteps).toEqual([15]);
    expect(fixture.steps).toEqual([15]);
    expect(fixture.subscriptions[0]).toMatchObject({
        operation: "SUBSCRIBE_BAR",
        instrument_id: "BTCUSDT.BINANCE",
        source_reference: {
            integration_id: integrationId,
            integration_revision_fingerprint: integrationRevision,
            expected_type_id: source.type_id
        },
        bar_semantic: semantic(15)
    });
    const observation = page.getByTestId("market-data-observation");
    await expect(observation).toHaveAttribute("data-observation-mode", "latest-closed");
    await expect(page.getByTestId("market-data-status")).toHaveAttribute(
        "data-loaded-bar-count",
        "3"
    );
    fixture.emitPreview();
    await expect(observation).toHaveAttribute("data-observation-mode", "preview");
    await expect(observation.locator('[data-observation-field="close"]')).toHaveText(
        "103.000000000000000001"
    );
    await expect(page.getByTestId("market-data-status")).toHaveAttribute(
        "data-loaded-bar-count",
        "3"
    );
    await expect(page.getByRole("combobox", { name: "时间周期" })).toHaveValue("15");
    expect(providerTraffic).toEqual([]);
});

test("chart type keeps realtime subscription and exact preview readout", async ({ page }) => {
    const fixture = await controlledRealtime(page);
    await page.goto("/");
    await page.getByRole("combobox", { name: "数据源" }).selectOption(integrationId);
    await page.getByRole("combobox", { name: "时间周期" }).selectOption("1");
    await page.getByRole("searchbox", { name: "搜索标的" }).fill("BTCUSDT");
    await page.getByRole("searchbox", { name: "搜索标的" }).press("Enter");
    await page.getByRole("button", { name: /BTCUSDT\.BINANCE/ }).click();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    const observation = page.getByTestId("market-data-observation");
    await expect(observation).toHaveAttribute("data-observation-mode", "latest-closed");
    fixture.emitPreview();
    await expect(observation).toHaveAttribute("data-observation-mode", "preview");
    await expect(observation.locator('[data-observation-field="close"]')).toHaveText(
        "103.000000000000000001"
    );
    await expect(observation.locator('[data-observation-field="volume"]')).toHaveText(
        "3.000000000000000001"
    );
    const barsRequests = fixture.historyAnchors.length;
    const subscriptions = fixture.cursors.length;
    for (const type of ["LINE", "CANDLESTICK"]) {
        await page.getByRole("combobox", { name: "图表类型" }).selectOption(type);
        await expect(page.getByTestId("price-chart")).toHaveAttribute("data-chart-type", type);
        await expect(observation).toHaveAttribute("data-observation-mode", "preview");
        await expect(observation.locator('[data-observation-field="close"]')).toHaveText(
            "103.000000000000000001"
        );
        expect(fixture.historyAnchors).toHaveLength(barsRequests);
        expect(fixture.cursors).toHaveLength(subscriptions);
        expect(fixture.acquisitions()).toBe(0);
        await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    }
});

test("history to realtime rollover and reconnect gap repair — CONTROLLED_TEST_EVIDENCE", async ({
    page
}) => {
    const fixture = await controlledRealtime(page, true);
    await page.goto("/");
    await page.getByRole("combobox", { name: "数据源" }).selectOption(integrationId);
    await page.getByRole("combobox", { name: "时间周期" }).selectOption("1");
    await page.getByRole("searchbox", { name: "搜索标的" }).fill("BTCUSDT");
    await page.getByRole("searchbox", { name: "搜索标的" }).press("Enter");
    await page.getByRole("button", { name: /BTCUSDT\.BINANCE/ }).click();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    expect(fixture.olderRequests).toHaveLength(0);
    await expect(page.getByTestId("market-data-status")).toHaveAttribute(
        "data-older-history-status",
        "idle"
    );

    await fixture.disconnect();
    await expect(page.getByTestId("market-data-status")).toContainText("● 行情中断");
    await expect(page.getByTestId("market-data-status")).toContainText("● 恢复中");
    fixture.releaseRecovery();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    expect(fixture.cursors).toHaveLength(2);
    expect(BigInt(fixture.cursors[1] ?? "0")).toBe(BigInt(fixture.cursors[0] ?? "0") + BigInt(1));
    expect(fixture.olderRequests).toHaveLength(0);
});

test("explicit history acquisition, typed realtime and exact reconnect — CONTROLLED_TEST_EVIDENCE", async ({
    page
}) => {
    const fixture = await controlledRealtime(page, true, true);
    await page.goto("/");
    await page.getByRole("combobox", { name: "数据源" }).selectOption(integrationId);
    await page.getByRole("combobox", { name: "时间周期" }).selectOption("1");
    await page.getByRole("searchbox", { name: "搜索标的" }).fill("BTCUSDT");
    await page.getByRole("searchbox", { name: "搜索标的" }).press("Enter");
    await page.getByRole("button", { name: /BTCUSDT\.BINANCE/ }).click();
    await expect(page.getByTestId("market-data-source-tag")).toHaveText("real · DB");
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    expect(fixture.acquisitions()).toBe(1);
    expect(fixture.historyAnchors.slice(0, 2)).toEqual(["LATEST_CLOSED", "BEFORE_TIME"]);
    await expect(page.getByTestId("price-chart").locator("canvas").first()).toBeVisible();

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("5");
    await expect.poll(() => fixture.steps[fixture.steps.length - 1]).toBe(5);
    fixture.releaseRecovery();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    await fixture.disconnect();
    await expect(page.getByTestId("market-data-status")).toContainText("● 行情中断");
    await expect(page.getByTestId("market-data-status")).toContainText("● 恢复中");
    fixture.releaseRecovery();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    expect(fixture.acquisitions()).toBe(2);
    expect(BigInt(fixture.cursors[fixture.cursors.length - 1] ?? "0")).toBeGreaterThan(
        BigInt(fixture.cursors[fixture.cursors.length - 2] ?? "0")
    );
});

test("preset and custom periods subscribe to matching derived realtime bars — CONTROLLED_TEST_EVIDENCE", async ({
    page
}) => {
    const fixture = await controlledRealtime(page);
    await page.goto("/");
    await page.getByRole("combobox", { name: "数据源" }).selectOption(integrationId);
    await page.getByRole("combobox", { name: "时间周期" }).selectOption("1");
    await page.getByRole("searchbox", { name: "搜索标的" }).fill("BTCUSDT");
    await page.getByRole("searchbox", { name: "搜索标的" }).press("Enter");
    await page.getByRole("button", { name: /BTCUSDT\.BINANCE/ }).click();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("15");
    await expect.poll(() => fixture.steps[fixture.steps.length - 1]).toBe(15);
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("60");
    await expect.poll(() => fixture.steps[fixture.steps.length - 1]).toBe(60);
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("custom");
    await page.getByRole("spinbutton", { name: "自定义周期分钟数" }).fill("7");
    await page.getByRole("button", { name: "应用" }).click();
    await expect.poll(() => fixture.steps[fixture.steps.length - 1]).toBe(7);
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    await page.getByRole("spinbutton", { name: "自定义周期分钟数" }).fill("37");
    await page.getByRole("button", { name: "应用" }).click();
    await expect.poll(() => fixture.steps[fixture.steps.length - 1]).toBe(37);
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    expect(fixture.steps).toEqual([1, 15, 60, 7, 37]);
});

test("native 15m and derived 7m use target acquisition and Product resume metadata", async ({
    page
}) => {
    const fixture = await controlledRealtime(page, false, true);
    await page.goto("/");
    await page.getByRole("combobox", { name: "数据源" }).selectOption(integrationId);
    await page.getByRole("combobox", { name: "时间周期" }).selectOption("1");
    await page.getByRole("searchbox", { name: "搜索标的" }).fill("BTCUSDT");
    await page.getByRole("searchbox", { name: "搜索标的" }).press("Enter");
    await page.getByRole("button", { name: /BTCUSDT\.BINANCE/ }).click();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("15");
    await expect.poll(() => fixture.acquisitionSteps).toEqual([1, 15]);
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("custom");
    await page.getByRole("spinbutton", { name: "自定义周期分钟数" }).fill("7");
    await page.getByRole("button", { name: "应用" }).click();
    await expect.poll(() => fixture.acquisitionSteps).toEqual([1, 15, 7]);
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    expect(fixture.steps).toEqual([1, 15, 7]);
});

test("a stale realtime preview cannot crash the chart — CONTROLLED_TEST_EVIDENCE", async ({
    page
}) => {
    const fixture = await controlledRealtime(page);
    await page.goto("/");
    await page.getByRole("combobox", { name: "数据源" }).selectOption(integrationId);
    await page.getByRole("combobox", { name: "时间周期" }).selectOption("1");
    await page.getByRole("searchbox", { name: "搜索标的" }).fill("BTCUSDT");
    await page.getByRole("searchbox", { name: "搜索标的" }).press("Enter");
    await page.getByRole("button", { name: /BTCUSDT\.BINANCE/ }).click();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    fixture.emitStalePreview();
    await expect(page.getByTestId("market-data-status")).toContainText("● 恢复中");
    await expect(page.getByTestId("price-chart").locator("canvas").first()).toBeVisible();
});
