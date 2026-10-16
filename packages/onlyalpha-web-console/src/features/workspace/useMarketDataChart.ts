import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
    admitMarketDataChartBars,
    projectMarketDataBar,
    MarketDataChartProjectionError,
    type MarketDataChartBarProjection
} from "../../charts/lightweight/marketDataChartProjection";
import {
    MarketDataWebError,
    type MarketDataApiClient,
    type MarketDataBarsQuery
} from "../../api/marketData/client";
import { nextMarketDataTiming, type MarketDataTiming } from "./marketDataTiming";
import type { MarketDataStreamEvent } from "../../api/marketData/stream";
import { openMarketDataStream } from "../../api/marketData/stream";
import type {
    MarketDataBarSemantic,
    MarketDataBars,
    MarketDataCoverage,
    MarketDataInstrument,
    MarketDataSource,
    MarketDataSourceReference
} from "../../api/marketData/model";
import { marketDataBarSemantic } from "../../api/marketData/model";
import { useMarketDataApi, useLocalReadCredentials } from "../../app/providers";
import {
    MarketDataBarLedgerConflictError,
    OnlyMarketDataBarLedger,
    type MarketDataBarLedgerSnapshot
} from "./marketDataBarLedger";
import {
    OnlyMarketDataHistoryLoader,
    onlyMarketDataChartContextKey
} from "./marketDataHistoryLoader";
import {
    MarketDataBarsAuthorityMismatchError,
    onlyAssertMarketDataBarsAuthority
} from "./marketDataBarsAuthority";

export const DEFAULT_TARGET_BAR_COUNT = 1_440;
/** Presentation preference only; mutable source/Revision identities come from the server. */
const DEFAULT_SOURCE_TYPE = "binance.spot.market_data";
const DEFAULT_SOURCE_ENVIRONMENT = "GLOBAL";
const DEFAULT_INSTRUMENT_ID = "BTCUSDT.BINANCE";
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
    readonly barSemantic: MarketDataBarSemantic;
    readonly barCapability: MarketDataSource["time_bar_capability"] | null;
    readonly status: MarketDataChartStatus;
    readonly message: string | null;
    readonly coverage: MarketDataCoverage | null;
    readonly chartContextKey: string | null;
    readonly bars: readonly MarketDataChartBarProjection[];
    readonly loadedClosedBarCount: number;
    readonly historyProjectionFingerprint: string | null;
    readonly realtimeStatus: MarketDataRealtimeStatus;
    readonly liveBar: MarketDataChartBarProjection | null;
    readonly olderHistoryStatus: "idle" | "loading" | "acquiring" | "failed" | "exhausted";
    readonly olderHistoryMessage: string | null;
    readonly streamId: string | null;
    readonly timing: MarketDataTiming | null;
    readonly streamError: string | null;
    readonly lastClosedCursor: string | null;
    readonly selectSource: (integrationId: string) => void;
    readonly refreshSources: () => void;
    readonly searchInstruments: (query: string) => Promise<void>;
    readonly selectInstrument: (instrument: MarketDataInstrument) => Promise<void>;
    readonly selectWatchlistInstrument: (
        source: MarketDataSourceReference,
        instrumentId: string,
        prepare?: boolean
    ) => Promise<void>;
    readonly selectBarDuration: (durationMinutes: number) => Promise<void>;
    readonly loadOlderHistory: () => Promise<void>;
}

/** The chart context is presentation state; every fact below comes from the Product API. */
export function onlyMarketDataSourceReference(source: MarketDataSource): MarketDataSourceReference {
    return {
        integration_id: source.integration_id,
        integration_revision_fingerprint: source.integration_revision_fingerprint,
        expected_type_id: source.type_id
    };
}

