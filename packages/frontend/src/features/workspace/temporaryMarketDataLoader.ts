import type { LocalReadCredentials } from "../../api/marketData/localReadCredentials";
import { MarketDataWebError, type MarketDataBarsQuery } from "../../api/marketData/client";
import type { MarketDataSourceReference } from "../../api/marketData/model";
import type { TemporaryMarketDataWindow } from "../../api/marketData/temporary.generated";
import { readTemporaryMarketData } from "../../api/marketData/temporary";

export async function loadTemporaryMarketDataWindow(
    credentials: LocalReadCredentials,
    reference: MarketDataSourceReference,
    query: MarketDataBarsQuery,
    pageId: string,
    options: {
        sourceId: string;
        environment: string;
        signal: AbortSignal;
        onWindow: (window: TemporaryMarketDataWindow) => void;
    }
): Promise<TemporaryMarketDataWindow> {
    let pinned = query,
        previousCount = 0;
    for (;;) {
        options.signal.throwIfAborted();
        const window = await readTemporaryMarketData(
            credentials,
            reference,
            pinned,
            pageId,
            options.signal
        );
        options.signal.throwIfAborted();
        if (
            window.source_selection.source_id !== options.sourceId ||
            window.source_selection.environment !== options.environment
        )
            throw new MarketDataWebError(
                "MARKET_DATA_TEMPORARY_RESPONSE_MISMATCH",
                "临时行情来源与当前选择不一致"
            );
        options.onWindow(window);
        const count = window.bars.length;
        if (window.coverage.status === "COMPLETE" || count <= previousCount) return window;
        previousCount = count;
        // Continue only when another bounded Provider page produced more closed
        // outputs. Keep the original resolved end even when real time advances.
        pinned = { ...query, anchor_kind: "BEFORE_TIME", before_ns: window.resolved_end_ns };
    }
}
