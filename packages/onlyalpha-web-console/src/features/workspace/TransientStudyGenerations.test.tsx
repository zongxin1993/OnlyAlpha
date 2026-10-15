import { act, render, screen, waitFor } from "@testing-library/react";
import { useLayoutEffect } from "react";
import { AppProviders, useLocalReadCredentials } from "../../app/providers";
import type { LocalReadCredentials } from "../../api/marketData/localReadCredentials";
import { marketDataBarsSchema } from "../../api/marketData/model";
import {
    ChartStudyCapabilitiesSchema,
    ChartStudyEvaluateSchema
} from "../../api/chartStudies/http.generated";
import { marketDataClient } from "../../test/marketDataClient";
import { projectMarketDataBar } from "../../charts/lightweight/marketDataChartProjection";
import sample from "../../../../../test-data/web/chart-studies/query.json";
import type { ChartStudyInstance } from "./chartStudy";
import { TransientStudyPriceChart } from "./TransientStudyPriceChart";

vi.mock("../../charts/lightweight/PriceChart", () => ({
    PriceChart: ({ studyEvidence }: { studyEvidence: readonly unknown[] }) => (
        <div data-testid="admitted-overlay-count">{studyEvidence.length}</div>
    )
}));
afterEach(() => {
    vi.unstubAllGlobals();
});

it.each(["configuration", "context", "credentials", "instances"])(
    "equal restored %s cannot revive an abandoned response occurrence",
    async (kind) => {
        vi.stubGlobal(
            "crypto",
            (await vi.importActual<{ webcrypto: Crypto }>("node:crypto")).webcrypto
        );
        const history = marketDataBarsSchema.parse({
            ...sample.history,
            instrument_id: "BTCUSDT.BINANCE"
        });
        const evaluation = ChartStudyEvaluateSchema.parse({
            ...sample.evaluation,
            instrument_id: history.instrument_id
        });
        const selectedCapability = ChartStudyCapabilitiesSchema.parse({
            schema_version: 1,
            capabilities: [sample.capability]
        }).capabilities[0];
        if (selectedCapability === undefined) throw new Error("Expected installed capability");
        const capability = selectedCapability;
        const pending: {
            request: unknown;
            promise: Promise<Response>;
            resolve: (value: Response) => void;
        }[] = [];
        const response = () =>
            new Response(JSON.stringify(evaluation), { headers: { "cache-control": "no-store" } });
        vi.stubGlobal(
            "fetch",
            vi.fn((url: string, init: RequestInit) => {
                if (url.endsWith("capabilities"))
                    return Promise.resolve(
                        new Response(
                            JSON.stringify({
                                schema_version: 1,
                                capabilities: [sample.capability]
                            }),
                            { headers: { "cache-control": "no-store" } }
                        )
                    );
                let resolve!: (value: Response) => void;
                const promise = new Promise<Response>((done) => {
                    resolve = done;
                });
                if (typeof init.body !== "string")
                    throw new Error("Expected formal JSON request body");
                pending.push({
                    request: JSON.parse(init.body) as unknown,
                    promise,
                    resolve
                });
                return promise;
            })
        );
        const acquisition = vi.fn();
        const market = marketDataClient({
            queryBars: () => Promise.resolve(history),
            createAcquisition: acquisition
        });
        let credentials: LocalReadCredentials | undefined;
        let initialized = false;
        function Query({
            period,
            other,
            duplicate
        }: {
            period: number;
            other: boolean;
            duplicate: boolean;
        }) {
            const active = useLocalReadCredentials();
            credentials = active;
            useLayoutEffect(() => {
                if (!initialized) {
                    initialized = true;
                    active.replace("ee".repeat(32));
                }
            }, [active]);
            const context = {
                key: other ? "other-source-context" : "original-source-context",
                source: {
                    integration_id: history.source_selection.integration_id,
                    integration_revision_fingerprint:
                        history.source_selection.integration_revision_fingerprint,
                    expected_type_id: history.source_selection.type_id
                },
                instrumentId: other ? "ETHUSDT.BINANCE" : history.instrument_id,
                barSemantic: history.bar_semantic
            };
            const instance: ChartStudyInstance = {
                instanceId: "one",
                context,
                selection: { source: "CHART_STUDY_TRANSIENT", capability },
                configuration: {
                    parameters: {
                        period: { type: "INTEGER", value: period },
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
            return (
                <TransientStudyPriceChart
                    context={context}
                    dataGeneration="verified"
                    expectedSourceId={history.source_selection.source_id}
                    expectedEnvironment={history.source_selection.environment}
                    contextKey={context.key}
                    incarnationKey="owner"
                    studies={
                        duplicate ? [instance, { ...instance, instanceId: "two" }] : [instance]
                    }
                    bars={history.bars.map(projectMarketDataBar)}
                    barSemantic={history.bar_semantic}
                />
            );
        }
        const tree = (period = 20, other = false, duplicate = false) => (
            <AppProviders marketDataClient={market}>
                <Query period={period} other={other} duplicate={duplicate} />
            </AppProviders>
        );
        const view = render(tree());
        await waitFor(() => {
            expect(pending).toHaveLength(1);
        });
        const first = pending[0];
        if (first === undefined) throw new Error("Expected first occurrence");
        // A single retained HTTP request owns its slot until response completion.
        // Intermediate intents coalesce; restored equality must still fence it.
        if (kind === "configuration") {
            view.rerender(tree(30));
            view.rerender(tree());
        } else if (kind === "context") {
            view.rerender(tree(20, true));
            view.rerender(tree());
        } else if (kind === "instances") {
            view.rerender(tree(20, false, true));
        } else {
            const active = credentials;
            if (active === undefined) throw new Error("Expected credential owner");
            act(() => {
                active.replace(null);
            });
            expect(screen.getByTestId("admitted-overlay-count")).toHaveTextContent("0");
            act(() => {
                active.replace("ee".repeat(32));
            });
        }
        expect(pending).toHaveLength(1);
        await act(async () => {
            first.resolve(response());
            await first.promise;
        });
        expect(screen.getByTestId("admitted-overlay-count")).toHaveTextContent("0");
        await waitFor(() => {
            expect(pending).toHaveLength(2);
        });
        if (kind === "instances") {
            const next = pending[1];
            if (next === undefined) throw new Error("Expected duplicate owner response");
            await act(async () => {
                next.resolve(response());
                await next.promise;
            });
            await waitFor(() => {
                expect(pending).toHaveLength(3);
            });
        }
        const latest = pending.at(-1);
        if (latest === undefined) throw new Error("Expected restored occurrence");
        await act(async () => {
            latest.resolve(response());
            await latest.promise;
        });
        await waitFor(() => {
            expect(screen.getByTestId("admitted-overlay-count")).toHaveTextContent(
                kind === "instances" ? "2" : "1"
            );
        });
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            "DISPLAYABLE"
        );
        await act(async () => {
            for (const item of pending) {
                item.resolve(response());
                await item.promise;
            }
        });
        expect(screen.getByTestId("admitted-overlay-count")).toHaveTextContent(
            kind === "instances" ? "2" : "1"
        );
        expect(acquisition).not.toHaveBeenCalled();
    }
);
