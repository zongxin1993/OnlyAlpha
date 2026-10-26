import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
    sourceSelectionKey,
    type InstrumentSearch,
    type InstrumentSearchResult
} from "../../api/marketData/discovery";
import type { MarketDataApiClient } from "../../api/marketData/client";
import type { MarketDataSource, MarketDataSourceReference } from "../../api/marketData/model";
import { keepDialogFocus } from "./dialogFocus";
import { watchlistMemberKey, type WatchlistController } from "./useWatchlists";
import "./symbolSearch.css";

const assetLabels: Readonly<Record<string, string>> = {
    EQUITY: "股票",
    FUND: "基金",
    INDEX: "指数",
    COMMODITY: "商品",
    FX: "外汇",
    CRYPTOCURRENCY: "加密货币",
    SYNTHETIC: "合成商品"
};
const categories = [
    { label: "全部", asset: "", types: [] },
    { label: "股票", asset: "EQUITY", types: [] },
    { label: "基金", asset: "FUND", types: [] },
    { label: "期货", asset: "", types: ["FUTURE", "CRYPTO_FUTURE", "CRYPTO_PERPETUAL"] },
    { label: "外汇", asset: "FX", types: [] },
    { label: "加密货币", asset: "CRYPTOCURRENCY", types: [] },
    { label: "指数", asset: "INDEX", types: [] },
    { label: "期权", asset: "", types: ["OPTION"] }
] as const;
const memberFor = (result: InstrumentSearchResult) => ({
    instrument_id: result.instrument.instrument_id,
    source: {
        integration_id: result.source_selection.integration_id,
        integration_revision_fingerprint: result.source_selection.integration_revision_fingerprint,
        expected_type_id: result.source_selection.type_id
    }
});

