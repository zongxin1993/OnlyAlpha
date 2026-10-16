import { useLayoutEffect } from "react";
import { AppProviders, useLocalReadCredentials } from "../../app/providers";
import { marketDataClient } from "../../test/marketDataClient";
import { marketDataBarsSchema } from "../../api/marketData/model";
import { ChartStudyCapabilitiesSchema } from "../../api/chartStudies/http.generated";
import { TransientStudyPriceChart } from "../../features/workspace/TransientStudyPriceChart";
import { projectMarketDataBar } from "./marketDataChartProjection";
import sample from "../../../../../test-data/web/chart-studies/query.json";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { PriceChart } from "./PriceChart";
import { studySeriesFixture } from "../../test/studySeries";

const renderer = vi.hoisted(() => {
    interface Pane {
        paneIndex: () => number;
        setPreserveEmptyPane: ReturnType<typeof vi.fn>;
        setStretchFactor: ReturnType<typeof vi.fn>;
        getHTMLElement: () => HTMLElement;
    }
    interface Series {
        readonly kind: string;
        readonly getPane: () => Pane;
        readonly moveToPane: ReturnType<typeof vi.fn<(index: number) => void>>;
        readonly setData: ReturnType<typeof vi.fn<(points: readonly unknown[]) => void>>;
        readonly update: ReturnType<typeof vi.fn<(point: unknown) => void>>;
        readonly applyOptions: ReturnType<typeof vi.fn<(options: unknown) => void>>;
    }
    const panes: Pane[] = [];
    const series: Series[] = [];
    const addPane = vi.fn((): Pane => {
        const pane: Pane = {
            paneIndex: () => panes.indexOf(pane),
            setPreserveEmptyPane: vi.fn(),
            setStretchFactor: vi.fn(),
            getHTMLElement: () => document.body
        };
        panes.push(pane);
        return pane;
    });
    const addSeries = vi.fn<(kind: string, options?: unknown, index?: number) => Series>(
        (kind, _options, index = 0) => {
            if (panes.length === 0) addPane();
            const initialPane = panes[index];
            if (initialPane === undefined) throw new Error("Invalid pane");
            let pane: Pane = initialPane;
            const created = {
                kind,
                getPane: () => pane,
                moveToPane: vi.fn((next: number) => {
                    const target = panes[next];
                    if (target === undefined) throw new Error("Invalid move");
                    pane = target;
                }),
                setData: vi.fn<(points: readonly unknown[]) => void>(),
                update: vi.fn<(point: unknown) => void>(),
                applyOptions: vi.fn<(options: unknown) => void>()
            };
            series.push(created);
            return created;
        }
    );
    const range = { value: { from: 30.25, to: 60.5 } };
    const timeScale = {
        applyOptions: vi.fn(),
        getVisibleLogicalRange: () => range.value,
        setVisibleLogicalRange: vi.fn((next: typeof range.value) => {
            range.value = next;
        }),
        subscribeVisibleLogicalRangeChange: vi.fn(),
        unsubscribeVisibleLogicalRangeChange: vi.fn()
    };
    const chart = {
        addSeries,
        applyOptions: vi.fn(),
        addPane,
        panes: () => panes,
        removePane: vi.fn((index: number) => {
            if (index < 0) throw new Error("Deleted pane reused");
            panes.splice(index, 1);
        }),
        removeSeries: vi.fn<(series: Series) => void>(),
        timeScale: () => timeScale,
        subscribeCrosshairMove: vi.fn(),
        unsubscribeCrosshairMove: vi.fn(),
        remove: vi.fn()
    };
    return { chart, addSeries, panes, series, range, timeScale, createChart: vi.fn(() => chart) };
});
vi.mock("lightweight-charts", () => ({
    CandlestickSeries: "Candlestick",
    LineSeries: "Line",
    HistogramSeries: "Histogram",
    ColorType: { Solid: "solid" },
    TickMarkType: { Time: 3, TimeWithSeconds: 4 },
    createChart: renderer.createChart
}));
beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    renderer.panes.length = 0;
    renderer.series.length = 0;
    renderer.range.value = { from: 30.25, to: 60.5 };
});
afterEach(cleanup);

