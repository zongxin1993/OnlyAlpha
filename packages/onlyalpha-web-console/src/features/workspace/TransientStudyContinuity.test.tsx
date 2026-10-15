import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChartStudies } from "./ChartStudies";
import { useLayoutEffect } from "react";
import { AppProviders, useLocalReadCredentials } from "../../app/providers";
import { marketDataBarSemantic, marketDataBarsSchema } from "../../api/marketData/model";
import {
    ChartStudyCapabilitiesSchema,
    ChartStudyEvaluateSchema
} from "../../api/chartStudies/http.generated";
import { MarketDataWebError, type MarketDataBarsQuery } from "../../api/marketData/client";
import type { MarketDataSourceReference } from "../../api/marketData/model";
import { marketDataClient } from "../../test/marketDataClient";
import { projectMarketDataBar } from "../../charts/lightweight/marketDataChartProjection";
import sample from "../../../../../test-data/web/chart-studies/query.json";
import { TransientStudyPriceChart } from "./TransientStudyPriceChart";
import { isAdmittedChartStudyEvidence } from "../../api/chartStudies/client";
import type { LocalReadCredentials } from "../../api/marketData/localReadCredentials";
import type { ChartStudyInstance } from "./chartStudy";

const observedEvidence: (readonly object[])[] = [];

vi.mock("../../charts/lightweight/PriceChart", () => ({
    PriceChart: ({ studyEvidence }: { studyEvidence: readonly { instanceId: string }[] }) => {
        observedEvidence.push(studyEvidence);
        return (
            <output data-testid="overlays">
                {studyEvidence
                    .filter(isAdmittedChartStudyEvidence)
                    .map((row) => row.instanceId)
                    .join(",")}
            </output>
        );
    }
}));
const modalMethods = {
    showModal: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal"),
    close: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close")
};
beforeEach(async () => {
    document.documentElement.style.setProperty("--accent-solid", "#2962FF");
    Object.defineProperties(HTMLDialogElement.prototype, {
        showModal: {
            configurable: true,
            value: function (this: HTMLDialogElement) {
                this.setAttribute("open", "");
            }
        },
        close: {
            configurable: true,
            value: function (this: HTMLDialogElement) {
                this.removeAttribute("open");
            }
        }
    });
    vi.stubGlobal(
        "crypto",
        (await vi.importActual<{ webcrypto: Crypto }>("node:crypto")).webcrypto
    );
});
afterEach(() => {
    observedEvidence.length = 0;
    vi.useRealTimers();
    vi.unstubAllGlobals();
    document.documentElement.style.removeProperty("--accent-solid");
    for (const name of ["showModal", "close"] as const) {
        const method = modalMethods[name];
        if (method === undefined) Reflect.deleteProperty(HTMLDialogElement.prototype, name);
        else Object.defineProperty(HTMLDialogElement.prototype, name, method);
    }
});

function required<T>(value: T | undefined): T {
    if (value === undefined) throw new Error("Missing required test fact");
    return value;
}

