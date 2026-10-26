import { render, screen } from "@testing-library/react";
import type { BarPrice, PriceFormat, SeriesPartialOptionsMap } from "lightweight-charts";
import { parseDecimalText } from "../../../domain/research/decimal";
import { parseUnixNanoseconds } from "../../../domain/research/time";
import type { FinancialLinePoint, FinancialSignalMarker } from "../../model/financial";
import { projectMarketEvidence } from "../../projection/financialProjection";
import { FinancialEvidenceChart } from "./FinancialEvidenceChart";

type TestSeriesOptions = (
    | Omit<SeriesPartialOptionsMap["Candlestick"], "priceFormat">
    | Omit<SeriesPartialOptionsMap["Histogram"], "priceFormat">
    | Omit<SeriesPartialOptionsMap["Line"], "priceFormat">
) & { readonly priceFormat?: Partial<PriceFormat> };

const chartMocks = vi.hoisted(() => {
    function series() {
        const applyOptions = vi.fn();
        return {
            setData: vi.fn<(points: readonly unknown[]) => void>(),
            priceScale: () => ({ applyOptions }),
            applyOptions
        };
    }
    const candle = series();
    const volume = series();
    const line = series();
    const addSeries = vi.fn<
        (
            definition: string,
            options?: TestSeriesOptions,
            paneIndex?: number
        ) => ReturnType<typeof series>
    >((definition) => {
        if (definition === "Candlestick") return candle;
        if (definition === "Histogram") return volume;
        return line;
    });
    const fitContent = vi.fn();
    const remove = vi.fn();
    const chart = { addSeries, timeScale: () => ({ fitContent }), remove };
    return {
        candle,
        volume,
        line,
        addSeries,
        fitContent,
        remove,
        createChart: vi.fn<(element: HTMLElement, options: unknown) => typeof chart>(() => chart),
        createSeriesMarkers: vi.fn<(target: unknown, markers: readonly unknown[]) => void>()
    };
});

vi.mock("lightweight-charts", () => ({
    CandlestickSeries: "Candlestick",
    HistogramSeries: "Histogram",
    LineSeries: "Line",
    ColorType: { Solid: "solid" },
    createChart: chartMocks.createChart,
    createSeriesMarkers: chartMocks.createSeriesMarkers
}));

beforeEach(() => {
    vi.clearAllMocks();
});

function financialFixture() {
    const projected = projectMarketEvidence(
        ["1000000000", "2000000000", "3000000000"].map((timestamp) => ({
            kind: "MARKET",
            instrumentId: "EXAMPLE.XTEST",
            tsEventNs: parseUnixNanoseconds(timestamp),
            open: parseDecimalText("100"),
            high: parseDecimalText("120"),
            low: parseDecimalText("90"),
            close: parseDecimalText("110"),
            volume: parseDecimalText("1000")
        }))
    );
    if (!projected.ok) throw new Error(projected.detail);
    const [first, second, third] = projected.value.candles;
    if (first === undefined || second === undefined || third === undefined)
        throw new Error("Incomplete market fixture");
    const markers: readonly FinancialSignalMarker[] = [
        {
            time: first.time,
            role: "ENTRY_SIGNAL",
            position: "belowBar",
            shape: "arrowUp"
        }
    ];
    return {
        ...projected.value,
        first: first.time,
        second: second.time,
        third: third.time,
        markers
    };
}

function factorFormatting() {
    const call = chartMocks.addSeries.mock.calls.find(([definition]) => definition === "Line");
    const format = call?.[1]?.priceFormat;
    if (format?.type !== "custom" || format.formatter === undefined)
        throw new Error("Factor formatter missing");
    return { formatter: format.formatter, minMove: format.minMove };
}

