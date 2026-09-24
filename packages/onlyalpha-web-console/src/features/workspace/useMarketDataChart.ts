import { useCallback, useMemo, useState } from "react";
import type { CandlestickData, UTCTimestamp } from "lightweight-charts";
import { MarketDataWebError, type MarketDataApiClient } from "../../api/marketData/client";
import type {
    MarketDataCoverage,
    MarketDataInstrument,
    MarketDataSourceSelection
} from "../../api/marketData/model";
import { useMarketDataApi } from "../../app/providers";
import type { IntegrationSummary } from "../../api/integrations/model";

export const DEFAULT_WINDOW_SECONDS = 86_400;
const MINUTE_SECONDS = 60;

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
    readonly selectableSources: readonly IntegrationSummary[];
    readonly selection: MarketDataSourceSelection | null;
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
export function onlyMarketDataSourceSelection(
    source: IntegrationSummary
): MarketDataSourceSelection | null {
    const revision = source.current_revision_fingerprint;
    if (revision === null || revision === undefined) return null;
    return {
        integration_id: source.integration_id,
        integration_revision_fingerprint: revision,
        type_id: source.type_id,
        source_id: source.type_id
    };
}

export function onlyRecentClosedMinuteRange(
    now = Date.now(),
    windowSeconds = DEFAULT_WINDOW_SECONDS
): { startNs: number; endNs: number } {
    const endNs = Math.floor((now / 1000 / MINUTE_SECONDS) * MINUTE_SECONDS) * 1_000_000_000;
    return { startNs: endNs - windowSeconds * 1_000_000_000, endNs };
}

export function onlyBarsToCandles(
    bars: readonly {
        readonly bar_start_ns: number;
        readonly open: string;
        readonly high: string;
        readonly low: string;
        readonly close: string;
    }[]
): CandlestickData<UTCTimestamp>[] {
    return bars.map((bar) => ({
        time: Math.floor(bar.bar_start_ns / 1_000_000_000) as UTCTimestamp,
        open: Number(bar.open),
        high: Number(bar.high),
        low: Number(bar.low),
        close: Number(bar.close)
    }));
}

export function useMarketDataChart(sources: readonly IntegrationSummary[]): MarketDataChartState {
    const client = useMarketDataApi();
    const [sourceId, setSourceId] = useState("");
    const [instruments, setInstruments] = useState<readonly MarketDataInstrument[]>([]);
    const [instrument, setInstrument] = useState<MarketDataInstrument | null>(null);
    const [status, setStatus] = useState<MarketDataChartStatus>("idle");
    const [message, setMessage] = useState<string | null>(null);
    const [coverage, setCoverage] = useState<MarketDataCoverage | null>(null);
    const [bars, setBars] = useState<readonly CandlestickData<UTCTimestamp>[]>([]);
    const [revisionFingerprint, setRevisionFingerprint] = useState<string | null>(null);

    const selectableSources = useMemo(
        () =>
            sources.filter(
                (item) =>
                    item.lifecycle_state === "ACTIVE" && item.current_revision_fingerprint !== null
            ),
        [sources]
    );
    const selection = useMemo(() => {
        const source = selectableSources.find((item) => item.integration_id === sourceId);
        return source === undefined ? null : onlyMarketDataSourceSelection(source);
    }, [selectableSources, sourceId]);

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
            active: MarketDataSourceSelection,
            query: {
                instrument_id: string;
                start_ns: number;
                end_ns: number;
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
        async (active: MarketDataSourceSelection, target: MarketDataInstrument) => {
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
        setStatus("idle");
        setMessage(null);
    }, []);

    const searchInstruments = useCallback(
        async (query: string) => {
            if (selection === null) {
                setInstruments([]);
                return;
            }
            setStatus("searching");
            try {
                const found = await client.listInstruments(selection, query);
                setInstruments(found);
                setStatus("idle");
                setMessage(found.length === 0 ? "未找到匹配标的" : null);
            } catch (error) {
                apply(error);
            }
        },
        [apply, client, selection]
    );

    const selectInstrument = useCallback(
        async (target: MarketDataInstrument) => {
            setInstrument(target);
            if (selection === null) {
                setMessage("请先选择数据源");
                return;
            }
            await load(selection, target);
        },
        [load, selection]
    );

    return {
        selectableSources,
        selection,
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
