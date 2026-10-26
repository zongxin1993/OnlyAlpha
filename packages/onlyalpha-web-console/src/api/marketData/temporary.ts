import type { LocalReadCredentials } from "./localReadCredentials";
import { MarketDataWebError, protectedRead, type MarketDataBarsQuery } from "./client";
import { marketDataBarSemanticSchema, type MarketDataSourceReference } from "./model";
import {
    temporaryMarketDataWindowSchema,
    type TemporaryMarketDataWindow
} from "./temporary.generated";

/** A display Query only. Neither a cache miss nor an error submits an Acquisition. */
export async function readTemporaryMarketData(
    credentials: LocalReadCredentials,
    reference: MarketDataSourceReference,
    query: MarketDataBarsQuery,
    pageId: string,
    signal?: AbortSignal
): Promise<TemporaryMarketDataWindow> {
    if (!credentials.localSession || credentials.capture().bearer !== null)
        throw new MarketDataWebError("LOCAL_READ_FORBIDDEN", "临时行情需要正式工作台会话");
    const params = new URLSearchParams({
        page_id: pageId,
        integration_id: reference.integration_id,
        integration_revision_fingerprint: reference.integration_revision_fingerprint,
        instrument_id: query.instrument_id,
        bar_semantic: JSON.stringify(query.bar_semantic),
        anchor_kind: query.anchor_kind,
        target_bar_count: String(query.target_bar_count)
    });
    if (reference.expected_type_id !== undefined)
        params.set("expected_type_id", reference.expected_type_id);
    if (query.before_ns !== undefined) params.set("before_ns", query.before_ns);
    const value = await protectedRead(
        credentials,
        temporaryMarketDataWindowSchema,
        `/api/v2/chart/market-data/bars?${params}`,
        signal
    );
    const mismatch = () =>
        new MarketDataWebError(
            "MARKET_DATA_TEMPORARY_RESPONSE_MISMATCH",
            "临时行情响应与当前图表不一致"
        );
    const source = value.source_selection;
    const complete = value.coverage.status === "COMPLETE";
    const before = query.anchor_kind === "BEFORE_TIME" ? query.before_ns : null;
    if (
        source.integration_id !== reference.integration_id ||
        source.integration_revision_fingerprint !== reference.integration_revision_fingerprint ||
        (reference.expected_type_id !== undefined &&
            source.type_id !== reference.expected_type_id) ||
        value.instrument_id !== query.instrument_id ||
        value.anchor_kind !== query.anchor_kind ||
        value.requested_before_ns !== before ||
        value.requested_bar_count !== query.target_bar_count ||
        JSON.stringify(marketDataBarSemanticSchema.parse(value.bar_semantic)) !==
            JSON.stringify(marketDataBarSemanticSchema.parse(query.bar_semantic)) ||
        value.coverage.expected_bar_count !== query.target_bar_count ||
        value.coverage.actual_bar_count !== value.bars.length ||
        value.bars.length + value.coverage.gaps.length !== query.target_bar_count ||
        complete !==
            (value.bars.length === query.target_bar_count && value.coverage.gaps.length === 0) ||
        BigInt(value.resolved_start_ns) >= BigInt(value.resolved_end_ns) ||
        (before != null && BigInt(value.resolved_end_ns) > BigInt(before)) ||
        value.bars.some((bar, index) => {
            const previous = value.bars[index - 1];
            return (
                !bar.closed ||
                (index > 0 &&
                    (previous === undefined ||
                        BigInt(previous.bar_start_ns) >= BigInt(bar.bar_start_ns)))
            );
        })
    )
        throw mismatch();
    const intervals = [
        ...value.bars,
        ...value.coverage.gaps.map((gap) => ({
            bar_start_ns: gap.start_ns,
            bar_end_ns: gap.end_ns
        }))
    ].sort((a, b) => (BigInt(a.bar_start_ns) < BigInt(b.bar_start_ns) ? -1 : 1));
    if (
        intervals[0]?.bar_start_ns !== value.resolved_start_ns ||
        intervals.at(-1)?.bar_end_ns !== value.resolved_end_ns
    )
        throw mismatch();
    if (
        intervals.some((interval, index) => {
            const previous = intervals[index - 1];
            return (
                BigInt(interval.bar_start_ns) < BigInt(value.resolved_start_ns) ||
                BigInt(interval.bar_start_ns) >= BigInt(interval.bar_end_ns) ||
                BigInt(interval.bar_end_ns) > BigInt(value.resolved_end_ns) ||
                (index > 0 &&
                    (previous === undefined ||
                        BigInt(previous.bar_end_ns) > BigInt(interval.bar_start_ns)))
            );
        })
    )
        throw mismatch();
    return value;
}