function setup(minutes = 15, instrument = "BTCUSDT.BINANCE") {
    const capability = ChartStudyCapabilitiesSchema.parse({
        schema_version: 1,
        capabilities: [sample.capability]
    }).capabilities[0];
    const admittedCapability = required(capability);
    const duration = BigInt(minutes) * 60_000_000_000n;
    const baseEnd = BigInt(sample.history.resolved_end_ns);
    const page = (anchor: string) => {
        const history = marketDataBarsSchema.parse(structuredClone(sample.history));
        const start = BigInt(anchor) - 2000n * duration;
        history.instrument_id = instrument;
        history.bar_semantic = marketDataBarSemantic(minutes);
        history.requested_before_ns = anchor;
        history.resolved_start_ns = start.toString();
        history.resolved_end_ns = anchor;
        history.bars.forEach((bar, index) => {
            bar.bar_start_ns = (start + BigInt(index) * duration).toString();
            bar.bar_end_ns = (start + BigInt(index + 1) * duration).toString();
        });
        return history;
    };
    const response = (anchor: string) => {
        const history = page(anchor);
        const value = ChartStudyEvaluateSchema.parse(structuredClone(sample.evaluation));
        value.instrument_id = instrument;
        value.bar_semantic = history.bar_semantic;
        value.input.before_ns = anchor;
        value.input.resolved_end_ns = anchor;
        value.input.resolved_start_ns = history.resolved_start_ns;
        value.series[0]?.points.forEach((point, index) => {
            point.time_ns = required(history.bars[index]).bar_start_ns;
        });
        return new Response(JSON.stringify(value), { headers: { "cache-control": "no-store" } });
    };
    const initial = page(baseEnd.toString());
    const context = {
        key: `${instrument}:${String(minutes)}`,
        source: {
            integration_id: initial.source_selection.integration_id,
            integration_revision_fingerprint:
                initial.source_selection.integration_revision_fingerprint,
            expected_type_id: initial.source_selection.type_id
        },
        instrumentId: instrument,
        barSemantic: initial.bar_semantic
    };
    const instance: ChartStudyInstance = {
        instanceId: "one",
        context,
        selection: { source: "CHART_STUDY_TRANSIENT", capability: admittedCapability },
        configuration: {
            parameters: {
                period: { type: "INTEGER", value: 20 },
                price_field: { type: "STRING", value: "CLOSE" }
            },
            outputName: "value"
        },
        presentation: {
            placement: "PRICE_OVERLAY",
            color: "#2962FF",
            lineWidth: 2,
            opacity: 1,
            visible: true
        },
        connectionState: "CONFIGURED_NOT_EXECUTED"
    };
    const traffic: {
        anchors: string[];
        held: { anchor: string; resolve: (value: Response) => void }[];
        hold: boolean;
        failSibling: boolean;
        siblingFailure: { code: string; status: number };
        siblingBody?: string;
        retryAfter?: string;
        conflict: boolean;
        derived: boolean;
    } = {
        anchors: [],
        held: [],
        hold: false,
        failSibling: false,
        siblingFailure: { code: "CHART_STUDY_CAPACITY_UNAVAILABLE", status: 503 },
        conflict: false,
        derived: false
    };
    const queryBars = vi.fn((_source: MarketDataSourceReference, query: MarketDataBarsQuery) => {
        const result = page(required(query.before_ns));
        if (traffic.conflict) required(result.bars.at(-1)).close = "999";
        if (traffic.derived) {
            result.resolution_mode = "DERIVED";
            result.derived_projection_fingerprint = "d".repeat(64);
            result.aggregation_semantics_version = "TIME_BAR@1";
        }
        return Promise.resolve(result);
    });
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string, init: RequestInit) => {
            if (url.endsWith("capabilities"))
                return Promise.resolve(
                    new Response(
                        JSON.stringify({ schema_version: 1, capabilities: [sample.capability] }),
                        { headers: { "cache-control": "no-store" } }
                    )
                );
            const request = JSON.parse(init.body as string) as {
                window: { before_ns: string };
                calculation: { typed_parameters: { period: { value: number } } };
            };
            const anchor = request.window.before_ns;
            traffic.anchors.push(anchor);
            if (traffic.failSibling && traffic.anchors.length > 1)
                return Promise.resolve(
                    new Response(
                        traffic.siblingBody ??
                            JSON.stringify({
                                schema_version: 1,
                                error: {
                                    phase: "QUERY",
                                    code: traffic.siblingFailure.code,
                                    detail: "Calculation capacity exhausted"
                                }
                            }),
                        {
                            status: traffic.siblingFailure.status,
                            headers:
                                traffic.retryAfter === undefined
                                    ? {}
                                    : { "Retry-After": traffic.retryAfter }
                        }
                    )
                );
            if (traffic.hold)
                return new Promise<Response>((resolve) => traffic.held.push({ anchor, resolve }));
            return Promise.resolve(response(anchor));
        })
    );
    const market = marketDataClient({ queryBars });
    let activeCredentials: LocalReadCredentials | undefined;
    function Query({
        step = 0,
        siblings = false,
        third = false,
        owner = false,
        hidden = false,
        proof = "verified",
        older = false,
        preview = false,
        stale = false
    }: {
        step?: number;
        siblings?: boolean;
        third?: boolean;
        owner?: boolean;
        hidden?: boolean;
        proof?: string | null;
        older?: boolean;
        preview?: boolean;
        stale?: boolean;
    }) {
        const credentials = useLocalReadCredentials();
        activeCredentials = credentials;
        useLayoutEffect(() => {
            if (credentials.capture().bearer === null) credentials.replace("ee".repeat(32));
        }, [credentials]);
        const anchor = (baseEnd + BigInt(step) * duration).toString();
        const raw = page(anchor).bars;
        if (older)
            raw.unshift({
                ...required(raw[0]),
                bar_start_ns: (BigInt(required(raw[0]).bar_start_ns) - duration).toString(),
                bar_end_ns: required(raw[0]).bar_start_ns
            });
        const bars = raw.map(projectMarketDataBar);
        if (owner)
            return (
                <ChartStudies context={context} credentials={credentials}>
                    {({ instances, incarnationKey, onTransientRevalidated }) => (
                        <TransientStudyPriceChart
                            context={context}
                            onTransientRevalidated={onTransientRevalidated}
                            dataGeneration={proof}
                            expectedSourceId={initial.source_selection.source_id}
                            expectedEnvironment={initial.source_selection.environment}
                            contextKey={context.key}
                            incarnationKey={incarnationKey}
                            studies={instances}
                            bars={bars}
                            barSemantic={context.barSemantic}
                        />
                    )}
                </ChartStudies>
            );
        return (
            <TransientStudyPriceChart
                context={context}
                dataGeneration={proof}
                expectedSourceId={initial.source_selection.source_id}
                expectedEnvironment={initial.source_selection.environment}
                contextKey={context.key}
                incarnationKey="owner"
                studies={
                    siblings
                        ? [
                              instance,
                              {
                                  ...instance,
                                  instanceId: "two",
                                  configuration: {
                                      ...instance.configuration,
                                      parameters: {
                                          ...instance.configuration.parameters,
                                          period: { type: "INTEGER", value: 20 }
                                      }
                                  }
                              },
                              ...(third ? [{ ...instance, instanceId: "three" }] : [])
                          ]
                        : [
                              {
                                  ...instance,
                                  presentation: { ...instance.presentation, visible: !hidden },
                                  connectionState: stale
                                      ? "STALE_CONFIG"
                                      : "CONFIGURED_NOT_EXECUTED"
                              }
                          ]
                }
                bars={bars}
                liveBar={
                    preview
                        ? {
                              ...required(bars.at(-1)),
                              barStartNs: anchor,
                              barEndNs: (BigInt(anchor) + duration).toString(),
                              closed: false
                          }
                        : null
                }
                barSemantic={context.barSemantic}
            />
        );
    }
    const tree = (props: Parameters<typeof Query>[0] = {}) => (
        <AppProviders key={context.key} marketDataClient={market}>
            <Query {...props} />
        </AppProviders>
    );
    const recoverSession = (bearer: string | null = "ee".repeat(32)) => {
        required(activeCredentials).replace(bearer);
    };
    return { traffic, tree, response, queryBars, baseEnd, duration, recoverSession };
}

