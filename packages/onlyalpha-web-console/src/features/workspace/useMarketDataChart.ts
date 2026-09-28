import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CandlestickData, UTCTimestamp } from "lightweight-charts";
import { MarketDataWebError, type MarketDataApiClient } from "../../api/marketData/client";
import { openMarketDataStream } from "../../api/marketData/stream";
import type {
    MarketDataBarSpecification,
    MarketDataCoverage,
    MarketDataInstrument,
    MarketDataSource,
    MarketDataSourceReference
} from "../../api/marketData/model";
import { marketDataBarSpecification } from "../../api/marketData/model";
import { useMarketDataApi } from "../../app/providers";

export const DEFAULT_WINDOW_SECONDS = 86_400;
const SECOND_NS = 1_000_000_000n;
export const STREAM_RECONNECT_DELAYS_MS = [250, 500, 1000, 2000, 4000] as const;

export type MarketDataChartStatus =
    | "no-source"
    | "idle"
    | "searching"
    | "loading"
    | "acquiring"
    | "ready"
    | "incomplete"
    | "failed";

export type MarketDataRealtimeStatus =
    "disabled" | "connecting" | "recovering" | "ready" | "degraded" | "failed";

export interface MarketDataChartState {
    readonly selectableSources: readonly MarketDataSource[];
    /** Non-null exactly when a real Market Data source context is selected. */
    readonly reference: MarketDataSourceReference | null;
    /** Canonical Market Source identity reported by the Product API, never client-declared. */
    readonly resolvedSourceId: string | null;
    readonly sourceId: string;
    readonly instruments: readonly MarketDataInstrument[];
    readonly instrument: MarketDataInstrument | null;
    readonly barSpecification: MarketDataBarSpecification;
    readonly barCapability: MarketDataSource["time_bar_capability"] | null;
    readonly status: MarketDataChartStatus;
    readonly message: string | null;
    readonly coverage: MarketDataCoverage | null;
    readonly bars: readonly CandlestickData<UTCTimestamp>[];
    readonly revisionFingerprint: string | null;
    readonly realtimeStatus: MarketDataRealtimeStatus;
    readonly liveBar: CandlestickData<UTCTimestamp> | null;
    readonly lastClosedStreamBar: CandlestickData<UTCTimestamp> | null;
    readonly streamId: string | null;
    readonly streamError: string | null;
    readonly lastClosedCursor: string | null;
    readonly selectSource: (integrationId: string) => void;
    readonly searchInstruments: (query: string) => Promise<void>;
    readonly selectInstrument: (instrument: MarketDataInstrument) => Promise<void>;
    readonly selectBarStep: (step: number) => Promise<void>;
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
    windowSeconds = DEFAULT_WINDOW_SECONDS,
    stepMinutes = 1
): { startNs: string; endNs: string } {
    // The UTC 24/7 Product grid requires complete target bars; cursor authority remains server-side.
    const dayMs = 86_400_000;
    const stepMs = stepMinutes * 60_000;
    let dayStart = Math.floor(now / dayMs) * dayMs;
    let end = dayStart + Math.floor((now - dayStart) / stepMs) * stepMs;
    if (end === dayStart && dayMs % stepMs !== 0) {
        dayStart -= dayMs;
        end = dayStart + Math.floor(dayMs / stepMs) * stepMs;
    }
    const start =
        dayMs % stepMs === 0
            ? end - Math.floor((windowSeconds * 1000) / stepMs) * stepMs
            : dayStart;
    return {
        startNs: (BigInt(start) * 1_000_000n).toString(10),
        endNs: (BigInt(end) * 1_000_000n).toString(10)
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
    return bars.map(onlyBarToCandle);
}

const onlyBarToCandle = (bar: {
    readonly bar_start_ns: string;
    readonly open: string;
    readonly high: string;
    readonly low: string;
    readonly close: string;
}): CandlestickData<UTCTimestamp> => ({
    time: Number(BigInt(bar.bar_start_ns) / SECOND_NS) as UTCTimestamp,
    open: Number(bar.open),
    high: Number(bar.high),
    low: Number(bar.low),
    close: Number(bar.close)
});

export function useMarketDataChart(): MarketDataChartState {
    const client = useMarketDataApi();
    const [sources, setSources] = useState<readonly MarketDataSource[]>([]);
    const [sourceId, setSourceId] = useState("");
    const [instruments, setInstruments] = useState<readonly MarketDataInstrument[]>([]);
    const [instrument, setInstrument] = useState<MarketDataInstrument | null>(null);
    const [barSpecification, setBarSpecification] = useState(marketDataBarSpecification(1));
    const [status, setStatus] = useState<MarketDataChartStatus>("idle");
    const [message, setMessage] = useState<string | null>(null);
    const [coverage, setCoverage] = useState<MarketDataCoverage | null>(null);
    const [bars, setBars] = useState<readonly CandlestickData<UTCTimestamp>[]>([]);
    const [revisionFingerprint, setRevisionFingerprint] = useState<string | null>(null);
    const [resolvedSourceId, setResolvedSourceId] = useState<string | null>(null);
    const [realtimeStatus, setRealtimeStatus] = useState<MarketDataRealtimeStatus>("disabled");
    const [liveBar, setLiveBar] = useState<CandlestickData<UTCTimestamp> | null>(null);
    const [lastClosedStreamBar, setLastClosedStreamBar] =
        useState<CandlestickData<UTCTimestamp> | null>(null);
    const [streamId, setStreamId] = useState<string | null>(null);
    const [streamError, setStreamError] = useState<string | null>(null);
    const [lastClosedCursor, setLastClosedCursor] = useState<string | null>(null);
    const lastLiveStartRef = useRef<bigint | null>(null);
    const lastClosedStartRef = useRef<bigint | null>(null);
    const streamGeneration = useRef(0);
    const historyGeneration = useRef(0);
    const resume = useRef<{ cursor: string; fingerprint: string } | null>(null);
    const previousRevision = useRef<string | null>(null);

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
    const barCapability = selectedSource?.time_bar_capability ?? null;

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
                bar_specification: MarketDataBarSpecification;
            },
            generation: number
        ) => {
            setStatus("acquiring");
            setMessage("正在同步历史行情…");
            try {
                const acquisition = await client.createAcquisition(active, query);
                if (generation !== historyGeneration.current) return;
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
                if (generation !== historyGeneration.current) return;
                setCoverage(reloaded.coverage);
                setResolvedSourceId(reloaded.source_selection.source_id);
                setBars(
                    reloaded.coverage.status === "COMPLETE" ? onlyBarsToCandles(reloaded.bars) : []
                );
                setRevisionFingerprint(reloaded.revision_fingerprint);
                resume.current =
                    reloaded.resume_after_sequence !== null &&
                    reloaded.resume_plan_fingerprint !== null
                        ? {
                              cursor: reloaded.resume_after_sequence,
                              fingerprint: reloaded.resume_plan_fingerprint
                          }
                        : null;
                setStatus(reloaded.coverage.status === "COMPLETE" ? "ready" : "incomplete");
                setMessage(
                    reloaded.coverage.status === "COMPLETE"
                        ? null
                        : `历史行情仍不完整：${reloaded.coverage.issues.join(", ") || reloaded.coverage.status}`
                );
            } catch (error) {
                if (generation === historyGeneration.current) apply(error);
            }
        },
        [apply, client]
    );

    const load = useCallback(
        async (
            active: MarketDataSourceReference,
            target: MarketDataInstrument,
            specification: MarketDataBarSpecification,
            generation: number
        ) => {
            const range = onlyRecentClosedMinuteRange(
                Date.now(),
                DEFAULT_WINDOW_SECONDS,
                specification.step
            );
            const query = {
                instrument_id: target.instrument_id,
                start_ns: range.startNs,
                end_ns: range.endNs,
                bar_specification: specification
            };
            resume.current = null;
            setStatus("loading");
            setRealtimeStatus("disabled");
            setMessage(null);
            try {
                const loaded = await client.queryBars(active, query);
                if (generation !== historyGeneration.current) return;
                setCoverage(loaded.coverage);
                setResolvedSourceId(loaded.source_selection.source_id);
                if (loaded.coverage.status === "COMPLETE") {
                    resume.current =
                        loaded.resume_after_sequence !== null &&
                        loaded.resume_plan_fingerprint !== null
                            ? {
                                  cursor: loaded.resume_after_sequence,
                                  fingerprint: loaded.resume_plan_fingerprint
                              }
                            : null;
                    setBars(onlyBarsToCandles(loaded.bars));
                    setRevisionFingerprint(loaded.revision_fingerprint);
                    setStatus("ready");
                    return;
                }
                setBars([]);
                setRevisionFingerprint(null);
                await acquire(active, query, generation);
            } catch (error) {
                if (generation === historyGeneration.current) apply(error);
            }
        },
        [acquire, apply, client]
    );

    useEffect(() => {
        const revision = reference?.integration_revision_fingerprint ?? null;
        if (previousRevision.current !== null && revision !== previousRevision.current) {
            streamGeneration.current += 1;
            const generation = ++historyGeneration.current;
            resume.current = null;
            setLastClosedCursor(null);
            setStreamId(null);
            setLiveBar(null);
            setLastClosedStreamBar(null);
            lastLiveStartRef.current = null;
            lastClosedStartRef.current = null;
            if (reference !== null && instrument !== null)
                void load(reference, instrument, barSpecification, generation);
        }
        previousRevision.current = revision;
    }, [reference, instrument, barSpecification, load]);

    useEffect(() => {
        if (
            status !== "ready" ||
            reference === null ||
            instrument === null ||
            resolvedSourceId === null ||
            bars.length === 0 ||
            resume.current === null
        ) {
            return;
        }
        const generation = ++streamGeneration.current;
        let close: () => void = () => undefined;
        let reconnect: number | undefined;
        let stopped = false;
        let terminal = false;
        let reconnectAttempt = 0;
        const connect = () => {
            if (stopped || resume.current === null) return;
            setRealtimeStatus("connecting");
            close = openMarketDataStream(
                {
                    schema_version: 2,
                    operation: "SUBSCRIBE_BAR",
                    source_reference: {
                        ...reference,
                        expected_type_id: reference.expected_type_id ?? ""
                    },
                    instrument_id: instrument.instrument_id,
                    bar_specification: barSpecification,
                    resume_after_sequence: resume.current.cursor,
                    resume_plan_fingerprint: resume.current.fingerprint
                },
                (event) => {
                    if (generation !== streamGeneration.current || terminal) return;
                    if (
                        (event.event === "SUBSCRIBED" ||
                            event.event === "BAR_PREVIEW" ||
                            event.event === "BAR_CLOSED") &&
                        (event.source_id !== resolvedSourceId ||
                            event.instrument_id !== instrument.instrument_id ||
                            (event.event !== "SUBSCRIBED" &&
                                event.bar_specification.step !== barSpecification.step))
                    ) {
                        terminal = true;
                        setStreamError("MARKET_DATA_BAR_SPECIFICATION_MISMATCH");
                        setRealtimeStatus("failed");
                        close();
                        return;
                    }
                    if (event.event === "SUBSCRIBED") {
                        if (event.resolution_plan_fingerprint !== resume.current?.fingerprint) {
                            terminal = true;
                            resume.current = null;
                            setLastClosedCursor(null);
                            setStreamId(null);
                            setLiveBar(null);
                            setLastClosedStreamBar(null);
                            lastLiveStartRef.current = null;
                            lastClosedStartRef.current = null;
                            setStreamError("MARKET_DATA_RESUME_PLAN_MISMATCH");
                            setRealtimeStatus("failed");
                            close();
                            return;
                        }
                        setStreamId(event.stream_id);
                    } else if (event.event === "STATE") {
                        setRealtimeStatus(
                            event.state === "CONNECTING"
                                ? "connecting"
                                : event.state === "RECOVERING"
                                  ? "recovering"
                                  : event.state === "READY"
                                    ? "ready"
                                    : event.state === "DEGRADED" || event.state === "CLOSED"
                                      ? "degraded"
                                      : "failed"
                        );
                    } else if (event.event === "BASE_CURSOR") {
                        const cursor = resume.current?.cursor ?? null;
                        if (cursor === null || BigInt(event.sequence) > BigInt(cursor)) {
                            setLastClosedCursor(event.sequence);
                            if (resume.current !== null)
                                resume.current = { ...resume.current, cursor: event.sequence };
                        }
                    } else if (event.event === "BAR_PREVIEW") {
                        const start = BigInt(event.bar.bar_start_ns);
                        if (
                            (lastLiveStartRef.current === null ||
                                start >= lastLiveStartRef.current) &&
                            (lastClosedStartRef.current === null ||
                                start > lastClosedStartRef.current)
                        ) {
                            lastLiveStartRef.current = start;
                            setLiveBar(onlyBarToCandle(event.bar));
                        }
                    } else if (event.event === "BAR_CLOSED") {
                        const start = BigInt(event.bar.bar_start_ns);
                        if (
                            lastClosedStartRef.current !== null &&
                            start <= lastClosedStartRef.current
                        )
                            return;
                        const candle = onlyBarToCandle(event.bar);
                        lastClosedStartRef.current = start;
                        if (
                            lastLiveStartRef.current === null ||
                            start >= lastLiveStartRef.current
                        ) {
                            lastLiveStartRef.current = start;
                            setLiveBar(candle);
                        }
                        setLastClosedStreamBar(candle);
                        const cursor = resume.current?.cursor ?? null;
                        if (cursor === null || BigInt(event.sequence) > BigInt(cursor)) {
                            setLastClosedCursor(event.sequence);
                            if (resume.current !== null)
                                resume.current = { ...resume.current, cursor: event.sequence };
                        }
                    } else {
                        terminal = true;
                        setStreamError(
                            `${event.code}${event.detail == null ? "" : `: ${event.detail}`}`
                        );
                        if (
                            event.code === "HISTORY_REFRESH_REQUIRED" ||
                            event.code === "MARKET_DATA_RESUME_PLAN_MISMATCH"
                        ) {
                            resume.current = null;
                            setLastClosedCursor(null);
                            setStreamId(null);
                            setLiveBar(null);
                            setLastClosedStreamBar(null);
                            lastLiveStartRef.current = null;
                            lastClosedStartRef.current = null;
                            void load(
                                reference,
                                instrument,
                                barSpecification,
                                ++historyGeneration.current
                            );
                        } else setRealtimeStatus("failed");
                    }
                },
                (failure) => {
                    if (generation !== streamGeneration.current || stopped || terminal) return;
                    if (failure !== undefined) {
                        terminal = true;
                        setStreamError(failure);
                        setRealtimeStatus("failed");
                        return;
                    }
                    setRealtimeStatus("degraded");
                    reconnect = window.setTimeout(
                        connect,
                        STREAM_RECONNECT_DELAYS_MS[
                            Math.min(reconnectAttempt++, STREAM_RECONNECT_DELAYS_MS.length - 1)
                        ]
                    );
                }
            );
        };
        queueMicrotask(() => {
            if (stopped) return;
            setLiveBar(null);
            setLastClosedStreamBar(null);
            setStreamId(null);
            setStreamError(null);
            connect();
        });
        return () => {
            stopped = true;
            streamGeneration.current += 1;
            if (reconnect !== undefined) window.clearTimeout(reconnect);
            close();
        };
    }, [barSpecification, bars, instrument, load, reference, resolvedSourceId, status]);

    const selectSource = useCallback((integrationId: string) => {
        streamGeneration.current += 1;
        historyGeneration.current += 1;
        setSourceId(integrationId);
        setBarSpecification(marketDataBarSpecification(1));
        setInstruments([]);
        setInstrument(null);
        setCoverage(null);
        setBars([]);
        setRevisionFingerprint(null);
        setResolvedSourceId(null);
        setLiveBar(null);
        setLastClosedStreamBar(null);
        setLastClosedCursor(null);
        resume.current = null;
        lastLiveStartRef.current = null;
        lastClosedStartRef.current = null;
        setStreamId(null);
        setStreamError(null);
        setRealtimeStatus("disabled");
        setStatus("idle");
        setMessage(null);
    }, []);

    const searchInstruments = useCallback(
        async (query: string) => {
            if (reference === null) {
                setInstruments([]);
                return;
            }
            const generation = historyGeneration.current;
            setStatus("searching");
            try {
                const found = await client.listInstruments(reference, query);
                if (generation !== historyGeneration.current) return;
                setInstruments(found);
                setStatus("idle");
                setMessage(found.length === 0 ? "未找到匹配标的" : null);
            } catch (error) {
                if (generation === historyGeneration.current) apply(error);
            }
        },
        [apply, client, reference]
    );

    const selectInstrument = useCallback(
        async (target: MarketDataInstrument) => {
            streamGeneration.current += 1;
            const generation = ++historyGeneration.current;
            setLiveBar(null);
            setLastClosedStreamBar(null);
            setLastClosedCursor(null);
            resume.current = null;
            lastLiveStartRef.current = null;
            lastClosedStartRef.current = null;
            setStreamId(null);
            setStreamError(null);
            setRealtimeStatus("disabled");
            setInstrument(target);
            if (reference === null) {
                setMessage("请先选择数据源");
                return;
            }
            await load(reference, target, barSpecification, generation);
        },
        [barSpecification, load, reference]
    );

    const selectBarStep = useCallback(
        async (step: number) => {
            if (
                barCapability === null ||
                step < barCapability.minimum_step_minutes ||
                step > barCapability.maximum_step_minutes
            )
                return;
            const specification = marketDataBarSpecification(step);
            streamGeneration.current += 1;
            const generation = ++historyGeneration.current;
            resume.current = null;
            lastLiveStartRef.current = null;
            lastClosedStartRef.current = null;
            setLastClosedCursor(null);
            setLiveBar(null);
            setLastClosedStreamBar(null);
            setStreamId(null);
            setStreamError(null);
            setRealtimeStatus("disabled");
            setBars([]);
            setBarSpecification(specification);
            if (reference !== null && instrument !== null)
                await load(reference, instrument, specification, generation);
        },
        [barCapability, instrument, load, reference]
    );

    return {
        selectableSources,
        reference,
        resolvedSourceId,
        sourceId,
        instruments,
        instrument,
        barSpecification,
        barCapability,
        status,
        message,
        coverage,
        bars,
        revisionFingerprint,
        realtimeStatus,
        liveBar,
        lastClosedStreamBar,
        streamId,
        streamError,
        lastClosedCursor,
        selectSource,
        searchInstruments,
        selectInstrument,
        selectBarStep
    };
}

export type { MarketDataApiClient };
