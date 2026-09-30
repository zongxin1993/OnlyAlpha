import type { MarketDataBar } from "../../api/marketData/model";

const BAR_FIELDS = [
    "bar_start_ns",
    "bar_end_ns",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "closed"
] as const;

export class MarketDataBarLedgerConflictError extends Error {
    readonly code = "MARKET_DATA_BAR_LEDGER_CONFLICT";

    constructor(detail: string) {
        super(detail);
        this.name = "MarketDataBarLedgerConflictError";
    }
}

export interface MarketDataBarLedgerSnapshot {
    readonly closedBars: readonly MarketDataBar[];
    readonly previewBar: MarketDataBar | null;
}

export interface MarketDataBarLedgerMutation {
    readonly changed: boolean;
    readonly acceptedCount: number;
    readonly prependedCount: number;
}

const sameBar = (left: MarketDataBar, right: MarketDataBar): boolean =>
    BAR_FIELDS.every((field) => left[field] === right[field]);

const validateBounds = (bar: MarketDataBar): void => {
    if (BigInt(bar.bar_start_ns) >= BigInt(bar.bar_end_ns)) {
        throw new MarketDataBarLedgerConflictError("Bar start must be before Bar end");
    }
};

export class MarketDataBarLedger {
    private closedByStart = new Map<string, MarketDataBar>();
    private preview: MarketDataBar | null = null;

    constructor(initialClosedBars: readonly MarketDataBar[] = []) {
        this.mergeHistory(initialClosedBars);
    }

    snapshot(): MarketDataBarLedgerSnapshot {
        return {
            closedBars: [...this.closedByStart.values()]
                .sort((left, right) =>
                    BigInt(left.bar_start_ns) < BigInt(right.bar_start_ns) ? -1 : 1
                )
                .map((bar) => ({ ...bar })),
            previewBar: this.preview === null ? null : { ...this.preview }
        };
    }

    mergeHistory(bars: readonly MarketDataBar[]): MarketDataBarLedgerMutation {
        const next = new Map(this.closedByStart);
        const previousEarliest = this.earliestClosedStart();
        let acceptedCount = 0;
        let prependedCount = 0;

        for (const bar of bars) {
            validateBounds(bar);
            if (!bar.closed) {
                throw new MarketDataBarLedgerConflictError("Historical Bar must be closed");
            }
            const existing = next.get(bar.bar_start_ns);
            if (existing !== undefined) {
                if (!sameBar(existing, bar)) {
                    throw new MarketDataBarLedgerConflictError(
                        `Conflicting Bar at ${bar.bar_start_ns}`
                    );
                }
                continue;
            }
            next.set(bar.bar_start_ns, { ...bar });
            acceptedCount += 1;
            if (previousEarliest !== null && BigInt(bar.bar_start_ns) < BigInt(previousEarliest)) {
                prependedCount += 1;
            }
        }

        if (acceptedCount > 0) this.closedByStart = next;
        return { changed: acceptedCount > 0, acceptedCount, prependedCount };
    }

    applyClosed(bar: MarketDataBar): MarketDataBarLedgerMutation {
        const mutation = this.mergeHistory([bar]);
        const clearsPreview =
            this.preview !== null && BigInt(this.preview.bar_start_ns) <= BigInt(bar.bar_start_ns);
        if (clearsPreview) this.preview = null;
        return { ...mutation, changed: mutation.changed || clearsPreview };
    }

    applyPreview(bar: MarketDataBar): MarketDataBarLedgerMutation {
        validateBounds(bar);
        if (bar.closed) {
            throw new MarketDataBarLedgerConflictError("Preview Bar must be open");
        }
        const latestClosed = this.latestClosedStart();
        if (
            (latestClosed !== null && BigInt(bar.bar_start_ns) <= BigInt(latestClosed)) ||
            (this.preview !== null && BigInt(bar.bar_start_ns) < BigInt(this.preview.bar_start_ns))
        ) {
            return { changed: false, acceptedCount: 0, prependedCount: 0 };
        }
        this.preview = { ...bar };
        return { changed: true, acceptedCount: 1, prependedCount: 0 };
    }

    private earliestClosedStart(): string | null {
        let earliest: string | null = null;
        for (const start of this.closedByStart.keys()) {
            if (earliest === null || BigInt(start) < BigInt(earliest)) earliest = start;
        }
        return earliest;
    }

    private latestClosedStart(): string | null {
        let latest: string | null = null;
        for (const start of this.closedByStart.keys()) {
            if (latest === null || BigInt(start) > BigInt(latest)) latest = start;
        }
        return latest;
    }
}
