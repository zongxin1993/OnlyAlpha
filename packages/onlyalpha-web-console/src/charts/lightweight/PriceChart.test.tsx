import { act, cleanup, render, screen } from "@testing-library/react";
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
        bars.map((bar) => ({ time: bar.time, value: bar.numeric.volume }))
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
    expect(volume?.update).toHaveBeenLastCalledWith({ time: last.time, value: 4 });
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
