import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import type { ResearchApiClient } from "../../../api/research/client";
import { AppProviders } from "../../../app/providers";
import { parseDecimalText } from "../../../domain/research/decimal";
import {
    parseResearchResultFingerprint,
    parseSha256Fingerprint
} from "../../../domain/research/identity";
import type {
    ResearchMarketPoint,
    ResearchScientificSeriesPage,
    ResearchVariablePoint
} from "../../../domain/research/model";
import { parseUnixNanoseconds } from "../../../domain/research/time";
import { researchClient } from "../../../test/researchClient";
import type { FinancialEvidenceChart } from "../../../visualization/financial/lightweight/FinancialEvidenceChart";
import { publishedSeriesKey } from "../results/model/selectors";
import { FactorInstrumentCard } from "./FactorInstrumentCard";
import type { FactorSeriesOption } from "./factorModel";

vi.mock("../../../visualization/financial/lightweight/FinancialEvidenceChart", () => ({
    FinancialEvidenceChart: (props: ComponentProps<typeof FinancialEvidenceChart>) => (
        <div
            data-testid="factor-financial-chart"
            data-candles={JSON.stringify(props.candles)}
            data-volume={JSON.stringify(props.volume)}
            data-variable={JSON.stringify(props.variable)}
            data-markers={JSON.stringify(props.markers)}
            data-variable-pane={String(props.variablePane)}
            data-variable-label={props.variableLabel}
        />
    )
}));

const result = parseResearchResultFingerprint("a".repeat(64));
const otherResult = parseResearchResultFingerprint("b".repeat(64));
const instrument = "AAA.XNAS";
const ns = parseUnixNanoseconds;
const decimal = parseDecimalText;
const series: FactorSeriesOption["series"] = {
    candidateFingerprint: parseSha256Fingerprint("c".repeat(64)),
    calculationFingerprint: parseSha256Fingerprint("d".repeat(64)),
    nodeFingerprint: parseSha256Fingerprint("e".repeat(64)),
    outputName: "score",
    valueKind: "DECIMAL"
};
const option: FactorSeriesOption = {
    key: publishedSeriesKey(series),
    series,
    label: "Momentum · example.momentum@1.0.0 · score",
    node: {
        nodeFingerprint: series.nodeFingerprint,
        alias: "Momentum",
        definition: {
            schemaVersion: 2,
            kind: "FACTOR",
            typeId: "example.momentum",
            semanticVersion: "1.0.0",
            parameters: {},
            inputs: [],
            inputBindings: {},
            outputs: [
                {
                    name: "score",
                    dataType: "DECIMAL",
                    semanticType: "FACTOR_SCORE",
                    nullable: true,
                    dimensions: ["TIME", "INSTRUMENT"],
                    unit: null
                }
            ],
            warmup: {
                minimumObservations: 1,
                readyCondition: "READY",
                preReadyOutput: "NULL",
                initialization: "FIRST_OBSERVATION"
            },
            missingValues: "PROPAGATE",
            timestamp: "OBSERVATION_TIME",
            numeric: {
                representation: "DECIMAL",
                precision: 28,
                outputQuantum: decimal("0.0001"),
                rounding: "ROUND_HALF_EVEN"
            },
            factorKind: "TIME_SERIES",
            extensions: {}
        }
    }
};

function marketPoint(time = "1000000000"): ResearchMarketPoint {
    return {
        kind: "MARKET",
        instrumentId: instrument,
        tsEventNs: ns(time),
        open: decimal("10.000"),
        high: decimal("12.000"),
        low: decimal("9.000"),
        close: decimal("11.000"),
        volume: decimal("123.000")
    };
}

function factorPoint(
    time = "1000000000",
    value: string | null = "0.012300"
): ResearchVariablePoint {
    return {
        kind: "VARIABLE",
        instrumentId: instrument,
        tsEventNs: ns(time),
        valueKind: "DECIMAL",
        decimalValue: value === null ? null : decimal(value),
        integerValue: null,
        booleanValue: null,
        stringValue: null
    };
}

function page(
    points: ResearchScientificSeriesPage["points"],
    hasMore = false
): ResearchScientificSeriesPage {
    return {
        researchResultFingerprint: result,
        points,
        hasMore,
        nextAfterTsEventNs: hasMore ? (points.at(-1)?.tsEventNs ?? null) : null
    };
}

type TestApi = {
    [Key in keyof ResearchApiClient]: (
        ...args: Parameters<ResearchApiClient[Key]>
    ) => ReturnType<ResearchApiClient[Key]>;
};

function client(
    market = page([marketPoint()]),
    factor = page([factorPoint()]),
    overrides: Partial<ResearchApiClient> = {}
): TestApi {
    const api = researchClient({
        getMarketSeries: () => Promise.resolve(market),
        getVariableSeries: () => Promise.resolve(factor),
        ...overrides
    });
    for (const method of Object.keys(api) as (keyof ResearchApiClient)[]) vi.spyOn(api, method);
    return api;
}

