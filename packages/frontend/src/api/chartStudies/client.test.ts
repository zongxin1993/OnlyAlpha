import { describe, expect, it, vi, afterEach } from "vitest";
import { ChartStudyEvaluateRequestSchema, ChartStudyEvaluateSchema } from "./http.generated";
import { marketDataBarSemantic } from "../marketData/model";
import { LocalReadCredentials } from "../marketData/localReadCredentials";
import {
    isAdmittedChartStudyEvidence,
    readChartStudyCapability,
    readChartStudyCapabilities
} from "./client";
import { isStudySeriesEvidence } from "../../charts/lightweight/studySeriesProjection";
import sample from "../../../../../test-data/web/chart-studies/query.json";
import { marketDataBarsSchema } from "../marketData/model";
import { ChartStudyCapabilitiesSchema } from "./http.generated";
import { readChartStudyEvaluation, readChartStudyEvidence } from "./client";

function vector() {
    const capability = ChartStudyCapabilitiesSchema.parse({
        schema_version: 2,
        capabilities: [sample.capability]
    }).capabilities[0];
    if (capability === undefined) throw new Error("Expected installed capability vector");
    const history = marketDataBarsSchema.parse(structuredClone(sample.history));
    const evaluated = ChartStudyEvaluateSchema.parse(structuredClone(sample.evaluation));
    const input = ChartStudyEvaluateRequestSchema.parse({
        schema_version: 2,
        source_reference: {
            integration_id: history.source_selection.integration_id,
            integration_revision_fingerprint:
                history.source_selection.integration_revision_fingerprint,
            expected_type_id: history.source_selection.type_id
        },
        instrument_id: history.instrument_id,
        bar_semantic: history.bar_semantic,
        window: {
            anchor_kind: "BEFORE_TIME",
            before_ns: evaluated.input.before_ns,
            target_bar_count: evaluated.input.target_bar_count
        },
        expected_history_projection_fingerprint: history.history_projection_fingerprint,
        calculation: {
            kind: capability.kind,
            type_id: capability.type_id,
            semantic_version: capability.semantic_version,
            typed_parameters: evaluated.calculation.normalized_typed_parameters,
            output_members: ["value"],
            expected_descriptor_fingerprint: capability.descriptor_fingerprint,
            expected_implementation_fingerprint: capability.implementation_fingerprint,
            expected_capability_projection_fingerprint: capability.capability_projection_fingerprint
        },
        include_unclosed_preview: false,
        preview_stream_id: null
    });
    const credentials = new LocalReadCredentials();
    credentials.replace("ee".repeat(32));
    const respond = () =>
        vi.stubGlobal(
            "fetch",
            vi.fn(() =>
                Promise.resolve(
                    new Response(JSON.stringify(evaluated), {
                        headers: { "cache-control": "no-store" }
                    })
                )
            )
        );
    return { capability, history, evaluated, input, credentials, respond };
}

const request = () => ({
    schema_version: 2,
    source_reference: {
        integration_id: "local-source",
        integration_revision_fingerprint: "a".repeat(64),
        expected_type_id: "binance.spot.market_data"
    },
    instrument_id: "BTCUSDT.BINANCE",
    bar_semantic: marketDataBarSemantic(15),
    window: {
        anchor_kind: "BEFORE_TIME",
        before_ns: "1769299200000000000",
        target_bar_count: 2000
    },
    expected_history_projection_fingerprint: "b".repeat(64),
    calculation: {
        kind: "INDICATOR",
        type_id: "onlyalpha.indicator.sma",
        semantic_version: "1",
        typed_parameters: {
            period: { type: "INTEGER", value: 20 },
            price_field: { type: "STRING", value: "CLOSE" }
        },
        output_members: ["value"],
        expected_descriptor_fingerprint: "c".repeat(64),
        expected_implementation_fingerprint: "d".repeat(64),
        expected_capability_projection_fingerprint: "e".repeat(64)
    },
    include_unclosed_preview: false,
    preview_stream_id: null
});
afterEach(() => {
    vi.unstubAllGlobals();
});
beforeEach(async () => {
    vi.stubGlobal(
        "crypto",
        (await vi.importActual<{ webcrypto: Crypto }>("node:crypto")).webcrypto
    );
});