export function useMarketDataChart(): MarketDataChartState {
    const client = useMarketDataApi();
    const credentials = useLocalReadCredentials();
    const [sources, setSources] = useState<readonly MarketDataSource[]>([]);
    const [sourceRefresh, setSourceRefresh] = useState(0);
    const refreshSources = useCallback(() => {
        setSourceRefresh((current) => current + 1);
    }, []);
    const [sourceId, setSourceId] = useState("");
    const selectedSourceId = useRef("");
    const [watchlistSource, setWatchlistSource] = useState<MarketDataSourceReference | null>(null);
    const watchlistSourceRef = useRef<MarketDataSourceReference | null>(null);
    const [instruments, setInstruments] = useState<readonly MarketDataInstrument[]>([]);
    const [instrument, setInstrument] = useState<MarketDataInstrument | null>(null);
    const [barSemantic, setBarSemantic] = useState(marketDataBarSemantic(15));
    const [status, setStatus] = useState<MarketDataChartStatus>("loading");
    const [message, setMessage] = useState<string | null>(null);
    const [coverage, setCoverage] = useState<MarketDataCoverage | null>(null);
    const [ledgerSnapshot, setLedgerSnapshot] = useState<MarketDataBarLedgerSnapshot | null>(null);
    const [historyProjectionFingerprint, setHistoryProjectionFingerprint] = useState<string | null>(
        null
    );
    const [resolvedSourceId, setResolvedSourceId] = useState<string | null>(null);
    const [realtimeStatus, setRealtimeStatus] = useState<MarketDataRealtimeStatus>("disabled");
    const [olderHistoryStatus, setOlderHistoryStatus] = useState<
        "idle" | "loading" | "acquiring" | "failed" | "exhausted"
    >("idle");
    const [olderHistoryMessage, setOlderHistoryMessage] = useState<string | null>(null);
    const [timing, setTiming] = useState<MarketDataTiming | null>(null);
    const [streamId, setStreamId] = useState<string | null>(null);
    const [streamError, setStreamError] = useState<string | null>(null);
    const [lastClosedCursor, setLastClosedCursor] = useState<string | null>(null);
    const ledger = useRef<OnlyMarketDataBarLedger | null>(null);
    const olderHistoryLoader = useRef<OnlyMarketDataHistoryLoader | null>(null);
    const streamGeneration = useRef(0);
    const historyGeneration = useRef(0);
    const searchGeneration = useRef(0);
    const resume = useRef<{ cursor: string; fingerprint: string } | null>(null);
    const previousRevision = useRef<string | null>(null);

    const chartContextKey = ledgerSnapshot?.contextKey ?? null;
    const bars = useMemo(
        () => (ledgerSnapshot?.closedBars ?? []).map(projectMarketDataBar),
        [ledgerSnapshot]
    );
    const liveBar = useMemo(
        () =>
            ledgerSnapshot?.preview === null || ledgerSnapshot === null
                ? null
                : projectMarketDataBar(ledgerSnapshot.preview),
        [ledgerSnapshot]
    );

    const selectableSources = sources;
    const selectedSource = useMemo(
        () =>
            selectableSources.find(
                (item) =>
                    item.integration_id === sourceId &&
                    (watchlistSource === null ||
                        (item.integration_revision_fingerprint ===
                            watchlistSource.integration_revision_fingerprint &&
                            item.type_id === watchlistSource.expected_type_id))
            ) ?? null,
        [selectableSources, sourceId, watchlistSource]
    );
    const reference = useMemo(
        () => (selectedSource === null ? null : onlyMarketDataSourceReference(selectedSource)),
        [selectedSource]
    );
    const barCapability = selectedSource?.time_bar_capability ?? null;

    const apply = useCallback((error: unknown) => {
        const webError =
            error instanceof MarketDataWebError ||
            error instanceof MarketDataBarsAuthorityMismatchError ||
            error instanceof MarketDataChartProjectionError
                ? error
                : null;
        ledger.current = null;
        olderHistoryLoader.current = null;
        setLedgerSnapshot(null);
        setHistoryProjectionFingerprint(null);
        setStatus("failed");
        setMessage(
            webError === null
                ? "行情请求失败"
                : `行情请求失败：${webError.code} ${webError.message}`.trim()
        );
    }, []);

    const failLedger = useCallback((error: MarketDataBarLedgerConflictError) => {
        historyGeneration.current += 1;
        streamGeneration.current += 1;
        olderHistoryLoader.current = null;
        // A retained equal fingerprint is not proof after contradictory facts.
        setHistoryProjectionFingerprint(null);
        setLedgerSnapshot((current) =>
            current === null ? null : { ...current, preview: null, version: current.version + 1 }
        );
        setStatus("failed");
        setMessage(`${error.code}: ${error.message}`);
        setRealtimeStatus("failed");
        setOlderHistoryStatus("failed");
        setOlderHistoryMessage(error.code);
    }, []);

    const automaticPreparation = useRef(true);

    const publishCompleteHistory = useCallback(
        (
            active: MarketDataSourceReference,
            expectedSourceId: string,
            generation: number,
            activeLedger: OnlyMarketDataBarLedger,
            loaded: MarketDataBars
        ) => {
            if (generation !== historyGeneration.current || ledger.current !== activeLedger) return;
            try {
                admitMarketDataChartBars(loaded.bars);
                const merged = activeLedger.mergeHistory(loaded.bars);
                setLedgerSnapshot(merged.snapshot);
            } catch (error) {
                if (error instanceof MarketDataBarLedgerConflictError) failLedger(error);
                else throw error;
                return;
            }
            setCoverage(loaded.coverage);
            setResolvedSourceId(loaded.source_selection.source_id);
            setHistoryProjectionFingerprint(loaded.history_projection_fingerprint);
            resume.current =
                loaded.resume_after_sequence !== null && loaded.resume_plan_fingerprint !== null
                    ? {
                          cursor: loaded.resume_after_sequence,
                          fingerprint: loaded.resume_plan_fingerprint
                      }
                    : null;
            olderHistoryLoader.current = new OnlyMarketDataHistoryLoader({
                readOnly: credentials.capture().bearer !== null || !automaticPreparation.current,
                client,
                reference: active,
                expectedSourceId,
                contextKey: activeLedger.contextKey,
                isCurrent: () =>
                    generation === historyGeneration.current && ledger.current === activeLedger,
                merge: (pageBars) => {
                    const current = activeLedger.snapshot();
                    admitMarketDataChartBars([
                        ...current.closedBars,
                        ...(current.preview === null ? [] : [current.preview]),
                        ...pageBars
                    ]);
                    const page = activeLedger.mergeHistory(pageBars);
                    setLedgerSnapshot(page.snapshot);
                    return page;
                },
                onAcquiring: () => {
                    setOlderHistoryStatus("acquiring");
                }
            });
            setOlderHistoryStatus("idle");
            setOlderHistoryMessage(null);
            setStatus("ready");
            setMessage(null);
        },
        [client, credentials, failLedger]
    );

    const acquire = useCallback(
        async (
            active: MarketDataSourceReference,
            expectedSourceId: string,
            query: MarketDataBarsQuery,
            ranges: readonly { start_ns: string; end_ns: string }[],
            generation: number,
            activeLedger: OnlyMarketDataBarLedger
        ) => {
            setStatus("acquiring");
            setMessage("正在同步历史行情…");
            try {
                for (const range of ranges) {
                    let acquisition = await client.createAcquisition(active, {
                        instrument_id: query.instrument_id,
                        start_ns: range.start_ns,
                        end_ns: range.end_ns,
                        bar_semantic: query.bar_semantic
                    });
                    while (
                        generation === historyGeneration.current &&
                        acquisition.status !== "COMPLETE"
                    ) {
                        if (acquisition.status === "FAILED") break;
                        if (generation !== historyGeneration.current) return;
                        if (acquisition.status === "PENDING") {
                            acquisition = await client.createAcquisition(active, {
                                instrument_id: query.instrument_id,
                                start_ns: range.start_ns,
                                end_ns: range.end_ns,
                                bar_semantic: query.bar_semantic
                            });
                        } else {
                            await new Promise((resolve) => window.setTimeout(resolve, 250));
                            if (generation !== historyGeneration.current) return;
                            acquisition = await client.getAcquisition(
                                active,
                                acquisition.acquisition_id
                            );
                        }
                    }
                    if (generation !== historyGeneration.current) return;
                    if (acquisition.status !== "COMPLETE") {
                        setCoverage(acquisition.coverage);
                        setStatus("failed");
                        setMessage(
                            `历史行情同步失败：${acquisition.failure_detail ?? acquisition.status}`
                        );
                        return;
                    }
                }
                const reloaded = await client.queryBars(active, query);
                if (generation !== historyGeneration.current) return;
                onlyAssertMarketDataBarsAuthority(
                    {
                        reference: active,
                        expectedSourceId,
                        instrumentId: query.instrument_id,
                        barSemantic: query.bar_semantic,
                        anchorKind: query.anchor_kind,
                        targetBarCount: query.target_bar_count,
                        ...(query.before_ns === undefined ? {} : { beforeNs: query.before_ns })
                    },
                    reloaded
                );
                setCoverage(reloaded.coverage);
                if (reloaded.coverage.status === "COMPLETE") {
                    publishCompleteHistory(
                        active,
                        expectedSourceId,
                        generation,
                        activeLedger,
                        reloaded
                    );
                } else {
                    setStatus("incomplete");
                    setMessage(
                        `历史行情仍不完整：${reloaded.coverage.issues.join(", ") || reloaded.coverage.status}`
                    );
                }
            } catch (error) {
                if (generation === historyGeneration.current) apply(error);
            }
        },
        [apply, client, publishCompleteHistory]
    );

    const load = useCallback(
        async (
            active: MarketDataSourceReference,
            expectedSourceId: string,
            target: MarketDataInstrument,
            specification: MarketDataBarSemantic,
            generation: number
        ) => {
            const query = {
                instrument_id: target.instrument_id,
                anchor_kind: "LATEST_CLOSED" as const,
                // The ordinary workspace prepares the full admitted Study input
                // before indicators are added; adding a Study never acquires data.
                target_bar_count: credentials.localSession ? 2000 : DEFAULT_TARGET_BAR_COUNT,
                bar_semantic: specification
            };
            const contextKey = onlyMarketDataChartContextKey(
                active,
                target.instrument_id,
                specification
            );
            const activeLedger = new OnlyMarketDataBarLedger(contextKey);
            ledger.current = activeLedger;
            olderHistoryLoader.current = null;
            setLedgerSnapshot(activeLedger.snapshot());
            setOlderHistoryStatus("idle");
            setOlderHistoryMessage(null);
            resume.current = null;
            setCoverage(null);
            setHistoryProjectionFingerprint(null);
            setResolvedSourceId(null);
            setStatus("loading");
            setTiming(null);
            setRealtimeStatus("disabled");
            setMessage(null);
            try {
                const loaded = await client.queryBars(active, query);
                if (generation !== historyGeneration.current) return;
                onlyAssertMarketDataBarsAuthority(
                    {
                        reference: active,
                        expectedSourceId,
                        instrumentId: query.instrument_id,
                        barSemantic: query.bar_semantic,
                        anchorKind: query.anchor_kind,
                        targetBarCount: query.target_bar_count
                    },
                    loaded
                );
                setCoverage(loaded.coverage);
                if (loaded.coverage.status === "COMPLETE") {
                    publishCompleteHistory(
                        active,
                        expectedSourceId,
                        generation,
                        activeLedger,
                        loaded
                    );
                    return;
                }
                setHistoryProjectionFingerprint(null);
                if (credentials.capture().bearer !== null || !automaticPreparation.current) {
                    setStatus("failed");
                    setMessage(
                        credentials.capture().bearer !== null
                            ? "只读行情覆盖不足；需要先完成受控历史准备，本页面不会自动采集"
                            : "行情覆盖不足；请明确选择准备行情，本次选择不会自动采集"
                    );
                    return;
                }
                await acquire(
                    active,
                    expectedSourceId,
                    {
                        ...query,
                        anchor_kind: "BEFORE_TIME",
                        before_ns: loaded.resolved_end_ns
                    },
                    loaded.coverage.planned_acquisition_ranges,
                    generation,
                    activeLedger
                );
            } catch (error) {
                if (generation === historyGeneration.current) apply(error);
            }
        },
        [acquire, apply, client, credentials, publishCompleteHistory]
    );

    useEffect(() => {
        const revision = reference?.integration_revision_fingerprint ?? null;
        if (previousRevision.current !== null && revision !== previousRevision.current) {
            streamGeneration.current += 1;
            const generation = ++historyGeneration.current;
            resume.current = null;
            setLastClosedCursor(null);
            setStreamId(null);
            if (reference !== null && selectedSource !== null && instrument !== null)
                void load(reference, selectedSource.source_id, instrument, barSemantic, generation);
            else if (watchlistSourceRef.current !== null) {
                ledger.current = null;
                olderHistoryLoader.current = null;
                setLedgerSnapshot(null);
                setCoverage(null);
                setHistoryProjectionFingerprint(null);
                setResolvedSourceId(null);
                setOlderHistoryStatus("idle");
                setOlderHistoryMessage(null);
                setRealtimeStatus("disabled");
                setTiming(null);
                setStatus("failed");
                setMessage("自选绑定的数据源不可用；请明确重新绑定，不会自动换源");
            }
        }
        previousRevision.current = revision;
    }, [reference, selectedSource, instrument, barSemantic, load]);

    useEffect(() => {
        if (
            status !== "ready" ||
            reference === null ||
            instrument === null ||
            resolvedSourceId === null ||
            ledger.current?.snapshot().closedBars.length === 0 ||
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
        let connectionAttempt = 0;
        const connect = () => {
            if (stopped || resume.current === null) return;
            const attempt = ++connectionAttempt;
            let connectionReady = false;
            let subscription: Extract<MarketDataStreamEvent, { event: "SUBSCRIBED" }> | null = null;
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
                    bar_semantic: barSemantic,
                    resume_after_sequence: resume.current.cursor,
                    resume_plan_fingerprint: resume.current.fingerprint
                },
                (event) => {
                    if (
                        generation !== streamGeneration.current ||
                        attempt !== connectionAttempt ||
                        stopped ||
                        terminal
                    )
                        return;
                    // React may apply functional state updates after later stream events.
                    const timingConnectionReady = connectionReady;
                    const timingSubscription = subscription;
                    if (
                        (event.event === "SUBSCRIBED" ||
                            event.event === "BAR_PREVIEW" ||
                            event.event === "BAR_CLOSED") &&
                        (event.source_id !== resolvedSourceId ||
                            event.instrument_id !== instrument.instrument_id ||
                            (event.event !== "SUBSCRIBED" &&
                                JSON.stringify(event.bar_semantic) !== JSON.stringify(barSemantic)))
                    ) {
                        terminal = true;
                        setStreamError("MARKET_DATA_BAR_SEMANTIC_MISMATCH");
                        setRealtimeStatus("failed");
                        close();
                        return;
                    }
                    if (event.event === "BAR_PREVIEW" || event.event === "BAR_CLOSED") {
                        try {
                            const current = ledger.current?.snapshot();
                            admitMarketDataChartBars([
                                ...(current?.closedBars ?? []),
                                ...(current?.preview == null ? [] : [current.preview]),
                                event.bar
                            ]);
                        } catch (error) {
                            if (!(error instanceof MarketDataChartProjectionError)) throw error;
                            terminal = true;
                            setStreamError(error.code);
                            setRealtimeStatus("failed");
                            close();
                            return;
                        }
                    }
                    if (event.event === "SUBSCRIBED") {
                        if (event.resolution_plan_fingerprint !== resume.current?.fingerprint) {
                            terminal = true;
                            resume.current = null;
                            setLastClosedCursor(null);
                            setStreamId(null);
                            setLedgerSnapshot((current) =>
                                current === null ? null : { ...current, preview: null }
                            );
                            setStreamError("MARKET_DATA_RESUME_PLAN_MISMATCH");
                            setRealtimeStatus("failed");
                            close();
                            return;
                        }
                        subscription = event;
                        setTiming(null);
                        setStreamId(event.stream_id);
                    } else if (event.event === "STATE") {
                        connectionReady = event.state === "READY";
                        if (!connectionReady)
                            setTiming((current) =>
                                current === null ? null : { ...current, currentConnection: false }
                            );
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
                        try {
                            const changed = ledger.current?.applyPreview(event.bar);
                            if (changed?.changed === true) setLedgerSnapshot(changed.snapshot);
                            // Identical current price may carry a new occurrence; rejected
                            // older/closed-overlap previews never update telemetry.
                            if (changed?.snapshot.preview?.bar_start_ns === event.bar.bar_start_ns)
                                setTiming((current) =>
                                    nextMarketDataTiming(
                                        current,
                                        event,
                                        timingSubscription,
                                        timingConnectionReady
                                    )
                                );
                        } catch (error) {
                            if (error instanceof MarketDataBarLedgerConflictError) {
                                terminal = true;
                                failLedger(error);
                                close();
                            } else throw error;
                        }
                    } else if (event.event === "BAR_CLOSED") {
                        try {
                            const previousStart =
                                ledger.current?.snapshot().latestClosedStartNs ?? null;
                            const changed = ledger.current?.applyClosed(event.bar);
                            if (changed?.changed === true) setLedgerSnapshot(changed.snapshot);
                            if (
                                changed?.appendedCount === 1 &&
                                (previousStart === null ||
                                    BigInt(event.bar.bar_start_ns) > BigInt(previousStart)) &&
                                (resume.current === null ||
                                    BigInt(event.sequence) > BigInt(resume.current.cursor))
                            )
                                setTiming((current) =>
                                    nextMarketDataTiming(
                                        current,
                                        event,
                                        timingSubscription,
                                        timingConnectionReady
                                    )
                                );
                        } catch (error) {
                            if (error instanceof MarketDataBarLedgerConflictError) {
                                terminal = true;
                                failLedger(error);
                                close();
                                return;
                            }
                            throw error;
                        }
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
                            void load(
                                reference,
                                resolvedSourceId,
                                instrument,
                                barSemantic,
                                ++historyGeneration.current
                            );
                        } else setRealtimeStatus("failed");
                    }
                },
                (failure) => {
                    if (
                        generation !== streamGeneration.current ||
                        attempt !== connectionAttempt ||
                        stopped ||
                        terminal
                    )
                        return;
                    connectionAttempt += 1;
                    connectionReady = false;
                    setTiming((current) =>
                        current === null ? null : { ...current, currentConnection: false }
                    );
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
                },
                credentials
            );
        };
        queueMicrotask(() => {
            if (stopped) return;
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
    }, [
        barSemantic,
        credentials,
        failLedger,
        instrument,
        load,
        reference,
        resolvedSourceId,
        status
    ]);

    const selectSource = useCallback((integrationId: string, preservePeriod = false) => {
        if (
            integrationId !== "" &&
            integrationId === selectedSourceId.current &&
            (preservePeriod || watchlistSourceRef.current === null)
        )
            return;
        if (!preservePeriod) {
            watchlistSourceRef.current = null;
            setWatchlistSource(null);
            automaticPreparation.current = true;
        }
        selectedSourceId.current = integrationId;
        searchGeneration.current += 1;
        streamGeneration.current += 1;
        historyGeneration.current += 1;
        setSourceId(integrationId);
        if (!preservePeriod) setBarSemantic(marketDataBarSemantic(15));
        setInstruments([]);
        setInstrument(null);
        setCoverage(null);
        ledger.current = null;
        olderHistoryLoader.current = null;
        setLedgerSnapshot(null);
        setOlderHistoryStatus("idle");
        setOlderHistoryMessage(null);
        setHistoryProjectionFingerprint(null);
        setResolvedSourceId(null);
        setLastClosedCursor(null);
        resume.current = null;
        previousRevision.current = null;
        setStreamId(null);
        setStreamError(null);
        setRealtimeStatus("disabled");
        setTiming(null);
        setStatus(integrationId === "" ? "no-source" : "idle");
        setMessage(integrationId === "" ? "请选择数据源" : null);
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        client
            .listSources(controller.signal)
            .then((found) => {
                if (controller.signal.aborted) return;
                if (new Set(found.map((item) => item.integration_id)).size !== found.length)
                    throw new MarketDataWebError(
                        "CONTRACT_ERROR",
                        "数据源 Integration identity 重复"
                    );
                setSources((current) =>
                    found.map((item) => {
                        const previous = current.find(
                            (source) => source.integration_id === item.integration_id
                        );
                        return previous !== undefined &&
                            JSON.stringify(previous) === JSON.stringify(item)
                            ? previous
                            : item;
                    })
                );
                // Preserve a user's exact still-available choice, not a new default
                // or an old response's choice after management changed the catalog.
                if (
                    watchlistSourceRef.current !== null ||
                    found.some((item) => item.integration_id === selectedSourceId.current)
                )
                    return;
                const matches = found.filter(
                    (item) =>
                        item.type_id === DEFAULT_SOURCE_TYPE &&
                        item.environment === DEFAULT_SOURCE_ENVIRONMENT
                );
                if (matches.length === 1 && matches[0] !== undefined)
                    selectSource(matches[0].integration_id);
                else {
                    selectSource("");
                    setMessage(
                        found.length === 0
                            ? "尚未配置可用的行情来源，请先添加行情来源。"
                            : "请在左上角搜索并选择商品。"
                    );
                }
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) return;
                setSources([]);
                if (watchlistSourceRef.current === null) selectSource("");
                apply(error);
                if (error instanceof MarketDataWebError && error.code === "TRANSPORT_ERROR")
                    setMessage("行情服务不可用：TRANSPORT_ERROR");
            });
        return () => {
            controller.abort();
        };
    }, [apply, client, selectSource, sourceRefresh]);

    useEffect(() => {
        // Manual selections remain valid; the Binance default resolves an actual instrument,
        // never a locally authored DTO or a first-row substitute.
        if (
            instrument !== null ||
            selectedSource?.type_id !== DEFAULT_SOURCE_TYPE ||
            selectedSource.environment !== DEFAULT_SOURCE_ENVIRONMENT
        )
            return;
        const controller = new AbortController();
        const generation = historyGeneration.current;
        const search = ++searchGeneration.current;
        const active = onlyMarketDataSourceReference(selectedSource);
        client
            .listInstruments(active, "BTCUSDT", controller.signal)
            .then(async (found) => {
                if (
                    controller.signal.aborted ||
                    generation !== historyGeneration.current ||
                    search !== searchGeneration.current
                )
                    return;
                const matches = found.filter(
                    (item) => item.instrument_id === DEFAULT_INSTRUMENT_ID
                );
                if (matches.length > 1)
                    throw new MarketDataWebError("CONTRACT_ERROR", "BTCUSDT.BINANCE identity 重复");
                setInstruments(found);
                const target = matches[0];
                if (target === undefined) {
                    setStatus("idle");
                    setMessage("当前数据源未提供 BTCUSDT.BINANCE");
                    return;
                }
                if (
                    selectedSource.time_bar_capability.minimum_window_minutes > 15 ||
                    selectedSource.time_bar_capability.maximum_window_minutes < 15
                )
                    throw new MarketDataWebError(
                        "CONTRACT_ERROR",
                        "当前数据源未提供 15m Bar capability"
                    );
                setInstrument(target);
                await load(
                    active,
                    selectedSource.source_id,
                    target,
                    marketDataBarSemantic(15),
                    generation
                );
            })
            .catch((error: unknown) => {
                if (
                    !controller.signal.aborted &&
                    generation === historyGeneration.current &&
                    search === searchGeneration.current
                )
                    apply(error);
            });
        return () => {
            controller.abort();
        };
    }, [apply, client, instrument, load, selectedSource]);

    const searchInstruments = useCallback(
        async (query: string) => {
            if (reference === null) {
                setInstruments([]);
                return;
            }
            const generation = historyGeneration.current;
            const search = ++searchGeneration.current;
            // Searching is an input operation, not a replacement of an active chart incarnation.
            if (instrument === null) setStatus("searching");
            try {
                const found = await client.listInstruments(reference, query);
                if (generation !== historyGeneration.current || search !== searchGeneration.current)
                    return;
                setInstruments(found);
                if (instrument === null) setStatus("idle");
                setMessage(found.length === 0 ? "未找到匹配标的" : null);
            } catch (error) {
                if (generation !== historyGeneration.current || search !== searchGeneration.current)
                    return;
                if (instrument === null) apply(error);
                else setMessage("标的搜索失败；当前行情上下文保持不变");
            }
        },
        [apply, client, instrument, reference]
    );

    const selectInstrument = useCallback(
        async (target: MarketDataInstrument) => {
            if (
                target.instrument_id === instrument?.instrument_id &&
                status !== "failed" &&
                status !== "incomplete" &&
                realtimeStatus !== "failed"
            )
                return;
            if (target.instrument_id !== instrument?.instrument_id) {
                watchlistSourceRef.current = null;
                setWatchlistSource(null);
                automaticPreparation.current = true;
            }
            streamGeneration.current += 1;
            const generation = ++historyGeneration.current;
            setLastClosedCursor(null);
            resume.current = null;
            setStreamId(null);
            setStreamError(null);
            setRealtimeStatus("disabled");
            setTiming(null);
            setInstrument(target);
            if (reference === null || selectedSource === null) {
                setMessage("请先选择数据源");
                return;
            }
            await load(reference, selectedSource.source_id, target, barSemantic, generation);
        },
        [barSemantic, instrument, load, realtimeStatus, reference, selectedSource, status]
    );

    const selectWatchlistInstrument = useCallback(
        async (active: MarketDataSourceReference, instrumentId: string, prepare = true) => {
            // Every user selection supersedes pending lookups, including a healthy A→A no-op.
            const search = ++searchGeneration.current;
            const history = historyGeneration.current;
            const source = sources.find(
                (item) =>
                    item.integration_id === active.integration_id &&
                    item.integration_revision_fingerprint ===
                        active.integration_revision_fingerprint &&
                    item.type_id === active.expected_type_id
            );
            if (source === undefined) {
                setMessage("自选绑定的数据源不可用；请明确重新绑定，不会自动换源");
                return;
            }
            if (
                reference?.integration_id === active.integration_id &&
                reference.integration_revision_fingerprint ===
                    active.integration_revision_fingerprint &&
                reference.expected_type_id === active.expected_type_id &&
                instrument?.instrument_id === instrumentId &&
                status === "ready" &&
                realtimeStatus !== "failed"
            )
                return;
            const minutes =
                barSemantic.formation.kind === "FIXED_DURATION"
                    ? barSemantic.formation.window_minutes
                    : 0;
            if (
                minutes < source.time_bar_capability.minimum_window_minutes ||
                minutes > source.time_bar_capability.maximum_window_minutes
            ) {
                setMessage("该数据源不支持当前图表周期；请先明确修改周期");
                return;
            }
            try {
                const found = await client.listInstruments(active, "", undefined, [instrumentId]);
                if (search !== searchGeneration.current || history !== historyGeneration.current)
                    return;
                const target = found.find((item) => item.instrument_id === instrumentId);
                if (found.length !== 1 || target === undefined)
                    throw new MarketDataWebError("CONTRACT_ERROR", "未取得 exact 自选标的");
                automaticPreparation.current = prepare;
                selectSource(source.integration_id, true);
                watchlistSourceRef.current = active;
                setWatchlistSource(active);
                streamGeneration.current++;
                const generation = ++historyGeneration.current;
                setLastClosedCursor(null);
                resume.current = null;
                setStreamId(null);
                setStreamError(null);
                setRealtimeStatus("disabled");
                setInstrument(target);
                await load(active, source.source_id, target, barSemantic, generation);
            } catch (error) {
                if (search === searchGeneration.current) apply(error);
            }
        },
        [
            apply,
            barSemantic,
            client,
            instrument,
            load,
            realtimeStatus,
            reference,
            selectSource,
            sources,
            status
        ]
    );

    const selectBarDuration = useCallback(
        async (durationMinutes: number) => {
            if (
                barCapability === null ||
                durationMinutes < barCapability.minimum_window_minutes ||
                durationMinutes > barCapability.maximum_window_minutes
            )
                return;
            const specification = marketDataBarSemantic(durationMinutes);
            if (
                JSON.stringify(specification) === JSON.stringify(barSemantic) &&
                status !== "failed" &&
                status !== "incomplete" &&
                realtimeStatus !== "failed"
            )
                return;
            streamGeneration.current += 1;
            const generation = ++historyGeneration.current;
            resume.current = null;
            setLastClosedCursor(null);
            setStreamId(null);
            setStreamError(null);
            setRealtimeStatus("disabled");
            setTiming(null);
            ledger.current = null;
            olderHistoryLoader.current = null;
            setLedgerSnapshot(null);
            setOlderHistoryStatus("idle");
            setOlderHistoryMessage(null);
            setBarSemantic(specification);
            if (reference !== null && selectedSource !== null && instrument !== null)
                await load(
                    reference,
                    selectedSource.source_id,
                    instrument,
                    specification,
                    generation
                );
        },
        [
            barCapability,
            barSemantic,
            instrument,
            load,
            realtimeStatus,
            reference,
            selectedSource,
            status
        ]
    );

    const loadOlderHistory = useCallback(async () => {
        const activeLedger = ledger.current;
        const loader = olderHistoryLoader.current;
        const beforeNs = activeLedger?.snapshot().earliestStartNs ?? null;
        if (activeLedger === null || loader === null || instrument === null || beforeNs === null)
            return;
        setOlderHistoryStatus("loading");
        setOlderHistoryMessage(null);
        try {
            const result = await loader.loadOlder({
                instrumentId: instrument.instrument_id,
                barSemantic,
                beforeNs
            });
            if (ledger.current !== activeLedger || result.status === "stale") return;
            setOlderHistoryStatus(result.status === "exhausted" ? "exhausted" : "idle");
        } catch (error) {
            if (ledger.current !== activeLedger) return;
            if (error instanceof MarketDataBarLedgerConflictError) {
                failLedger(error);
                return;
            }
            setOlderHistoryStatus("failed");
            setOlderHistoryMessage(
                error instanceof Error ? `较早行情加载失败：${error.message}` : "较早行情加载失败"
            );
        }
    }, [barSemantic, failLedger, instrument]);

    return {
        selectableSources,
        reference,
        resolvedSourceId,
        sourceId: watchlistSource !== null && selectedSource === null ? "" : sourceId,
        instruments,
        instrument,
        barSemantic,
        barCapability,
        status,
        message,
        coverage,
        chartContextKey,
        bars,
        loadedClosedBarCount: ledgerSnapshot?.closedBars.length ?? 0,
        historyProjectionFingerprint,
        realtimeStatus,
        liveBar,
        olderHistoryStatus,
        olderHistoryMessage,
        streamId,
        timing,
        streamError,
        lastClosedCursor,
        selectSource,
        refreshSources,
        searchInstruments,
        selectInstrument,
        selectWatchlistInstrument,
        selectBarDuration,
        loadOlderHistory
    };
}

export type { MarketDataApiClient };