it.each([1, 3, 5, 15, 30, 60, 120, 240])(
    "loads ETH proved native %sm without source capability guessing",
    async (minutes) => {
        const test = setup(minutes, "ETHUSDT.BINANCE");
        render(test.tree());
        await waitFor(() => {
            expect(screen.getByTestId("overlays")).toHaveTextContent("one");
        });
    }
);
it("coalesces new closes behind the actual issued response and ignores presentation and duplicate anchors", async () => {
    const test = setup();
    test.traffic.hold = true;
    const view = render(test.tree());
    await waitFor(() => {
        expect(test.traffic.held).toHaveLength(1);
    });
    view.rerender(test.tree({ step: 1 }));
    view.rerender(test.tree({ step: 2 }));
    expect(test.traffic.anchors).toHaveLength(1);
    const first = required(test.traffic.held[0]);
    await act(async () => {
        first.resolve(test.response(first.anchor));
        await Promise.resolve();
    });
    await waitFor(() => {
        expect(test.traffic.held).toHaveLength(2);
    });
    const latest = required(test.traffic.held[1]);
    expect(latest.anchor).toBe((test.baseEnd + 2n * test.duration).toString());
    await act(async () => {
        latest.resolve(test.response(latest.anchor));
        await Promise.resolve();
    });
    await waitFor(() => {
        expect(screen.getByTestId("overlays")).toHaveTextContent("one");
    });
    view.rerender(test.tree({ step: 2, hidden: true }));
    expect(test.traffic.anchors).toHaveLength(2);
});
it("fails closed when the fresh Study input conflicts with current main-chart closed values", async () => {
    const test = setup();
    test.traffic.conflict = true;
    render(test.tree());
    await waitFor(() => {
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "INVALID"
        );
    });
    expect(test.traffic.anchors).toHaveLength(0);
});
it("preserves successful sibling when evaluation fails and makes Query retry discoverable", async () => {
    const test = setup();
    test.traffic.failSibling = true;
    render(test.tree({ siblings: true }));
    await waitFor(() => {
        expect(screen.getByTestId("overlays")).toHaveTextContent("one");
    });
    expect(screen.getByTestId("overlays")).not.toHaveTextContent("two");
    expect(screen.getByRole("button", { name: /重试.*two/ })).toBeEnabled();
    test.traffic.failSibling = false;
    fireEvent.click(screen.getByRole("button", { name: /重试.*two/ }));
    await waitFor(() => {
        expect(screen.getByTestId("overlays")).toHaveTextContent("one,two");
    });
    expect(test.traffic.anchors).toHaveLength(3);
});
it("does not evaluate partial main history even if old closed bars are displayed", async () => {
    const test = setup();
    render(test.tree({ proof: null }));
    await waitFor(() => {
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "INPUT_INCOMPLETE"
        );
    });
    expect(test.traffic.anchors).toHaveLength(0);
});