function renderCard(
    api = client(),
    props: Partial<ComponentProps<typeof FactorInstrumentCard>> = {}
) {
    return render(
        <AppProviders client={api}>
            <FactorInstrumentCard
                result={result}
                option={option}
                instrumentId={instrument}
                range={{}}
                {...props}
            />
        </AppProviders>
    );
}

async function openExactTables() {
    await userEvent.click(screen.getByText(/^Exact Market data/));
    await userEvent.click(screen.getByText(/^Exact Factor data/));
}

function deferredPage() {
    let complete: ((value: ResearchScientificSeriesPage) => void) | undefined;
    const promise = new Promise<ResearchScientificSeriesPage>((resolve) => {
        complete = resolve;
    });
    return {
        promise,
        resolve: (value: ResearchScientificSeriesPage) => {
            if (complete === undefined) throw new Error("Deferred page was not initialized");
            complete(value);
        }
    };
}

it("plots separate exact timestamp series without ordinal joining or filling missing dates", async () => {
    const api = client(
        page([marketPoint("1000000000"), marketPoint("3000000000")]),
        page([factorPoint("2000000000"), factorPoint("3000000000", null)])
    );
    const range = { from: ns("1000000000"), to: ns("4000000000") };
    renderCard(api, { range });
    const chart = await screen.findByTestId("factor-financial-chart");
    expect(chart).toHaveAttribute(
        "data-candles",
        JSON.stringify([
            { time: 1, open: 10, high: 12, low: 9, close: 11 },
            { time: 3, open: 10, high: 12, low: 9, close: 11 }
        ])
    );
    expect(chart).toHaveAttribute(
        "data-variable",
        JSON.stringify([{ time: 2, value: 0.0123 }, { time: 3 }])
    );
    expect(chart).toHaveAttribute("data-variable-pane", "true");
    expect(chart).toHaveAttribute("data-variable-label", option.label);
    expect(chart).toHaveAttribute("data-markers", "[]");
    expect(screen.getByText(/not a time-series correlation coefficient/)).toBeInTheDocument();
    await openExactTables();
    const market = screen.getByRole("table", { name: `${instrument} exact Market evidence` });
    const factor = screen.getByRole("table", { name: `${instrument} exact Factor evidence` });
    expect(within(market).getByText("1000000000")).toBeInTheDocument();
    expect(within(market).queryByText("2000000000")).not.toBeInTheDocument();
    expect(within(factor).queryByText("1000000000")).not.toBeInTheDocument();
    expect(within(factor).getByText("2000000000")).toBeInTheDocument();
    expect(within(factor).getByText("0.012300")).toBeInTheDocument();
    expect(within(factor).getByText("NULL")).toBeInTheDocument();
    expect(api.getMarketSeries).toHaveBeenCalledWith(
        result,
        instrument,
        {
            limit: 500,
            fromTsEventNs: range.from,
            toTsEventNs: range.to
        },
        expect.any(AbortSignal)
    );
    expect(api.getVariableSeries).toHaveBeenCalledWith(
        {
            researchResultFingerprint: result,
            instrumentId: instrument,
            candidateFingerprint: series.candidateFingerprint,
            calculationFingerprint: series.calculationFingerprint,
            nodeFingerprint: series.nodeFingerprint,
            outputName: series.outputName,
            limit: 500,
            fromTsEventNs: range.from,
            toTsEventNs: range.to
        },
        expect.any(AbortSignal)
    );
    for (const method of Object.keys(api) as (keyof ResearchApiClient)[])
        if (method !== "getMarketSeries" && method !== "getVariableSeries")
            expect(api[method]).not.toHaveBeenCalled();
});

it("preserves large integer text and NULL Factor rows without converting NULL to zero", async () => {
    const integerOption: FactorSeriesOption = {
        ...option,
        series: { ...series, valueKind: "INTEGER" },
        node: {
            ...option.node,
            definition: {
                ...option.node.definition,
                outputs: option.node.definition.outputs.map((output) => ({
                    ...output,
                    dataType: "INTEGER"
                }))
            }
        }
    };
    const integer = {
        ...factorPoint(),
        valueKind: "INTEGER" as const,
        decimalValue: null,
        integerValue: "9007199254740993"
    };
    renderCard(
        client(
            page([marketPoint()]),
            page([integer, { ...integer, tsEventNs: ns("2000000000"), integerValue: null }])
        ),
        { option: integerOption }
    );
    const chart = await screen.findByTestId("factor-financial-chart");
    expect(chart).toHaveAttribute(
        "data-variable",
        JSON.stringify([{ time: 1, value: 9007199254740992 }, { time: 2 }])
    );
    await openExactTables();
    const exact = screen.getByRole("table", { name: `${instrument} exact Factor evidence` });
    expect(within(exact).getByText("9007199254740993")).toBeInTheDocument();
    expect(within(exact).getByText("NULL")).toBeInTheDocument();
});

