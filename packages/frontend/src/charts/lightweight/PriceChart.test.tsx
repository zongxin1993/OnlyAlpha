import {
    temporaryWindowVector,
    temporaryEvaluationVector,
    temporaryBatchVector
} from "../../test/temporaryChartVectors";
import { AppProviders } from "../../app/providers";
import { marketDataClient } from "../../test/marketDataClient";
import { marketDataBarsSchema } from "../../api/marketData/model";
import {
    ChartStudyCapabilitiesSchema,
    ChartStudyEvaluateSchema
} from "../../api/chartStudies/http.generated";
import { TransientStudyPriceChart } from "../../features/workspace/TransientStudyPriceChart";
import { projectMarketDataBar } from "./marketDataChartProjection";
import sample from "../../../../../test-data/web/chart-studies/query.json";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { displayTimezones } from "./chartDisplayTime";
import { PriceChart } from "./PriceChart";
import { studySeriesFixture } from "../../test/studySeries";

it("updates preview prices without rewriting unchanged closed study series", () => {
    const { bars, instance, evidence } = studySeriesFixture();
    const last = bars.at(-1);
    if (last === undefined) throw new Error("Missing last bar");
    const studies = [instance];
    const studyEvidence = [evidence];
    const preview = {
        ...last,
        closed: false,
        time: (last.time + 900) as typeof last.time,
        barStartNs: last.barEndNs,
        barEndNs: (BigInt(last.barEndNs) + 900_000_000_000n).toString()
    };
    const renderChart = (close: number, time = preview.time) => (
        <PriceChart
            bars={bars}
            studies={studies}
            studyEvidence={studyEvidence}
            contextKey={instance.context.key}
            incarnationKey={evidence.incarnationKey}
            liveBar={{ ...preview, time, numeric: { ...preview.numeric, close } }}
        />
    );
    const view = render(renderChart(101));
    const curves = renderer.series.slice(2);
    expect(curves.length).toBeGreaterThan(0);
    const writes = curves.map((curve) => curve.setData.mock.calls.length);
    const priceWrites = renderer.series[0]?.setData.mock.calls.length;
    const volumeWrites = renderer.series[1]?.setData.mock.calls.length;
    for (let close = 102; close <= 111; close++) view.rerender(renderChart(close));
    expect(curves.map((curve) => curve.setData.mock.calls.length)).toEqual(writes);
    expect(renderer.series[0]?.setData.mock.calls.length).toBe(priceWrites);
    expect(renderer.series[1]?.setData.mock.calls.length).toBe(volumeWrites);
    expect(renderer.series[0]?.update.mock.calls.at(-1)?.[0]).toMatchObject({ close: 111 });
    view.rerender(renderChart(112, (preview.time + 900) as typeof preview.time));
    const nextWindow = renderer.series[0]?.setData.mock.calls.at(-1)?.[0];
    expect(nextWindow).toHaveLength(bars.length + 1);
    expect(nextWindow).not.toContainEqual(expect.objectContaining({ time: preview.time }));
    expect(
        curves.some(
            (curve, index) =>
                curve.setData.mock.calls.length > (writes[index] ?? 0) ||
                curve.update.mock.calls.length > 0
        )
    ).toBe(true);
});

it("appends admitted closes without replacing price or volume history", () => {
    const { bars, instance } = studySeriesFixture();
    const initial = bars.slice(0, -1);
    const closed = bars.at(-1);
    if (closed === undefined) throw new Error("Missing closed bar");
    const view = render(
        <PriceChart
            bars={initial}
            contextKey={instance.context.key}
            liveBar={{ ...closed, closed: false }}
        />
    );
    const price = renderer.series[0];
    const volume = renderer.series[1];
    const priceWrites = price?.setData.mock.calls.length;
    const volumeWrites = volume?.setData.mock.calls.length;
    view.rerender(<PriceChart bars={bars} contextKey={instance.context.key} />);
    expect(price?.setData.mock.calls.length).toBe(priceWrites);
    expect(volume?.setData.mock.calls.length).toBe(volumeWrites);
    expect(price?.update).toHaveBeenLastCalledWith(
        expect.objectContaining({ time: closed.time, close: closed.numeric.close })
    );
    expect(volume?.update).toHaveBeenLastCalledWith(
        expect.objectContaining({ time: closed.time, value: closed.numeric.volume })
    );
});

it("updates an appended study point while retaining its existing series", () => {
    const { bars, instance, evidence } = studySeriesFixture();
    const renderChart = (count: number) => (
        <PriceChart
            bars={bars.slice(0, count)}
            contextKey={instance.context.key}
            incarnationKey={evidence.incarnationKey}
            studies={[instance]}
            studyEvidence={[{ ...evidence, points: evidence.points.slice(0, count) }]}
        />
    );
    const view = render(renderChart(79));
    const curves = renderer.series.slice(2);
    const writes = curves.map((curve) => curve.setData.mock.calls.length);
    view.rerender(renderChart(80));
    expect(renderer.series.slice(2)).toEqual(curves);
    expect(curves.map((curve) => curve.setData.mock.calls.length)).toEqual(writes);
    expect(curves.some((curve) => curve.update.mock.calls.length > 0)).toBe(true);
});