it("renders only formal market volume and updates preview, preserving the same volume pane through chart mode changes", () => {
    const { bars } = studySeriesFixture();
    const view = render(<PriceChart bars={bars} contextKey="controlled-chart" />);
    const price = renderer.series[0],
        volume = renderer.series[1];
    expect(volume?.kind).toBe("Histogram");
    expect(volume?.setData).toHaveBeenLastCalledWith(
        bars.map((bar) => ({ time: bar.time, value: bar.numeric.volume, color: "#c8332a" }))
    );
    expect(screen.getByTestId("price-chart")).toHaveAttribute("data-study-series-count", "0");
    const last = bars.at(-1);
    if (last === undefined) throw new Error("Missing bar");
    view.rerender(
        <PriceChart
            bars={bars}
            contextKey="controlled-chart"
            liveBar={{
                ...last,
                closed: false,
                volume: "4.000000000000000001",
                numeric: { ...last.numeric, volume: 4 }
            }}
            chartType="LINE"
        />
    );
    expect(volume?.setData.mock.calls.at(-1)?.[0]).toEqual(
        bars.map((bar) => ({
            time: bar.time,
            value: bar.time === last.time ? 4 : bar.numeric.volume,
            color: "#c8332a"
        }))
    );
    expect(screen.getByTestId("price-chart")).toHaveAttribute(
        "data-volume-latest",
        "4.000000000000000001"
    );
    expect(renderer.chart.removeSeries).toHaveBeenCalledWith(price);
    expect(renderer.chart.removeSeries).not.toHaveBeenCalledWith(volume);
    expect(renderer.createChart).toHaveBeenCalledTimes(1);
    expect(renderer.panes).toHaveLength(2);
});
it("keeps separate pane refs and instance resources across hide/move/remove without resetting price viewport or callbacks", () => {
    const { bars, instance, evidence } = studySeriesFixture();
    const a = {
        ...instance,
        presentation: { ...instance.presentation, placement: "SEPARATE_PANE" as const }
    };
    const b = { ...a, instanceId: "other" };
    const otherEvidence = { ...evidence, instanceId: b.instanceId };
    const view = render(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            studies={[a, b]}
            incarnationKey={evidence.incarnationKey}
            studyEvidence={[evidence, otherEvidence]}
        />
    );
    expect(screen.getByTestId("price-chart")).toHaveAttribute("data-pane-count", "4");
    expect(screen.getByTestId("price-chart")).toHaveAttribute("data-study-series-count", "4");
    const otherLines = renderer.series.slice(4);
    const bPane = otherLines[0]?.getPane();
    const range = { ...renderer.range.value };
    view.rerender(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            studies={[{ ...a, presentation: { ...a.presentation, visible: false } }, b]}
            incarnationKey={evidence.incarnationKey}
            studyEvidence={[evidence, otherEvidence]}
        />
    );
    expect(renderer.panes).toHaveLength(3);
    expect(renderer.panes[2]).toBe(bPane);
    expect(
        otherLines.every(
            (line) => !renderer.chart.removeSeries.mock.calls.some(([removed]) => removed === line)
        )
    ).toBe(true);
    view.rerender(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            studies={[{ ...a, presentation: { ...a.presentation, placement: "PRICE_OVERLAY" } }, b]}
            incarnationKey={evidence.incarnationKey}
            studyEvidence={[evidence, otherEvidence]}
            selectedStudyId={a.instanceId}
        />
    );
    expect(renderer.panes).toHaveLength(3);
    expect(renderer.range.value).toEqual(range);
    expect(renderer.createChart).toHaveBeenCalledTimes(1);
    view.rerender(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            studies={[b]}
            incarnationKey={evidence.incarnationKey}
            studyEvidence={[otherEvidence]}
        />
    );
    expect(screen.getAllByTestId("study-hover")).toHaveLength(1);
    expect(renderer.chart.subscribeCrosshairMove).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(renderer.chart.unsubscribeCrosshairMove).toHaveBeenCalledTimes(1);
    expect(renderer.chart.remove).toHaveBeenCalledTimes(1);
});
it("hover uses exact timestamp/identity, never a previous point; stale/context change clear lines and hover", () => {
    const { bars, instance, evidence } = studySeriesFixture();
    const onSelection = vi.fn();
    const view = render(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            studies={[instance]}
            incarnationKey={evidence.incarnationKey}
            studyEvidence={[evidence]}
            onSelection={onSelection}
        />
    );
    const callback = renderer.chart.subscribeCrosshairMove.mock.calls[0]?.[0] as
        ((event: unknown) => void) | undefined;
    act(() => {
        callback?.({ point: { x: 1, y: 2 }, time: bars[40]?.time });
    });
    expect(screen.getByText(/UTC ns/)).not.toBeVisible();
    fireEvent.click(within(screen.getByTestId("study-hover")).getByLabelText("指标点详情 SMA"));
    expect(screen.getByText(/UTC ns/)).toBeVisible();
    expect(screen.getByTestId("study-hover")).toHaveTextContent(
        "PRE_READY · controlled missing value"
    );
    act(() => {
        callback?.({ point: { x: 1, y: 2 }, time: (bars[40]?.time ?? 0) + 1 });
    });
    expect(screen.getByTestId("study-hover")).toHaveTextContent("此时间无对应结果");
    expect(onSelection).toHaveBeenLastCalledWith(null);
    view.rerender(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            studies={[{ ...instance, connectionState: "STALE_CONFIG" }]}
            incarnationKey={evidence.incarnationKey}
            studyEvidence={[evidence]}
        />
    );
    expect(screen.getByTestId("price-chart")).toHaveAttribute("data-study-series-count", "0");
    expect(screen.getByTestId("study-hover")).toHaveTextContent("配置已过期");
    view.rerender(
        <PriceChart
            bars={bars}
            contextKey="different"
            studies={[instance]}
            incarnationKey="new"
            studyEvidence={[evidence]}
        />
    );
    expect(screen.queryByTestId("study-hover")).not.toBeInTheDocument();
    expect(renderer.panes).toHaveLength(2);
});
it("new incarnation suppresses old hover immediately even with matching context and new evidence", () => {
    const { bars, instance, evidence } = studySeriesFixture();
    const view = render(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            studies={[instance]}
            incarnationKey={evidence.incarnationKey}
            studyEvidence={[evidence]}
        />
    );
    const callback = renderer.chart.subscribeCrosshairMove.mock.calls[0]?.[0] as
        ((event: unknown) => void) | undefined;
    act(() => {
        callback?.({ point: { x: 1, y: 1 }, time: bars[0]?.time });
    });
    expect(screen.getByTestId("study-hover")).toHaveTextContent("102.000000000000000001");
    view.rerender(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            studies={[instance]}
            incarnationKey="new-incarnation"
            studyEvidence={[{ ...evidence, incarnationKey: "new-incarnation" }]}
        />
    );
    expect(screen.getByTestId("study-hover")).toHaveTextContent("请移动十字线");
    act(() => {
        callback?.({ point: { x: 1, y: 1 }, time: bars[0]?.time });
    });
    expect(screen.getByTestId("study-hover")).toHaveTextContent("102.000000000000000001");
});
it("malformed presentation and null evidence release prior curves without affecting Price/Volume/another owner", () => {
    const { bars, instance, evidence } = studySeriesFixture();
    const a = {
        ...instance,
        presentation: { ...instance.presentation, placement: "SEPARATE_PANE" as const }
    };
    const b = { ...instance, instanceId: "other-owner" };
    const otherEvidence = { ...evidence, instanceId: b.instanceId };
    const view = render(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            studies={[a, b]}
            incarnationKey={evidence.incarnationKey}
            studyEvidence={[evidence, otherEvidence]}
        />
    );
    const stable = [renderer.series[0], renderer.series[1], ...renderer.series.slice(4)];
    view.rerender(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            studies={[
                {
                    ...a,
                    connectionState: "STALE_CONFIG",
                    presentation: { ...a.presentation, opacity: NaN }
                },
                b
            ]}
            incarnationKey={evidence.incarnationKey}
            studyEvidence={[evidence, otherEvidence]}
        />
    );
    expect(screen.getByTestId("price-chart")).toHaveAttribute("data-study-series-count", "2");
    expect(renderer.panes).toHaveLength(2);
    expect(
        stable.every(
            (line) => !renderer.chart.removeSeries.mock.calls.some(([removed]) => removed === line)
        )
    ).toBe(true);
    view.rerender(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            studies={[a, b]}
            incarnationKey={evidence.incarnationKey}
            studyEvidence={[null as unknown as typeof evidence]}
        />
    );
    expect(screen.getByTestId("price-chart")).toHaveAttribute("data-study-series-count", "0");
    expect(
        screen
            .getAllByTestId("study-hover")
            .every((element) => element.textContent.includes("非法"))
    ).toBe(true);
});