describe("one server-derived strict Chart schema", () => {
    it("local-session transport uses same-origin cookies without inventing a bearer or permission", async () => {
        const credentials = new LocalReadCredentials(true);
        const fetcher = vi.fn<typeof fetch>(() =>
            Promise.resolve(
                new Response(
                    JSON.stringify({
                        schema_version: 2,
                        capabilities: [sample.capability]
                    }),
                    { headers: { "cache-control": "no-store" } }
                )
            )
        );
        vi.stubGlobal("fetch", fetcher);
        expect(
            (
                await readChartStudyCapability(credentials, undefined, {
                    kind: "INDICATOR",
                    type_id: sample.capability.type_id,
                    semantic_version: sample.capability.semantic_version
                })
            ).type_id
        ).toBe("onlyalpha.indicator.sma");
        const init = fetcher.mock.calls[0]?.[1];
        expect(init?.credentials).toBe("same-origin");
        expect(new Headers(init?.headers).has("Authorization")).toBe(false);
        vi.stubGlobal(
            "fetch",
            vi.fn(() =>
                Promise.resolve(
                    new Response(
                        JSON.stringify({
                            schema_version: 1,
                            error: {
                                phase: "QUERY",
                                code: "LOCAL_READ_UNAUTHORIZED",
                                detail: "LOCAL_READ_UNAUTHORIZED"
                            }
                        }),
                        { status: 401 }
                    )
                )
            )
        );
        await expect(readChartStudyCapabilities(credentials)).rejects.toMatchObject({
            code: "LOCAL_READ_UNAUTHORIZED",
            status: 401
        });
        expect(credentials.capture().bearer).toBeNull();
    });

    it.each(
        [401, 403, 409].flatMap((status) =>
            ["", "<html>Denied</html>", '{"schema_version":'].map((body) => ({ status, body }))
        )
    )("preserves HTTP $status for undecodable body $body", async ({ status, body }) => {
        const v = vector();
        vi.stubGlobal(
            "fetch",
            vi.fn(() => Promise.resolve(new Response(body, { status })))
        );
        await expect(readChartStudyCapabilities(v.credentials)).rejects.toMatchObject({
            code: "INVALID",
            status
        });
        await expect(
            readChartStudyEvaluation(v.credentials, v.input, v.capability, v.history)
        ).rejects.toMatchObject({ code: "INVALID", status });
    });

    it("admits owning complete-to-incomplete without requiring its absent cursor to match the old history", async () => {
        const v = vector();
        expect(v.history.resume_after_sequence).not.toBeNull();
        v.evaluated.query_status = "INPUT_INCOMPLETE";
        v.evaluated.series = [];
        v.evaluated.coverage.status = "INCOMPLETE";
        v.evaluated.coverage.actual_bar_count = 0;
        v.evaluated.coverage.gaps = [
            {
                start_ns: v.evaluated.input.resolved_start_ns,
                end_ns: v.evaluated.input.resolved_end_ns
            }
        ];
        v.evaluated.input.history_projection_fingerprint = null;
        v.evaluated.input.resume_after_sequence = null;
        v.evaluated.input.resume_plan_fingerprint = null;
        v.evaluated.input.revision_evidence = [];
        v.respond();
        const result = await readChartStudyEvaluation(
            v.credentials,
            v.input,
            v.capability,
            v.history
        );
        expect(result.query_status).toBe("INPUT_INCOMPLETE");
        expect(result.series).toEqual([]);
        const evidence = await readChartStudyEvidence(
            v.credentials,
            v.input,
            v.capability,
            v.history,
            {
                instanceId: "one",
                chartContextKey: "context",
                incarnationKey: "incarnation",
                configurationKey: JSON.stringify({
                    parameters: v.input.calculation.typed_parameters,
                    outputNames: ["value"]
                })
            },
            () => true,
            new AbortController().signal
        );
        expect(evidence).toBeNull();
    });
    it("admits the exact producer vector and copies backend values/readiness without recalculation", async () => {
        const v = vector();
        v.respond();
        const controller = new AbortController();
        const configurationKey = JSON.stringify({
            parameters: v.input.calculation.typed_parameters,
            outputNames: ["value"]
        });
        const evidence = await readChartStudyEvidence(
            v.credentials,
            v.input,
            v.capability,
            v.history,
            {
                instanceId: "one",
                chartContextKey: "context",
                incarnationKey: "incarnation",
                configurationKey
            },
            () => true,
            controller.signal
        );
        expect(evidence?.[0]?.points[19]).toEqual({
            timeNs: v.evaluated.series[0]?.points[19]?.time_ns,
            value: "10.500000000000",
            readiness: "READY",
            reason: "NONE"
        });
        if (evidence?.[0] === undefined) throw new Error("Expected admitted evidence");
        expect(isAdmittedChartStudyEvidence(evidence[0])).toBe(true);
        expect(evidence[0].outputUnit).toBe("PRICE");
        expect(v.capability.descriptor.outputs[0]?.unit).toBeNull();
        expect(isAdmittedChartStudyEvidence(structuredClone(evidence))).toBe(false);
        controller.abort();
        expect(isAdmittedChartStudyEvidence(evidence[0])).toBe(false);
    });
    it.each([
        "definition",
        "history-instrument",
        "history-count",
        "history-window",
        "resume",
        "aggregation",
        "duplicate-owner",
        "missing-proof",
        "incomplete-wrong-owner"
    ])("rejects structural mutation: %s", async (kind) => {
        const v = vector();
        if (kind === "definition") v.evaluated.calculation.definition_fingerprint = "b".repeat(64);
        if (kind === "history-instrument" || kind === "incomplete-wrong-owner")
            v.history.instrument_id = "OTHER.TEST";
        if (kind === "history-count") v.history.requested_bar_count = 24;
        if (kind === "history-window")
            v.history.resolved_start_ns = (
                BigInt(v.history.resolved_start_ns) - 900_000_000_000n
            ).toString();
        if (kind === "resume") v.evaluated.input.resume_plan_fingerprint = "b".repeat(64);
        if (kind === "aggregation") v.evaluated.input.aggregation_semantics_version = "different";
        if (kind === "duplicate-owner") {
            const first = v.evaluated.input.revision_evidence[0];
            if (first === undefined) throw new Error("Expected revision owner");
            v.evaluated.input.revision_evidence.push({
                ...first
            });
        }
        if (kind === "missing-proof") v.evaluated.input.revision_evidence = [];
        if (kind === "incomplete-wrong-owner") {
            v.evaluated.query_status = "INPUT_INCOMPLETE";
            v.evaluated.series = [];
            v.evaluated.coverage.status = "INCOMPLETE";
            v.evaluated.input.history_projection_fingerprint = null;
        }
        v.respond();
        await expect(
            readChartStudyEvaluation(v.credentials, v.input, v.capability, v.history)
        ).rejects.toThrow();
    });
    it("period20 cannot be labelled with a period30 display configuration", async () => {
        const v = vector();
        v.respond();
        await expect(
            readChartStudyEvidence(
                v.credentials,
                v.input,
                v.capability,
                v.history,
                {
                    instanceId: "one",
                    chartContextKey: "context",
                    incarnationKey: "incarnation",
                    configurationKey: JSON.stringify({
                        parameters: {
                            ...v.input.calculation.typed_parameters,
                            period: { type: "INTEGER", value: 30 }
                        },
                        outputNames: ["value"]
                    })
                },
                () => true,
                new AbortController().signal
            )
        ).rejects.toThrow("INVALID");
        expect(fetch).not.toHaveBeenCalled();
    });
    it("accepts the declared bounded request and refuses substitutions, extras and oversize arrays", () => {
        expect(ChartStudyEvaluateRequestSchema.safeParse(request()).success).toBe(true);
        const variants: unknown[] = [
            { ...request(), schema_version: true },
            { ...request(), include_unclosed_preview: 0 },
            { ...request(), bars: [] },
            { ...request(), window: { ...request().window, target_bar_count: true } },
            { ...request(), window: { ...request().window, target_bar_count: 2001 } },
            {
                ...request(),
                calculation: { ...request().calculation, output_members: ["value", "value"] }
            },
            {
                ...request(),
                calculation: {
                    ...request().calculation,
                    typed_parameters: {
                        ...request().calculation.typed_parameters,
                        period: { type: "INTEGER", value: "20" }
                    }
                }
            },
            {
                ...request(),
                source_reference: { ...request().source_reference, credentials: "secret" }
            }
        ];
        const admissions = variants.map(
            (variant) => ChartStudyEvaluateRequestSchema.safeParse(variant).success
        );
        expect(admissions).toEqual(variants.map(() => false));
        expect(
            ChartStudyEvaluateSchema.safeParse({
                schema_version: 1,
                source_kind: "CONTROLLED_TEST_EVIDENCE"
            }).success
        ).toBe(false);
    });
    it("copied fixture/provenance-shaped objects never gain production admission", () => {
        const forged = {
            source: {
                kind: "CHART_STUDY_TRANSIENT",
                historyProjectionFingerprint: "a".repeat(64),
                capabilityProjectionFingerprint: "b".repeat(64)
            },
            instanceId: "one",
            chartContextKey: "context",
            incarnationKey: "incarnation",
            configurationKey: "configuration",
            outputName: "value",
            points: []
        };
        expect(isAdmittedChartStudyEvidence(forged)).toBe(false);
        expect(isStudySeriesEvidence(forged)).toBe(false);
        expect(isAdmittedChartStudyEvidence(structuredClone(forged))).toBe(false);
    });
    it("absent authentication never calls the transport", async () => {
        const transport = vi.fn();
        vi.stubGlobal("fetch", transport);
        await expect(readChartStudyCapabilities(new LocalReadCredentials())).rejects.toThrow(
            "UNAUTHORIZED"
        );
        expect(transport).not.toHaveBeenCalled();
    });
    it("logout and same-token restoration fence an already-started capability response", async () => {
        const credentials = new LocalReadCredentials();
        credentials.replace("ee".repeat(32));
        let resolve!: (response: Response) => void;
        const response = new Promise<Response>((done) => {
            resolve = done;
        });
        vi.stubGlobal(
            "fetch",
            vi.fn(() => response)
        );
        const pending = readChartStudyCapabilities(credentials);
        credentials.replace(null);
        credentials.replace("ee".repeat(32));
        resolve(
            new Response(JSON.stringify({ schema_version: 2, capabilities: [] }), {
                headers: { "cache-control": "no-store" }
            })
        );
        await expect(pending).rejects.toThrow("STALE");
    });
});

