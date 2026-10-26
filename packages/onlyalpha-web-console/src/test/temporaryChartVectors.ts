// Controlled transport vectors for component regressions; no Product/Research proof.
import type { MarketDataBars } from "../api/marketData/model";
import type { ChartStudyEvaluate } from "../api/chartStudies/http.generated";
export const TEMPORARY_VECTOR_FINGERPRINT = "9".repeat(64);
function gaps(
    coverage: MarketDataBars["coverage"],
    semantic: MarketDataBars["bar_semantic"],
    start: string,
    end: string,
    count: number
) {
    const stride =
        BigInt(
            semantic.formation.kind === "FIXED_DURATION" ? semantic.formation.stride_minutes : 1
        ) * 60_000_000_000n;
    return coverage.gaps.flatMap((gap) => {
        if (BigInt(gap.start_ns) < BigInt(start) || BigInt(gap.end_ns) > BigInt(end)) return [gap];
        const result: { start_ns: string; end_ns: string }[] = [];
        for (
            let at = BigInt(gap.start_ns);
            at < BigInt(gap.end_ns) && result.length <= count;
            at += stride
        )
            result.push({ start_ns: at.toString(), end_ns: (at + stride).toString() });
        return result;
    });
}
export function temporaryWindowVector(history: MarketDataBars) {
    return {
        schema_version: 1,
        source_kind: "TEMPORARY_MARKET_DATA",
        authority: "DISPLAY_ONLY",
        publication_status: "NOT_A_RESEARCH_RESULT",
        source_selection: history.source_selection,
        instrument_id: history.instrument_id,
        bar_semantic: history.bar_semantic,
        anchor_kind: history.anchor_kind,
        requested_before_ns: history.requested_before_ns,
        requested_bar_count: history.requested_bar_count,
        resolved_start_ns: history.resolved_start_ns,
        resolved_end_ns: history.resolved_end_ns,
        bars: history.bars,
        coverage: {
            status: history.coverage.status === "COMPLETE" ? "COMPLETE" : "PARTIAL",
            expected_bar_count: history.coverage.expected_bar_count,
            actual_bar_count: history.coverage.actual_bar_count,
            gaps: gaps(
                history.coverage,
                history.bar_semantic,
                history.resolved_start_ns,
                history.resolved_end_ns,
                history.requested_bar_count
            )
        },
        window_fingerprint: TEMPORARY_VECTOR_FINGERPRINT,
        calendar_fingerprint: history.calendar_fingerprint ?? "b".repeat(64),
        resolution_plan_fingerprint: history.resolution_plan_fingerprint,
        resolution_mode: history.resolution_mode
    };
}
export function temporaryEvaluationVector(value: ChartStudyEvaluate) {
    const input = value.input;
    return {
        ...value,
        input: {
            source_kind: "TEMPORARY_MARKET_DATA",
            anchor_kind: input.anchor_kind,
            initialization: input.initialization,
            before_ns: input.before_ns,
            target_bar_count: input.target_bar_count,
            resolved_start_ns: input.resolved_start_ns,
            resolved_end_ns: input.resolved_end_ns,
            window_fingerprint: TEMPORARY_VECTOR_FINGERPRINT,
            calendar_fingerprint: input.calendar_fingerprint,
            resolution_plan_fingerprint: input.resolution_plan_fingerprint,
            resolution_mode: input.resolution_mode
        },
        coverage: {
            status: value.coverage.status === "COMPLETE" ? "COMPLETE" : "PARTIAL",
            expected_bar_count: value.coverage.expected_bar_count,
            actual_bar_count: value.coverage.actual_bar_count,
            gaps: gaps(
                value.coverage,
                value.bar_semantic,
                input.resolved_start_ns,
                input.resolved_end_ns,
                input.target_bar_count
            )
        },
        preview: null
    };
}

/** Controlled complete batch transport, preserving each independently supplied evaluation. */
export function temporaryBatchVector(evaluations: readonly unknown[]) {
    return {
        schema_version: 2,
        source_kind: "CHART_STUDY_TRANSIENT",
        authority: "DISPLAY_ONLY",
        publication_status: "NOT_A_RESEARCH_RESULT",
        window_fingerprint: TEMPORARY_VECTOR_FINGERPRINT,
        results: evaluations.map((evaluation, request_index) => ({
            status: "EVALUATED",
            request_index,
            evaluation
        }))
    };
}