it("keeps both PRICE outputs on the main right scale and isolates controlled other/unknown units without changing values", () => {
    const { bars, instance, evidence } = studySeriesFixture();
    const units = ["PRICE", "PRICE", "PERCENT", null];
    const studies = units.map((_, index) => ({
        ...instance,
        instanceId: String(index),
        configuration: {
            ...instance.configuration,
            parameters: {
                ...instance.configuration.parameters,
                period: { type: "INTEGER" as const, value: index === 1 ? 10 : 20 }
            }
        }
    }));
    render(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            studies={studies}
            incarnationKey={evidence.incarnationKey}
            studyEvidence={units.map((outputUnit, index) => ({
                ...evidence,
                instanceId: String(index),
                outputUnit,
                configurationKey: JSON.stringify(studies[index]?.configuration)
            }))}
        />
    );
    expect(renderer.panes).toHaveLength(4);
    expect(renderer.series.slice(2, 6).every((line) => line.getPane() === renderer.panes[0])).toBe(
        true
    );
    expect(renderer.series.slice(6, 8).every((line) => line.getPane() === renderer.panes[2])).toBe(
        true
    );
    expect(renderer.series.slice(8).every((line) => line.getPane() === renderer.panes[3])).toBe(
        true
    );
    expect(
        renderer.series
            .slice(2)
            .every((line) =>
                line.applyOptions.mock.calls.some(
                    ([options]) => (options as { priceScaleId?: string }).priceScaleId === "right"
                )
            )
    ).toBe(true);
    expect(screen.getAllByTestId("study-hover")[3]).toHaveTextContent("单位未知");
    expect(renderer.series[6]?.setData.mock.calls[0]?.[0][0]).toEqual({
        time: bars[0]?.time,
        value: 102
    });
});
it("colors up/down/doji volume and preview by the corresponding candle and keeps exact hover", () => {
    const { bars } = studySeriesFixture();
    const first = bars[0];
    if (!first) throw new Error("Missing bar");
    const controlled = [
        first,
        { ...first, time: first.time + 900, numeric: { ...first.numeric, close: 99 } },
        { ...first, time: first.time + 1800, numeric: { ...first.numeric, close: 100 } }
    ] as typeof bars;
    const view = render(<PriceChart bars={controlled} contextKey="volume" />);
    expect(renderer.series[1]?.setData.mock.calls.at(-1)?.[0]).toEqual([
        { time: first.time, value: first.numeric.volume, color: "#c8332a" },
        { time: first.time + 900, value: first.numeric.volume, color: "#2f7d47" },
        { time: first.time + 1800, value: first.numeric.volume, color: "#c8332a" }
    ]);
    view.rerender(
        <PriceChart
            bars={controlled}
            contextKey="volume"
            liveBar={{
                ...first,
                closed: false,
                time: (first.time + 2700) as typeof first.time,
                volume: "4.000000000000000001",
                numeric: { ...first.numeric, close: 99, volume: 4 }
            }}
        />
    );
    expect(renderer.series[1]?.setData.mock.calls.at(-1)?.[0].at(-1)).toEqual({
        time: first.time + 2700,
        value: 4,
        color: "#2f7d47"
    });
    act(() => {
        const callback = renderer.chart.subscribeCrosshairMove.mock.calls[0]?.[0] as (
            event: unknown
        ) => void;
        callback({ point: { x: 1, y: 1 }, time: first.time + 900 });
    });
    expect(screen.getByLabelText("成交量悬浮信息")).toHaveTextContent("2.1234567890123456789");
    act(() => {
        const callback = renderer.chart.subscribeCrosshairMove.mock.calls[0]?.[0] as (
            event: unknown
        ) => void;
        callback({ point: { x: 1, y: 1 }, time: first.time + 2700 });
    });
    expect(screen.getByLabelText("成交量悬浮信息")).toHaveTextContent("4.000000000000000001");
    view.rerender(
        <PriceChart
            bars={controlled}
            contextKey="volume"
            liveBar={{
                ...first,
                closed: false,
                time: (first.time + 2700) as typeof first.time,
                volume: "5.000000000000000001",
                numeric: { ...first.numeric, close: 101, volume: 5 }
            }}
        />
    );
    expect(screen.getByLabelText("成交量悬浮信息")).toHaveTextContent("5.000000000000000001");
    expect(renderer.series[1]?.setData.mock.calls.at(-1)?.[0].at(-1)).toEqual({
        time: first.time + 2700,
        value: 5,
        color: "#c8332a"
    });
});
it("changes only native formatters for timezone, preserving all series data and viewport", () => {
    const { bars } = studySeriesFixture();
    render(<PriceChart bars={bars} contextKey="timezone" />);
    const range = { ...renderer.range.value };
    const writes = renderer.series.map((line) => line.setData.mock.calls.length);
    const select = screen.getByRole("combobox", { name: "显示时区" });
    expect(select).toHaveValue("UTC");
    fireEvent.change(select, { target: { value: "Asia/Shanghai" } });
    expect(select).toHaveValue("Asia/Shanghai");
    expect(renderer.series.map((line) => line.setData.mock.calls.length)).toEqual(writes);
    expect(renderer.range.value).toEqual(range);
    expect(renderer.createChart).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem("onlyalpha.chart.displayTimezone")).toBe("Asia/Shanghai");
});
it("recovers corrupt display preference and remains selectable when storage is denied", () => {
    localStorage.setItem("onlyalpha.chart.displayTimezone", "invalid-zone");
    const { bars } = studySeriesFixture();
    render(<PriceChart bars={bars} />);
    const select = screen.getByRole("combobox", { name: "显示时区" });
    expect(select).toHaveValue("UTC");
    expect(screen.getByRole("status")).toHaveTextContent("时区偏好已损坏");
    const storage = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new Error("denied");
    });
    fireEvent.change(select, { target: { value: "USER_LOCAL" } });
    expect(select).toHaveValue("USER_LOCAL");
    expect(screen.getByRole("status")).toHaveTextContent("仅本次显示生效");
    storage.mockRestore();
});

