import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
    admitMarketDataChartBars,
    projectMarketDataBar,
    MarketDataChartProjectionError,
    type MarketDataChartBarProjection
} from "../../charts/lightweight/marketDataChartProjection";
import { MarketDataWebError, type MarketDataApiClient } from "../../api/marketData/client";
import { nextMarketDataTiming, type MarketDataTiming } from "./marketDataTiming";
import type { TemporaryMarketDataStreamEvent } from "../../api/marketData/stream.generated";
import { openTemporaryMarketDataStream } from "../../api/marketData/temporaryStream";
import { readTemporaryMarketData } from "../../api/marketData/temporary";
import type { TemporaryMarketDataWindow } from "../../api/marketData/temporary.generated";
import { loadTemporaryMarketDataWindow } from "./temporaryMarketDataLoader";
import type {
    MarketDataBarSemantic,
    MarketDataInstrument,
    MarketDataSource,
    MarketDataSourceReference
} from "../../api/marketData/model";
import {
    marketDataBarSemantic,
    marketDataBarSemanticSchema,
    marketDataSourceChoiceKey
} from "../../api/marketData/model";
import { useMarketDataApi, useLocalReadCredentials } from "../../app/providers";
import {
    MarketDataBarLedgerConflictError,
    OnlyMarketDataBarLedger,
    type MarketDataBarLedgerSnapshot
} from "./marketDataBarLedger";
import { onlyMarketDataChartContextKey } from "./marketDataChartContext";
import { MarketDataBarsAuthorityMismatchError } from "./marketDataBarsAuthority";

export const DEFAULT_TARGET_BAR_COUNT = 2000;
/** Presentation preference only; mutable source/Revision identities come from the server. */
const DEFAULT_SOURCE_TYPE = "binance.spot.market_data";
const DEFAULT_SOURCE_ENVIRONMENT = "GLOBAL";
const DEFAULT_INSTRUMENT_ID = "BTCUSDT.BINANCE";
export const STREAM_RECONNECT_DELAYS_MS = [250, 500, 1000, 2000, 4000] as const;

export type MarketDataChartStatus =
    "no-source" | "idle" | "searching" | "loading" | "ready" | "incomplete" | "failed";

export type MarketDataRealtimeStatus =
    "disabled" | "connecting" | "recovering" | "ready" | "degraded" | "failed";

export interface MarketDataChartState {
    readonly selectableSources: readonly MarketDataSource[];
    /** Non-null exactly when a real Market Data source context is selected. */
    readonly pageId: string;
    readonly catalogStatus: "loading" | "ready" | "failed";
    readonly restoreSelection: (
        source: MarketDataSourceReference,
        instrumentId: string,
        semantic: MarketDataBarSemantic
    ) => Promise<boolean>;
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
    readonly pageReloadRequired: boolean;
    readonly coverage: TemporaryMarketDataWindow["coverage"] | null;
    readonly chartContextKey: string | null;
    readonly bars: readonly MarketDataChartBarProjection[];
    readonly loadedClosedBarCount: number;
    readonly windowFingerprint: string | null;
    readonly realtimeStatus: MarketDataRealtimeStatus;
    readonly liveBar: MarketDataChartBarProjection | null;
    readonly olderHistoryStatus: "idle" | "loading" | "failed" | "empty";
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
        instrumentId: string
    ) => Promise<void>;
    readonly selectBarDuration: (durationMinutes: number) => Promise<void>;
    readonly loadOlderHistory: (manual?: boolean) => Promise<void>;
}

/** The chart context is presentation state; every fact below comes from the Product API. */
export function onlyMarketDataSourceReference(source: MarketDataSource): MarketDataSourceReference {
    return {
        integration_id: source.integration_id,
        integration_revision_fingerprint: source.integration_revision_fingerprint,
        expected_type_id: source.type_id
    };
}

