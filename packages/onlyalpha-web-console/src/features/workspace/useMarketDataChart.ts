import { useCallback, useEffect, useMemo, useState } from "react";
import type { CandlestickData, UTCTimestamp } from "lightweight-charts";
import { MarketDataWebError, type MarketDataApiClient } from "../../api/marketData/client";
import type {
    MarketDataCoverage,
    MarketDataInstrument,
    MarketDataSource,
    MarketDataSourceReference
} from "../../api/marketData/model";
import { useMarketDataApi } from "../../app/providers";

export const DEFAULT_WINDOW_SECONDS = 86_400;
const SECOND_NS = 1_000_000_000n;

export type MarketDataChartStatus =
    | "no-source"
    | "idle"
    | "searching"
    | "loading"
    | "acquiring"
    | "ready"
    | "incomplete"
    | "failed";

export interface MarketDataChartState {
    readonly selectableSources: readonly MarketDataSource[];
    /** Non-null exactly when a real Market Data source context is selected. */
    readonly reference: MarketDataSourceReference | null;
    /** Canonical Market Source identity reported by the Product API, never client-declared. */
    readonly resolvedSourceId: string | null;
    readonly sourceId: string;
    readonly instruments: readonly MarketDataInstrument[];
    readonly instrument: MarketDataInstrument | null;
    readonly status: MarketDataChartStatus;
    readonly message: string | null;
    readonly coverage: MarketDataCoverage | null;
    readonly bars: readonly CandlestickData<UTCTimestamp>[];
    readonly revisionFingerprint: string | null;
    readonly selectSource: (integrationId: string) => void;
    readonly searchInstruments: (query: string) => Promise<void>;
    readonly selectInstrument: (instrument: MarketDataInstrument) => Promise<void>;
}

/** The chart context is presentation state; every fact below comes from the Product API. */
export function onlyMarketDataSourceReference(source: MarketDataSource): MarketDataSourceReference {
    return {
        integration_id: source.integration_id,
        integration_revision_fingerprint: source.integration_revision_fingerprint,
        expected_type_id: source.type_id
    };
}

export function onlyRecentClosedMinuteRange(
    now = Date.now(),
    windowSeconds = DEFAULT_WINDOW_SECONDS
): { startNs: string; endNs: string } {
    // Exact nanoseconds stay decimal strings end to end; only the chart uses seconds.
    const endNs = BigInt(Math.floor(now / 60_000)) * 60n * SECOND_NS;
    return {
        startNs: (endNs - BigInt(windowSeconds) * SECOND_NS).toString(10),
        endNs: endNs.toString(10)
    };
}

export function onlyBarsToCandles(
    bars: readonly {
        readonly bar_start_ns: string;
        readonly open: string;
        readonly high: string;
        readonly low: string;
        readonly close: string;
    }[]
): CandlestickData<UTCTimestamp>[] {
    return bars.map((bar) => ({
        time: Number(BigInt(bar.bar_start_ns) / SECOND_NS) as UTCTimestamp,
        open: Number(bar.open),
        high: Number(bar.high),
        low: Number(bar.low),
        close: Number(bar.close)
    }));
}