it("a displayed admitted transient study keeps every Query input and call unchanged across all timezone choices and denied storage", async () => {
    vi.stubGlobal(
        "crypto",
        (await vi.importActual<{ webcrypto: Crypto }>("node:crypto")).webcrypto
    );
    const history = marketDataBarsSchema.parse(sample.history);
    const capability = ChartStudyCapabilitiesSchema.parse({
        schema_version: 2,
        capabilities: [sample.capability]
    }).capabilities[0];
    if (!capability) throw new Error("Missing producer capability");
    const { instance } = studySeriesFixture();
    const context = {
        key: "admitted-display",
        source: {
            integration_id: history.source_selection.integration_id,
            integration_revision_fingerprint:
                history.source_selection.integration_revision_fingerprint,
            expected_type_id: history.source_selection.type_id
        },
        instrumentId: history.instrument_id,
        barSemantic: history.bar_semantic
    };
    const studies = [
        {
            ...instance,
            context,
            selection: { source: "CHART_STUDY_TRANSIENT" as const, capability }
        }
    ];
    const bars = history.bars.map(projectMarketDataBar);
    const queryBars = vi.fn(() => Promise.resolve(history));
    const transport = vi.fn((url: string) =>
        Promise.resolve(
            new Response(
                JSON.stringify(
                    url.endsWith("capabilities")
                        ? { schema_version: 2, capabilities: [sample.capability] }
                        : sample.evaluation
                ),
                { headers: { "cache-control": "no-store" } }
            )
        )
    );
    vi.stubGlobal("fetch", transport);
    function Query() {
        const credentials = useLocalReadCredentials();
        useLayoutEffect(() => {
            if (credentials.capture().bearer === null) credentials.replace("ee".repeat(32));
        }, [credentials]);
        return (
            <TransientStudyPriceChart
                context={context}
                contextKey={context.key}
                incarnationKey="display-owner"
                dataGeneration="verified-closed"
                expectedSourceId={history.source_selection.source_id}
                expectedEnvironment={history.source_selection.environment}
                studies={studies}
                bars={bars}
            />
        );
    }
    const view = render(
        <AppProviders marketDataClient={marketDataClient({ queryBars })}>
            <Query />
        </AppProviders>
    );
    await waitFor(() => {
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "DISPLAYABLE"
        );
    });
    const reads = queryBars.mock.calls.length,
        requests = transport.mock.calls.length;
    const series = renderer.series.map((line) => line.setData.mock.calls.length);
    const range = { ...renderer.range.value };
    const storage = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new Error("denied");
    });
    for (const zone of ["Asia/Shanghai", "USER_LOCAL", "UTC"]) {
        act(() => {
            fireEvent.change(screen.getByRole("combobox", { name: "显示时区" }), {
                target: { value: zone }
            });
        });
        expect(screen.getByRole("combobox", { name: "显示时区" })).toHaveValue(zone);
        expect(queryBars).toHaveBeenCalledTimes(reads);
        expect(transport).toHaveBeenCalledTimes(requests);
        expect(renderer.series.map((line) => line.setData.mock.calls.length)).toEqual(series);
        expect(renderer.range.value).toEqual(range);
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "DISPLAYABLE"
        );
    }
    storage.mockRestore();
    view.unmount();
    vi.unstubAllGlobals();
});

it("keeps two selected outputs in one instance pane and rejects a duplicate output owner", () => {
    const { bars, instance, evidence } = studySeriesFixture();
    const group = {
        ...instance,
        configuration: { ...instance.configuration, outputNames: ["fast", "slow"] },
        presentation: { ...instance.presentation, placement: "SEPARATE_PANE" as const }
    };
    const rows = ["fast", "slow"].map((outputName) => ({
        ...evidence,
        outputName,
        configurationKey: JSON.stringify(group.configuration)
    }));
    const view = render(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            incarnationKey={evidence.incarnationKey}
            studies={[group]}
            studyEvidence={rows}
        />
    );
    expect(renderer.panes).toHaveLength(3);
    expect(screen.getByTestId("price-chart")).toHaveAttribute("data-study-series-count", "4");
    view.rerender(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            incarnationKey={evidence.incarnationKey}
            studies={[group]}
            studyEvidence={[...rows, ...rows.slice(0, 1)]}
        />
    );
    expect(screen.getAllByTestId("study-hover")[0]).toHaveTextContent("重复身份");
});
