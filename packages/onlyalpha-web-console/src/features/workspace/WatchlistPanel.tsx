import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocalReadCredentials, useMarketDataApi } from "../../app/providers";
import { MarketDataWebError } from "../../api/marketData/client";
import { createUuidV4 } from "../../api/integrations/submissionIntent";
import {
    marketDataBarSemanticSchema,
    type MarketDataInstrument,
    type MarketDataSource,
    type MarketDataSourceReference
} from "../../api/marketData/model";
import {
    FetchWatchlistApiClient,
    WatchlistWebError,
    type Watchlist,
    type WatchlistBook,
    type WatchlistSave
} from "../../api/watchlists/client";
import { onlyMarketDataSourceReference } from "./useMarketDataChart";
import { onlyAssertMarketDataBarsAuthority } from "./marketDataBarsAuthority";
import "./watchlists.css";

let quoteReads: Promise<unknown> = Promise.resolve();
const PENDING = "onlyalpha.watchlist.pending-command";
function readPending(): string | null {
    try {
        return sessionStorage.getItem(PENDING);
    } catch {
        return null;
    }
}
function forgetPending(): void {
    try {
        sessionStorage.removeItem(PENDING);
    } catch {
        /* A retained ID remains queryable after storage recovers. */
    }
}
const errorCopy = (error: unknown, submitting = false): string =>
    error instanceof WatchlistWebError
        ? error.code === "WATCHLIST_VERSION_CONFLICT"
            ? "其他窗口已修改自选，请重新加载后再编辑。"
            : error.code === "WATCHLIST_INVALID"
              ? "未保存：请检查名称是否重复，或列表、成员数量是否超过上限。"
              : error.code === "WATCHLIST_OWNER_REQUIRED" ||
                  /FORBIDDEN|UNAUTHORIZED/.test(error.code)
                ? "自选管理需要 Owner 授权；行情只读凭据不能修改列表。"
                : error.definitive
                  ? `未保存：${error.code}`
                  : submitting
                    ? "提交结果未知，请核对提交结果；不会自动重试。"
                    : "自选服务暂不可用，请重新加载。"
        : "服务响应不可用，请重新加载；提交操作需先核对结果。";