it("keeps readable candle spacing when progressive history fills a partial first window", () => {
    const { bars, instance } = studySeriesFixture();
    const renderChart = (rows: typeof bars) => (
        <PriceChart
            bars={rows}
            barSemantic={instance.context.barSemantic}
            contextKey={instance.context.key}
        />
    );
    const view = render(renderChart(bars.slice(-2)));
    const initial = { ...renderer.range.value };
    expect(initial.to - initial.from).toBeGreaterThanOrEqual(30);
    view.rerender(renderChart(bars));
    expect(renderer.range.value.to - renderer.range.value.from).toBe(initial.to - initial.from);
    expect(renderer.range.value.to).toBe(bars.length + 4);
});

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
        chartElement: vi.fn(() => document.createElement("div")),
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
    vi.stubGlobal(
        "ResizeObserver",
        class {
            observe() {
                /* Canvas geometry is provided by the renderer test. */
            }
            disconnect() {
                /* No native observation in jsdom. */
            }
            unobserve() {
                /* Canvas geometry is provided by the renderer test. */
            }
        }
    );
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
    moveCrosshair(bars[0]?.time);
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
    expect(screen.getByText(/UTC ns/)).toBeVisible();
    expect(screen.getByTestId("study-hover")).toHaveTextContent(
        "PRE_READY · controlled missing value"
    );
    act(() => {
        callback?.({ point: { x: 1, y: 2 }, time: (bars[40]?.time ?? 0) + 1 });
    });
    expect(screen.queryByTestId("study-hover")).not.toBeInTheDocument();
    expect(onSelection).toHaveBeenLastCalledWith(null);
    const missing = bars[41];
    if (!missing) throw new Error("Missing controlled bar");
    view.rerender(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            studies={[instance]}
            incarnationKey={evidence.incarnationKey}
            studyEvidence={[
                {
                    ...evidence,
                    points: evidence.points.filter((point) => point.timeNs !== missing.barStartNs)
                }
            ]}
        />
    );
    act(() => {
        callback?.({ point: { x: 1, y: 2 }, time: missing.time });
    });
    expect(screen.getByTestId("study-hover")).toHaveTextContent("此时间无对应结果");
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
    expect(screen.queryByTestId("study-hover")).not.toBeInTheDocument();
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
    moveCrosshair(bars[0]?.time);
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
    moveCrosshair(bars[0]?.time);
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
    expect(
        screen
            .getByRole("tooltip", { name: "K 线信息" })
            .querySelector("[data-observation-field=volume]")
    ).toHaveTextContent("2.1234567890123456789");
    act(() => {
        const callback = renderer.chart.subscribeCrosshairMove.mock.calls[0]?.[0] as (
            event: unknown
        ) => void;
        callback({ point: { x: 1, y: 1 }, time: first.time + 2700 });
    });
    expect(
        screen
            .getByRole("tooltip", { name: "K 线信息" })
            .querySelector("[data-observation-field=volume]")
    ).toHaveTextContent("4.000000000000000001");
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
    expect(
        screen
            .getByRole("tooltip", { name: "K 线信息" })
            .querySelector("[data-observation-field=volume]")
    ).toHaveTextContent("5.000000000000000001");
    expect(renderer.series[1]?.update.mock.calls.at(-1)?.[0]).toEqual({
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
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true");
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
                    url.includes("/api/v2/chart/market-data/bars?")
                        ? temporaryWindowVector(history)
                        : url.endsWith("capabilities")
                          ? { schema_version: 2, capabilities: [sample.capability] }
                          : temporaryBatchVector([
                                temporaryEvaluationVector(
                                    ChartStudyEvaluateSchema.parse(sample.evaluation)
                                )
                            ])
                ),
                { headers: { "cache-control": "no-store" } }
            )
        )
    );
    vi.stubGlobal("fetch", transport);
    const statusTarget = document.createElement("div");
    document.body.append(statusTarget);
    function Query() {
        return (
            <TransientStudyPriceChart
                statusTarget={statusTarget}
                pageId="00000000-0000-4000-8000-000000000001"
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
        // Query admission precedes the child renderer's passive series sync.
        expect(screen.getByTestId("price-chart")).toHaveAttribute("data-study-series-count", "1");
    });
    expect(statusTarget).toContainElement(screen.getByTestId("chart-study-query-status"));
    expect(
        screen.getByTestId("price-chart").closest(".transient-study-chart")
    ).not.toContainElement(screen.getByTestId("chart-study-query-status"));
    const reads = queryBars.mock.calls.length,
        requests = transport.mock.calls.length;
    const series = renderer.series.map((line) => line.setData.mock.calls.length);
    const range = { ...renderer.range.value };
    const storage = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new Error("denied");
    });
    for (const zone of displayTimezones.map(([zone]) => zone)) {
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
    vi.unstubAllEnvs();
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
    moveCrosshair(bars[0]?.time);
    expect(screen.getAllByTestId("study-hover")[0]).toHaveTextContent("重复身份");
});