it.each([1, 3, 5, 15, 30, 60, 120, 240])(
    "admits the proved ETH native %sm finite window",
    async (minutes) => {
        const v = vector();
        const end = BigInt(v.input.window.before_ns);
        const duration = BigInt(minutes) * 60_000_000_000n;
        const start = end - BigInt(v.input.window.target_bar_count) * duration;
        for (const item of [v.input, v.history, v.evaluated]) {
            item.instrument_id = "ETHUSDT.BINANCE";
            item.bar_semantic = marketDataBarSemantic(minutes);
        }
        v.history.resolved_start_ns = start.toString();
        v.evaluated.input.resolved_start_ns = start.toString();
        v.history.bars.forEach((bar, index) => {
            bar.bar_start_ns = (start + BigInt(index) * duration).toString();
            bar.bar_end_ns = (start + BigInt(index + 1) * duration).toString();
        });
        v.evaluated.series[0]?.points.forEach((point, index) => {
            point.time_ns = (start + BigInt(index) * duration).toString();
        });
        v.respond();
        await expect(
            readChartStudyEvaluation(v.credentials, v.input, v.capability, v.history)
        ).resolves.toEqual(v.evaluated);
    }
);

it.each([
    ["4", 4],
    [null, null],
    ["0", null],
    ["1.5", null],
    ["2147484", null]
] as const)("preserves only strict evaluate readiness Retry-After %s", async (header, expected) => {
    const v = vector();
    vi.stubGlobal(
        "fetch",
        vi.fn(() =>
            Promise.resolve(
                new Response(
                    JSON.stringify({
                        schema_version: 1,
                        error: {
                            phase: "QUERY",
                            code: "MARKET_DATA_WINDOW_NOT_CLOSED",
                            detail: "Window not closed"
                        }
                    }),
                    { status: 503, headers: header === null ? {} : { "Retry-After": header } }
                )
            )
        )
    );
    await expect(
        readChartStudyEvaluation(v.credentials, v.input, v.capability, v.history)
    ).rejects.toMatchObject({
        code: "MARKET_DATA_WINDOW_NOT_CLOSED",
        status: 503,
        retryAfterSeconds: expected
    });
    await expect(readChartStudyCapabilities(v.credentials)).rejects.toMatchObject({
        retryAfterSeconds: null
    });
});

