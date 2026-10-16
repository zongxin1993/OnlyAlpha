import { useCallback, useEffect, useRef, useState } from "react";
import { type MarketQuote } from "../../api/marketData/discovery";
import type { MarketDataSource, MarketDataSourceReference } from "../../api/marketData/model";
import type { WatchlistMember } from "../../api/watchlists/client";
import type { MarketDataApiClient } from "../../api/marketData/client";
import { createUuidV4 } from "../../api/integrations/submissionIntent";
import { watchlistMemberKey, type WatchlistController } from "./useWatchlists";
import "./watchlists.css";

const sourceFor = (sources: readonly MarketDataSource[], member: WatchlistMember) =>
    sources.find(
        (source) =>
            source.integration_id === member.source.integration_id &&
            source.integration_revision_fingerprint ===
                member.source.integration_revision_fingerprint &&
            source.type_id === member.source.expected_type_id
    );
/** Display exact decimals without rounding or altering the provider observation. */
function quoteDisplay(value: string): string {
    const match = /^(-?\d+)(?:\.(\d+))?$/.exec(value);
    if (match?.[1] === undefined) return value;
    return `${match[1]}.${(match[2] ?? "").replace(/0+$/, "").padEnd(2, "0")}`;
}

interface Price {
    quote: MarketQuote | null;
    status: string;
}