it("places a lower-pane candle note near the actual pointer and clamps to the canvas", () => {
    const { bars } = studySeriesFixture();
    const first = bars[0];
    if (!first) throw new Error("Missing bar");
    render(<PriceChart bars={bars} contextKey="pane-position" />);
    const canvas = screen.getByTestId("price-chart");
    Object.defineProperties(canvas, { clientWidth: { value: 600 }, clientHeight: { value: 600 } });
    const move = renderer.chart.subscribeCrosshairMove.mock.calls[0]?.[0] as (
        event: object
    ) => void;
    act(() => {
        move({
            time: first.time,
            point: { x: 10, y: 10 },
            paneIndex: 1,
            sourceEvent: { clientX: 100, clientY: 420 }
        });
    });
    expect(screen.getByRole("tooltip").style.top).toBe("436px");
    expect(screen.getByRole("tooltip").style.left).toBe("116px");
    act(() => {
        move({
            time: first.time,
            point: { x: 10, y: 10 },
            paneIndex: 1,
            sourceEvent: { clientX: 999, clientY: 999 }
        });
    });
    expect(screen.getByRole("tooltip").style.top).toBe("596px");
});

it("shows study values only inside the hovered candle note with the curve's exact color", () => {
    const { bars, instance, evidence } = studySeriesFixture();
    const first = bars[0];
    if (!first) throw new Error("Missing bar");
    const colored = {
        ...instance,
        presentation: { ...instance.presentation, color: "#c8332a", opacity: 0.5 }
    };
    const view = render(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            incarnationKey={evidence.incarnationKey}
            studies={[colored]}
            studyEvidence={[evidence]}
        />
    );
    expect(screen.queryByTestId("study-hover")).not.toBeInTheDocument();
    const move = renderer.chart.subscribeCrosshairMove.mock.calls[0]?.[0] as (
        event: object
    ) => void;
    act(() => {
        move({ point: { x: 10, y: 10 }, time: first.time });
    });
    const note = screen.getByRole("tooltip", { name: "K 线信息" });
    const value = within(note).getByTestId("study-hover");
    expect(value).toHaveTextContent("102.000000000000000001");
    expect(value).toHaveStyle({ color: "#c8332a80" });
    expect(renderer.series[2]?.applyOptions).toHaveBeenLastCalledWith(
        expect.objectContaining({ color: "#c8332a80" })
    );
    const writes = renderer.series[2]?.setData.mock.calls.length;
    view.rerender(
        <PriceChart
            bars={bars}
            contextKey={instance.context.key}
            incarnationKey={evidence.incarnationKey}
            studies={[
                {
                    ...colored,
                    presentation: {
                        ...colored.presentation,
                        seriesStyles: { value: { color: "#123abc", visible: true } }
                    }
                }
            ]}
            studyEvidence={[evidence]}
        />
    );
    expect(within(screen.getByRole("tooltip")).getByTestId("study-hover")).toHaveStyle({
        color: "#123abc80"
    });
    expect(renderer.series[2]?.applyOptions).toHaveBeenLastCalledWith(
        expect.objectContaining({ color: "#123abc80" })
    );
    expect(renderer.series[2]?.setData.mock.calls.length).toBe(writes);
    fireEvent.mouseLeave(screen.getByTestId("price-chart"));
    expect(screen.queryByTestId("study-hover")).not.toBeInTheDocument();
});

function moveCrosshair(time: number | undefined) {
    act(() => {
        const move = renderer.chart.subscribeCrosshairMove.mock.calls[0]?.[0] as (
            event: object
        ) => void;
        move({ point: { x: 1, y: 1 }, time });
    });
}

it("follows the actual axis corner through resize and releases its observer", () => {
    const element = document.createElement("div");
    element.innerHTML = "<table><tbody><tr><td></td></tr></tbody></table>";
    const corner = element.querySelector("td");
    if (!corner) throw new Error("Axis corner required");
    const rect = vi
        .spyOn(corner, "getBoundingClientRect")
        .mockReturnValue(new DOMRect(900, 600, 72, 28));
    renderer.chart.chartElement.mockReturnValueOnce(element);
    let resize: () => void = vi.fn();
    const observe = vi.fn(),
        disconnect = vi.fn();
    vi.stubGlobal(
        "ResizeObserver",
        class {
            constructor(callback: () => void) {
                resize = callback;
            }
            observe = observe;
            disconnect = disconnect;
        }
    );
    const { bars } = studySeriesFixture();
    const view = render(<PriceChart bars={bars} />);
    const controls = screen.getByRole("combobox", { name: "显示时区" }).parentElement;
    expect(controls).toHaveStyle({ left: "900px", top: "600px", width: "72px", height: "28px" });
    expect(observe).toHaveBeenCalledWith(corner);
    rect.mockReturnValue(new DOMRect(320.25, 720.5, 80, 28));
    act(() => {
        resize();
    });
    expect(controls).toHaveStyle({
        left: "320.25px",
        top: "720.5px",
        width: "80px",
        height: "28px"
    });
    view.unmount();
    expect(disconnect).toHaveBeenCalledOnce();
});