it("rejects duplicate exact capability owners instead of picking the first", async () => {
    const credentials = new LocalReadCredentials(true);
    vi.stubGlobal(
        "fetch",
        vi.fn(() =>
            Promise.resolve(
                new Response(
                    JSON.stringify({
                        schema_version: 2,
                        capabilities: [sample.capability, sample.capability]
                    }),
                    { headers: { "cache-control": "no-store" } }
                )
            )
        )
    );
    await expect(readChartStudyCapabilities(credentials)).rejects.toMatchObject({
        code: "INVALID"
    });
});

it.each(["type", "version", "unrequested-output", "duplicate-series", "unit"])(
    "rejects a complete response with wrong grouped relation %s",
    async (mutation) => {
        const v = vector();
        const series = v.evaluated.series[0];
        const output = v.evaluated.calculation.output_members[0];
        if (series === undefined || output === undefined) throw new Error("Missing output");
        if (mutation === "type") v.evaluated.calculation.type_id = "onlyalpha.indicator.other";
        if (mutation === "version") v.evaluated.calculation.semantic_version = "999";
        if (mutation === "unrequested-output") series.output_name = "unrequested";
        if (mutation === "duplicate-series") v.evaluated.series.push(structuredClone(series));
        if (mutation === "unit") output.unit = "RATIO";
        v.respond();
        await expect(
            readChartStudyEvaluation(v.credentials, v.input, v.capability, v.history)
        ).rejects.toMatchObject({ code: "INVALID" });
    }
);

