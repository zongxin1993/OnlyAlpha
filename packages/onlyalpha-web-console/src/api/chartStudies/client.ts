import type { z } from "zod";
import { windowRetryAfterSeconds } from "../marketData/client";
import type { LocalReadCredentials } from "../marketData/localReadCredentials";
import type { MarketDataBars, MarketDataBarSemantic } from "../marketData/model";
import type { StudySeriesEvidence } from "../../charts/lightweight/studySeriesProjection";
import { onlyAssertMarketDataBarsAuthority } from "../../features/workspace/marketDataBarsAuthority";
import {
    ChartStudyCapabilitiesSchema,
    ChartStudyEvaluateSchema,
    ChartStudyEvaluateRequestSchema,
    ChartStudyErrorEnvelopeSchema,
    type ChartStudyCapabilities,
    type ChartStudyEvaluateRequest,
    type ChartStudyEvaluate
} from "./http.generated";

export type ChartStudyCapability = ChartStudyCapabilities["capabilities"][number];
const admittedEvidence = new WeakMap<object, () => boolean>();
export function isAdmittedChartStudyEvidence(value: object): boolean {
    return admittedEvidence.get(value)?.() === true;
}
/** Canonical readiness contract v1 pairing; null does not imply unavailable or unready. */
export function isChartStudyReadiness(
    point: { readonly value: string | null; readonly readiness: string; readonly reason: string },
    nullable: boolean
): boolean {
    if (point.readiness === "PARTIAL")
        return point.reason === "WARMUP_INCOMPLETE" && (point.value !== null || nullable);
    if (point.readiness === "READY")
        return point.value !== null
            ? point.reason === "NONE"
            : nullable && point.reason === "VALUE_UNDEFINED";
    return (
        point.readiness === "UNAVAILABLE" &&
        point.value === null &&
        ["INPUT_UNAVAILABLE", "DEPENDENCY_UNAVAILABLE"].includes(point.reason)
    );
}
export class ChartStudyWebError extends Error {
    constructor(
        readonly code: string,
        readonly status?: number,
        readonly retryAfterSeconds: number | null = null
    ) {
        super(code);
    }
}

function canonical(value: unknown): string {
    if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
    if (value !== null && typeof value === "object")
        return `{${Object.entries(value)
            .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
            .map(([name, item]) => `${JSON.stringify(name)}:${canonical(item)}`)
            .join(",")}}`;
    return JSON.stringify(value);
}
export const sameChartBinding = (left: unknown, right: unknown): boolean =>
    canonical(left) === canonical(right);
