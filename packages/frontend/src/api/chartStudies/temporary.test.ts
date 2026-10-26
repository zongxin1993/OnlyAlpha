import { projectStudySeries } from "../../charts/lightweight/studySeriesProjection";
import { studySeriesFixture } from "../../test/studySeries";
import { requiredValue } from "../../test/requiredValue";
import { afterEach, expect, it, vi } from "vitest";
import sample from "../../../../../test-data/web/chart-studies/query.json";
import { LocalReadCredentials } from "../marketData/localReadCredentials";
import { temporaryMarketDataWindowSchema } from "../marketData/temporary.generated";
import {
    ChartStudyCapabilitiesSchema,
    TemporaryChartStudyEvaluateRequestSchema,
    TemporaryChartStudyEvaluateSchema
} from "./http.generated";
import {
    isAdmittedChartStudyEvidence,
    readTemporaryChartStudyEvidence,
    readTemporaryChartStudyBatchEvidence,
    readTemporaryChartStudyEvaluation
} from "./client";
function vector() {
    const capability = requiredValue(
        ChartStudyCapabilitiesSchema.parse({
            schema_version: 2,
            capabilities: [sample.capability]
        }).capabilities[0]
    );
    const h = sample.history;
    const e = sample.evaluation;
    const window = temporaryMarketDataWindowSchema.parse({
        schema_version: 1,
        source_kind: "TEMPORARY_MARKET_DATA",
        authority: "DISPLAY_ONLY",
        publication_status: "NOT_A_RESEARCH_RESULT",
        source_selection: h.source_selection,
        instrument_id: h.instrument_id,
        bar_semantic: h.bar_semantic,
        anchor_kind: "BEFORE_TIME",
        requested_before_ns: e.input.before_ns,
        requested_bar_count: 2000,
        resolved_start_ns: h.resolved_start_ns,
        resolved_end_ns: h.resolved_end_ns,
        coverage: {
            status: "COMPLETE",
            expected_bar_count: 2000,
            actual_bar_count: 2000,
            gaps: []
        },
        bars: h.bars,
        window_fingerprint: "d".repeat(64),
        calendar_fingerprint: h.calendar_fingerprint,
        resolution_plan_fingerprint: h.resolution_plan_fingerprint,
        resolution_mode: h.resolution_mode
    });
    const request = TemporaryChartStudyEvaluateRequestSchema.parse({
        schema_version: 2,
        source_kind: "TEMPORARY_MARKET_DATA",
        page_id: "00000000-0000-4000-8000-000000000001",
        source_reference: {
            integration_id: h.source_selection.integration_id,
            integration_revision_fingerprint: h.source_selection.integration_revision_fingerprint,
            expected_type_id: h.source_selection.type_id
        },
        instrument_id: h.instrument_id,
        bar_semantic: h.bar_semantic,
        window: {
            anchor_kind: "BEFORE_TIME",
            before_ns: e.input.before_ns,
            target_bar_count: 2000
        },
        expected_window_fingerprint: window.window_fingerprint,
        calculation: {
            kind: capability.kind,
            type_id: capability.type_id,
            semantic_version: capability.semantic_version,
            typed_parameters: e.calculation.normalized_typed_parameters,
            output_members: ["value"],
            expected_descriptor_fingerprint: capability.descriptor_fingerprint,
            expected_implementation_fingerprint: capability.implementation_fingerprint,
            expected_capability_projection_fingerprint: capability.capability_projection_fingerprint
        }
    });
    const result = TemporaryChartStudyEvaluateSchema.parse({
        ...e,
        input: {
            source_kind: "TEMPORARY_MARKET_DATA",
            anchor_kind: "BEFORE_TIME",
            initialization: "FINITE_WINDOW_START",
            before_ns: e.input.before_ns,
            target_bar_count: 2000,
            resolved_start_ns: h.resolved_start_ns,
            resolved_end_ns: h.resolved_end_ns,
            window_fingerprint: window.window_fingerprint,
            calendar_fingerprint: h.calendar_fingerprint,
            resolution_plan_fingerprint: h.resolution_plan_fingerprint,
            resolution_mode: h.resolution_mode
        },
        coverage: window.coverage,
        preview: null
    });
    const respond = (value: unknown = result) =>
        vi.stubGlobal(
            "fetch",
            vi.fn(() =>
                Promise.resolve(
                    new Response(JSON.stringify(value), {
                        headers: { "cache-control": "no-store" }
                    })
                )
            )
        );
    return {
        capability,
        window,
        request,
        result,
        respond,
        credentials: new LocalReadCredentials(true)
    };
}
afterEach(() => vi.unstubAllGlobals());
it("reads a closed temporary study through only its explicit Product API", async () => {
    const v = vector();
    v.respond();
    const result = await readTemporaryChartStudyEvaluation(
        v.credentials,
        v.request,
        v.capability,
        v.window
    );
    expect(result).toEqual(v.result);
    expect(fetch).toHaveBeenCalledExactlyOnceWith(
        "/api/v2/chart/temporary-studies/evaluate",
        expect.objectContaining({ method: "POST", cache: "no-store", credentials: "same-origin" })
    );
    expect(result.input).not.toHaveProperty("revision_evidence");
    expect(result.preview).toBeNull();
});
it.each(["window", "source", "provider", "catalog", "invocation", "point", "seal", "preview"])(
    "rejects a mismatched temporary result: %s",
    async (kind) => {
        const v = vector();
        let result: unknown = v.result;
        if (kind === "window")
            result = {
                ...v.result,
                input: { ...v.result.input, window_fingerprint: "e".repeat(64) }
            };
        if (kind === "source")
            result = {
                ...v.result,
                source_selection: {
                    ...v.result.source_selection,
                    integration_revision_fingerprint: "e".repeat(64)
                }
            };
        if (kind === "provider")
            result = {
                ...v.result,
                calculation: {
                    ...v.result.calculation,
                    provider_content_fingerprint: "e".repeat(64)
                }
            };
        if (kind === "catalog" || kind === "invocation")
            result = {
                ...v.result,
                calculation: {
                    ...v.result.calculation,
                    [kind === "catalog"
                        ? "catalog_generation_fingerprint"
                        : "invocation_implementation_fingerprint"]: "e".repeat(64)
                }
            };
        if (kind === "point")
            result = {
                ...v.result,
                series: v.result.series.map((series, index) =>
                    index === 0
                        ? {
                              ...series,
                              points: series.points.map((point, i) =>
                                  i === 0 ? { ...point, time_ns: "1" } : point
                              )
                          }
                        : series
                )
            };
        if (kind === "seal")
            result = {
                ...v.result,
                input: { ...v.result.input, revision_evidence: [{ seal_id: "fake" }] }
            };
        if (kind === "preview")
            result = { ...v.result, preview: { source_kind: "PREVIEW_UNCLOSED" } };
        v.respond(result);
        await expect(
            readTemporaryChartStudyEvaluation(v.credentials, v.request, v.capability, v.window)
        ).rejects.toMatchObject({ code: "INVALID" });
    }
);
it("keeps partial inputs incomplete without padding or shrinking the window", async () => {
    const v = vector();
    v.window.bars.pop();
    v.window.coverage = {
        status: "PARTIAL",
        expected_bar_count: 2000,
        actual_bar_count: 1999,
        gaps: [
            {
                start_ns: requiredValue(sample.history.bars.at(-1)).bar_start_ns,
                end_ns: requiredValue(sample.history.bars.at(-1)).bar_end_ns
            }
        ]
    };
    v.result.coverage = v.window.coverage;
    v.result.query_status = "INPUT_INCOMPLETE";
    v.result.series = [];
    v.respond();
    const result = await readTemporaryChartStudyEvaluation(
        v.credentials,
        v.request,
        v.capability,
        v.window
    );
    expect(result.query_status).toBe("INPUT_INCOMPLETE");
    expect(result.input.target_bar_count).toBe(2000);
});
it("admits only original temporary display evidence and withdraws it on cancellation", async () => {
    const v = vector();
    v.respond();
    const controller = new AbortController();
    const binding = {
        instanceId: "study",
        chartContextKey: "context",
        incarnationKey: "incarnation",
        configurationKey: JSON.stringify({
            parameters: v.request.calculation.typed_parameters,
            outputNames: v.request.calculation.output_members
        })
    };
    const result = await readTemporaryChartStudyEvidence(
        v.credentials,
        v.request,
        v.capability,
        v.window,
        binding,
        () => true,
        controller.signal
    );
    expect(result).not.toBeNull();
    const evidence = requiredValue(requiredValue(result)[0]);
    expect(evidence.source).toEqual({
        kind: "CHART_STUDY_TEMPORARY",
        windowFingerprint: v.window.window_fingerprint,
        capabilityProjectionFingerprint: v.capability.capability_projection_fingerprint
    });
    expect(isAdmittedChartStudyEvidence(evidence)).toBe(true);
    expect(isAdmittedChartStudyEvidence(structuredClone(evidence))).toBe(false);
    const instance = {
        ...studySeriesFixture().instance,
        instanceId: binding.instanceId,
        context: { ...studySeriesFixture().instance.context, key: binding.chartContextKey },
        configuration: {
            parameters: v.request.calculation.typed_parameters,
            outputNames: v.request.calculation.output_members
        }
    };
    const timeline = v.window.bars.map((bar) => Number(BigInt(bar.bar_start_ns) / 1_000_000_000n));
    const first = projectStudySeries(instance, binding.incarnationKey, timeline, evidence);
    const older = projectStudySeries(
        instance,
        binding.incarnationKey,
        [requiredValue(timeline[0]) - 900, ...timeline],
        evidence
    );
    expect(first.status).toBe("PROJECTED");
    expect(older.status).toBe("PROJECTED");
    if (first.status !== "PROJECTED" || older.status !== "PROJECTED")
        throw new Error("Expected projections");
    // Loading older bars must not clone the same admitted point ledger again.
    expect(older.projection.pointsByTime).toBe(first.projection.pointsByTime);
    expect(older.projection.segments[0]).toHaveLength(timeline.length + 1);
    controller.abort();
    expect(isAdmittedChartStudyEvidence(evidence)).toBe(false);
    expect(projectStudySeries(instance, binding.incarnationKey, timeline, evidence).status).toBe(
        "INVALID"
    );
});
it.each(["PROVIDER_NATIVE", "DERIVED"] as const)(
    "accepts the owning temporary input mode without treating it as sealed history: %s",
    async (mode) => {
        const v = vector();
        v.window.resolution_mode = mode;
        v.result.input.resolution_mode = mode;
        v.respond();
        const value = await readTemporaryChartStudyEvaluation(
            v.credentials,
            v.request,
            v.capability,
            v.window
        );
        expect(value.input.resolution_mode).toBe(mode);
        expect(value.input.source_kind).toBe("TEMPORARY_MARKET_DATA");
    }
);
it("rejects a changed resolution mode even when both modes are transport-valid", async () => {
    const v = vector();
    v.result.input.resolution_mode = "DERIVED";
    v.respond();
    await expect(
        readTemporaryChartStudyEvaluation(v.credentials, v.request, v.capability, v.window)
    ).rejects.toMatchObject({ code: "INVALID" });
});