it("admits an owning preview separately and rejects stream substitution", async () => {
    const v = vector();
    v.input.include_unclosed_preview = true;
    v.input.preview_stream_id = "10000000-0000-4000-8000-000000000001";
    const time = v.input.window.before_ns;
    const point = v.evaluated.series[0]?.points.at(-1);
    if (point === undefined) throw new Error("Missing point");
    v.evaluated.preview = {
        source_kind: "PREVIEW_UNCLOSED",
        stream_id: "10000000-0000-4000-8000-000000000001",
        revision_fingerprint: "e".repeat(64),
        bar_start_ns: time,
        bar_end_ns: (BigInt(time) + 900_000_000_000n).toString(),
        series: [
            {
                output_name: "value",
                point: { ...point, time_ns: time, quality: "PREVIEW_UNCLOSED", closed: false }
            }
        ]
    };
    v.respond();
    const evidence = await readChartStudyEvidence(
        v.credentials,
        v.input,
        v.capability,
        v.history,
        {
            instanceId: "one",
            chartContextKey: "context",
            incarnationKey: "incarnation",
            configurationKey: JSON.stringify({
                parameters: v.input.calculation.typed_parameters,
                outputNames: ["value"]
            })
        },
        () => true,
        new AbortController().signal
    );
    expect(evidence?.[0]?.previewPoint?.timeNs).toBe(time);
    expect(evidence?.[0]?.points.some((row) => row.timeNs === time)).toBe(false);
    v.evaluated.preview.stream_id = "10000000-0000-4000-8000-000000000002";
    await expect(
        readChartStudyEvaluation(v.credentials, v.input, v.capability, v.history)
    ).rejects.toMatchObject({ code: "INVALID" });
});