it("preserves the default overlay, main-pane OHLC and volume, marker ownership and attribution", () => {
    const fixture = financialFixture();
    const variable = [{ time: fixture.first, value: 12 }];
    render(<FinancialEvidenceChart {...fixture} variable={variable} />);
    expect(screen.getByRole("region", { name: "Financial evidence chart" })).toBeInTheDocument();
    expect(screen.getByTestId("financial-chart")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "TradingView" })).toHaveAttribute(
        "href",
        "https://www.tradingview.com/"
    );
    expect(chartMocks.addSeries.mock.calls.map(([kind, , pane]) => [kind, pane])).toEqual([
        ["Candlestick", undefined],
        ["Histogram", undefined],
        ["Line", undefined]
    ]);
    expect(chartMocks.addSeries.mock.calls[2]).toEqual([
        "Line",
        { color: "#67e8f9", lineWidth: 2 }
    ]);
    expect(chartMocks.candle.setData).toHaveBeenCalledWith(fixture.candles);
    expect(chartMocks.volume.setData).toHaveBeenCalledWith([
        { time: 1, value: 1000, color: "#34d39980" },
        { time: 2, value: 1000, color: "#34d39980" },
        { time: 3, value: 1000, color: "#34d39980" }
    ]);
    expect(chartMocks.line.setData).toHaveBeenCalledWith(variable);
    expect(chartMocks.volume.applyOptions).toHaveBeenCalledWith({
        scaleMargins: { top: 0.82, bottom: 0 }
    });
    expect(chartMocks.createSeriesMarkers).toHaveBeenCalledWith(chartMocks.candle, [
        {
            time: 1,
            position: "belowBar",
            shape: "arrowUp",
            color: "#34d399",
            text: "ENTRY_SIGNAL"
        }
    ]);
    expect(chartMocks.fitContent).toHaveBeenCalledTimes(1);
});

it("does not add a default Variable series when no evidence was supplied", () => {
    render(<FinancialEvidenceChart {...financialFixture()} variable={[]} />);
    expect(chartMocks.addSeries).toHaveBeenCalledTimes(2);
    expect(chartMocks.line.setData).not.toHaveBeenCalled();
    expect(screen.queryByRole("figure")).not.toBeInTheDocument();
});

it("bounds the auto-size viewport independently of the renderer's internal table height", () => {
    render(<FinancialEvidenceChart {...financialFixture()} variable={[]} variablePane />);
    const viewport = screen.getByTestId("financial-chart");
    expect(viewport).toHaveStyle({ height: "480px" });
    expect(viewport).toHaveClass("onlyalpha-financial-chart");
    expect(chartMocks.createChart.mock.calls[0]?.[0]).toBe(viewport);
    expect(chartMocks.createChart.mock.calls[0]?.[1]).toMatchObject({
        autoSize: true,
        height: 480
    });
});

it("places Factor values in pane one on an independent value scale with a shared time axis", () => {
    const fixture = financialFixture();
    const variable: readonly FinancialLinePoint[] = [
        { time: fixture.first, value: -1e-18 },
        { time: fixture.second },
        { time: fixture.third, value: 0 }
    ];
    render(
        <FinancialEvidenceChart
            {...fixture}
            variable={variable}
            variablePane
            variableLabel="Momentum score"
        />
    );
    expect(
        screen.getByRole("figure", {
            name: "Financial evidence chart with independent Factor pane"
        })
    ).toBeInTheDocument();
    expect(screen.getByText(/Momentum score · Independent Factor pane/)).toBeInTheDocument();
    expect(screen.getByText(/not a correlation result/)).toBeInTheDocument();
    expect(chartMocks.createChart).toHaveBeenCalledTimes(1);
    expect(chartMocks.addSeries.mock.calls.map(([kind, , pane]) => [kind, pane])).toEqual([
        ["Candlestick", undefined],
        ["Histogram", undefined],
        ["Line", 1]
    ]);
    expect(chartMocks.addSeries.mock.calls[2]?.[1]).toMatchObject({
        priceScaleId: "right",
        title: "Momentum score",
        priceFormat: { type: "custom" }
    });
    expect(chartMocks.line.setData).toHaveBeenCalledWith([
        { time: 1, value: -1e-18 },
        { time: 2 },
        { time: 3, value: 0 }
    ]);
    expect(chartMocks.candle.setData).toHaveBeenCalledWith(fixture.candles);
    const { formatter, minMove } = factorFormatting();
    expect(formatter(-1e-18 as BarPrice)).toBe("-1.00000e-18");
    expect(formatter(1e-18 as BarPrice)).toBe("1.00000e-18");
    expect(formatter(-0.000045 as BarPrice)).toBe("-0.0000450000");
    expect(formatter(0 as BarPrice)).toBe("0.00000");
    expect(minMove).toBeLessThan(1e-18);
    expect(chartMocks.fitContent).toHaveBeenCalledTimes(1);
});