it.each(["Market", "Factor"] as const)("rejects %s pages bound to another Result", async (kind) => {
    const market = page([marketPoint()]);
    const factor = page([factorPoint()]);
    renderCard(
        client(
            kind === "Market" ? { ...market, researchResultFingerprint: otherResult } : market,
            kind === "Factor" ? { ...factor, researchResultFingerprint: otherResult } : factor
        )
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("CONTRACT_ERROR");
    expect(screen.queryByTestId("factor-financial-chart")).not.toBeInTheDocument();
    expect(screen.queryByText("0.012300")).not.toBeInTheDocument();
    expect(screen.queryByText(/^Exact Market data/)).not.toBeInTheDocument();
});

it.each(["Market", "Factor"] as const)(
    "rejects a foreign instrument inside %s pages",
    async (kind) => {
        const foreignMarket = { ...marketPoint("2000000000"), instrumentId: "BBB.XNAS" };
        const foreignFactor = { ...factorPoint("2000000000"), instrumentId: "BBB.XNAS" };
        renderCard(
            client(
                page(kind === "Market" ? [marketPoint(), foreignMarket] : [marketPoint()]),
                page(kind === "Factor" ? [factorPoint(), foreignFactor] : [factorPoint()])
            )
        );
        expect(await screen.findByRole("alert")).toHaveTextContent("CONTRACT_ERROR");
        expect(screen.queryByTestId("factor-financial-chart")).not.toBeInTheDocument();
        expect(screen.queryByText("0.012300")).not.toBeInTheDocument();
    }
);

it.each(["Market", "Factor"] as const)(
    "rejects an unexpected %s evidence kind without filtering it away",
    async (kind) => {
        renderCard(
            client(
                page(kind === "Market" ? [factorPoint()] : [marketPoint()]),
                page(kind === "Factor" ? [marketPoint()] : [factorPoint()])
            )
        );
        expect(await screen.findByRole("alert")).toHaveTextContent("CONTRACT_ERROR");
        expect(screen.queryByTestId("factor-financial-chart")).not.toBeInTheDocument();
    }
);

it("rejects Factor values with a different Published Series value kind", async () => {
    renderCard(
        client(
            page([marketPoint()]),
            page([
                { ...factorPoint(), valueKind: "INTEGER", decimalValue: null, integerValue: "7" }
            ])
        )
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("CONTRACT_ERROR");
    expect(screen.queryByTestId("factor-financial-chart")).not.toBeInTheDocument();
});

it.each([
    ["Market", "0"],
    ["Market", "2000000000"],
    ["Factor", "0"],
    ["Factor", "2000000000"]
])("rejects %s rows outside the requested [from,to) at %s", async (kind, time) => {
    renderCard(
        client(
            page([marketPoint(kind === "Market" ? time : "1000000000")]),
            page([factorPoint(kind === "Factor" ? time : "1000000000")])
        ),
        { range: { from: ns("1000000000"), to: ns("2000000000") } }
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("CONTRACT_ERROR");
    expect(screen.queryByTestId("factor-financial-chart")).not.toBeInTheDocument();
});

it("rejects cursor mismatch and does not show partly admitted facts", async () => {
    renderCard(client({ ...page([marketPoint()], true), nextAfterTsEventNs: ns("9000000000") }));
    expect(await screen.findByRole("alert")).toHaveTextContent("CONTRACT_ERROR");
    expect(screen.queryByText("1000000000")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Load next/ })).not.toBeInTheDocument();
});

it("rejects an empty page claiming an unavailable next cursor", async () => {
    renderCard(client(page([], true)));
    expect(await screen.findByRole("alert")).toHaveTextContent("CONTRACT_ERROR");
    expect(screen.queryByTestId("factor-financial-chart")).not.toBeInTheDocument();
});

it("suppresses cross-series nanosecond collisions but keeps both exact tables visible", async () => {
    renderCard(client(page([marketPoint("1000000001")]), page([factorPoint("1000000002")])));
    expect(await screen.findByText(/FINANCIAL_PROJECTION_ERROR/)).toHaveTextContent(
        "Market and Factor"
    );
    expect(screen.queryByTestId("factor-financial-chart")).not.toBeInTheDocument();
    const market = screen.getByRole("table", { name: `${instrument} exact Market evidence` });
    const factor = screen.getByRole("table", { name: `${instrument} exact Factor evidence` });
    expect(within(market).getByText("1000000001")).toBeVisible();
    expect(within(factor).getByText("1000000002")).toBeVisible();
    expect(within(factor).getByText("0.012300")).toBeVisible();
});

it("preserves exact rows on within-series timestamp projection failure", async () => {
    renderCard(
        client(
            page([marketPoint()]),
            page([factorPoint("1000000000"), factorPoint("1000000001", null)])
        )
    );
    expect(await screen.findByText(/FINANCIAL_PROJECTION_ERROR/)).toBeInTheDocument();
    expect(screen.queryByTestId("factor-financial-chart")).not.toBeInTheDocument();
    const exact = screen.getByRole("table", { name: `${instrument} exact Factor evidence` });
    expect(within(exact).getByText("1000000001")).toBeVisible();
    expect(within(exact).getByText("NULL")).toBeVisible();
});

it("preserves exact Decimal evidence when a finite chart coordinate cannot represent it", async () => {
    const enormous = "9".repeat(310);
    renderCard(client(page([marketPoint()]), page([factorPoint("1000000000", enormous)])));
    expect(await screen.findByText(/FINANCIAL_PROJECTION_ERROR/)).toHaveTextContent(
        "finite renderer"
    );
    expect(screen.queryByTestId("factor-financial-chart")).not.toBeInTheDocument();
    expect(screen.getByText(enormous)).toBeVisible();
});

it("does not manufacture a chart when both evidence series are empty", async () => {
    renderCard(client(page([]), page([])));
    expect(
        await screen.findByText("No Factor rows exist in this exact selection.")
    ).toBeInTheDocument();
    expect(screen.queryByTestId("factor-financial-chart")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Load next/ })).not.toBeInTheDocument();
});