export function WatchlistPanel({
    controller,
    market,
    sources,
    enabled,
    onSelect,
    onSearch
}: {
    readonly controller: WatchlistController;
    readonly market: Pick<MarketDataApiClient, "queryQuotes">;
    readonly sources: readonly MarketDataSource[];
    readonly enabled: boolean;
    readonly onSelect: (
        source: MarketDataSourceReference,
        instrumentId: string
    ) => void | Promise<void>;
    readonly onSearch: () => void;
}) {
    const { book, active, busy, pending, message, save } = controller;
    const [name, setName] = useState("");
    const [rename, setRename] = useState("");
    const [pageVisible, setPageVisible] = useState(document.visibilityState !== "hidden");
    const [visible, setVisible] = useState<ReadonlySet<string>>(() => new Set());
    const [prices, setPrices] = useState<ReadonlyMap<string, Price>>(() => new Map());
    const onVisibility = useCallback((key: string, shown: boolean) => {
        setVisible((current) => {
            if (current.has(key) === shown) return current;
            const next = new Set(current);
            if (shown) next.add(key);
            else next.delete(key);
            return next;
        });
    }, []);
    useEffect(() => {
        const changed = () => {
            setPageVisible(document.visibilityState !== "hidden");
        };
        document.addEventListener("visibilitychange", changed);
        return () => {
            document.removeEventListener("visibilitychange", changed);
        };
    }, []);
    useEffect(() => {
        if (!enabled || !pageVisible || active === undefined) return;
        const controller = new AbortController();
        let timer: number | undefined;
        const cancelled = () => controller.signal.aborted;
        const membership = new Set(active.members.map(watchlistMemberKey));
        // A single serialized cycle batches visible members by exact Source (25 per Query).
        const refresh = async () => {
            const groups = new Map<MarketDataSource, WatchlistMember[]>();
            for (const member of active.members) {
                if (!visible.has(watchlistMemberKey(member))) continue;
                const source = sourceFor(sources, member);
                if (source !== undefined)
                    groups.set(source, [...(groups.get(source) ?? []), member]);
            }
            for (const [source, members] of groups)
                for (let offset = 0; offset < members.length; offset += 25) {
                    if (cancelled()) return;
                    const batch = members.slice(offset, offset + 25);
                    setPrices((previous) => {
                        const next = new Map([...previous].filter(([key]) => membership.has(key)));
                        for (const member of batch)
                            next.set(watchlistMemberKey(member), {
                                quote: previous.get(watchlistMemberKey(member))?.quote ?? null,
                                status: "正在更新，显示上次报价"
                            });
                        return next;
                    });
                    try {
                        const result = await market.queryQuotes(
                            source,
                            batch.map((member) => member.instrument_id),
                            AbortSignal.any([controller.signal, AbortSignal.timeout(12_000)])
                        );
                        if (cancelled()) return;
                        setPrices((previous) => {
                            const next = new Map(
                                [...previous].filter(([key]) => membership.has(key))
                            );
                            for (const member of batch) {
                                const quote =
                                    result.quotes.find(
                                        (item) => item.instrument_id === member.instrument_id
                                    ) ?? null;
                                next.set(watchlistMemberKey(member), {
                                    quote,
                                    status:
                                        quote?.status === "AVAILABLE"
                                            ? ""
                                            : result.status === "TIMEOUT"
                                              ? "报价超时"
                                              : result.status === "UNSUPPORTED"
                                                ? "此来源不支持报价"
                                                : result.status === "UNAVAILABLE"
                                                  ? "行情来源暂不可用"
                                                  : "暂无报价"
                                });
                            }
                            return next;
                        });
                    } catch {
                        if (cancelled()) return;
                        setPrices((previous) => {
                            const next = new Map(
                                [...previous].filter(([key]) => membership.has(key))
                            );
                            for (const member of batch)
                                next.set(watchlistMemberKey(member), {
                                    quote: previous.get(watchlistMemberKey(member))?.quote ?? null,
                                    status: "更新失败，报价可能已过期"
                                });
                            return next;
                        });
                    }
                }
            if (!cancelled()) timer = window.setTimeout(() => void refresh(), 15_000);
        };
        void refresh();
        return () => {
            controller.abort();
            window.clearTimeout(timer);
        };
    }, [active, market, enabled, pageVisible, sources, visible]);
    const blocked = busy || pending !== null || book === null;
    return (
        <section className="watchlists" aria-label="自选行情">
            <header className="watchlists__header">
                {active === undefined ? (
                    <strong>自选</strong>
                ) : (
                    <select
                        aria-label="自选列表"
                        value={active.list_id}
                        onChange={(event) => {
                            controller.setSelected(event.target.value);
                        }}
                    >
                        {book?.lists.map((list) => (
                            <option key={list.list_id} value={list.list_id}>
                                {list.name}
                            </option>
                        ))}
                    </select>
                )}
                <button
                    type="button"
                    className="watchlists__icon"
                    aria-label="搜索并添加商品"
                    onClick={onSearch}
                >
                    ＋
                </button>
                <details className="watchlists__manage">
                    <summary aria-label="管理自选列表">⋯</summary>
                    <div className="watchlists__menu">
                        <button
                            type="button"
                            disabled={busy}
                            onClick={() => void controller.reload()}
                        >
                            重新加载自选
                        </button>
                        <form
                            onSubmit={(event) => {
                                event.preventDefault();
                                if (book !== null && name.trim())
                                    void save([
                                        ...book.lists,
                                        { list_id: createUuidV4(), name: name.trim(), members: [] }
                                    ]).then((saved) => {
                                        if (saved) setName("");
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
                                    disabled={blocked}
                                />
                            </label>
                            <button type="submit" disabled={blocked || !name.trim()}>
                                创建列表
                            </button>
                        </form>
                        {active === undefined ? null : (
                            <>
                                <form
                                    onSubmit={(event) => {
                                        event.preventDefault();
                                        if (book !== null && rename.trim())
                                            void save(
                                                book.lists.map((list) =>
                                                    list.list_id === active.list_id
                                                        ? { ...list, name: rename.trim() }
                                                        : list
                                                )
                                            ).then((saved) => {
                                                if (saved) setRename("");
                                            });
                                    }}
                                >
                                    <label>
                                        列表新名称
                                        <input
                                            value={rename}
                                            maxLength={64}
                                            placeholder={active.name}
                                            disabled={blocked}
                                            onChange={(event) => {
                                                setRename(event.target.value);
                                            }}
                                        />
                                    </label>
                                    <button type="submit" disabled={blocked || !rename.trim()}>
                                        重命名列表
                                    </button>
                                </form>
                                <button
                                    type="button"
                                    disabled={blocked}
                                    onClick={() => {
                                        if (
                                            book !== null &&
                                            window.confirm(
                                                `删除列表“${active.name}”？行情历史将保留。`
                                            )
                                        )
                                            void save(
                                                book.lists.filter(
                                                    (list) => list.list_id !== active.list_id
                                                )
                                            );
                                    }}
                                >
                                    删除列表
                                </button>
                            </>
                        )}
                    </div>
                </details>
            </header>
            {message === null ? (
                book === null ? (
                    <p role="status">正在加载自选…</p>
                ) : null
            ) : (
                <p className="watchlists__status" role={message === "已保存" ? "status" : "alert"}>
                    {message}
                </p>
            )}
            {pending === null ? null : (
                <button
                    type="button"
                    disabled={busy}
                    onClick={() => void controller.resolvePending()}
                >
                    核对提交结果
                </button>
            )}
            {active === undefined ? (
                <p className="panel-note">还没有自选，在搜索结果中点 ☆ 添加。</p>
            ) : (
                <div className="watchlists__rows">
                    <table className="data-table">
                        <caption className="visually-hidden">{active.name}</caption>
                        <thead>
                            <tr>
                                <th>商品</th>
                                <th>最新价</th>
                                <th title="股票等较上一交易日收盘；加密现货为24小时变动。具体以行详情为准。">
                                    涨跌幅
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {active.members.map((member, index) => {
                                const key = watchlistMemberKey(member);
                                return (
                                    <WatchlistRow
                                        key={key}
                                        member={member}
                                        source={sourceFor(sources, member)}
                                        price={prices.get(key)}
                                        current={enabled && pageVisible && visible.has(key)}
                                        onVisibility={onVisibility}
                                        onSelect={() =>
                                            onSelect(member.source, member.instrument_id)
                                        }
                                        blocked={blocked}
                                        onRemove={() => void controller.toggle(member)}
                                        onMove={(delta) => {
                                            if (book === null) return;
                                            const target = index + delta;
                                            if (target < 0 || target >= active.members.length)
                                                return;
                                            const members = [...active.members];
                                            members.splice(index, 1);
                                            members.splice(target, 0, member);
                                            void save(
                                                book.lists.map((list) =>
                                                    list.list_id === active.list_id
                                                        ? { ...list, members }
                                                        : list
                                                )
                                            );
                                        }}
                                        first={index === 0}
                                        last={index === active.members.length - 1}
                                    />
                                );
                            })}
                        </tbody>
                    </table>
                    {active.members.length === 0 ? (
                        <p className="panel-note">列表为空，在搜索结果中点 ☆ 添加。</p>
                    ) : null}
                </div>
            )}
        </section>
    );
}

function WatchlistRow({
    member,
    source,
    price,
    current,
    onVisibility,
    onSelect,
    onRemove,
    onMove,
    blocked,
    first,
    last
}: {
    readonly member: WatchlistMember;
    readonly source: MarketDataSource | undefined;
    readonly price: Price | undefined;
    readonly current: boolean;
    readonly onVisibility: (key: string, visible: boolean) => void;
    readonly onSelect: () => void | Promise<void>;
    readonly onRemove: () => void;
    readonly onMove: (delta: number) => void;
    readonly blocked: boolean;
    readonly first: boolean;
    readonly last: boolean;
}) {
    const element = useRef<HTMLTableRowElement>(null);
    const key = watchlistMemberKey(member);
    useEffect(() => {
        const node = element.current;
        if (node === null) return;
        if (typeof IntersectionObserver === "undefined") {
            onVisibility(key, true);
            return () => {
                onVisibility(key, false);
            };
        }
        const observer = new IntersectionObserver(([entry]) => {
            onVisibility(key, entry?.isIntersecting ?? false);
        });
        observer.observe(node);
        return () => {
            observer.disconnect();
            onVisibility(key, false);
        };
    }, [key, onVisibility]);
    const quote = price?.quote;
    const time =
        quote?.ts_event_ns == null
            ? null
            : new Date(Number(BigInt(quote.ts_event_ns) / 1_000_000n));
    const timeCopy =
        time === null || !Number.isFinite(time.getTime()) ? "无报价时间" : time.toISOString();
    const status =
        source === undefined
            ? "来源不可用"
            : !current
              ? "未更新，报价可能已过期"
              : (price?.status ?? "正在读取报价…");
    const basis =
        quote?.change_basis === "ROLLING_24H"
            ? "24小时变动"
            : quote?.change_basis === "PREVIOUS_CLOSE"
              ? "较上一交易日收盘"
              : "暂无变动基准";
    const symbol = member.instrument_id.slice(0, member.instrument_id.lastIndexOf("."));
    return (
        <tr
            ref={element}
            data-testid="watchlist-row"
            title={`${member.instrument_id} · ${source?.display_name ?? "来源不可用"} · ${timeCopy} · ${basis} · 原始报价 ${quote?.last_price ?? "—"}`}
        >
            <td>
                <button
                    type="button"
                    className="watchlists__symbol"
                    disabled={source === undefined}
                    onClick={() => void onSelect()}
                >
                    {symbol}
                </button>
                <small>{source?.display_name ?? "来源不可用"}</small>
                <details className="watchlists__row-menu">
                    <summary aria-label={`管理 ${member.instrument_id}`}>⋯</summary>
                    <div>
                        <button
                            type="button"
                            disabled={blocked || first}
                            onClick={() => {
                                onMove(-1);
                            }}
                        >
                            上移
                        </button>
                        <button
                            type="button"
                            disabled={blocked || last}
                            onClick={() => {
                                onMove(1);
                            }}
                        >
                            下移
                        </button>
                        <button type="button" disabled={blocked} onClick={onRemove}>
                            移出自选
                        </button>
                    </div>
                </details>
            </td>
            <td>
                <span className="value">
                    {quote?.last_price == null ? "—" : quoteDisplay(quote.last_price)}
                </span>
                {status ? <small role="status">{status}</small> : null}
            </td>
            <td
                title={basis}
                className={
                    quote?.change_pct?.startsWith("-") ? "watchlists__down" : "watchlists__up"
                }
            >
                {quote?.change_pct == null ? "—" : `${quote.change_pct}%`}
            </td>
        </tr>
    );
}