it("viewport older pages and Preview do not change finite Study initialization", async () => {
    const test = setup();
    const view = render(test.tree());
    await waitFor(() => {
        expect(screen.getByTestId("overlays")).toHaveTextContent("one");
    });
    view.rerender(test.tree({ older: true, preview: true }));
    expect(test.traffic.anchors).toHaveLength(1);
    expect(test.queryBars).toHaveBeenCalledTimes(1);
});
it("focus-stale intent is revalidated through fresh capability and finite owning history", async () => {
    const test = setup();
    render(test.tree({ stale: true }));
    await waitFor(() => {
        expect(screen.getByTestId("overlays")).toHaveTextContent("one");
    });
    expect(test.queryBars).toHaveBeenCalledTimes(1);
});

it("proved complete derived 7m stays on the main chart while Study is explicitly unsupported", async () => {
    const test = setup(7);
    test.traffic.derived = true;
    render(test.tree());
    await waitFor(() => {
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "UNSUPPORTED"
        );
    });
    expect(test.traffic.anchors).toHaveLength(0);
});

it("retrying one failed Study retains the other failed sibling's retry and valid sibling evidence", async () => {
    const test = setup();
    test.traffic.failSibling = true;
    render(test.tree({ siblings: true, third: true }));
    await waitFor(() => {
        expect(screen.getByRole("button", { name: /重试.*three/ })).toBeEnabled();
    });
    test.traffic.failSibling = false;
    fireEvent.click(screen.getByRole("button", { name: /重试.*two/ }));
    await waitFor(() => {
        expect(screen.getByTestId("overlays")).toHaveTextContent("one,two");
    });
    expect(screen.getByRole("button", { name: /重试.*three/ })).toBeEnabled();
    expect(test.traffic.anchors).toHaveLength(4);
});

it("a queued latest closed full batch takes priority over a same-turn sibling retry", async () => {
    const test = setup();
    test.traffic.failSibling = true;
    const view = render(test.tree({ siblings: true, third: true }));
    await waitFor(() => {
        expect(screen.getByRole("button", { name: /重试.*three/ })).toBeEnabled();
    });
    test.traffic.failSibling = false;
    test.traffic.hold = true;
    fireEvent.click(screen.getByRole("button", { name: /重试.*two/ }));
    await waitFor(() => {
        expect(test.traffic.held).toHaveLength(1);
    });
    // The unrelated failure remains visible while two's issued request is held.
    const retryThree = screen.getByRole("button", { name: /重试.*three/ });
    act(() => {
        fireEvent.click(retryThree);
        view.rerender(test.tree({ siblings: true, third: true, step: 1 }));
    });
    const first = required(test.traffic.held[0]);
    await act(async () => {
        first.resolve(test.response(first.anchor));
        await Promise.resolve();
    });
    for (let index = 1; index <= 3; index++) {
        await waitFor(() => {
            expect(test.traffic.held).toHaveLength(index + 1);
        });
        const pending = required(test.traffic.held[index]);
        expect(pending.anchor).toBe((test.baseEnd + test.duration).toString());
        await act(async () => {
            pending.resolve(test.response(pending.anchor));
            await Promise.resolve();
        });
    }
    await waitFor(() => {
        expect(screen.getByTestId("overlays")).toHaveTextContent("one,two,three");
    });
    expect(test.traffic.anchors).toHaveLength(7);
});

it("a queued sibling retry sees the prior completion's committed evidence", async () => {
    const test = setup();
    test.traffic.failSibling = true;
    render(test.tree({ siblings: true, third: true }));
    await waitFor(() => {
        expect(screen.getByRole("button", { name: /重试.*three/ })).toBeEnabled();
    });
    test.traffic.failSibling = false;
    test.traffic.hold = true;
    fireEvent.click(screen.getByRole("button", { name: /重试.*two/ }));
    await waitFor(() => {
        expect(test.traffic.held).toHaveLength(1);
    });
    fireEvent.click(screen.getByRole("button", { name: /重试.*three/ }));
    for (let index = 0; index < 2; index++) {
        await waitFor(() => {
            expect(test.traffic.held).toHaveLength(index + 1);
        });
        const pending = required(test.traffic.held[index]);
        await act(async () => {
            pending.resolve(test.response(pending.anchor));
            await Promise.resolve();
        });
    }
    await waitFor(() => {
        expect(screen.getByTestId("overlays")).toHaveTextContent("one,two,three");
    });
    expect(test.traffic.anchors).toHaveLength(5);
});

it("focus reproof followed by color-only editor confirmation does not reevaluate", async () => {
    const test = setup();
    const user = userEvent.setup();
    render(test.tree({ owner: true }));
    await user.click(screen.getByRole("button", { name: "指标" }));
    await user.click(await screen.findByRole("button", { name: "选择 SMA · 配置草稿" }));
    await user.click(screen.getByRole("button", { name: "添加" }));
    await waitFor(() => {
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "DISPLAYABLE"
        );
    });
    expect(test.traffic.anchors).toHaveLength(1);
    fireEvent.focus(window);
    await waitFor(() => {
        expect(test.traffic.anchors).toHaveLength(2);
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "DISPLAYABLE"
        );
    });
    await user.click(screen.getByRole("button", { name: "编辑 SMA" }));
    await user.click(screen.getByRole("button", { name: "红色" }));
    await user.click(screen.getByRole("button", { name: "应用" }));
    await waitFor(() => {
        expect(screen.getByTestId("chart-study-instance")).toHaveAttribute(
            "data-presentation",
            expect.stringContaining("#c8332a")
        );
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "DISPLAYABLE"
        );
    });
    expect(test.traffic.anchors).toHaveLength(2);
});