function batchVector() {
    const v = vector();
    const items = [0, 1, 2, 3].map((index) => ({
        request: v.request,
        capability: v.capability,
        binding: {
            instanceId: `study-${String(index)}`,
            chartContextKey: "context",
            incarnationKey: "incarnation",
            configurationKey: JSON.stringify({
                parameters: v.request.calculation.typed_parameters,
                outputNames: v.request.calculation.output_members
            })
        },
        admissionCurrent: (): boolean => true
    }));
    const payload = {
        schema_version: 2,
        source_kind: "CHART_STUDY_TRANSIENT",
        authority: "DISPLAY_ONLY",
        publication_status: "NOT_A_RESEARCH_RESULT",
        window_fingerprint: v.window.window_fingerprint,
        results: items.map((_, request_index) => ({
            status: "EVALUATED",
            request_index,
            evaluation: structuredClone(v.result)
        }))
    };
    const query = (input = items) =>
        readTemporaryChartStudyBatchEvidence(
            v.credentials,
            input,
            v.window,
            () => true,
            new AbortController().signal
        );
    return { ...v, items, payload, query };
}
it("admits four independent occurrences through one bounded batch and retires each exact occurrence", async () => {
    const v = batchVector();
    let active = true;
    v.items[2] = { ...requiredValue(v.items[2]), admissionCurrent: () => active };
    v.respond(v.payload);
    const results = await v.query();
    expect(fetch).toHaveBeenCalledTimes(1);
    const call = vi.mocked(fetch).mock.calls[0];
    expect(call?.[0]).toBe("/api/v2/chart/temporary-studies/evaluate-batch");
    const body = JSON.parse(call?.[1]?.body as string) as Record<string, unknown>;
    expect(body).not.toHaveProperty("calculation");
    expect(body.calculations).toHaveLength(4);
    const evidence = results.map((result) =>
        result.status === "EVALUATED" ? requiredValue(requiredValue(result.evidence)[0]) : null
    );
    expect(evidence.every((row) => row !== null && isAdmittedChartStudyEvidence(row))).toBe(true);
    active = false;
    expect(evidence.map((row) => row !== null && isAdmittedChartStudyEvidence(row))).toEqual([
        true,
        true,
        false,
        true
    ]);
});
it.each([
    "missing",
    "duplicate-index",
    "reorder",
    "window",
    "last-value",
    "unknown-rejection",
    "extra-field"
])("rejects the entire batch after %s", async (kind) => {
    const v = batchVector();
    const payload: Record<string, unknown> = structuredClone(v.payload);
    const rows = payload.results as Record<string, unknown>[];
    if (kind === "missing") rows.pop();
    if (kind === "duplicate-index") requiredValue(rows[3]).request_index = 0;
    if (kind === "reorder") rows.reverse();
    if (kind === "window") payload.window_fingerprint = "f".repeat(64);
    if (kind === "last-value")
        requiredValue(
            requiredValue(requiredValue(v.payload.results[3]).evaluation.series[0]).points[0]
        ).time_ns = "1";
    if (kind === "unknown-rejection")
        rows[3] = { status: "REJECTED", request_index: 3, error: "REGISTRATION_CHANGED" };
    if (kind === "extra-field") payload.research_result_id = "forbidden";
    v.respond(kind === "last-value" ? v.payload : payload);
    await expect(v.query()).rejects.toMatchObject({ code: "INVALID" });
    expect(fetch).toHaveBeenCalledTimes(1);
});
it("isolates only a typed local request rejection and keeps successful indexes bound", async () => {
    const v = batchVector();
    const payload = {
        ...v.payload,
        results: v.payload.results.map((row, index) =>
            index === 1
                ? { status: "REJECTED", request_index: 1, error: "CHART_STUDY_REQUEST_INVALID" }
                : row
        )
    };
    v.respond(payload);
    const results = await v.query();
    expect(results.map((row) => row.status)).toEqual([
        "EVALUATED",
        "REJECTED",
        "EVALUATED",
        "EVALUATED"
    ]);
    expect(results[1]).toMatchObject({ error: { code: "CHART_STUDY_REQUEST_INVALID" } });
});
it.each([0, 5])("refuses %s items without issuing work", async (count) => {
    const v = batchVector();
    v.respond(v.payload);
    await expect(
        v.query(Array.from({ length: count }, () => requiredValue(v.items[0])))
    ).rejects.toMatchObject({ code: "INVALID" });
    expect(fetch).not.toHaveBeenCalled();
});
it("refuses mixed windows before issuing batch work", async () => {
    const v = batchVector();
    v.respond(v.payload);
    v.items[3] = {
        ...requiredValue(v.items[3]),
        request: { ...v.request, page_id: "00000000-0000-4000-8000-000000000002" }
    };
    await expect(v.query()).rejects.toMatchObject({ code: "INVALID" });
    expect(fetch).not.toHaveBeenCalled();
});
