import type { MarketDataApiClient, MarketDataBarsQuery } from "../../api/marketData/client";
import {
    marketDataBarSemanticSchema,
    type MarketDataBar,
    type MarketDataBarSemantic,
    type MarketDataSourceReference
} from "../../api/marketData/model";
import type { MarketDataBarLedgerMerge } from "./marketDataBarLedger";
import { onlyAssertMarketDataBarsAuthority } from "./marketDataBarsAuthority";

export const OLDER_HISTORY_TARGET_BAR_COUNT = 240;

export const onlyMarketDataChartContextKey = (
    reference: MarketDataSourceReference,
    instrumentId: string,
    barSemantic: MarketDataBarSemantic
): string =>
    JSON.stringify([
        reference.integration_id,
        reference.integration_revision_fingerprint,
        instrumentId,
        marketDataBarSemanticSchema.parse(barSemantic)
    ]);

export type OlderHistoryLoadStatus = "loaded" | "exhausted" | "stale";

export interface OlderHistoryLoadResult {
    readonly status: OlderHistoryLoadStatus;
    readonly prependedCount: number;
}

interface OlderHistoryLoaderOptions {
    readonly client: MarketDataApiClient;
    readonly reference: MarketDataSourceReference;
    readonly expectedSourceId: string;
    readonly contextKey: string;
    readonly isCurrent: () => boolean;
    readonly merge: (bars: readonly MarketDataBar[]) => MarketDataBarLedgerMerge;
    readonly onAcquiring?: () => void;
}

interface OlderHistoryRequest {
    readonly instrumentId: string;
    readonly barSemantic: MarketDataBarSemantic;
    readonly beforeNs: string;
}

export class OnlyMarketDataHistoryLoader {
    private readonly inFlight = new Map<string, Promise<OlderHistoryLoadResult>>();
    private readonly completed = new Map<string, OlderHistoryLoadResult>();
    private exhausted = false;

    constructor(private readonly options: OlderHistoryLoaderOptions) {}

    loadOlder(request: OlderHistoryRequest): Promise<OlderHistoryLoadResult> {
        if (this.exhausted) return Promise.resolve({ status: "exhausted", prependedCount: 0 });
        const query: MarketDataBarsQuery = {
            instrument_id: request.instrumentId,
            anchor_kind: "BEFORE_TIME",
            before_ns: request.beforeNs,
            target_bar_count: OLDER_HISTORY_TARGET_BAR_COUNT,
            bar_semantic: request.barSemantic
        };
        const pageKey = JSON.stringify([
            this.options.contextKey,
            request.beforeNs,
            OLDER_HISTORY_TARGET_BAR_COUNT,
            marketDataBarSemanticSchema.parse(request.barSemantic)
        ]);
        const completed = this.completed.get(pageKey);
        if (completed !== undefined) return Promise.resolve(completed);
        const existing = this.inFlight.get(pageKey);
        if (existing !== undefined) return existing;

        const pending = this.fetchAndMerge(query)
            .then((result) => {
                if (result.status !== "stale") this.completed.set(pageKey, result);
                return result;
            })
            .finally(() => {
                this.inFlight.delete(pageKey);
            });
        this.inFlight.set(pageKey, pending);
        return pending;
    }

    private async fetchAndMerge(query: MarketDataBarsQuery): Promise<OlderHistoryLoadResult> {
        let page = await this.options.client.queryBars(this.options.reference, query);
        if (!this.options.isCurrent()) return { status: "stale", prependedCount: 0 };

        const expectation = {
            reference: this.options.reference,
            expectedSourceId: this.options.expectedSourceId,
            instrumentId: query.instrument_id,
            barSemantic: query.bar_semantic,
            anchorKind: query.anchor_kind,
            targetBarCount: query.target_bar_count,
            ...(query.before_ns === undefined ? {} : { beforeNs: query.before_ns })
        };
        onlyAssertMarketDataBarsAuthority(expectation, page);

        if (page.coverage.status !== "COMPLETE") {
            this.options.onAcquiring?.();
            for (const range of page.coverage.planned_acquisition_ranges) {
                let acquisition = await this.options.client.createAcquisition(
                    this.options.reference,
                    {
                        instrument_id: query.instrument_id,
                        start_ns: range.start_ns,
                        end_ns: range.end_ns,
                        bar_semantic: query.bar_semantic
                    }
                );
                if (!this.options.isCurrent()) return { status: "stale", prependedCount: 0 };
                while (acquisition.status !== "COMPLETE") {
                    if (acquisition.status === "FAILED") {
                        throw new Error(
                            `Older history acquisition failed: ${acquisition.failure_detail ?? acquisition.status}`
                        );
                    }
                    if (acquisition.status === "PENDING") {
                        acquisition = await this.options.client.createAcquisition(
                            this.options.reference,
                            {
                                instrument_id: query.instrument_id,
                                start_ns: range.start_ns,
                                end_ns: range.end_ns,
                                bar_semantic: query.bar_semantic
                            }
                        );
                    } else {
                        await new Promise((resolve) => window.setTimeout(resolve, 250));
                        if (!this.options.isCurrent())
                            return { status: "stale", prependedCount: 0 };
                        acquisition = await this.options.client.getAcquisition(
                            this.options.reference,
                            acquisition.acquisition_id
                        );
                    }
                    if (!this.options.isCurrent()) return { status: "stale", prependedCount: 0 };
                }
            }
            page = await this.options.client.queryBars(this.options.reference, query);
            if (!this.options.isCurrent()) return { status: "stale", prependedCount: 0 };
            onlyAssertMarketDataBarsAuthority(expectation, page);
        }
        if (page.coverage.status !== "COMPLETE") {
            throw new Error("Older history remains incomplete after server-planned acquisition");
        }

        const merged = this.options.merge(page.bars);
        const status = merged.prependedCount === 0 ? "exhausted" : "loaded";
        if (status === "exhausted") this.exhausted = true;
        return { status, prependedCount: merged.prependedCount };
    }
}