it.each([
    ["MARKET_DATA_REVISION_EVIDENCE_INVALID", 500],
    ["MARKET_DATA_FACT_STORE_UNAVAILABLE", 503],
    ["MARKET_DATA_SOURCE_SELECTION_MISMATCH", 400],
    ["CHART_STUDY_INPUT_UNAVAILABLE", 503],
    ["CHART_STUDY_INPUT_UNSUPPORTED", 400],
    ["CHART_STUDY_CAPABILITY_UNAVAILABLE", 503],
    ["CHART_STUDY_IMPLEMENTATION_UNAVAILABLE", 503],
    ["CHART_STUDY_DEPENDENCY_UNAVAILABLE", 503],
    ["LOCAL_READ_FORBIDDEN", 403],
    ["CHART_STUDY_DATA_CHANGED", 409],
    ["UNKNOWN_QUERY_PROOF_FAILURE", 503]
] as const)(
    "withdraws all sibling values after shared or unclassified proof failure %s",
    async (code, status) => {
        const test = setup();
        test.traffic.failSibling = true;
        test.traffic.siblingFailure = { code, status };
        render(test.tree({ siblings: true }));
        await waitFor(() => {
            expect(test.traffic.anchors).toHaveLength(2);
            expect(screen.getByTestId("chart-study-query-status")).not.toHaveAttribute(
                "data-query-status",
                "QUERYING"
            );
        });
        expect(screen.getByTestId("chart-study-query-status")).toHaveTextContent(code);
        expect(screen.getByTestId("overlays")).toBeEmptyDOMElement();
        expect(screen.getByTestId("chart-study-query-status")).not.toHaveAttribute(
            "data-query-status",
            "PARTIALLY_DISPLAYABLE"
        );
    }
);

it.each([
    ["MARKET_DATA_WINDOW_REQUEST_INVALID", 400, "UNAVAILABLE"],
    ["MARKET_DATA_FACT_STORE_UNAVAILABLE", 503, "UNAVAILABLE"],
    ["LOCAL_READ_UNAUTHORIZED", 401, "UNAUTHORIZED"],
    ["LOCAL_READ_FORBIDDEN", 403, "FORBIDDEN"],
    ["MARKET_DATA_RANGE_COMPOSITION_CONFLICT", 409, "STALE"]
] as const)("shows the formal shared history failure %s", async (code, status, visibleStatus) => {
    const test = setup();
    const view = render(test.tree({ siblings: true }));
    await waitFor(() => {
        expect(screen.getByTestId("overlays")).toHaveTextContent("one,two");
    });
    const prior = required(observedEvidence.at(-1)?.[0]);
    test.queryBars.mockRejectedValueOnce(
        new MarketDataWebError(code, "Formal history read refused", status)
    );
    view.rerender(test.tree({ siblings: true, step: 1 }));
    await waitFor(() => {
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            visibleStatus
        );
        expect(screen.getByTestId("chart-study-query-status")).toHaveTextContent(code);
        expect(screen.getByTestId("chart-study-query-status")).toHaveTextContent(
            "Formal history read refused"
        );
    });
    expect(screen.getByTestId("overlays")).toBeEmptyDOMElement();
    expect(isAdmittedChartStudyEvidence(prior)).toBe(false);
    if (status === 401 || status === 403) {
        expect(screen.queryByRole("button", { name: "重新查询指标" })).not.toBeInTheDocument();
    } else {
        fireEvent.click(screen.getByRole("button", { name: "重新查询指标" }));
        await waitFor(() => {
            expect(screen.getByTestId("overlays")).toHaveTextContent("one,two");
        });
        expect(screen.getByTestId("chart-study-query-status")).not.toHaveTextContent(code);
        expect(screen.getByTestId("chart-study-query-status")).not.toHaveTextContent(
            "Formal history read refused"
        );
        expect(isAdmittedChartStudyEvidence(prior)).toBe(false);
    }
});

it("keeps unknown shared history exceptions private", async () => {
    const test = setup();
    test.queryBars.mockRejectedValueOnce(new Error("internal credential=do-not-display"));
    render(test.tree({ siblings: true }));
    await waitFor(() => {
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "UNAVAILABLE"
        );
    });
    expect(screen.getByTestId("overlays")).toBeEmptyDOMElement();
    expect(document.body).not.toHaveTextContent("do-not-display");
    expect(screen.getByRole("button", { name: "重新查询指标" })).toBeEnabled();
});