export function useMarketDataChart(): MarketDataChartState {
    const client = useMarketDataApi();
    const [sources, setSources] = useState<readonly MarketDataSource[]>([]);
    const [sourceId, setSourceId] = useState("");
    const [instruments, setInstruments] = useState<readonly MarketDataInstrument[]>([]);
    const [instrument, setInstrument] = useState<MarketDataInstrument | null>(null);
    const [status, setStatus] = useState<MarketDataChartStatus>("idle");
    const [message, setMessage] = useState<string | null>(null);
    const [coverage, setCoverage] = useState<MarketDataCoverage | null>(null);
    const [bars, setBars] = useState<readonly CandlestickData<UTCTimestamp>[]>([]);
    const [revisionFingerprint, setRevisionFingerprint] = useState<string | null>(null);
    const [resolvedSourceId, setResolvedSourceId] = useState<string | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        client
            .listSources(controller.signal)
            .then((found) => {
                setSources(found);
            })
            .catch(() => {
                setSources([]);
            });
        return () => {
            controller.abort();
        };
    }, [client]);

    const selectableSources = sources;
    const selectedSource = useMemo(
        () => selectableSources.find((item) => item.integration_id === sourceId) ?? null,
        [selectableSources, sourceId]
    );
    const reference = useMemo(
        () => (selectedSource === null ? null : onlyMarketDataSourceReference(selectedSource)),
        [selectedSource]
    );

    const apply = useCallback((error: unknown) => {
        const webError = error instanceof MarketDataWebError ? error : null;
        setBars([]);
        setRevisionFingerprint(null);
        setStatus("failed");
        setMessage(
            webError === null
                ? "行情请求失败"
                : `行情请求失败：${webError.code} ${webError.message}`.trim()
        );
    }, []);

    const acquire = useCallback(
        async (
            active: MarketDataSourceReference,
            query: {
                instrument_id: string;
                start_ns: string;
                end_ns: string;
                bar_specification: string;
            },
            pending: MarketDataCoverage
        ) => {
            setStatus("acquiring");
            setMessage(
                pending.status === "UNPROVABLE"
                    ? "该数据源暂不能证明覆盖率，正在同步历史行情…"
                    : `正在同步历史行情…（缺口 ${String(pending.gaps.length)} 分钟）`
            );
            try {
                const acquisition = await client.createAcquisition(active, query);
                if (acquisition.status !== "COMPLETE") {
                    setCoverage(acquisition.coverage);
                    setStatus("failed");
                    setMessage(
                        `历史行情同步${acquisition.status === "FAILED" ? "失败" : "未完成"}：${
                            acquisition.failure_detail ?? acquisition.status
                        }`
                    );
                    return;
                }
                const reloaded = await client.queryBars(active, query);
                setCoverage(reloaded.coverage);
                setResolvedSourceId(reloaded.source_selection.source_id);
                setBars(
                    reloaded.coverage.status === "COMPLETE" ? onlyBarsToCandles(reloaded.bars) : []
                );
                setRevisionFingerprint(reloaded.revision_fingerprint);
                setStatus(reloaded.coverage.status === "COMPLETE" ? "ready" : "incomplete");
                setMessage(
                    reloaded.coverage.status === "COMPLETE"
                        ? null
                        : `历史行情仍不完整：${reloaded.coverage.issues.join(", ") || reloaded.coverage.status}`
                );
            } catch (error) {
                apply(error);
            }
        },
        [apply, client]
    );

    const load = useCallback(
        async (active: MarketDataSourceReference, target: MarketDataInstrument) => {
            const range = onlyRecentClosedMinuteRange();
            const query = {
                instrument_id: target.instrument_id,
                start_ns: range.startNs,
                end_ns: range.endNs,
                bar_specification: "1m"
            };
            setStatus("loading");
            setMessage(null);
            try {
                const loaded = await client.queryBars(active, query);
                setCoverage(loaded.coverage);
                setResolvedSourceId(loaded.source_selection.source_id);
                if (loaded.coverage.status === "COMPLETE") {
                    setBars(onlyBarsToCandles(loaded.bars));
                    setRevisionFingerprint(loaded.revision_fingerprint);
                    setStatus("ready");
                    return;
                }
                setBars([]);
                setRevisionFingerprint(null);
                await acquire(active, query, loaded.coverage);
            } catch (error) {
                apply(error);
            }
        },
        [acquire, apply, client]
    );

    const selectSource = useCallback((integrationId: string) => {
        setSourceId(integrationId);
        setInstruments([]);
        setInstrument(null);
        setCoverage(null);
        setBars([]);
        setRevisionFingerprint(null);
        setResolvedSourceId(null);
        setStatus("idle");
        setMessage(null);
    }, []);

    const searchInstruments = useCallback(
        async (query: string) => {
            if (reference === null) {
                setInstruments([]);
                return;
            }
            setStatus("searching");
            try {
                const found = await client.listInstruments(reference, query);
                setInstruments(found);
                setStatus("idle");
                setMessage(found.length === 0 ? "未找到匹配标的" : null);
            } catch (error) {
                apply(error);
            }
        },
        [apply, client, reference]
    );

    const selectInstrument = useCallback(
        async (target: MarketDataInstrument) => {
            setInstrument(target);
            if (reference === null) {
                setMessage("请先选择数据源");
                return;
            }
            await load(reference, target);
        },
        [load, reference]
    );

    return {
        selectableSources,
        reference,
        resolvedSourceId,
        sourceId,
        instruments,
        instrument,
        status,
        message,
        coverage,
        bars,
        revisionFingerprint,
        selectSource,
        searchInstruments,
        selectInstrument
    };
}

export type { MarketDataApiClient };