export function WatchlistPanel({
    sources,
    enabled,
    onSelect,
    onPrepare,
    onRefreshSources
}: {
    readonly sources: readonly MarketDataSource[];
    readonly enabled: boolean;
    readonly onRefreshSources?: () => void;
    readonly onSelect: (
        source: MarketDataSourceReference,
        instrumentId: string
    ) => Promise<void> | void;
    readonly onPrepare: (
        source: MarketDataSourceReference,
        instrumentId: string
    ) => Promise<void> | void;
}) {
    const [pageVisible, setPageVisible] = useState(document.visibilityState !== "hidden");
    useEffect(() => {
        const changed = () => {
            setPageVisible(document.visibilityState !== "hidden");
        };
        document.addEventListener("visibilitychange", changed);
        return () => {
            document.removeEventListener("visibilitychange", changed);
        };
    }, []);
    const credentials = useLocalReadCredentials();
    const api = useMemo(() => new FetchWatchlistApiClient(credentials), [credentials]);
    const market = useMarketDataApi();
    const [book, setBook] = useState<WatchlistBook | null>(null);
    const [selected, setSelected] = useState("");
    const [name, setName] = useState("");
    const [sourceId, setSourceId] = useState("");
    const [rename, setRename] = useState("");
    const [query, setQuery] = useState("");
    const [results, setResults] = useState<readonly MarketDataInstrument[]>([]);
    const [resultsOwner, setResultsOwner] = useState("");
    const [message, setMessage] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const writing = useRef(false);
    const searchGeneration = useRef(0);
    const [pending, setPending] = useState<string | null>(readPending);
    const bookGeneration = useRef(0);
    const active = book?.lists.find((item) => item.list_id === selected) ?? book?.lists[0];
    const source = sources.find(
        (item) =>
            item.integration_id === active?.source.integration_id &&
            item.integration_revision_fingerprint ===
                active.source.integration_revision_fingerprint &&
            item.type_id === active.source.expected_type_id
    );
    const contextKey = active === undefined ? "" : active.list_id + JSON.stringify(active.source);
    const reload = useCallback(async () => {
        const generation = ++bookGeneration.current;
        try {
            const value = await api.read();
            if (generation === bookGeneration.current) {
                setBook(value);
                setMessage(null);
            }
        } catch (error) {
            if (generation === bookGeneration.current) setMessage(errorCopy(error));
        }
    }, [api]);
    useEffect(() => {
        const controller = new AbortController();
        const generation = ++bookGeneration.current;
        void api
            .read(controller.signal)
            .then((value) => {
                if (!controller.signal.aborted && generation === bookGeneration.current)
                    setBook(value);
            })
            .catch((error: unknown) => {
                if (!controller.signal.aborted && generation === bookGeneration.current)
                    setMessage(errorCopy(error));
            });
        return () => {
            controller.abort();
        };
    }, [api]);
    const save = async (lists: readonly Watchlist[]) => {
        if (book === null || writing.current || pending !== null) return false;
        writing.current = true;
        setBusy(true);
        setMessage(null);
        const intent: WatchlistSave = {
            schema_version: 1,
            command_id: createUuidV4(),
            expected_version: book.version,
            lists
        };
        try {
            sessionStorage.setItem(PENDING, intent.command_id);
        } catch {
            setMessage("无法保存本次提交标识，本次未提交；请检查站点会话存储权限。");
            writing.current = false;
            setBusy(false);
            return false;
        }
        ++bookGeneration.current;
        setPending(intent.command_id);
        try {
            const saved = await api.save(intent);
            setBook(saved);
            setPending(null);
            forgetPending();
            setMessage("已保存");
            return true;
        } catch (error) {
            setMessage(errorCopy(error, true));
            if (error instanceof WatchlistWebError && error.definitive) {
                setPending(null);
                forgetPending();
            }
            return false;
        } finally {
            writing.current = false;
            setBusy(false);
        }
    };
    const replace = (value: Watchlist) =>
        save(book?.lists.map((item) => (item.list_id === value.list_id ? value : item)) ?? []);
    const search = async () => {
        if (active === undefined || source === undefined) return;
        const generation = ++searchGeneration.current;
        setResults([]);
        setMessage("正在搜索标的…");
        try {
            const found = await market.listInstruments(active.source, query);
            if (generation === searchGeneration.current) {
                setResultsOwner(contextKey);
                setResults(found);
                setMessage(found.length === 0 ? "未找到匹配标的" : null);
            }
        } catch {
            if (generation === searchGeneration.current) setMessage("标的搜索失败，请重试。");
        }
    };
    return (
        <section className="watchlists" aria-label="自选列表管理">
            <div
                className="watchlists__status"
                role={message !== null && message !== "已保存" ? "alert" : "status"}
            >
                {message ?? (book === null ? "正在加载自选…" : "列表保存在服务端")}
            </div>
            <button type="button" disabled={busy} onClick={() => void reload()}>
                重新加载自选
            </button>
            {pending !== null ? (
                <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                        setBusy(true);
                        void api
                            .command(pending)
                            .then(async (result) => {
                                const latest = await api.read();
                                setBook(latest);
                                setPending(null);
                                forgetPending();
                                setMessage(
                                    result === null
                                        ? "命令未提交，已重新读取服务端列表。"
                                        : "提交结果已确认，已重新读取服务端列表。"
                                );
                            })
                            .catch((error: unknown) => {
                                setMessage(errorCopy(error));
                            })
                            .finally(() => {
                                setBusy(false);
                            });
                    }}
                >
                    核对提交结果
                </button>
            ) : null}
            {book === null ? null : (
                <fieldset disabled={busy || pending !== null}>
                    <legend>管理自选列表</legend>
                    {onRefreshSources !== undefined && (
                        <button type="button" onClick={onRefreshSources}>
                            刷新行情来源
                        </button>
                    )}
                    <form
                        onSubmit={(event) => {
                            event.preventDefault();
                            const target = sources.find((item) => item.integration_id === sourceId);
                            if (target === undefined || !name.trim()) return;
                            const list: Watchlist = {
                                list_id: createUuidV4(),
                                name: name.trim(),
                                source: {
                                    ...onlyMarketDataSourceReference(target),
                                    expected_type_id: target.type_id
                                },
                                instrument_ids: []
                            };
                            void save([...book.lists, list]).then((saved) => {
                                if (saved) {
                                    setSelected(list.list_id);
                                    setName("");
                                }
                            });
                        }}
                    >
                        <label>
                            新列表名称
                            <input
                                value={name}
                                maxLength={64}
                                onChange={(event) => {
                                    setName(event.target.value);
                                }}
                            />
                        </label>
                        <label>
                            列表行情来源
                            <select
                                value={sourceId}
                                onChange={(event) => {
                                    setSourceId(event.target.value);
                                }}
                            >
                                <option value="">选择数据源</option>
                                {sources.map((item) => (
                                    <option key={item.integration_id} value={item.integration_id}>
                                        {item.display_name}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <button
                            type="submit"
                            disabled={!name.trim() || sourceId === "" || book.lists.length >= 20}
                        >
                            创建列表
                        </button>
                    </form>
                    {book.lists.length === 0 ? <p>还没有自选列表，请先创建。</p> : null}
                    {active === undefined ? null : (
                        <>
                            <label>
                                自选列表
                                <select
                                    value={active.list_id}
                                    onChange={(event) => {
                                        searchGeneration.current++;
                                        setSelected(event.target.value);
                                        setResults([]);
                                        setQuery("");
                                        setRename("");
                                        setMessage(null);
                                    }}
                                >
                                    {book.lists.map((item) => (
                                        <option key={item.list_id} value={item.list_id}>
                                            {item.name}
                                        </option>
                                    ))}
                                </select>
                            </label>
                            <form
                                onSubmit={(event) => {
                                    event.preventDefault();
                                    if (rename.trim())
                                        void replace({ ...active, name: rename.trim() });
                                }}
                            >
                                <label>
                                    列表新名称
                                    <input
                                        value={rename}
                                        maxLength={64}
                                        placeholder={active.name}
                                        onChange={(event) => {
                                            setRename(event.target.value);
                                        }}
                                    />
                                </label>
                                <button type="submit" disabled={!rename.trim()}>
                                    重命名列表
                                </button>
                            </form>
                            <button
                                type="button"
                                onClick={() => {
                                    if (
                                        window.confirm(`删除列表“${active.name}”？行情历史将保留。`)
                                    )
                                        void save(
                                            book.lists.filter(
                                                (item) => item.list_id !== active.list_id
                                            )
                                        );
                                }}
                            >
                                删除列表
                            </button>
                            <p>数据源：{source?.display_name ?? "原数据源不可用，列表已保留"}</p>
                            {source === undefined ? (
                                <label>
                                    重新选择行情来源
                                    <select
                                        value=""
                                        onChange={(event) => {
                                            const target = sources.find(
                                                (item) => item.integration_id === event.target.value
                                            );
                                            if (
                                                target !== undefined &&
                                                window.confirm(
                                                    "明确改用所选数据源？服务器将验证全部成员。"
                                                )
                                            )
                                                void replace({
                                                    ...active,
                                                    source: {
                                                        ...onlyMarketDataSourceReference(target),
                                                        expected_type_id: target.type_id
                                                    }
                                                });
                                        }}
                                    >
                                        <option value="">选择可用数据源</option>
                                        {sources.map((item) => (
                                            <option
                                                key={item.integration_id}
                                                value={item.integration_id}
                                            >
                                                {item.display_name}
                                            </option>
                                        ))}
                                    </select>
                                </label>
                            ) : null}
                            <form
                                onSubmit={(event) => {
                                    event.preventDefault();
                                    void search();
                                }}
                            >
                                <label>
                                    搜索自选标的
                                    <input
                                        value={query}
                                        onChange={(event) => {
                                            setQuery(event.target.value);
                                        }}
                                        disabled={source === undefined}
                                    />
                                </label>
                                <button
                                    type="submit"
                                    disabled={!query.trim() || source === undefined}
                                >
                                    查找标的
                                </button>
                            </form>
                            <ul aria-label="自选标的搜索结果">
                                {(resultsOwner === contextKey ? results : []).map((item) => (
                                    <li key={item.instrument_id}>
                                        {item.display_symbol} · {item.venue}
                                        <button
                                            type="button"
                                            disabled={
                                                active.instrument_ids.includes(
                                                    item.instrument_id
                                                ) || active.instrument_ids.length >= 100
                                            }
                                            onClick={() =>
                                                void replace({
                                                    ...active,
                                                    instrument_ids: [
                                                        ...active.instrument_ids,
                                                        item.instrument_id
                                                    ]
                                                })
                                            }
                                        >
                                            {active.instrument_ids.includes(item.instrument_id)
                                                ? "已加入"
                                                : `加入 ${item.display_symbol}`}
                                        </button>
                                    </li>
                                ))}
                            </ul>
                            <div className="watchlists__rows">
                                <table className="data-table">
                                    <caption>{active.name} · 原生 K 线收盘价</caption>
                                    <thead>
                                        <tr>
                                            <th>标的 / 管理</th>
                                            <th>价格 / 状态 / 数据时间</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {active.instrument_ids.map((id, index) => (
                                            <WatchlistRow
                                                key={`${active.list_id}:${id}:${active.source.integration_revision_fingerprint}`}
                                                instrumentId={id}
                                                source={source}
                                                enabled={enabled && pageVisible}
                                                onSelect={() => onSelect(active.source, id)}
                                                onPrepare={() => onPrepare(active.source, id)}
                                                onRemove={() =>
                                                    void replace({
                                                        ...active,
                                                        instrument_ids:
                                                            active.instrument_ids.filter(
                                                                (value) => value !== id
                                                            )
                                                    })
                                                }
                                                onMove={(delta) => {
                                                    const members = [...active.instrument_ids];
                                                    const target = index + delta;
                                                    if (target < 0 || target >= members.length)
                                                        return;
                                                    members.splice(index, 1);
                                                    members.splice(target, 0, id);
                                                    void replace({
                                                        ...active,
                                                        instrument_ids: members
                                                    });
                                                }}
                                                first={index === 0}
                                                last={index === active.instrument_ids.length - 1}
                                            />
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                            {active.instrument_ids.length === 0 ? (
                                <p>列表为空，搜索标的后加入。</p>
                            ) : null}
                        </>
                    )}
                </fieldset>
            )}
        </section>
    );
}

function WatchlistRow({
    instrumentId,
    source,
    enabled,
    onSelect,
    onPrepare,
    onRemove,
    onMove,
    first,
    last
}: {
    readonly instrumentId: string;
    readonly source: MarketDataSource | undefined;
    readonly enabled: boolean;
    readonly onSelect: () => void | Promise<void>;
    readonly onPrepare: () => void | Promise<void>;
    readonly onRemove: () => void;
    readonly onMove: (delta: number) => void;
    readonly first: boolean;
    readonly last: boolean;
}) {
    const market = useMarketDataApi();
    const row = useRef<HTMLTableRowElement>(null);
    const [visible, setVisible] = useState(false);
    const [quote, setQuote] = useState<{ price: string; time: string } | null>(null);
    const [state, setState] = useState("尚未读取");
    const preparing = useRef(false);
    const [nativePreparing, setNativePreparing] = useState(false);
    const [nativeMessage, setNativeMessage] = useState<string | null>(null);
    const [refreshGeneration, setRefreshGeneration] = useState(0);
    const prepareNative = async () => {
        if (source === undefined || preparing.current) return;
        preparing.current = true;
        setNativePreparing(true);
        setNativeMessage("正在检查原生历史覆盖…");
        try {
            const reference = onlyMarketDataSourceReference(source);
            const semantic = source.time_bar_capability.provider_base_semantic;
            const result = await market.queryBars(reference, {
                instrument_id: instrumentId,
                anchor_kind: "LATEST_CLOSED",
                target_bar_count: 1,
                bar_semantic: semantic
            });
            onlyAssertMarketDataBarsAuthority(
                {
                    reference,
                    expectedSourceId: source.source_id,
                    instrumentId,
                    barSemantic: semantic,
                    anchorKind: "LATEST_CLOSED",
                    targetBarCount: 1
                },
                result
            );
            const ranges = result.coverage.planned_acquisition_ranges;
            if (result.coverage.status === "COMPLETE") {
                if (result.bars.length !== 1 || ranges.length !== 0)
                    throw new MarketDataWebError("CONTRACT_ERROR", "原生历史证明不一致");
            } else if (result.coverage.status !== "INCOMPLETE" || ranges.length === 0) {
                throw new MarketDataWebError(
                    "MARKET_DATA_RANGE_EVIDENCE_UNAVAILABLE",
                    "没有可受理的准备范围"
                );
            }
            if (
                ranges.some(
                    (range) =>
                        BigInt(range.start_ns) >= BigInt(range.end_ns) ||
                        BigInt(range.start_ns) < BigInt(result.resolved_start_ns) ||
                        BigInt(range.end_ns) > BigInt(result.resolved_end_ns)
                )
            )
                throw new MarketDataWebError("CONTRACT_ERROR", "原生准备范围超出已证明窗口");
            let pending = false;
            for (const range of result.coverage.planned_acquisition_ranges) {
                const acquired = await market.createAcquisition(reference, {
                    instrument_id: instrumentId,
                    start_ns: range.start_ns,
                    end_ns: range.end_ns,
                    bar_semantic: semantic
                });
                if (
                    acquired.source_id !== source.source_id ||
                    acquired.instrument_id !== instrumentId ||
                    acquired.start_ns !== range.start_ns ||
                    acquired.end_ns !== range.end_ns ||
                    JSON.stringify(marketDataBarSemanticSchema.parse(acquired.bar_semantic)) !==
                        JSON.stringify(marketDataBarSemanticSchema.parse(semantic))
                )
                    throw new MarketDataWebError("CONTRACT_ERROR", "准备结果不匹配原生请求");
                if (acquired.status === "FAILED")
                    throw new MarketDataWebError(
                        "MARKET_DATA_ACQUISITION_FAILED",
                        acquired.failure_detail ?? "原生准备失败"
                    );
                pending ||= acquired.status !== "COMPLETE";
            }
            setNativeMessage(
                pending
                    ? "原生准备尚未完成，可稍后核对或明确准备；价格以已存历史为准。"
                    : "原生准备请求已处理；价格以已存历史为准。"
            );
            setRefreshGeneration((current) => current + 1);
        } catch (error) {
            setNativeMessage(
                `原生行情准备未确认：${error instanceof MarketDataWebError ? error.code : "UNAVAILABLE"}；不会自动重交。`
            );
        } finally {
            preparing.current = false;
            setNativePreparing(false);
        }
    };
    useEffect(() => {
        const element = row.current;
        if (element === null) return;
        const observer = new IntersectionObserver(([entry]) => {
            setVisible(entry?.isIntersecting ?? false);
        });
        observer.observe(element);
        return () => {
            observer.disconnect();
        };
    }, []);
    useEffect(() => {
        if (!enabled || !visible || source === undefined) return;
        const controller = new AbortController();
        let timer: number | undefined;
        const refresh = async () => {
            setState("读取中 / 上次价格可能已过期");
            try {
                const reference = onlyMarketDataSourceReference(source);
                const semantic = source.time_bar_capability.provider_base_semantic;
                const read = quoteReads.then(() => {
                    if (controller.signal.aborted)
                        throw new DOMException("Cancelled", "AbortError");
                    return market.queryLatestBar(
                        reference,
                        instrumentId,
                        semantic,
                        controller.signal
                    );
                });
                quoteReads = read.catch(() => undefined);
                const result = await read;
                if (controller.signal.aborted) return;
                if (result === null) {
                    setQuote(null);
                    setState("暂无已存历史");
                } else {
                    onlyAssertMarketDataBarsAuthority(
                        {
                            reference,
                            expectedSourceId: source.source_id,
                            instrumentId,
                            barSemantic: semantic,
                            anchorKind: "BEFORE_TIME",
                            beforeNs: result.requested_before_ns ?? "",
                            targetBarCount: 1
                        },
                        result
                    );
                    const bar =
                        result.coverage.status === "COMPLETE" ? result.bars.at(-1) : undefined;
                    setQuote(
                        bar === undefined
                            ? null
                            : {
                                  price: bar.close,
                                  time: new Date(
                                      Number(BigInt(bar.bar_end_ns) / 1_000_000n)
                                  ).toISOString()
                              }
                    );
                    setState(bar === undefined ? "历史证明不可用" : "已收盘历史 / 非实时成交价");
                }
            } catch {
                if (!controller.signal.aborted) setState("行情不可用 / 上次价格已过期");
            }
            if (!controller.signal.aborted) timer = window.setTimeout(() => void refresh(), 15_000);
        };
        void refresh();
        return () => {
            controller.abort();
            window.clearTimeout(timer);
        };
    }, [market, source, instrumentId, enabled, visible, refreshGeneration]);
    return (
        <tr ref={row}>
            <td>
                <button
                    type="button"
                    disabled={source === undefined}
                    onClick={() => void onSelect()}
                >
                    {instrumentId}
                </button>
                <div className="watchlists__member-actions">
                    <button
                        type="button"
                        aria-label={`上移 ${instrumentId}`}
                        disabled={first}
                        onClick={() => {
                            onMove(-1);
                        }}
                    >
                        ↑
                    </button>
                    <button
                        type="button"
                        aria-label={`下移 ${instrumentId}`}
                        disabled={last}
                        onClick={() => {
                            onMove(1);
                        }}
                    >
                        ↓
                    </button>
                    <button type="button" aria-label={`移除 ${instrumentId}`} onClick={onRemove}>
                        移除
                    </button>
                </div>
                <button
                    type="button"
                    aria-label={`准备 ${instrumentId} 图表行情`}
                    disabled={source === undefined}
                    onClick={() => void onPrepare()}
                >
                    准备图表行情
                </button>
            </td>
            <td>
                <span className="value">{quote?.price ?? "—"}</span>
                <small>
                    {source === undefined
                        ? "数据源不可用"
                        : !enabled || !visible
                          ? "未更新 / 上次价格可能已过期"
                          : state}
                </small>
                <small>{quote?.time ?? "无数据时间"}</small>
                <button
                    type="button"
                    aria-label={`准备 ${instrumentId} 原生行情`}
                    disabled={source === undefined || nativePreparing}
                    onClick={() => void prepareNative()}
                >
                    准备原生行情
                </button>
                {nativeMessage === null ? null : <small role="status">{nativeMessage}</small>}
            </td>
        </tr>
    );
}