it.each([
    ["CHART_STUDY_CAPACITY_UNAVAILABLE", 503],
    ["CHART_STUDY_CAPACITY_EXCEEDED", 503],
    ["CHART_STUDY_REQUEST_INVALID", 400],
    ["CHART_STUDY_OUTPUT_INVALID", 500]
] as const)("isolates proved per-instance failure %s", async (code, status) => {
    const test = setup();
    test.traffic.failSibling = true;
    test.traffic.siblingFailure = { code, status };
    render(test.tree({ siblings: true }));
    await waitFor(() => {
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "PARTIALLY_DISPLAYABLE"
        );
    });
    expect(screen.getByTestId("overlays")).toHaveTextContent("one");
    expect(screen.getByTestId("overlays")).not.toHaveTextContent("two");
    expect(screen.getByRole("button", { name: /重试.*two/ })).toBeEnabled();
});

it("shared input failure revokes a retained sibling's response admission before explicit recovery", async () => {
    const test = setup();
    test.traffic.failSibling = true;
    render(test.tree({ siblings: true }));
    await waitFor(() => {
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "PARTIALLY_DISPLAYABLE"
        );
    });
    const prior = required(observedEvidence.at(-1)?.[0]);
    expect(isAdmittedChartStudyEvidence(prior)).toBe(true);
    test.traffic.siblingFailure = { code: "MARKET_DATA_REVISION_EVIDENCE_INVALID", status: 500 };
    fireEvent.click(screen.getByRole("button", { name: /重试.*two/ }));
    await waitFor(() => {
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "INVALID"
        );
    });
    expect(screen.getByTestId("overlays")).toBeEmptyDOMElement();
    expect(isAdmittedChartStudyEvidence(prior)).toBe(false);
    test.traffic.failSibling = false;
    fireEvent.click(screen.getByRole("button", { name: "重新查询指标" }));
    await waitFor(() => {
        expect(screen.getByTestId("overlays")).toHaveTextContent("one,two");
    });
    expect(isAdmittedChartStudyEvidence(prior)).toBe(false);
});

const malformedFailures = (
    [
        [401, "UNAUTHORIZED"],
        [403, "FORBIDDEN"],
        [409, "STALE"]
    ] as const
).flatMap(([status, terminal]) =>
    ["", "<html>Denied</html>", '{"schema_version":'].map((body) => ({
        status,
        terminal,
        body
    }))
);

it.each(malformedFailures)(
    "withdraws a successful first sibling on HTTP $status with undecodable body $body",
    async ({ status, terminal, body }) => {
        const test = setup();
        test.traffic.failSibling = true;
        test.traffic.siblingFailure = { code: "INVALID", status };
        test.traffic.siblingBody = body;
        render(test.tree({ siblings: true }));
        await waitFor(() => {
            expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
                "data-query-status",
                terminal
            );
        });
        expect(test.traffic.anchors).toHaveLength(2);
        expect(screen.getByTestId("overlays")).toBeEmptyDOMElement();
    }
);

it.each(malformedFailures)(
    "retires retained sibling admission on HTTP $status with undecodable body $body",
    async ({ status, terminal, body }) => {
        const test = setup();
        test.traffic.failSibling = true;
        render(test.tree({ siblings: true }));
        await waitFor(() => {
            expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
                "data-query-status",
                "PARTIALLY_DISPLAYABLE"
            );
        });
        const prior = required(observedEvidence.at(-1)?.[0]);
        expect(isAdmittedChartStudyEvidence(prior)).toBe(true);
        test.traffic.siblingFailure = { code: "INVALID", status };
        test.traffic.siblingBody = body;
        fireEvent.click(screen.getByRole("button", { name: /重试.*two/ }));
        await waitFor(() => {
            expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
                "data-query-status",
                terminal
            );
        });
        expect(screen.getByTestId("overlays")).toBeEmptyDOMElement();
        expect(isAdmittedChartStudyEvidence(prior)).toBe(false);
        const capabilityReadsBeforeRecovery = vi
            .mocked(fetch)
            .mock.calls.filter(
                ([url]) => typeof url === "string" && url.endsWith("capabilities")
            ).length;
        test.traffic.failSibling = false;
        act(() => {
            test.recoverSession();
        });
        await waitFor(() => {
            expect(screen.getByTestId("overlays")).toHaveTextContent("one,two");
        });
        expect(test.queryBars).toHaveBeenCalledTimes(3);
        expect(
            vi
                .mocked(fetch)
                .mock.calls.filter(
                    ([url]) => typeof url === "string" && url.endsWith("capabilities")
                )
        ).toHaveLength(capabilityReadsBeforeRecovery + 1);
        expect(isAdmittedChartStudyEvidence(prior)).toBe(false);
    }
);