export function SymbolSearch({
    controller,
    sources,
    onSelect,
    onClose,
    returnFocus,
    market
}: {
    readonly controller: WatchlistController;
    readonly sources: readonly MarketDataSource[];
    readonly onSelect: (source: MarketDataSourceReference, id: string) => void | Promise<void>;
    readonly onClose: () => void;
    readonly returnFocus: HTMLElement | null;
    readonly market: Pick<MarketDataApiClient, "discoverInstruments">;
}) {
    const dialog = useRef<HTMLDialogElement>(null);
    const input = useRef<HTMLInputElement>(null);
    const [query, setQuery] = useState("");
    const [category, setCategory] = useState<(typeof categories)[number]>(categories[0]);
    const [response, setResponse] = useState<InstrumentSearch | null>(null);
    const [status, setStatus] = useState("输入商品代码或名称，搜索可用行情来源。");
    const [revision, setRevision] = useState(0);
    useEffect(() => {
        const node = dialog.current;
        node?.showModal();
        input.current?.focus();
        return () => {
            node?.close();
            if (returnFocus?.isConnected) returnFocus.focus();
        };
    }, [returnFocus]);
    useEffect(() => {
        if (!query.trim()) return;
        const abort = new AbortController();
        const timer = window.setTimeout(() => {
            const signal = AbortSignal.any([abort.signal, AbortSignal.timeout(12_000)]);
            void market
                .discoverInstruments(query.trim(), category.asset, signal, category.types)
                .then((value) => {
                    if (abort.signal.aborted) return;
                    setResponse(value);
                    const failed = value.sources.filter((source) => source.status !== "COMPLETE");
                    setStatus(
                        value.sources.length > 0 &&
                            value.sources.every((source) => source.status === "UNSUPPORTED")
                            ? "当前行情来源不支持商品搜索"
                            : value.sources.length > 0 && failed.length === value.sources.length
                              ? "全部来源查询未完成，请重试或查看来源状态。"
                              : failed.length > 0
                                ? `${String(failed.length)} 个来源暂未完成，已显示可用结果。`
                                : value.truncated
                                  ? "搜索结果未完整显示，请输入更完整的代码或筛选。"
                                  : value.results.length > 0
                                    ? ""
                                    : value.sources.length === 0
                                      ? "没有可搜索的行情来源，请先配置行情来源。"
                                      : category.asset &&
                                          !value.sources.some((source) =>
                                              source.asset_classes.includes(category.asset)
                                          )
                                        ? "当前没有支持该类别的行情来源。"
                                        : "未找到匹配商品"
                    );
                })
                .catch(() => {
                    if (!abort.signal.aborted) setStatus("搜索未完成，请重试或检查行情来源。");
                });
        }, 200);
        return () => {
            abort.abort();
            window.clearTimeout(timer);
        };
    }, [category, market, query, revision]);
    const choose = (result: InstrumentSearchResult) => {
        const member = memberFor(result);
        void onSelect(member.source, member.instrument_id);
        onClose();
    };
    const navigate = (event: React.KeyboardEvent) => {
        if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
        const buttons = [
            ...(dialog.current?.querySelectorAll<HTMLButtonElement>("[data-symbol-choice]") ?? [])
        ];
        if (buttons.length === 0) return;
        event.preventDefault();
        const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next =
            current < 0
                ? event.key === "ArrowDown"
                    ? 0
                    : buttons.length - 1
                : (current + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) %
                  buttons.length;
        buttons[next]?.focus();
    };
    return createPortal(
        <dialog
            ref={dialog}
            className="symbol-search"
            aria-labelledby="symbol-search-title"
            onCancel={(event) => {
                event.preventDefault();
                onClose();
            }}
            onKeyDown={(event) => {
                keepDialogFocus(event);
                navigate(event);
            }}
        >
            <header>
                <h2 id="symbol-search-title">商品搜索</h2>
                <button type="button" aria-label="关闭商品搜索" onClick={onClose}>
                    ×
                </button>
            </header>
            <input
                ref={input}
                type="search"
                aria-label="商品代码或名称"
                placeholder="搜索代码或名称"
                value={query}
                maxLength={128}
                onChange={(event) => {
                    setQuery(event.target.value);
                    setResponse(null);
                    setStatus(
                        event.target.value.trim()
                            ? "正在搜索…"
                            : "输入商品代码或名称，搜索可用行情来源。"
                    );
                }}
            />
            <div className="symbol-search__categories" role="group" aria-label="商品类别">
                {categories.map((item) => (
                    <button
                        type="button"
                        key={item.label}
                        aria-pressed={item === category}
                        onClick={() => {
                            setCategory(item);
                            setResponse(null);
                            setStatus(
                                query.trim()
                                    ? "正在搜索…"
                                    : "输入商品代码或名称，搜索可用行情来源。"
                            );
                        }}
                    >
                        {item.label}
                    </button>
                ))}
            </div>
            {controller.book !== null && controller.book.lists.length > 1 ? (
                <label className="symbol-search__target">
                    加入到
                    <select
                        aria-label="加入到自选表"
                        value={controller.active?.list_id ?? ""}
                        onChange={(event) => {
                            controller.setSelected(event.target.value);
                        }}
                    >
                        {controller.book.lists.map((list) => (
                            <option key={list.list_id} value={list.list_id}>
                                {list.name}
                            </option>
                        ))}
                    </select>
                </label>
            ) : null}
            <p role="status">{status}</p>
            {status.includes("未完成") ? (
                <button
                    type="button"
                    onClick={() => {
                        setResponse(null);
                        setStatus("正在搜索…");
                        setRevision((value) => value + 1);
                    }}
                >
                    重试搜索
                </button>
            ) : null}
            {response?.sources.some((source) => source.status !== "COMPLETE") ? (
                <details>
                    <summary>来源状态</summary>
                    <ul>
                        {response.sources.map((source) => (
                            <li key={sourceSelectionKey(source.source_selection)}>
                                {sources.find(
                                    (item) =>
                                        item.integration_id ===
                                            source.source_selection.integration_id &&
                                        item.integration_revision_fingerprint ===
                                            source.source_selection.integration_revision_fingerprint
                                )?.display_name ?? source.source_selection.type_id}{" "}
                                ·{" "}
                                {
                                    {
                                        COMPLETE: "已完成",
                                        TIMEOUT: "超时",
                                        UNAVAILABLE: "暂不可用",
                                        UNSUPPORTED: "不支持搜索"
                                    }[source.status]
                                }
                            </li>
                        ))}
                    </ul>
                </details>
            ) : null}
            <ul className="symbol-search__results" aria-label="商品搜索结果">
                {response?.results.map((result) => {
                    const member = memberFor(result),
                        key = watchlistMemberKey(member);
                    const starred =
                        controller.active?.members.some(
                            (item) => watchlistMemberKey(item) === key
                        ) ?? false;
                    const source = sources.find(
                        (item) =>
                            item.integration_id === member.source.integration_id &&
                            item.integration_revision_fingerprint ===
                                member.source.integration_revision_fingerprint &&
                            item.type_id === member.source.expected_type_id
                    );
                    return (
                        <li key={key}>
                            <button
                                type="button"
                                data-symbol-choice=""
                                aria-label={`查看 ${result.instrument.display_symbol} · ${result.instrument.venue} · ${source?.display_name ?? result.source_selection.type_id}`}
                                onClick={() => {
                                    choose(result);
                                }}
                            >
                                <strong>{result.instrument.display_symbol}</strong>
                                <span>
                                    {result.instrument.venue} ·{" "}
                                    {assetLabels[result.instrument.asset_class] ??
                                        result.instrument.asset_class}{" "}
                                    · {result.instrument.market}
                                </span>
                                <small>
                                    {source?.display_name ?? result.source_selection.type_id}
                                </small>
                            </button>
                            <button
                                type="button"
                                className="symbol-search__star"
                                aria-label={`${starred ? "移出" : "加入"}自选 ${result.instrument.display_symbol}`}
                                aria-pressed={starred}
                                disabled={
                                    controller.busy ||
                                    controller.pending !== null ||
                                    controller.book === null ||
                                    (!starred && (controller.active?.members.length ?? 0) >= 100)
                                }
                                onClick={() => void controller.toggle(member)}
                            >
                                {starred ? "★" : "☆"}
                            </button>
                        </li>
                    );
                })}
            </ul>
            {controller.message === null ? null : <p role="alert">{controller.message}</p>}
            {controller.message?.includes("重新加载") ? (
                <button
                    type="button"
                    disabled={controller.busy}
                    onClick={() => void controller.reload()}
                >
                    重新加载自选
                </button>
            ) : null}
            {controller.pending === null ? null : (
                <button
                    type="button"
                    disabled={controller.busy}
                    onClick={() => void controller.resolvePending()}
                >
                    核对提交结果
                </button>
            )}
        </dialog>,
        document.body
    );
}