it("loads only explicitly requested next pages and disables the button while either request is pending", async () => {
    const next = deferredPage();
    const first = page([marketPoint()], true);
    const api = client(first, page([factorPoint()]), {
        getMarketSeries: (_result, _instrument, request) =>
            request?.afterTsEventNs === undefined ? Promise.resolve(first) : next.promise
    });
    renderCard(api);
    await screen.findByTestId("factor-financial-chart");
    expect(api.getMarketSeries).toHaveBeenCalledTimes(1);
    expect(api.getVariableSeries).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/bounded partial view/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load next bounded evidence pages" }));
    expect(screen.getByRole("button", { name: "Loading exact pages…" })).toBeDisabled();
    expect(api.getMarketSeries).toHaveBeenCalledTimes(2);
    expect(api.getMarketSeries).toHaveBeenLastCalledWith(
        result,
        instrument,
        { limit: 500, afterTsEventNs: ns("1000000000") },
        expect.any(AbortSignal)
    );
    expect(api.getVariableSeries).toHaveBeenCalledTimes(1);
    act(() => {
        next.resolve(page([marketPoint("2000000000")]));
    });
    await waitFor(() => {
        expect(
            screen.queryByRole("button", { name: /Loading exact pages/ })
        ).not.toBeInTheDocument();
    });
    expect(screen.getByText(/2 Market rows · 1 Factor rows loaded/)).toBeInTheDocument();
    expect(api.getMarketSeries).toHaveBeenCalledTimes(2);
});

it("rejects repeated timestamps on a subsequently loaded page", async () => {
    const first = page([marketPoint()], true);
    const api = client(first, page([factorPoint()]), {
        getMarketSeries: (_result, _instrument, request) =>
            Promise.resolve(request?.afterTsEventNs === undefined ? first : page([marketPoint()]))
    });
    renderCard(api);
    await screen.findByTestId("factor-financial-chart");
    await userEvent.click(screen.getByRole("button", { name: "Load next bounded evidence pages" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("CONTRACT_ERROR");
    expect(screen.queryByTestId("factor-financial-chart")).not.toBeInTheDocument();
    expect(screen.queryByText("0.012300")).not.toBeInTheDocument();
});

it("passes AbortSignals through both query options and aborts pending reads on unmount", async () => {
    const market = deferredPage();
    const factor = deferredPage();
    const api = client(undefined, undefined, {
        getMarketSeries: () => market.promise,
        getVariableSeries: () => factor.promise
    });
    const view = renderCard(api);
    await waitFor(() => {
        expect(api.getMarketSeries).toHaveBeenCalledTimes(1);
        expect(api.getVariableSeries).toHaveBeenCalledTimes(1);
    });
    const marketSignal = vi.mocked(api.getMarketSeries).mock.calls[0]?.[3];
    const factorSignal = vi.mocked(api.getVariableSeries).mock.calls[0]?.[1];
    expect(marketSignal).toBeInstanceOf(AbortSignal);
    expect(factorSignal).toBeInstanceOf(AbortSignal);
    expect(marketSignal?.aborted).toBe(false);
    expect(factorSignal?.aborted).toBe(false);
    view.unmount();
    expect(marketSignal?.aborted).toBe(true);
    expect(factorSignal?.aborted).toBe(true);
});