async function fingerprint(value: unknown): Promise<string> {
    const bytes = new TextEncoder().encode(canonical(value));
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function read<T>(
    credentials: LocalReadCredentials,
    path: string,
    schema: z.ZodType<T>,
    signal?: AbortSignal,
    body?: ChartStudyEvaluateRequest
): Promise<T> {
    const captured = credentials.capture();
    if (captured.bearer === null && !credentials.localSession)
        throw new ChartStudyWebError("UNAUTHORIZED", 401);
    const current = () => !signal?.aborted && credentials.isCurrent(captured.generation);
    const response = await fetch(`/api/v2/chart/studies/${path}`, {
        method: body === undefined ? "GET" : "POST",
        cache: "no-store",
        credentials: credentials.localSession ? "same-origin" : "omit",
        headers: {
            Accept: "application/json",
            ...(captured.bearer === null ? {} : { Authorization: `Bearer ${captured.bearer}` }),
            ...(body === undefined ? {} : { "Content-Type": "application/json" })
        },
        ...(body === undefined
            ? {}
            : { body: JSON.stringify(ChartStudyEvaluateRequestSchema.parse(body)) }),
        ...(signal === undefined ? {} : { signal })
    });
    if (!current()) throw new ChartStudyWebError("STALE");
    let value: unknown;
    try {
        value = await response.json();
    } catch {
        throw new ChartStudyWebError("INVALID", response.status);
    }
    if (!current()) throw new ChartStudyWebError("STALE");
    if (!response.ok) {
        const error = ChartStudyErrorEnvelopeSchema.safeParse(value);
        throw new ChartStudyWebError(
            error.success ? error.data.error.code : "INVALID",
            response.status,
            error.success && path === "evaluate"
                ? windowRetryAfterSeconds(response, error.data.error.code, error.data.error.phase)
                : null
        );
    }
    if (response.headers.get("cache-control") !== "no-store")
        throw new ChartStudyWebError("INVALID");
    const result = schema.safeParse(value);
    if (!result.success) throw new ChartStudyWebError("INVALID");
    return result.data;
}

/** Structural schemas come only from the server. These checks close owning relations. */
export async function readChartStudyCapabilities(
    credentials: LocalReadCredentials,
    signal?: AbortSignal
): Promise<readonly ChartStudyCapability[]> {
    const generation = credentials.getGeneration();
    const result = await read(credentials, "capabilities", ChartStudyCapabilitiesSchema, signal);
    const identities = result.capabilities.map((row) =>
        JSON.stringify([row.kind, row.type_id, row.semantic_version])
    );
    if (new Set(identities).size !== identities.length) throw new ChartStudyWebError("INVALID");
    for (const capability of result.capabilities) {
        const p = capability.capability_projection;
        if (
            (await fingerprint(p)) !== capability.capability_projection_fingerprint ||
            (await fingerprint(p.descriptor)) !== capability.descriptor_fingerprint ||
            (await fingerprint(p.numeric_binding.core_policy)) !==
                p.numeric_binding.core_policy_fingerprint ||
            !sameChartBinding(
                Object.keys(capability.presentation.default_parameters).sort(),
                capability.descriptor.parameters.map((parameter) => parameter.name).sort()
            ) ||
            capability.descriptor.parameters.some((parameter) => {
                const value = capability.presentation.default_parameters[parameter.name];
                return parameter.parameter_type === "INTEGER"
                    ? typeof value !== "number" || !Number.isSafeInteger(value)
                    : parameter.parameter_type === "BOOLEAN"
                      ? typeof value !== "boolean"
                      : typeof value !== "string";
            }) ||
            capability.type_id !== capability.descriptor.type_id ||
            capability.semantic_version !== capability.descriptor.semantic_version ||
            new Set(capability.output_members).size !== capability.output_members.length ||
            !sameChartBinding(
                [...capability.output_members].sort(),
                capability.presentation.series.map((row) => row.output_name).sort()
            ) ||
            !sameChartBinding(capability.descriptor, p.descriptor) ||
            !sameChartBinding(capability.presentation, p.presentation) ||
            !sameChartBinding(capability.numeric_execution_binding, p.numeric_binding) ||
            !sameChartBinding(capability.limits, p.limits) ||
            capability.implementation_fingerprint !== p.implementation.implementation_fingerprint ||
            capability.invocation_implementation_fingerprint !==
                p.invocation.implementation_fingerprint ||
            capability.provider_id !== p.provider_manifest.provider_id ||
            capability.provider_version !== p.provider_manifest.provider_version ||
            capability.provider_content_fingerprint !== p.provider_content_fingerprint ||
            capability.catalog_generation_fingerprint !== p.catalog_generation_fingerprint ||
            !sameChartBinding(p.output_members, capability.output_members) ||
            !sameChartBinding(p.readiness_contract_versions, [
                capability.readiness_contract_version
            ]) ||
            !sameChartBinding(p.implementation.calculation_type_reference, {
                kind: capability.kind,
                type_id: capability.type_id,
                semantic_version: capability.semantic_version
            })
        )
            throw new ChartStudyWebError("INVALID");
        if (signal?.aborted || !credentials.isCurrent(generation))
            throw new ChartStudyWebError("STALE");
    }
    return result.capabilities;
}
export async function readChartStudyCapability(
    credentials: LocalReadCredentials,
    signal: AbortSignal | undefined,
    reference: Pick<ChartStudyCapability, "kind" | "type_id" | "semantic_version">
): Promise<ChartStudyCapability> {
    const entries = await readChartStudyCapabilities(credentials, signal);
    const entry = entries.find(
        (row) =>
            row.type_id === reference.type_id && row.semantic_version === reference.semantic_version
    );
    if (entry === undefined) throw new ChartStudyWebError("UNAVAILABLE");
    return entry;
}

/** Duration is request semantics, never evidence of Provider-native support. */
function studyDurationNs(semantic: MarketDataBarSemantic): bigint {
    if (
        semantic.formation.kind !== "FIXED_DURATION" ||
        semantic.formation.alignment !== "SESSION_START" ||
        semantic.formation.window_minutes !== semantic.formation.stride_minutes
    )
        throw new ChartStudyWebError("UNSUPPORTED");
    return BigInt(semantic.formation.window_minutes) * 60_000_000_000n;
}

/** Admit the requested owner/window before interpreting even an initial shortage. */
export function assertChartStudyHistory(
    selection: Pick<
        ChartStudyEvaluateRequest,
        "source_reference" | "instrument_id" | "bar_semantic" | "window"
    >,
    expectedSourceId: string,
    expectedEnvironment: string,
    history: MarketDataBars
): void {
    try {
        onlyAssertMarketDataBarsAuthority(
            {
                reference: selection.source_reference,
                expectedSourceId,
                instrumentId: selection.instrument_id,
                barSemantic: selection.bar_semantic,
                anchorKind: "BEFORE_TIME",
                beforeNs: selection.window.before_ns,
                targetBarCount: selection.window.target_bar_count
            },
            history
        );
        const end = BigInt(selection.window.before_ns);
        const start =
            end -
            BigInt(selection.window.target_bar_count) * studyDurationNs(selection.bar_semantic);
        if (
            history.source_selection.environment !== expectedEnvironment ||
            history.resolved_start_ns !== start.toString() ||
            history.resolved_end_ns !== end.toString() ||
            history.resolution_mode !== "PROVIDER_NATIVE" ||
            history.resolution_plan_fingerprint === null ||
            history.calendar_fingerprint === null ||
            history.derived_projection_fingerprint !== null ||
            history.coverage.expected_bar_count !== selection.window.target_bar_count ||
            history.coverage.actual_bar_count < 0 ||
            history.coverage.actual_bar_count > selection.window.target_bar_count ||
            [...history.coverage.gaps, ...history.coverage.planned_acquisition_ranges].some(
                (gap) =>
                    BigInt(gap.start_ns) < start ||
                    BigInt(gap.start_ns) >= BigInt(gap.end_ns) ||
                    BigInt(gap.end_ns) > end
            )
        )
            throw new ChartStudyWebError("INVALID");
    } catch {
        throw new ChartStudyWebError("INVALID");
    }
}

export async function readChartStudyEvaluation(
    credentials: LocalReadCredentials,
    request: ChartStudyEvaluateRequest,
    capability: ChartStudyCapability,
    history: MarketDataBars,
    signal?: AbortSignal
): Promise<ChartStudyEvaluate> {
    if (
        new Set(request.calculation.output_members).size !==
        request.calculation.output_members.length
    )
        throw new ChartStudyWebError("INVALID");
    assertChartStudyHistory(
        request,
        history.source_selection.source_id,
        history.source_selection.environment,
        history
    );
    const result = await read(credentials, "evaluate", ChartStudyEvaluateSchema, signal, request);
    const input = result.input,
        calc = result.calculation;
    const count = request.window.target_bar_count;
    const duration = studyDurationNs(request.bar_semantic);
    const start = BigInt(request.window.before_ns) - BigInt(count) * duration;
    if (
        !sameChartBinding(result.source_selection, history.source_selection) ||
        result.instrument_id !== request.instrument_id ||
        !sameChartBinding(result.bar_semantic, history.bar_semantic) ||
        !sameChartBinding(result.bar_semantic, request.bar_semantic) ||
        request.source_reference.integration_id !== result.source_selection.integration_id ||
        request.source_reference.integration_revision_fingerprint !==
            result.source_selection.integration_revision_fingerprint ||
        request.source_reference.expected_type_id !== result.source_selection.type_id ||
        input.before_ns !== request.window.before_ns ||
        input.target_bar_count !== count ||
        input.resolved_start_ns !== start.toString() ||
        input.resolved_end_ns !== input.before_ns ||
        history.resolved_start_ns !== input.resolved_start_ns ||
        history.resolved_end_ns !== input.resolved_end_ns ||
        input.resolution_plan_fingerprint !== history.resolution_plan_fingerprint ||
        input.calendar_fingerprint !== history.calendar_fingerprint ||
        input.aggregation_semantics_version !== history.aggregation_semantics_version ||
        input.derived_projection_fingerprint !== history.derived_projection_fingerprint ||
        new Set(calc.output_members.map((member) => member.name)).size !==
            calc.output_members.length ||
        new Set(result.series.map((series) => series.output_name)).size !== result.series.length ||
        calc.type_id !== request.calculation.type_id ||
        calc.semantic_version !== request.calculation.semantic_version ||
        !sameChartBinding(
            calc.output_members.map((member) => member.name).sort(),
            [...request.calculation.output_members].sort()
        ) ||
        calc.output_members.some(
            (member) =>
                !capability.presentation.series.some(
                    (series) => series.output_name === member.name && series.unit === member.unit
                )
        ) ||
        calc.capability_projection_fingerprint !== capability.capability_projection_fingerprint ||
        calc.descriptor_fingerprint !== capability.descriptor_fingerprint ||
        calc.implementation_fingerprint !== capability.implementation_fingerprint ||
        calc.provider_id !== capability.provider_id ||
        calc.provider_version !== capability.provider_version ||
        calc.provider_content_fingerprint !== capability.provider_content_fingerprint ||
        calc.catalog_generation_fingerprint !== capability.catalog_generation_fingerprint ||
        calc.invocation_implementation_fingerprint !==
            capability.invocation_implementation_fingerprint ||
        !sameChartBinding(calc.numeric, capability.descriptor.numeric) ||
        !sameChartBinding(calc.numeric_execution_binding, capability.numeric_execution_binding) ||
        !sameChartBinding(calc.normalized_typed_parameters, request.calculation.typed_parameters) ||
        (await fingerprint(calc.normalized_definition)) !== calc.definition_fingerprint ||
        calc.normalized_definition.type_id !== request.calculation.type_id ||
        calc.normalized_definition.semantic_version !== request.calculation.semantic_version ||
        !sameChartBinding(
            calc.normalized_definition.parameters,
            Object.fromEntries(
                Object.entries(request.calculation.typed_parameters).map(([name, scalar]) => [
                    name,
                    scalar.value
                ])
            )
        ) ||
        !sameChartBinding(calc.normalized_definition.numeric, capability.descriptor.numeric) ||
        !sameChartBinding(calc.normalized_definition.inputs, capability.descriptor.inputs) ||
        !sameChartBinding(calc.normalized_definition.outputs, capability.descriptor.outputs) ||
        result.coverage.expected_bar_count !== count ||
        result.coverage.actual_bar_count < 0 ||
        result.coverage.actual_bar_count > count ||
        [...result.coverage.gaps, ...result.coverage.planned_acquisition_ranges].some(
            (gap) =>
                BigInt(gap.start_ns) < start ||
                BigInt(gap.start_ns) >= BigInt(gap.end_ns) ||
                BigInt(gap.end_ns) > BigInt(request.window.before_ns)
        ) ||
        new Set(input.revision_evidence.map((row) => row.revision_id)).size !==
            input.revision_evidence.length
    )
        throw new ChartStudyWebError("INVALID");
    if (result.query_status === "INPUT_INCOMPLETE") {
        if (
            result.series.length !== 0 ||
            result.preview !== null ||
            result.coverage.status !== "INCOMPLETE" ||
            input.history_projection_fingerprint !== null ||
            input.resume_after_sequence !== null ||
            input.resume_plan_fingerprint !== null
        )
            throw new ChartStudyWebError("INVALID");
        return result;
    }
    if (
        input.resume_after_sequence !== history.resume_after_sequence ||
        input.resume_plan_fingerprint !== history.resume_plan_fingerprint ||
        history.anchor_kind !== "BEFORE_TIME" ||
        history.requested_before_ns !== input.before_ns ||
        history.history_projection_fingerprint !==
            request.expected_history_projection_fingerprint ||
        input.history_projection_fingerprint !== request.expected_history_projection_fingerprint ||
        !sameChartBinding(input.revision_evidence, history.revision_evidence) ||
        input.revision_evidence.length === 0 ||
        !sameChartBinding(result.coverage, history.coverage) ||
        result.coverage.status !== "COMPLETE" ||
        result.coverage.actual_bar_count !== count ||
        result.coverage.expected_bar_count !== count ||
        !sameChartBinding(
            result.series.map((series) => series.output_name).sort(),
            [...request.calculation.output_members].sort()
        ) ||
        history.bars.length !== count
    )
        throw new ChartStudyWebError("INVALID");
    for (const series of result.series) {
        const points = series.points;
        const output = capability.descriptor.outputs.find(
            (port) => port.name === series.output_name
        );
        if (output === undefined) throw new ChartStudyWebError("INVALID");
        if (points.length !== count) throw new ChartStudyWebError("INVALID");
        for (const [index, point] of points.entries()) {
            const bar = history.bars[index];
            if (point.value !== null) {
                const plotted = Number(point.value);
                if (
                    !Number.isFinite(plotted) ||
                    Math.abs(plotted) > Number.MAX_SAFE_INTEGER ||
                    (plotted === 0 && /[1-9]/.test(point.value))
                )
                    throw new ChartStudyWebError("INVALID");
            }
            if (
                bar?.closed !== true ||
                point.time_ns !== bar.bar_start_ns ||
                BigInt(point.time_ns) !== start + BigInt(index) * duration ||
                BigInt(bar.bar_end_ns) !== BigInt(point.time_ns) + duration ||
                !isChartStudyReadiness(point, output.nullable)
            )
                throw new ChartStudyWebError("INVALID");
        }
    }
    if (result.preview !== null) {
        const preview = result.preview;
        if (
            !request.include_unclosed_preview ||
            preview.stream_id !== request.preview_stream_id ||
            preview.bar_start_ns !== request.window.before_ns ||
            BigInt(preview.bar_end_ns) !== BigInt(preview.bar_start_ns) + duration ||
            !sameChartBinding(
                preview.series.map((row) => row.output_name).sort(),
                [...request.calculation.output_members].sort()
            ) ||
            new Set(preview.series.map((row) => row.output_name)).size !== preview.series.length ||
            preview.series.some((row) => {
                const output = capability.descriptor.outputs.find(
                    (port) => port.name === row.output_name
                );
                return (
                    row.point.time_ns !== preview.bar_start_ns ||
                    output === undefined ||
                    !isChartStudyReadiness(row.point, output.nullable)
                );
            })
        )
            throw new ChartStudyWebError("INVALID");
    }
    return result;
}

/** The production renderer cannot accept a copied DTO, fixture or object-shaped witness. */
export async function readChartStudyEvidence(
    credentials: LocalReadCredentials,
    request: ChartStudyEvaluateRequest,
    capability: ChartStudyCapability,
    history: MarketDataBars,
    binding: Pick<
        StudySeriesEvidence,
        "instanceId" | "chartContextKey" | "incarnationKey" | "configurationKey"
    >,
    current: () => boolean,
    signal: AbortSignal
): Promise<readonly StudySeriesEvidence[] | null> {
    if (
        !sameChartBinding(JSON.parse(binding.configurationKey) as unknown, {
            parameters: request.calculation.typed_parameters,
            outputNames: request.calculation.output_members
        })
    )
        throw new ChartStudyWebError("INVALID");
    const generation = credentials.getGeneration();
    const result = await readChartStudyEvaluation(
        credentials,
        request,
        capability,
        history,
        signal
    );
    const active = () => !signal.aborted && credentials.isCurrent(generation) && current();
    if (!active()) throw new ChartStudyWebError("STALE");
    if (result.query_status === "INPUT_INCOMPLETE") return null;
    return result.series.map((series) => {
        const output = result.calculation.output_members.find(
            (member) => member.name === series.output_name
        );
        if (
            output === undefined ||
            !request.calculation.output_members.includes(series.output_name)
        )
            throw new ChartStudyWebError("INVALID");
        const preview = result.preview?.series.find(
            (row) => row.output_name === series.output_name
        )?.point;
        const evidence: StudySeriesEvidence = Object.freeze({
            ...binding,
            source: Object.freeze({
                kind: "CHART_STUDY_TRANSIENT" as const,
                historyProjectionFingerprint: request.expected_history_projection_fingerprint,
                capabilityProjectionFingerprint: capability.capability_projection_fingerprint
            }),
            outputName: series.output_name,
            outputUnit: output.unit,
            ...(preview === undefined
                ? {}
                : {
                      previewPoint: Object.freeze({
                          timeNs: preview.time_ns,
                          value: preview.value,
                          readiness: preview.readiness,
                          reason: preview.reason,
                          sourceKind: "PREVIEW_UNCLOSED" as const
                      })
                  }),
            points: Object.freeze(
                series.points.map((point) =>
                    Object.freeze({
                        timeNs: point.time_ns,
                        value: point.value,
                        readiness: point.readiness,
                        reason: point.reason
                    })
                )
            )
        });
        admittedEvidence.set(evidence, active);
        return evidence;
    });
}
