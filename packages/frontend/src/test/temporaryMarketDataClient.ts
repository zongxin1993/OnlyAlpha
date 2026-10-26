// Controlled temporary transport data; never real-market or Product acceptance evidence.
import type { MarketDataBarsQuery } from "../api/marketData/client";
import type { MarketDataSourceReference } from "../api/marketData/model";
import { temporaryMarketDataWindowSchema } from "../api/marketData/temporary.generated";
import { FIXTURE_SELECTION } from "./marketDataClient";
export function temporaryWindowForQuery(
    reference: MarketDataSourceReference,
    query: MarketDataBarsQuery
) {
    const stride =
        BigInt(
            query.bar_semantic.formation.kind === "FIXED_DURATION"
                ? query.bar_semantic.formation.window_minutes
                : 1
        ) * 60_000_000_000n;
    const end = BigInt(query.before_ns ?? "1767225600000000000"),
        start = end - BigInt(query.target_bar_count) * stride;
    return temporaryMarketDataWindowSchema.parse({
        schema_version: 1,
        source_kind: "TEMPORARY_MARKET_DATA",
        authority: "DISPLAY_ONLY",
        publication_status: "NOT_A_RESEARCH_RESULT",
        source_selection: {
            ...FIXTURE_SELECTION,
            integration_id: reference.integration_id,
            integration_revision_fingerprint: reference.integration_revision_fingerprint,
            type_id: reference.expected_type_id ?? FIXTURE_SELECTION.type_id
        },
        instrument_id: query.instrument_id,
        bar_semantic: query.bar_semantic,
        anchor_kind: query.anchor_kind,
        requested_before_ns: query.before_ns ?? null,
        requested_bar_count: query.target_bar_count,
        resolved_start_ns: start.toString(),
        resolved_end_ns: end.toString(),
        coverage: {
            status: "COMPLETE",
            expected_bar_count: query.target_bar_count,
            actual_bar_count: query.target_bar_count,
            gaps: []
        },
        bars: Array.from({ length: query.target_bar_count }, (_, index) => ({
            bar_start_ns: (start + BigInt(index) * stride).toString(),
            bar_end_ns: (start + BigInt(index + 1) * stride).toString(),
            open: "10.00",
            high: "12.00",
            low: "9.00",
            close: "11.00",
            volume: "1.00",
            closed: true
        })),
        window_fingerprint: "a".repeat(64),
        calendar_fingerprint: "b".repeat(64),
        resolution_plan_fingerprint: "c".repeat(64),
        resolution_mode: "PROVIDER_NATIVE"
    });
}