it.each(["", "<html>Malformed</html>", '{"schema_version":'])(
    "isolates malformed HTTP 200 body %s without retiring the valid sibling",
    async (body) => {
        const test = setup();
        test.traffic.failSibling = true;
        test.traffic.siblingFailure = { code: "INVALID", status: 200 };
        test.traffic.siblingBody = body;
        render(test.tree({ siblings: true }));
        await waitFor(() => {
            expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
                "data-query-status",
                "PARTIALLY_DISPLAYABLE"
            );
        });
        const prior = required(observedEvidence.at(-1)?.[0]);
        expect(screen.getByTestId("overlays")).toHaveTextContent("one");
        expect(screen.getByTestId("overlays")).not.toHaveTextContent("two");
        expect(isAdmittedChartStudyEvidence(prior)).toBe(true);
        fireEvent.click(screen.getByRole("button", { name: /重试.*two/ }));
        await waitFor(() => {
            expect(test.traffic.anchors).toHaveLength(3);
            expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
                "data-query-status",
                "PARTIALLY_DISPLAYABLE"
            );
        });
        expect(screen.getByTestId("overlays")).toHaveTextContent("one");
        expect(isAdmittedChartStudyEvidence(prior)).toBe(true);
    }
);

it.each(["history", "evaluation"])(
    "defers one shared %s window once and then freshly admits both SMA instances",
    async (failureAt) => {
        const test = setup(1);
        const view = render(test.tree({ siblings: true }));
        await waitFor(() => {
            expect(screen.getByTestId("overlays")).toHaveTextContent("one,two");
        });
        const prior = required(observedEvidence.at(-1)?.[0]);
        vi.useFakeTimers();
        if (failureAt === "history")
            test.queryBars.mockRejectedValueOnce(
                new MarketDataWebError("MARKET_DATA_WINDOW_NOT_CLOSED", "Window not closed", 503, 4)
            );
        else {
            test.traffic.failSibling = true;
            test.traffic.siblingFailure = { code: "MARKET_DATA_WINDOW_NOT_CLOSED", status: 503 };
            test.traffic.retryAfter = "4";
        }
        view.rerender(test.tree({ siblings: true, step: 1 }));
        await act(async () => {
            await Promise.resolve();
        });
        await vi.waitFor(() => {
            expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
                "data-query-status",
                "WAITING_FOR_CLOSED_WINDOW"
            );
        });
        expect(screen.getByTestId("overlays")).toBeEmptyDOMElement();
        expect(isAdmittedChartStudyEvidence(prior)).toBe(false);
        expect(screen.getByTestId("chart-study-query-status")).toHaveTextContent(
            "MARKET_DATA_WINDOW_NOT_CLOSED"
        );
        expect(screen.getByTestId("chart-study-query-status")).toHaveTextContent(
            "等待 K 线时间窗口就绪 · 将自动重新查询一次"
        );
        const count = test.queryBars.mock.calls.length;
        vi.setSystemTime(new Date("2000-01-01T00:00:00Z"));
        test.traffic.failSibling = false;
        await act(async () => {
            await vi.advanceTimersByTimeAsync(4000);
        });
        await act(async () => {
            await Promise.resolve();
        });
        await vi.waitFor(() => {
            expect(screen.getByTestId("overlays")).toHaveTextContent("one,two");
        });
        expect(test.queryBars).toHaveBeenCalledTimes(count + 1);
        expect(test.queryBars.mock.calls.at(-1)?.[1].before_ns).toBe(
            (test.baseEnd + test.duration).toString()
        );
        expect(test.queryBars.mock.calls.at(-1)?.[1].target_bar_count).toBe(2000);
        expect(isAdmittedChartStudyEvidence(prior)).toBe(false);
        await act(async () => {
            await vi.advanceTimersByTimeAsync(60_000);
        });
        expect(test.queryBars).toHaveBeenCalledTimes(count + 1);
    }
);

it("stops after the one server-directed reobservation is still not ready", async () => {
    const test = setup(1);
    test.queryBars.mockRejectedValue(
        new MarketDataWebError("MARKET_DATA_WINDOW_NOT_CLOSED", "Window not closed", 503, 4)
    );
    vi.useFakeTimers();
    render(test.tree({ siblings: true }));
    await act(async () => {
        await Promise.resolve();
    });
    await vi.waitFor(() => {
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "WAITING_FOR_CLOSED_WINDOW"
        );
    });
    await act(async () => {
        await vi.advanceTimersByTimeAsync(4000);
    });
    await act(async () => {
        await Promise.resolve();
    });
    await vi.waitFor(() => {
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "UNAVAILABLE"
        );
    });
    expect(screen.getByTestId("chart-study-query-status")).toHaveTextContent(
        "MARKET_DATA_WINDOW_NOT_CLOSED"
    );
    expect(screen.getByTestId("overlays")).toBeEmptyDOMElement();
    await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(test.queryBars).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "重新查询指标" }));
    await act(async () => {
        await Promise.resolve();
    });
    await vi.waitFor(() => {
        expect(test.queryBars).toHaveBeenCalledTimes(3);
    });
    await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(test.queryBars).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
        "data-query-status",
        "UNAVAILABLE"
    );
});