it("keeps an explicitly requested empty Factor pane empty without making a zero series", () => {
    render(<FinancialEvidenceChart {...financialFixture()} variable={[]} variablePane />);
    expect(chartMocks.addSeries.mock.calls[2]?.[2]).toBe(1);
    expect(chartMocks.addSeries.mock.calls[2]?.[1]).toMatchObject({ title: "Factor" });
    expect(chartMocks.line.setData).toHaveBeenCalledWith([]);
    const { formatter } = factorFormatting();
    expect(formatter(NaN as BarPrice)).toBe("—");
    expect(formatter(Infinity as BarPrice)).toBe("—");
});

it("retains very small admitted nonzero values in scientific notation rather than a zero label", () => {
    const fixture = financialFixture();
    render(
        <FinancialEvidenceChart
            {...fixture}
            variable={[{ time: fixture.first, value: Number.MIN_VALUE }]}
            variablePane
        />
    );
    const { formatter, minMove } = factorFormatting();
    expect(formatter(Number.MIN_VALUE as BarPrice)).not.toMatch(/^0(?:\.0+)?$/);
    expect(formatter(Number.MIN_VALUE as BarPrice)).toContain("e-");
    expect(minMove).toBe(1e-300);
    expect(chartMocks.line.setData).toHaveBeenCalledWith([{ time: 1, value: Number.MIN_VALUE }]);
});

it("disposes the previous renderer when the selected series identity changes and cleans up on unmount", () => {
    const fixture = financialFixture();
    const initial = [{ time: fixture.first, value: 0.1 }];
    const { rerender, unmount } = render(
        <FinancialEvidenceChart
            {...fixture}
            variable={initial}
            variablePane
            variableLabel="Factor A"
        />
    );
    rerender(
        <FinancialEvidenceChart
            {...fixture}
            variable={[{ time: fixture.first, value: -0.2 }]}
            variablePane
            variableLabel="Factor B"
        />
    );
    expect(chartMocks.createChart).toHaveBeenCalledTimes(2);
    expect(chartMocks.remove).toHaveBeenCalledTimes(1);
    expect(chartMocks.line.setData).toHaveBeenLastCalledWith([{ time: 1, value: -0.2 }]);
    expect(chartMocks.addSeries.mock.calls[5]?.[1]).toMatchObject({ title: "Factor B" });
    const removedAt = chartMocks.remove.mock.invocationCallOrder[0];
    const recreatedAt = chartMocks.createChart.mock.invocationCallOrder[1];
    if (removedAt === undefined || recreatedAt === undefined)
        throw new Error("Renderer lifecycle not recorded");
    expect(removedAt).toBeLessThan(recreatedAt);
    unmount();
    expect(chartMocks.remove).toHaveBeenCalledTimes(2);
});

it("rebuilds a changed Factor label and can return to the original overlay without retaining its pane", () => {
    const fixture = financialFixture();
    const variable = [{ time: fixture.first, value: 0.1 }];
    const { rerender } = render(
        <FinancialEvidenceChart
            {...fixture}
            variable={variable}
            variablePane
            variableLabel="Factor A"
        />
    );
    rerender(
        <FinancialEvidenceChart
            {...fixture}
            variable={variable}
            variablePane
            variableLabel="Factor B"
        />
    );
    expect(chartMocks.createChart).toHaveBeenCalledTimes(2);
    expect(chartMocks.addSeries.mock.calls[5]?.[1]).toMatchObject({ title: "Factor B" });
    rerender(<FinancialEvidenceChart {...fixture} variable={variable} variablePane={false} />);
    expect(chartMocks.remove).toHaveBeenCalledTimes(2);
    expect(chartMocks.addSeries.mock.calls[8]).toEqual([
        "Line",
        { color: "#67e8f9", lineWidth: 2 }
    ]);
    expect(screen.getByRole("region", { name: "Financial evidence chart" })).toBeInTheDocument();
    expect(screen.queryByRole("figure")).not.toBeInTheDocument();
});