export function useMarketDataChart({
    startup = "default"
}: { startup?: "pending" | "default" | "restore" } = {}): MarketDataChartState {
    const client = useMarketDataApi();
    const [pageId] = useState(() => crypto.randomUUID());
    const credentials = useLocalReadCredentials();
    const [catalogStatus, setCatalogStatus] = useState<"loading" | "ready" | "failed">("loading");
    const [sources, setSources] = useState<readonly MarketDataSource[]>([]);
    const [sourceRefresh, setSourceRefresh] = useState(0);
    const refreshSources = useCallback(() => {
        setCatalogStatus("loading");
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
    const [pageReloadRequired, setPageReloadRequired] = useState(false);
    const [coverage, setCoverage] = useState<TemporaryMarketDataWindow["coverage"] | null>(null);
    const [ledgerSnapshot, setLedgerSnapshot] = useState<MarketDataBarLedgerSnapshot | null>(null);
    const [windowFingerprint, setWindowFingerprint] = useState<string | null>(null);
    const [resolvedSourceId, setResolvedSourceId] = useState<string | null>(null);
    const [realtimeStatus, setRealtimeStatus] = useState<MarketDataRealtimeStatus>("disabled");
    const [olderHistoryStatus, setOlderHistoryStatus] = useState<
        "idle" | "loading" | "failed" | "empty"
    >("idle");
    const [olderHistoryMessage, setOlderHistoryMessage] = useState<string | null>(null);
    const [timing, setTiming] = useState<MarketDataTiming | null>(null);
    const [streamId, setStreamId] = useState<string | null>(null);
    const [streamError, setStreamError] = useState<string | null>(null);
    const [lastClosedCursor, setLastClosedCursor] = useState<string | null>(null);
    const ledger = useRef<OnlyMarketDataBarLedger | null>(null);
    const historyAbort = useRef<AbortController | null>(null);
    const olderAbort = useRef<AbortController | null>(null);
    const olderNoProgress = useRef<string | null>(null);
    const lastClosedEnd = useRef<string | null>(null);
    const streamGeneration = useRef(0);
    const historyGeneration = useRef(0);
    const searchGeneration = useRef(0);
    const resume = useRef<{
        before: string;
        fingerprint: string;
        plan: string;
        count: number;
    } | null>(null);
    const previousRevision = useRef<string | null>(null);
    const automaticFullRefreshUsed = useRef(false);

    const chartContextKey = ledgerSnapshot?.contextKey ?? null;
    const closedBars = ledgerSnapshot?.closedBars;
    const bars = useMemo(() => (closedBars ?? []).map(projectMarketDataBar), [closedBars]);
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
                    marketDataSourceChoiceKey(item) === sourceId &&
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

    const apply = useCallback(
        (error: unknown) => {
            const webError =
                error instanceof MarketDataWebError ||
                error instanceof MarketDataBarsAuthorityMismatchError ||
                error instanceof MarketDataChartProjectionError
                    ? error
                    : null;
            // Fence pending history and socket callbacks synchronously, before
            // React retires the corresponding effects.
            historyGeneration.current += 1;
            streamGeneration.current += 1;
            historyAbort.current?.abort();
            resume.current = null;
            lastClosedEnd.current = null;
            setLastClosedCursor(null);
            setStreamId(null);
            setTiming(null);
            setResolvedSourceId(null);
            setCoverage(null);
            setRealtimeStatus("failed");
            ledger.current = null;
            olderAbort.current?.abort();
            olderNoProgress.current = null;
            setLedgerSnapshot(null);
            setWindowFingerprint(null);
            setStatus("failed");
            if (
                credentials.localSession &&
                credentials.capture().bearer === null &&
                webError instanceof MarketDataWebError &&
                webError.code === "LOCAL_READ_UNAUTHORIZED" &&
                webError.status === 401
            )
                setPageReloadRequired(true);
            setMessage(
                webError === null
                    ? "行情请求失败"
                    : `行情请求失败：${webError.code} ${webError.message}`.trim()
            );
        },
        [credentials]
    );

    const failLedger = useCallback((error: MarketDataBarLedgerConflictError) => {
        historyGeneration.current += 1;
        streamGeneration.current += 1;
        olderAbort.current?.abort();
        olderNoProgress.current = null;
        // A retained equal fingerprint is not proof after contradictory facts.
        setWindowFingerprint(null);
        setLedgerSnapshot((current) =>
            current === null ? null : { ...current, preview: null, version: current.version + 1 }
        );
        setStatus("failed");
        setMessage(`${error.code}: ${error.message}`);
        setRealtimeStatus("failed");
        setOlderHistoryStatus("failed");
        setOlderHistoryMessage(error.code);
    }, []);

    const load = useCallback(
        async (
            active: MarketDataSourceReference,
            expectedSourceId: string,
            target: MarketDataInstrument,
            specification: MarketDataBarSemantic,
            generation: number,
            recovery = false
        ) => {
            if (!recovery) automaticFullRefreshUsed.current = false;
            historyAbort.current?.abort();
            olderAbort.current?.abort();
            const controller = new AbortController();
            historyAbort.current = controller;
            const current = () =>
                !controller.signal.aborted && generation === historyGeneration.current;
            const source = sources.find(
                (item) =>
                    item.integration_id === active.integration_id &&
                    item.integration_revision_fingerprint ===
                        active.integration_revision_fingerprint &&
                    item.type_id === active.expected_type_id &&
                    item.source_id === expectedSourceId
            );
            const activeLedger = new OnlyMarketDataBarLedger(
                onlyMarketDataChartContextKey(active, target.instrument_id, specification)
            );
            ledger.current = activeLedger;
            setLedgerSnapshot(activeLedger.snapshot());
            resume.current = null;
            lastClosedEnd.current = null;
            olderNoProgress.current = null;
            setWindowFingerprint(null);
            setCoverage(null);
            setResolvedSourceId(null);
            setOlderHistoryStatus("idle");
            setOlderHistoryMessage(null);
            setRealtimeStatus("disabled");
            setTiming(null);
            setStatus("loading");
            setMessage(null);
            const progress: { lastWindow: TemporaryMarketDataWindow | null } = { lastWindow: null };
            try {
                if (
                    source === undefined ||
                    target.market_data_capabilities.includes("HISTORICAL_ONLY")
                )
                    throw new MarketDataWebError(
                        "MARKET_DATA_SOURCE_SELECTION_UNRESOLVED",
                        "当前精确来源不能提供临时行情，不会读取入库历史或自动换源"
                    );
                const loaded = await loadTemporaryMarketDataWindow(
                    credentials,
                    active,
                    {
                        instrument_id: target.instrument_id,
                        bar_semantic: specification,
                        anchor_kind: "LATEST_CLOSED",
                        target_bar_count: DEFAULT_TARGET_BAR_COUNT
                    },
                    pageId,
                    {
                        sourceId: expectedSourceId,
                        environment: source.environment,
                        signal: controller.signal,
                        onWindow: (window) => {
                            if (!current() || ledger.current !== activeLedger) return;
                            admitMarketDataChartBars(window.bars);
                            const merged = activeLedger.mergeHistory(
                                window.bars,
                                window.resolved_end_ns
                            );
                            setLedgerSnapshot(merged.snapshot);
                            setCoverage(window.coverage);
                            setResolvedSourceId(window.source_selection.source_id);
                            setWindowFingerprint(window.window_fingerprint);
                            progress.lastWindow = window;
                        }
                    }
                );
                if (!current()) return;
                lastClosedEnd.current = loaded.bars.at(-1)?.bar_end_ns ?? null;
                resume.current =
                    lastClosedEnd.current === null
                        ? null
                        : {
                              before: loaded.resolved_end_ns,
                              fingerprint: loaded.window_fingerprint,
                              plan: loaded.resolution_plan_fingerprint,
                              count: loaded.requested_bar_count
                          };
                setStatus(loaded.coverage.status === "COMPLETE" ? "ready" : "incomplete");
                setMessage(
                    loaded.coverage.status === "COMPLETE"
                        ? null
                        : `临时行情窗口不完整：${String(loaded.coverage.actual_bar_count)}/${String(loaded.coverage.expected_bar_count)} 根闭合 K 线；可明确重试，不会自动入库。`
                );
            } catch (error) {
                if (!current()) return;
                if (
                    error instanceof MarketDataWebError &&
                    progress.lastWindow !== null &&
                    activeLedger.snapshot().closedBars.length > 0 &&
                    [
                        "TRANSPORT_ERROR",
                        "CHART_STUDY_QUERY_UNAVAILABLE",
                        "MARKET_DATA_SOURCE_TIMEOUT",
                        "MARKET_DATA_SOURCE_UNAVAILABLE"
                    ].includes(error.code)
                ) {
                    // A network failure cannot erase already verified rows. This
                    // remains failed/stale, with no stream or completion claim.
                    setStatus("failed");
                    setRealtimeStatus("disabled");
                    setMessage(
                        `临时行情加载未完成：${error.code}；保留 ${String(progress.lastWindow.coverage.actual_bar_count)} 根已验证闭合 K 线，可明确重新读取。`
                    );
                } else if (error instanceof MarketDataBarLedgerConflictError) failLedger(error);
                else apply(error);
            }
        },
        [apply, credentials, failLedger, pageId, sources]
    );
    useEffect(
        () => () => {
            historyAbort.current?.abort();
            olderAbort.current?.abort();
        },
        []
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
                olderAbort.current?.abort();
                olderNoProgress.current = null;
                setLedgerSnapshot(null);
                setCoverage(null);
                setWindowFingerprint(null);
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
            (status !== "ready" && status !== "incomplete") ||
            reference === null ||
            instrument === null ||
            resolvedSourceId === null ||
            selectedSource === null ||
            resume.current === null ||
            lastClosedEnd.current === null
        )
            return;
        const generation = ++streamGeneration.current;
        const controller = new AbortController();
        let stopped = false,
            terminal = false,
            attempt = 0,
            retries = 0;
        let close: (() => void) | undefined;
        let timer: number | undefined;
        const current = (incarnation: number) =>
            !stopped &&
            !terminal &&
            generation === streamGeneration.current &&
            incarnation === attempt;
        const schedule = () => {
            if (stopped || terminal) return;
            setTiming((value) => (value === null ? null : { ...value, currentConnection: false }));
            if (retries >= STREAM_RECONNECT_DELAYS_MS.length) {
                terminal = true;
                setRealtimeStatus("failed");
                setStreamError("MARKET_DATA_RECONNECT_EXHAUSTED");
                setMessage("临时行情重连未成功；保留旧行情，请明确重新读取。");
                return;
            }
            setRealtimeStatus("degraded");
            timer = window.setTimeout(
                () => void connect(true),
                STREAM_RECONNECT_DELAYS_MS[
                    Math.min(retries++, STREAM_RECONNECT_DELAYS_MS.length - 1)
                ]
            );
        };
        const connect = async (refresh: boolean) => {
            const incarnation = ++attempt;
            let ready = false;
            let subscription: Extract<
                TemporaryMarketDataStreamEvent,
                { event: "SUBSCRIBED" }
            > | null = null;
            try {
                if (refresh && lastClosedEnd.current !== null) {
                    // Re-pin the last actually received closed target. The Source
                    // still owns its native checkpoint and continuity proof.
                    const pinned = await readTemporaryMarketData(
                        credentials,
                        reference,
                        {
                            instrument_id: instrument.instrument_id,
                            bar_semantic: barSemantic,
                            anchor_kind: "BEFORE_TIME",
                            before_ns: lastClosedEnd.current,
                            target_bar_count: DEFAULT_TARGET_BAR_COUNT
                        },
                        pageId,
                        controller.signal
                    );
                    if (!current(incarnation)) return;
                    if (
                        pinned.source_selection.source_id !== resolvedSourceId ||
                        pinned.source_selection.environment !== selectedSource.environment
                    )
                        throw new MarketDataWebError(
                            "MARKET_DATA_TEMPORARY_RESPONSE_MISMATCH",
                            "来源不匹配"
                        );
                    resume.current = {
                        before: pinned.resolved_end_ns,
                        fingerprint: pinned.window_fingerprint,
                        plan: pinned.resolution_plan_fingerprint,
                        count: pinned.requested_bar_count
                    };
                }
                if (!current(incarnation) || resume.current === null) return;
                const bootstrap = resume.current;
                setRealtimeStatus(refresh ? "recovering" : "connecting");
                close = openTemporaryMarketDataStream(
                    {
                        schema_version: 2,
                        operation: "SUBSCRIBE_TEMPORARY_BARS",
                        page_id: pageId,
                        source_reference: {
                            ...reference,
                            expected_type_id: reference.expected_type_id ?? ""
                        },
                        instrument_id: instrument.instrument_id,
                        bar_semantic: barSemantic,
                        before_ns: bootstrap.before,
                        target_bar_count: bootstrap.count,
                        expected_window_fingerprint: bootstrap.fingerprint
                    },
                    (event) => {
                        if (!current(incarnation)) return;
                        if (
                            (event.event === "SUBSCRIBED" ||
                                event.event === "BAR_CLOSED" ||
                                event.event === "BAR_PREVIEW") &&
                            (event.source_id !== resolvedSourceId ||
                                event.instrument_id !== instrument.instrument_id ||
                                (event.event !== "SUBSCRIBED" &&
                                    JSON.stringify(
                                        marketDataBarSemanticSchema.parse(event.bar_semantic)
                                    ) !==
                                        JSON.stringify(
                                            marketDataBarSemanticSchema.parse(barSemantic)
                                        )))
                        ) {
                            terminal = true;
                            close?.();
                            apply(
                                new MarketDataWebError(
                                    "MARKET_DATA_TEMPORARY_RESPONSE_MISMATCH",
                                    "行情上下文不匹配"
                                )
                            );
                            return;
                        }
                        if (event.event === "SUBSCRIBED") {
                            if (event.resolution_plan_fingerprint !== bootstrap.plan) {
                                terminal = true;
                                close?.();
                                setStreamError("MARKET_DATA_RESUME_PLAN_MISMATCH");
                                setRealtimeStatus("failed");
                                apply(
                                    new MarketDataWebError(
                                        "MARKET_DATA_RESUME_PLAN_MISMATCH",
                                        "临时行情计划不匹配"
                                    )
                                );
                                return;
                            }
                            subscription = event;
                            setStreamId(event.stream_id);
                            setTiming(null);
                        } else if (event.event === "STATE") {
                            ready = event.state === "READY";
                            if (ready) {
                                retries = 0;
                                automaticFullRefreshUsed.current = false;
                            }
                            setRealtimeStatus(
                                event.state === "READY"
                                    ? "ready"
                                    : event.state === "RECOVERING"
                                      ? "recovering"
                                      : event.state === "CONNECTING"
                                        ? "connecting"
                                        : "degraded"
                            );
                        } else if (event.event === "BAR_CLOSED" || event.event === "BAR_PREVIEW") {
                            try {
                                const active = ledger.current;
                                if (active === null) return;
                                const snapshot = active.snapshot();
                                admitMarketDataChartBars([
                                    ...snapshot.closedBars,
                                    ...(snapshot.preview === null ? [] : [snapshot.preview]),
                                    event.bar
                                ]);
                                const merged =
                                    event.event === "BAR_CLOSED"
                                        ? active.applyClosed(event.bar)
                                        : active.applyPreview(event.bar);
                                if (merged.changed) setLedgerSnapshot(merged.snapshot);
                                if (event.event === "BAR_CLOSED") {
                                    if (
                                        lastClosedEnd.current === null ||
                                        BigInt(event.bar.bar_end_ns) > BigInt(lastClosedEnd.current)
                                    )
                                        lastClosedEnd.current = event.bar.bar_end_ns;
                                    setLastClosedCursor(event.sequence);
                                }
                                if (merged.changed)
                                    setTiming((value) =>
                                        nextMarketDataTiming(value, event, subscription, ready)
                                    );
                            } catch (error) {
                                terminal = true;
                                close?.();
                                if (error instanceof MarketDataBarLedgerConflictError)
                                    failLedger(error);
                                else apply(error);
                            }
                        } else {
                            if (event.code === "MARKET_DATA_SOURCE_UNAVAILABLE") {
                                // Retire this socket before closing it: its late
                                // disconnect must not schedule a second retry.
                                attempt += 1;
                                ready = false;
                                close?.();
                                setStreamError(event.code);
                                schedule();
                                return;
                            }
                            terminal = true;
                            close?.();
                            setStreamError(event.code);
                            if (
                                event.code === "HISTORY_REFRESH_REQUIRED" ||
                                event.code === "MARKET_DATA_CONTINUITY_UNPROVEN"
                            ) {
                                setWindowFingerprint(null);
                                if (automaticFullRefreshUsed.current) {
                                    setRealtimeStatus("failed");
                                    setStreamError("MARKET_DATA_REFRESH_EXHAUSTED");
                                    setMessage(
                                        "临时行情完整刷新后仍无法证明连续；保留旧行情，请明确重新读取。"
                                    );
                                } else {
                                    automaticFullRefreshUsed.current = true;
                                    void load(
                                        reference,
                                        resolvedSourceId,
                                        instrument,
                                        barSemantic,
                                        ++historyGeneration.current,
                                        true
                                    );
                                }
                            } else if (event.code === "MARKET_DATA_ACCESS_DENIED")
                                apply(new MarketDataWebError(event.code, "行情授权已撤销", 403));
                            else {
                                setRealtimeStatus("failed");
                                if (
                                    [
                                        "MARKET_DATA_IDENTITY_CONFLICT",
                                        "MARKET_DATA_PROVENANCE_CONFLICT",
                                        "MARKET_DATA_SOURCE_CATALOG_CORRUPT"
                                    ].includes(event.code)
                                )
                                    apply(
                                        new MarketDataWebError(event.code, "临时行情完整性验证失败")
                                    );
                            }
                        }
                    },
                    (failure) => {
                        if (!current(incarnation)) return;
                        attempt += 1;
                        ready = false;
                        if (failure !== undefined) {
                            terminal = true;
                            setStreamError(failure);
                            setRealtimeStatus("failed");
                            if (failure === "AUTHENTICATION_ERROR")
                                apply(
                                    new MarketDataWebError(
                                        "MARKET_DATA_ACCESS_DENIED",
                                        "行情授权已撤销",
                                        403
                                    )
                                );
                            else apply(new MarketDataWebError(failure, "临时行情协议验证失败"));
                            return;
                        }
                        schedule();
                    },
                    credentials
                );
            } catch (error) {
                if (!current(incarnation)) return;
                if (
                    error instanceof MarketDataWebError &&
                    (error.status === 401 || error.status === 403)
                ) {
                    terminal = true;
                    apply(error);
                    return;
                }
                setStreamError(
                    error instanceof MarketDataWebError ? error.code : "TRANSPORT_ERROR"
                );
                schedule();
            }
        };
        queueMicrotask(() => {
            if (!stopped) {
                setStreamId(null);
                setStreamError(null);
                void connect(false);
            }
        });
        return () => {
            stopped = true;
            controller.abort();
            streamGeneration.current += 1;
            if (timer !== undefined) window.clearTimeout(timer);
            close?.();
        };
    }, [
        apply,
        barSemantic,
        credentials,
        failLedger,
        instrument,
        load,
        pageId,
        reference,
        resolvedSourceId,
        selectedSource,
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
        olderAbort.current?.abort();
        olderNoProgress.current = null;
        setLedgerSnapshot(null);
        setOlderHistoryStatus("idle");
        setOlderHistoryMessage(null);
        setWindowFingerprint(null);
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
        if (startup === "pending") return;
        const controller = new AbortController();
        client
            .listSources(controller.signal)
            .then((found) => {
                if (controller.signal.aborted) return;
                if (new Set(found.map(marketDataSourceChoiceKey)).size !== found.length)
                    throw new MarketDataWebError(
                        "CONTRACT_ERROR",
                        "数据源 exact Revision reference 重复"
                    );
                setSources((current) =>
                    found.map((item) => {
                        const previous = current.find(
                            (source) =>
                                marketDataSourceChoiceKey(source) ===
                                marketDataSourceChoiceKey(item)
                        );
                        return previous !== undefined &&
                            JSON.stringify(previous) === JSON.stringify(item)
                            ? previous
                            : item;
                    })
                );
                setCatalogStatus("ready");
                // Preserve a user's exact still-available choice, not a new default
                // or an old response's choice after management changed the catalog.
                if (
                    watchlistSourceRef.current !== null ||
                    found.some(
                        (item) => marketDataSourceChoiceKey(item) === selectedSourceId.current
                    )
                )
                    return;
                if (selectedSourceId.current !== "") {
                    historyAbort.current?.abort();
                    streamGeneration.current += 1;
                    ledger.current = null;
                    setLedgerSnapshot(null);
                    setWindowFingerprint(null);
                    setStatus("failed");
                    setRealtimeStatus("disabled");
                    setMessage("原数据源 Revision 已不可用，请明确重新选择来源，不会自动换源。");
                    return;
                }
                if (startup !== "default") return;
                const matches = found.filter(
                    (item) =>
                        item.is_current_revision &&
                        item.type_id === DEFAULT_SOURCE_TYPE &&
                        item.environment === DEFAULT_SOURCE_ENVIRONMENT
                );
                if (matches.length === 1 && matches[0] !== undefined)
                    selectSource(marketDataSourceChoiceKey(matches[0]));
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
                setCatalogStatus("failed");
                setSources([]);
                // Keep the exact unavailable choice across a catalog transport failure.
                apply(error);
                if (error instanceof MarketDataWebError && error.code === "TRANSPORT_ERROR")
                    setMessage("行情服务不可用：TRANSPORT_ERROR");
            });
        return () => {
            controller.abort();
        };
    }, [apply, client, selectSource, sourceRefresh, startup]);

    useEffect(() => {
        // Manual selections remain valid; the Binance default resolves an actual instrument,
        // never a locally authored DTO or a first-row substitute.
        if (
            startup !== "default" ||
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
    }, [apply, client, instrument, load, selectedSource, startup]);

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

    const selectExactContext = useCallback(
        async (
            active: MarketDataSourceReference,
            instrumentId: string,
            semantic: MarketDataBarSemantic
        ) => {
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
                setMessage("绑定的数据源不可用；请明确重新绑定，不会自动换源");
                return false;
            }
            if (
                reference?.integration_id === active.integration_id &&
                reference.integration_revision_fingerprint ===
                    active.integration_revision_fingerprint &&
                reference.expected_type_id === active.expected_type_id &&
                instrument?.instrument_id === instrumentId &&
                JSON.stringify(barSemantic) === JSON.stringify(semantic) &&
                status === "ready" &&
                realtimeStatus !== "failed"
            )
                return true;
            const minutes =
                semantic.formation.kind === "FIXED_DURATION"
                    ? semantic.formation.window_minutes
                    : 0;
            if (
                minutes < source.time_bar_capability.minimum_window_minutes ||
                minutes > source.time_bar_capability.maximum_window_minutes
            ) {
                setMessage("该数据源不支持当前图表周期；请先明确修改周期");
                return false;
            }
            try {
                const found = await client.listInstruments(active, "", undefined, [instrumentId]);
                if (search !== searchGeneration.current || history !== historyGeneration.current)
                    return false;
                const target = found.find((item) => item.instrument_id === instrumentId);
                if (found.length !== 1 || target === undefined)
                    throw new MarketDataWebError("CONTRACT_ERROR", "未取得 exact 自选标的");
                selectSource(marketDataSourceChoiceKey(source), true);
                watchlistSourceRef.current = active;
                setWatchlistSource(active);
                streamGeneration.current++;
                const generation = ++historyGeneration.current;
                setLastClosedCursor(null);
                resume.current = null;
                setStreamId(null);
                setStreamError(null);
                setRealtimeStatus("disabled");
                setBarSemantic(semantic);
                setInstrument(target);
                await load(active, source.source_id, target, semantic, generation);
                return true;
            } catch (error) {
                if (search === searchGeneration.current) apply(error);
                return false;
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

    const selectWatchlistInstrument = useCallback(
        async (source: MarketDataSourceReference, instrumentId: string) => {
            await selectExactContext(source, instrumentId, barSemantic);
        },
        [barSemantic, selectExactContext]
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
            olderAbort.current?.abort();
            olderNoProgress.current = null;
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

    const loadOlderHistory = useCallback(
        async (manual = false) => {
            const active = ledger.current,
                before = active?.snapshot().earliestStartNs ?? null;
            if (
                active === null ||
                before === null ||
                reference === null ||
                selectedSource === null ||
                instrument === null ||
                (olderAbort.current !== null && !olderAbort.current.signal.aborted) ||
                (!manual && olderNoProgress.current === before)
            )
                return;
            const controller = new AbortController();
            olderAbort.current = controller;
            const current = () => !controller.signal.aborted && ledger.current === active;
            setOlderHistoryStatus("loading");
            setOlderHistoryMessage(null);
            try {
                let added = 0;
                const result = await loadTemporaryMarketDataWindow(
                    credentials,
                    reference,
                    {
                        instrument_id: instrument.instrument_id,
                        bar_semantic: barSemantic,
                        anchor_kind: "BEFORE_TIME",
                        before_ns: before,
                        target_bar_count: 240
                    },
                    pageId,
                    {
                        sourceId: selectedSource.source_id,
                        environment: selectedSource.environment,
                        signal: controller.signal,
                        onWindow: (window) => {
                            if (!current()) return;
                            const snapshot = active.snapshot();
                            admitMarketDataChartBars([...snapshot.closedBars, ...window.bars]);
                            const merged = active.mergeHistory(window.bars, window.resolved_end_ns);
                            added += merged.prependedCount;
                            if (merged.changed) setLedgerSnapshot(merged.snapshot);
                        }
                    }
                );
                if (!current()) return;
                olderNoProgress.current = added === 0 ? before : null;
                setOlderHistoryStatus(added === 0 ? "empty" : "idle");
                setOlderHistoryMessage(
                    result.coverage.status === "COMPLETE"
                        ? null
                        : "较早临时行情仍有缺口，可明确重试。"
                );
            } catch (error) {
                if (!current()) return;
                if (error instanceof MarketDataBarLedgerConflictError) failLedger(error);
                else {
                    // A page-local failure does not contradict the retained
                    // window. A formal denial or unknown shared proof does.
                    if (
                        error instanceof MarketDataBarsAuthorityMismatchError ||
                        (error instanceof MarketDataWebError &&
                            ([401, 403, 409].includes(error.status ?? 0) ||
                                ![
                                    "TRANSPORT_ERROR",
                                    "MARKET_DATA_SOURCE_TIMEOUT",
                                    "MARKET_DATA_SOURCE_UNAVAILABLE",
                                    "MARKET_DATA_REQUEST_INVALID",
                                    "MARKET_DATA_WINDOW_NOT_CLOSED"
                                ].includes(error.code)))
                    )
                        apply(error);
                    setOlderHistoryStatus("failed");
                    setOlderHistoryMessage(
                        error instanceof Error ? error.message : "较早行情加载失败"
                    );
                }
            } finally {
                controller.abort();
                if (olderAbort.current === controller) olderAbort.current = null;
            }
        },
        [apply, barSemantic, credentials, failLedger, instrument, pageId, reference, selectedSource]
    );

    return {
        catalogStatus,
        restoreSelection: selectExactContext,
        pageId,
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
        pageReloadRequired,
        coverage,
        chartContextKey,
        bars,
        loadedClosedBarCount: ledgerSnapshot?.closedBars.length ?? 0,
        windowFingerprint,
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
