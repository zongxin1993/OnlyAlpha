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
const NANOS = /^(?:0|[1-9][0-9]*)$/;

export class MarketDataBarLedgerConflictError extends Error {
    readonly code = "MARKET_DATA_BAR_LEDGER_CONFLICT";

    constructor(detail: string) {
        super(detail);
        this.name = "MarketDataBarLedgerConflictError";
    }
}

export interface MarketDataBarLedgerSnapshot {
    readonly contextKey: string;
    readonly closedBars: readonly MarketDataBar[];
    readonly preview: MarketDataBar | null;
    readonly earliestStartNs: string | null;
    readonly latestClosedStartNs: string | null;
    readonly version: number;
}

export interface MarketDataBarLedgerMerge {
    readonly changed: boolean;
    readonly prependedCount: number;
    readonly appendedCount: number;
    readonly snapshot: MarketDataBarLedgerSnapshot;
}

const sameBar = (left: MarketDataBar, right: MarketDataBar): boolean =>
    BAR_FIELDS.every((field) => left[field] === right[field]);

const validateBounds = (bar: MarketDataBar): void => {
    if (!NANOS.test(bar.bar_start_ns) || !NANOS.test(bar.bar_end_ns)) {
        throw new MarketDataBarLedgerConflictError("Bar bounds must be canonical nanoseconds");
    }
    if (BigInt(bar.bar_start_ns) >= BigInt(bar.bar_end_ns)) {
        throw new MarketDataBarLedgerConflictError("Bar start must be before Bar end");
    }
};

export class OnlyMarketDataBarLedger {
    private closedByStart = new Map<string, MarketDataBar>();
    private closedSnapshot: readonly MarketDataBar[] | null = null;
    private preview: MarketDataBar | null = null;
    private version = 0;

    constructor(readonly contextKey: string) {}

    snapshot(): MarketDataBarLedgerSnapshot {
        const closedBars = (this.closedSnapshot ??= Object.freeze(
            [...this.closedByStart.values()]
                .sort((left, right) =>
                    BigInt(left.bar_start_ns) < BigInt(right.bar_start_ns) ? -1 : 1
                )
                .map((bar) => Object.freeze({ ...bar }))
        ));
        return {
            contextKey: this.contextKey,
            closedBars,
            preview: this.preview === null ? null : { ...this.preview },
            earliestStartNs: closedBars[0]?.bar_start_ns ?? null,
            latestClosedStartNs: closedBars.at(-1)?.bar_start_ns ?? null,
            version: this.version
        };
    }

    mergeHistory(bars: readonly MarketDataBar[], anchorEndNs?: string): MarketDataBarLedgerMerge {
        if (anchorEndNs !== undefined && !NANOS.test(anchorEndNs))
            throw new MarketDataBarLedgerConflictError(
                "Retention anchor must be canonical nanoseconds"
            );
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

        if (next.size > 4000) {
            const anchor =
                anchorEndNs === undefined
                    ? bars.reduce(
                          (latest, bar) =>
                              BigInt(bar.bar_end_ns) > latest ? BigInt(bar.bar_end_ns) : latest,
                          0n
                      )
                    : BigInt(anchorEndNs);
            const distance = (bar: MarketDataBar) => {
                const delta = BigInt(bar.bar_end_ns) - anchor;
                return delta < 0n ? -delta : delta;
            };
            const retained = new Set(
                [...next.values()]
                    .sort((left, right) =>
                        BigInt(left.bar_start_ns) < BigInt(right.bar_start_ns) ? -1 : 1
                    )
                    .slice(-2000)
                    .map((bar) => bar.bar_start_ns)
            );
            // Historical browsing shares this bound with the latest closed
            // calculation prefix. Retaining facts supplies no continuity proof.
            const candidates = [...next.values()].sort((left, right) => {
                const a = distance(left),
                    b = distance(right);
                return a < b
                    ? -1
                    : a > b
                      ? 1
                      : BigInt(left.bar_start_ns) < BigInt(right.bar_start_ns)
                        ? -1
                        : 1;
            });
            for (const bar of candidates) {
                if (retained.size === 4000) break;
                retained.add(bar.bar_start_ns);
            }
            for (const key of next.keys()) if (!retained.has(key)) next.delete(key);
            const inserted = [...next.keys()].filter((key) => !this.closedByStart.has(key));
            acceptedCount = inserted.length;
            prependedCount =
                previousEarliest === null
                    ? 0
                    : inserted.filter((key) => BigInt(key) < BigInt(previousEarliest)).length;
        }
        if (acceptedCount > 0 || next.size !== this.closedByStart.size) {
            this.closedByStart = next;
            this.closedSnapshot = null;
            this.version += 1;
        }
        return {
            changed: acceptedCount > 0,
            prependedCount,
            appendedCount: acceptedCount - prependedCount,
            snapshot: this.snapshot()
        };
    }

    applyClosed(bar: MarketDataBar): MarketDataBarLedgerMerge {
        const mutation = this.mergeHistory([bar]);
        const clearsPreview =
            this.preview !== null && BigInt(this.preview.bar_start_ns) <= BigInt(bar.bar_start_ns);
        if (clearsPreview) {
            this.preview = null;
            if (!mutation.changed) this.version += 1;
        }
        return {
            ...mutation,
            changed: mutation.changed || clearsPreview,
            snapshot: this.snapshot()
        };
    }

    applyPreview(bar: MarketDataBar): MarketDataBarLedgerMerge {
        validateBounds(bar);
        if (bar.closed) {
            throw new MarketDataBarLedgerConflictError("Preview Bar must be open");
        }
        const latestClosed = this.latestClosedStart();
        if (
            (latestClosed !== null && BigInt(bar.bar_start_ns) <= BigInt(latestClosed)) ||
            (this.preview !== null &&
                (BigInt(bar.bar_start_ns) < BigInt(this.preview.bar_start_ns) ||
                    sameBar(this.preview, bar)))
        ) {
            return {
                changed: false,
                prependedCount: 0,
                appendedCount: 0,
                snapshot: this.snapshot()
            };
        }
        this.preview = { ...bar };
        this.version += 1;
        return {
            changed: true,
            prependedCount: 0,
            appendedCount: 0,
            snapshot: this.snapshot()
        };
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