it.each(["new-close", "context", "auth-replacement", "logout", "unmount"])(
    "retires a pending window timer after %s",
    async (change) => {
        const test = setup(1);
        test.queryBars.mockRejectedValueOnce(
            new MarketDataWebError("MARKET_DATA_WINDOW_NOT_CLOSED", "Window not closed", 503, 4)
        );
        vi.useFakeTimers();
        const view = render(test.tree({ siblings: true }));
        await act(async () => {
            await Promise.resolve();
        });
        await vi.waitFor(() => {
            expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
                "data-query-status",
                "WAITING_FOR_CLOSED_WINDOW"
            );
        });
        if (change === "unmount") view.unmount();
        else if (change === "logout" || change === "auth-replacement")
            act(() => {
                test.recoverSession(change === "logout" ? null : "ff".repeat(32));
            });
        else {
            const replacement = change === "context" ? setup(15) : test;
            view.rerender(replacement.tree({ siblings: true, step: 1 }));
            await act(async () => {
                await Promise.resolve();
            });
            await vi.waitFor(() => {
                expect(screen.getByTestId("overlays")).toHaveTextContent("one,two");
            });
        }
        const count = test.queryBars.mock.calls.length;
        await act(async () => {
            await vi.advanceTimersByTimeAsync(4000);
        });
        expect(test.queryBars).toHaveBeenCalledTimes(count);
    }
);

it.each([
    new MarketDataWebError("MARKET_DATA_WINDOW_NOT_CLOSED", "Not ready", 503),
    new MarketDataWebError("MARKET_DATA_WINDOW_NOT_CLOSED", "Not ready", 400, 4),
    new MarketDataWebError("LOCAL_READ_UNAUTHORIZED", "Denied", 401, 4),
    new MarketDataWebError("LOCAL_READ_FORBIDDEN", "Denied", 403, 4),
    new MarketDataWebError("MARKET_DATA_RANGE_COMPOSITION_CONFLICT", "Conflict", 409, 4)
])("does not schedule unadmitted readiness or denial %s", async (error) => {
    const test = setup(1);
    test.queryBars.mockRejectedValue(error);
    vi.useFakeTimers();
    render(test.tree({ siblings: true }));
    await act(async () => {
        await Promise.resolve();
    });
    await vi.waitFor(() => {
        expect(screen.getByTestId("chart-study-query-status")).toHaveTextContent(error.code);
    });
    expect(screen.getByTestId("overlays")).toBeEmptyDOMElement();
    await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(test.queryBars).toHaveBeenCalledTimes(1);
});

it("ignores queued stale timer callbacks without disturbing the latest intent timer", async () => {
    const test = setup(1);
    test.queryBars.mockRejectedValueOnce(
        new MarketDataWebError("MARKET_DATA_WINDOW_NOT_CLOSED", "Not ready", 503, 4)
    );
    test.queryBars.mockRejectedValueOnce(
        new MarketDataWebError("MARKET_DATA_WINDOW_NOT_CLOSED", "Not ready", 503, 4)
    );
    vi.useFakeTimers();
    const callbacks: (() => void)[] = [];
    const schedule = globalThis.setTimeout;
    const spy = vi.spyOn(globalThis, "setTimeout").mockImplementation((callback, delay) => {
        if (delay === 4000 && typeof callback === "function")
            callbacks.push(callback as () => void);
        return schedule(callback, delay);
    });
    const view = render(test.tree({ siblings: true }));
    await act(async () => {
        await Promise.resolve();
    });
    await vi.waitFor(() => {
        expect(callbacks).toHaveLength(1);
    });
    view.rerender(test.tree({ siblings: true, step: 1 }));
    await act(async () => {
        await Promise.resolve();
    });
    await vi.waitFor(() => {
        expect(callbacks).toHaveLength(2);
    });
    act(() => {
        required(callbacks[0])();
    });
    view.rerender(test.tree({ siblings: true, step: 1, hidden: true, older: true, preview: true }));
    expect(test.queryBars).toHaveBeenCalledTimes(2);
    await act(async () => {
        await vi.advanceTimersByTimeAsync(4000);
    });
    await act(async () => {
        await Promise.resolve();
    });
    await vi.waitFor(() => {
        expect(screen.getByTestId("overlays")).toHaveTextContent("one,two");
    });
    expect(test.queryBars).toHaveBeenCalledTimes(3);
    spy.mockRestore();
});
