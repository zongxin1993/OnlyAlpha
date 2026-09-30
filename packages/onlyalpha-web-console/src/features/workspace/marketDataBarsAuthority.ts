import {
    marketDataBarsSchema,
    marketDataBarSemanticSchema,
    type MarketDataBars,
    type MarketDataBarSemantic,
    type MarketDataSourceReference
} from "../../api/marketData/model";

export class MarketDataBarsAuthorityMismatchError extends Error {
    readonly code = "MARKET_DATA_HISTORY_RESPONSE_MISMATCH";

    constructor() {
        super("MARKET_DATA_HISTORY_RESPONSE_MISMATCH: Bars do not prove the exact chart request");
        this.name = "MarketDataBarsAuthorityMismatchError";
    }
}

export interface MarketDataBarsExpectation {
    readonly reference: MarketDataSourceReference;
    readonly expectedSourceId: string;
    readonly instrumentId: string;
    readonly barSemantic: MarketDataBarSemantic;
    readonly anchorKind: "LATEST_CLOSED" | "BEFORE_TIME";
    readonly beforeNs?: string;
    readonly targetBarCount: number;
}

/** Admission only: the server still owns range planning, Coverage and Revision truth. */
export function onlyAssertMarketDataBarsAuthority(
    expected: MarketDataBarsExpectation,
    actual: MarketDataBars
): void {
    const admitted = marketDataBarsSchema.safeParse(actual);
    if (!admitted.success) throw new MarketDataBarsAuthorityMismatchError();
    const page = admitted.data;
    const source = page.source_selection;
    const before = expected.anchorKind === "BEFORE_TIME" ? expected.beforeNs : null;
    if (
        source.integration_id !== expected.reference.integration_id ||
        source.integration_revision_fingerprint !==
            expected.reference.integration_revision_fingerprint ||
        (expected.reference.expected_type_id !== undefined &&
            source.type_id !== expected.reference.expected_type_id) ||
        source.source_id !== expected.expectedSourceId ||
        page.instrument_id !== expected.instrumentId ||
        JSON.stringify(marketDataBarSemanticSchema.parse(page.bar_semantic)) !==
            JSON.stringify(marketDataBarSemanticSchema.parse(expected.barSemantic)) ||
        page.anchor_kind !== expected.anchorKind ||
        page.requested_before_ns !== before ||
        page.requested_bar_count !== expected.targetBarCount ||
        !page.closed_only ||
        BigInt(page.resolved_start_ns) >= BigInt(page.resolved_end_ns) ||
        (before != null && BigInt(page.resolved_end_ns) > BigInt(before)) ||
        page.bars.some(
            (bar) =>
                !bar.closed ||
                BigInt(bar.bar_start_ns) < BigInt(page.resolved_start_ns) ||
                BigInt(bar.bar_start_ns) >= BigInt(bar.bar_end_ns) ||
                BigInt(bar.bar_end_ns) > BigInt(page.resolved_end_ns)
        )
    )
        throw new MarketDataBarsAuthorityMismatchError();
}
