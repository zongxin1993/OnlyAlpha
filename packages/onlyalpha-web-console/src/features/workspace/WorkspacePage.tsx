import { useEffect, useRef, useState } from "react";
import { PriceChart } from "../../charts/lightweight/PriceChart";
import { type OverlaySpec, type Timeframe } from "../../charts/lightweight/placeholderBars";
import { DataSourceEntry } from "../data/sources/DataSourceEntry";
import { DataSourceManager } from "../data/sources/DataSourceManager";
import { useDataSourceOverview } from "../data/sources/overview";
import { WorkspaceIcon, type WorkspaceIconName } from "../../shared/components/WorkspaceIcon";
import { useMarketDataChart } from "./useMarketDataChart";

const timeframes: readonly Timeframe[] = ["1m", "5m", "15m", "1H", "1D", "1W"];

/**
 * Shell-only fallback used when the workspace has no published market-data source.
 * Binance W1 symbols and real bars always come from the Market Data Product API.
 */
const syntheticInstruments = [
    { code: "600519.SH", name: "贵州茅台" },
    { code: "000001.SZ", name: "平安银行" },
    { code: "510300.SH", name: "沪深300ETF" },
    { code: "IF2603", name: "沪深300期指" },
    { code: "600036.SH", name: "招商银行" },
    { code: "513050.SH", name: "中概互联ETF" },
    { code: "000300.SH", name: "沪深300" }
] as const;

const indicatorCatalog: readonly OverlaySpec[] = [
    { id: "ma-5", label: "MA 5", kind: "indicator" },
    { id: "ma-10", label: "MA 10", kind: "indicator" },
    { id: "ma-20", label: "MA 20", kind: "indicator" },
    { id: "ma-60", label: "MA 60", kind: "indicator" }
];

const factorCatalog: readonly OverlaySpec[] = [
    { id: "momentum-20", label: "20 日动量", kind: "factor" },
    { id: "reversal-5", label: "5 日反转", kind: "factor" },
    { id: "volatility-20", label: "20 日波动率", kind: "factor" },
    { id: "turnover-20", label: "20 日换手率", kind: "factor" }
];

function CatalogPicker({
    label,
    placeholder,
    items,
    selected,
    onToggle
}: {
    readonly label: string;
    readonly placeholder: string;
    readonly items: readonly OverlaySpec[];
    readonly selected: readonly OverlaySpec[];
    readonly onToggle: (overlay: OverlaySpec) => void;
}) {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState("");
    const root = useRef<HTMLDivElement>(null);
    const needle = query.trim().toLowerCase();
    const matches =
        needle === "" ? items : items.filter((item) => item.label.toLowerCase().includes(needle));
    useEffect(() => {
        if (!open) return;
        function close(event: KeyboardEvent | MouseEvent) {
            if (event instanceof KeyboardEvent) {
                if (event.key === "Escape") setOpen(false);
                return;
            }
            if (root.current !== null && !root.current.contains(event.target as Node)) {
                setOpen(false);
            }
        }
        document.addEventListener("keydown", close);
        document.addEventListener("mousedown", close);
        return () => {
            document.removeEventListener("keydown", close);
            document.removeEventListener("mousedown", close);
        };
    }, [open]);
    return (
        <div className="picker" ref={root}>
            <button
                type="button"
                className="picker__trigger"
                aria-expanded={open}
                onClick={() => {
                    setOpen(!open);
                }}
            >
                <WorkspaceIcon name="results" />
                <span>{label}</span>
                {selected.length === 0 ? null : (
                    <span className="picker__count">{selected.length}</span>
                )}
            </button>
            {open ? (
                <div className="picker__popover" role="group" aria-label={`${label}选择`}>
                    <input
                        className="picker__search"
                        type="search"
                        placeholder={placeholder}
                        aria-label={placeholder}
                        value={query}
                        onChange={(event) => {
                            setQuery(event.target.value);
                        }}
                    />
                    <ul className="picker__list">
                        {matches.map((item) => (
                            <li key={item.id}>
                                <button
                                    type="button"
                                    aria-pressed={selected.some((picked) => picked.id === item.id)}
                                    onClick={() => {
                                        onToggle(item);
                                    }}
                                >
                                    {item.label}
                                </button>
                            </li>
                        ))}
                        {matches.length === 0 ? (
                            <li className="picker__empty">没有匹配项</li>
                        ) : null}
                    </ul>
                </div>
            ) : null}
        </div>
    );
}

const tools: readonly {
    readonly id: string;
    readonly label: string;
    readonly icon: WorkspaceIconName;
}[] = [
    { id: "pointer", label: "指针", icon: "pointer" },
    { id: "segment", label: "线段", icon: "segment" },
    { id: "level", label: "水平线", icon: "level" },
    { id: "zone", label: "区间", icon: "zone" },
    { id: "measure", label: "测量", icon: "measure" }
] as const;

const watchlist = [
    { code: "600519.SH", name: "贵州茅台", last: "1486.20", change: "+1.24%", direction: "up" },
    { code: "000001.SZ", name: "平安银行", last: "11.86", change: "-0.42%", direction: "down" },
    { code: "510300.SH", name: "沪深300ETF", last: "4.012", change: "+0.31%", direction: "up" },
    { code: "IF2603", name: "沪深300期指", last: "3988.6", change: "-0.07%", direction: "down" },
    { code: "513050.SH", name: "中概互联ETF", last: "1.284", change: "-0.93%", direction: "down" },
    { code: "000300.SH", name: "沪深300", last: "3988.42", change: "+0.18%", direction: "up" },
    { code: "600036.SH", name: "招商银行", last: "未更新", change: "UNKNOWN", direction: "stale" }
] as const;

const runs = [
    {
        id: "run-0f3a91",
        state: "完成",
        revision: "rev-2c7d18",
        started: "09-23 09:31",
        took: "42s"
    },
    {
        id: "run-5b27c4",
        state: "运行中",
        revision: "rev-2c7d18",
        started: "09-23 10:04",
        took: "—"
    },
    { id: "run-91ae02", state: "失败", revision: "rev-88b310", started: "09-22 15:20", took: "6s" },
    {
        id: "run-c40d77",
        state: "未知",
        revision: "rev-88b310",
        started: "09-22 14:58",
        took: "UNKNOWN"
    }
] as const;

const results = [
    { fingerprint: "res-4d81…a7c2", scope: "因子 20 日动量", runs: "3", updated: "09-22 21:10" },
    { fingerprint: "res-7b09…31fe", scope: "参数邻域 ±10%", runs: "1", updated: "09-22 18:03" }
] as const;

const backtests = [
    { id: "bt-2f5e18", stage: "BACKTEST", state: "完成", revision: "rev-2c7d18" },
    { id: "bt-9d1a03", stage: "BACKTEST", state: "运行中", revision: "rev-88b310" }
] as const;

const inspector = [
    { label: "标的", value: "600519.SH · 贵州茅台" },
    { label: "Strategy Revision", value: "rev-2c7d18" },
    { label: "Dataset Snapshot", value: "snap-1f0a…9de4" },
    { label: "Kernel 语义版本", value: "1" },
    { label: "运行阶段", value: "BACKTEST" },
    { label: "最近事实", value: "fill-88c1 · 09:58:12" },
    { label: "数据新鲜度", value: "stale · 09:20:00" }
] as const;

const stateClass: Record<string, string> = {
    完成: "run-state run-state-completed",
    运行中: "run-state run-state-running",
    失败: "run-state run-state-failed",
    未知: "run-state"
};

const changeClass: Record<string, string> = {
    up: "value value--up",
    down: "value value--down",
    stale: "value value--stale"
};

export function WorkspacePage() {
    const [toolsCollapsed, setToolsCollapsed] = useState(false);
    const [activeTool, setActiveTool] = useState<string>("pointer");
    const [panelTab, setPanelTab] = useState<"watchlist" | "inspector">("watchlist");
    const [panelOpen, setPanelOpen] = useState(false);
    const [bottomTab, setBottomTab] = useState<"runs" | "results" | "backtest">("runs");
    const [bottomCollapsed, setBottomCollapsed] = useState(false);
    const [timeframe, setTimeframe] = useState<Timeframe>("1D");
    const [symbol, setSymbol] = useState<{ readonly code: string; readonly name: string }>(
        syntheticInstruments[0]
    );
    const [symbolQuery, setSymbolQuery] = useState("");
    const [overlays, setOverlays] = useState<readonly OverlaySpec[]>([]);
    const [managerOpen, setManagerOpen] = useState(false);
    const dataSources = useDataSourceOverview();
    const marketData = useMarketDataChart(dataSources.sources);
    const realPath = marketData.selection !== null;
    const realInstrument = marketData.instrument;
    const chartTimeframe: Timeframe = realInstrument === null ? timeframe : "1m";
    const symbolNeedle = symbolQuery.trim().toLowerCase();
    const symbolMatches: readonly { readonly code: string; readonly name: string }[] = realPath
        ? marketData.instruments.map((item) => ({
              code: item.instrument_id,
              name: `${item.display_symbol} · ${item.market}`
          }))
        : symbolNeedle === ""
          ? []
          : syntheticInstruments.filter((item) =>
                `${item.code}${item.name}`.toLowerCase().includes(symbolNeedle)
            );
    function toggleOverlay(overlay: OverlaySpec) {
        setOverlays((current) =>
            current.some((picked) => picked.id === overlay.id)
                ? current.filter((picked) => picked.id !== overlay.id)
                : [...current, overlay]
        );
    }

    return (
        <section
            className="chart-workspace"
            aria-label="图表工作区"
            data-tools-collapsed={toolsCollapsed}
            data-panel-open={panelOpen}
            data-bottom-collapsed={bottomCollapsed}
        >
            <div
                className="workspace-rail"
                role="toolbar"
                aria-label="图表工具"
                aria-orientation="vertical"
            >
                {tools.map((tool) => (
                    <button
                        key={tool.id}
                        type="button"
                        className="rail-button"
                        aria-pressed={activeTool === tool.id}
                        title={tool.label}
                        onClick={() => {
                            setActiveTool(tool.id);
                        }}
                    >
                        <WorkspaceIcon name={tool.icon} />
                        <span className="visually-hidden">{tool.label}</span>
                    </button>
                ))}
                <button
                    type="button"
                    className="rail-button rail-toggle"
                    aria-expanded={!toolsCollapsed}
                    aria-label={toolsCollapsed ? "展开工具条" : "收起工具条"}
                    onClick={() => {
                        setToolsCollapsed(!toolsCollapsed);
                    }}
                >
                    <WorkspaceIcon name={toolsCollapsed ? "expand" : "collapse"} />
                </button>
            </div>

            <section className="chart-region" aria-label="主图">
                <header className="chart-region__header">
                    <span className="chart-region__title">
                        {realInstrument === null
                            ? `${symbol.code} · ${symbol.name}`
                            : `${realInstrument.instrument_id} · ${realInstrument.market}`}
                    </span>
                    <div className="chart-region__controls">
                        <label className="chart-region__source">
                            <span className="visually-hidden">数据源</span>
                            <select
                                aria-label="数据源"
                                value={marketData.sourceId}
                                onChange={(event) => {
                                    marketData.selectSource(event.target.value);
                                }}
                            >
                                <option value="">未选择数据源</option>
                                {marketData.selectableSources.map((item) => (
                                    <option key={item.integration_id} value={item.integration_id}>
                                        {item.display_name} · {item.type_id}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <div className="chart-region__search">
                            <input
                                type="search"
                                placeholder={
                                    realPath ? "搜索标的（Binance 参考）" : "搜索标的 / 代码"
                                }
                                aria-label="搜索标的"
                                value={symbolQuery}
                                onChange={(event) => {
                                    setSymbolQuery(event.target.value);
                                }}
                                onKeyDown={(event) => {
                                    if (event.key === "Enter" && realPath) {
                                        void marketData.searchInstruments(symbolQuery);
                                    }
                                }}
                            />
                            <select
                                className="chart-region__timeframe"
                                aria-label="时间周期"
                                value={chartTimeframe}
                                disabled={realInstrument !== null}
                                onChange={(event) => {
                                    setTimeframe(event.target.value as Timeframe);
                                }}
                            >
                                {timeframes.map((item) => (
                                    <option
                                        key={item}
                                        value={item}
                                        disabled={realInstrument !== null && item !== "1m"}
                                    >
                                        {item}
                                    </option>
                                ))}
                            </select>
                        </div>
                        {symbolMatches.length === 0 ? null : (
                            <ul className="chart-region__suggestions">
                                {symbolMatches.map((item) => (
                                    <li key={item.code}>
                                        <button
                                            type="button"
                                            onClick={() => {
                                                if (realPath) {
                                                    const target = marketData.instruments.find(
                                                        (candidate) =>
                                                            candidate.instrument_id === item.code
                                                    );
                                                    if (target !== undefined)
                                                        void marketData.selectInstrument(target);
                                                } else {
                                                    setSymbol(item);
                                                }
                                                setSymbolQuery("");
                                            }}
                                        >
                                            <span className="value">{item.code}</span>
                                            <span>{item.name}</span>
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                    <CatalogPicker
                        label="指标"
                        placeholder="搜索指标"
                        items={indicatorCatalog}
                        selected={overlays.filter((item) => item.kind === "indicator")}
                        onToggle={toggleOverlay}
                    />
                    <CatalogPicker
                        label="因子"
                        placeholder="搜索因子"
                        items={factorCatalog}
                        selected={overlays.filter((item) => item.kind === "factor")}
                        onToggle={toggleOverlay}
                    />
                    <span className="chart-region__spacer">
                        <DataSourceEntry
                            overview={dataSources}
                            onManage={() => {
                                setManagerOpen(true);
                            }}
                        />
                        {marketData.status === "ready" ? (
                            <span className="real-tag" data-testid="market-data-source-tag">
                                real · DB
                            </span>
                        ) : (
                            <span className="synthetic-tag">synthetic</span>
                        )}
                        <button
                            type="button"
                            className="panel-toggle"
                            aria-expanded={panelOpen}
                            aria-label={panelOpen ? "关闭上下文面板" : "打开上下文面板"}
                            onClick={() => {
                                setPanelOpen(!panelOpen);
                            }}
                        >
                            <WorkspaceIcon name="menu" />
                        </button>
                    </span>
                </header>
                <p
                    className="chart-region__status"
                    data-status={marketData.status}
                    data-testid="market-data-status"
                >
                    {marketData.message ??
                        (marketData.status === "ready"
                            ? `历史 1m K 线来自 canonical Revision ${
                                  marketData.revisionFingerprint?.slice(0, 12) ?? "—"
                              }（realtime 未启用）`
                            : "未连接真实行情；当前图表为 synthetic 占位")}
                </p>
                <div className="chart-region__body">
                    <PriceChart
                        timeframe={chartTimeframe}
                        overlays={overlays}
                        bars={marketData.status === "ready" ? marketData.bars : undefined}
                    />
                </div>
            </section>

            <aside className="context-panel" aria-label="上下文面板">
                <div className="panel-tabs" role="group" aria-label="上下文面板视图">
                    <button
                        type="button"
                        className="panel-tab"
                        aria-pressed={panelTab === "watchlist"}
                        onClick={() => {
                            setPanelTab("watchlist");
                        }}
                    >
                        自选
                    </button>
                    <button
                        type="button"
                        className="panel-tab"
                        aria-pressed={panelTab === "inspector"}
                        onClick={() => {
                            setPanelTab("inspector");
                        }}
                    >
                        检查器
                    </button>
                </div>
                <div className="panel-scroll">
                    {panelTab === "watchlist" ? (
                        <table className="data-table">
                            <caption className="visually-hidden">自选列表（synthetic）</caption>
                            <thead>
                                <tr>
                                    <th scope="col">标的</th>
                                    <th scope="col">最新</th>
                                    <th scope="col">涨跌</th>
                                </tr>
                            </thead>
                            <tbody>
                                {watchlist.map((row) => (
                                    <tr key={row.code}>
                                        <td>
                                            <span className="value">{row.code}</span>
                                            <br />
                                            <span className="muted">{row.name}</span>
                                        </td>
                                        <td>
                                            <span className={changeClass[row.direction]}>
                                                {row.last}
                                            </span>
                                        </td>
                                        <td>
                                            <span className={changeClass[row.direction]}>
                                                {row.change}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    ) : (
                        <table className="data-table">
                            <caption className="visually-hidden">检查器（synthetic）</caption>
                            <tbody>
                                {inspector.map((row) => (
                                    <tr key={row.label}>
                                        <th scope="row">{row.label}</th>
                                        <td className="value">{row.value}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
                <p className="panel-note">
                    面板内容为 synthetic 占位；权威事实由服务端 Product API 提供。
                </p>
            </aside>

            <div
                className="workspace-tray"
                role="toolbar"
                aria-label="工作区面板"
                aria-orientation="vertical"
            >
                <button
                    type="button"
                    className="rail-button"
                    aria-pressed={panelTab === "watchlist"}
                    aria-label="自选"
                    title="自选"
                    onClick={() => {
                        setPanelTab("watchlist");
                        setPanelOpen(true);
                    }}
                >
                    <WorkspaceIcon name="results" />
                </button>
                <button
                    type="button"
                    className="rail-button"
                    aria-pressed={panelTab === "inspector"}
                    aria-label="检查器"
                    title="检查器"
                    onClick={() => {
                        setPanelTab("inspector");
                        setPanelOpen(true);
                    }}
                >
                    <WorkspaceIcon name="shield" />
                </button>
                <button
                    type="button"
                    className="rail-button"
                    aria-pressed={bottomTab === "backtest"}
                    aria-label="回测"
                    title="回测"
                    onClick={() => {
                        setBottomTab("backtest");
                        setBottomCollapsed(false);
                    }}
                >
                    <WorkspaceIcon name="runs" />
                </button>
            </div>

            <section className="bottom-panel" aria-label="研究面板">
                <header className="bottom-panel__header">
                    <div className="panel-tabs" role="group" aria-label="下方面板视图">
                        <button
                            type="button"
                            className="panel-tab"
                            aria-pressed={bottomTab === "runs"}
                            onClick={() => {
                                setBottomTab("runs");
                            }}
                        >
                            研究运行
                        </button>
                        <button
                            type="button"
                            className="panel-tab"
                            aria-pressed={bottomTab === "results"}
                            onClick={() => {
                                setBottomTab("results");
                            }}
                        >
                            研究结果
                        </button>
                        <button
                            type="button"
                            className="panel-tab"
                            aria-pressed={bottomTab === "backtest"}
                            onClick={() => {
                                setBottomTab("backtest");
                            }}
                        >
                            回测
                        </button>
                    </div>
                    <div className="bottom-panel__meta">
                        <span className="synthetic-tag">synthetic</span>
                        <button
                            type="button"
                            className="rail-button"
                            aria-expanded={!bottomCollapsed}
                            aria-label={bottomCollapsed ? "展开下方面板" : "收起下方面板"}
                            onClick={() => {
                                setBottomCollapsed(!bottomCollapsed);
                            }}
                        >
                            <WorkspaceIcon name={bottomCollapsed ? "up" : "down"} />
                        </button>
                    </div>
                </header>
                <div className="panel-scroll" hidden={bottomCollapsed}>
                    {bottomTab === "runs" ? (
                        <table className="data-table">
                            <caption className="visually-hidden">研究运行（synthetic）</caption>
                            <thead>
                                <tr>
                                    <th scope="col">运行</th>
                                    <th scope="col">状态</th>
                                    <th scope="col">策略 Revision</th>
                                    <th scope="col">开始</th>
                                    <th scope="col">耗时</th>
                                </tr>
                            </thead>
                            <tbody>
                                {runs.map((row) => (
                                    <tr key={row.id}>
                                        <td className="value">{row.id}</td>
                                        <td>
                                            <span className={stateClass[row.state]}>
                                                {row.state}
                                            </span>
                                        </td>
                                        <td className="value">{row.revision}</td>
                                        <td className="value">{row.started}</td>
                                        <td className="value">{row.took}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    ) : null}
                    {bottomTab === "results" ? (
                        <table className="data-table">
                            <caption className="visually-hidden">研究结果（synthetic）</caption>
                            <thead>
                                <tr>
                                    <th scope="col">结果指纹</th>
                                    <th scope="col">范围</th>
                                    <th scope="col">运行数</th>
                                    <th scope="col">更新时间</th>
                                </tr>
                            </thead>
                            <tbody>
                                {results.map((row) => (
                                    <tr key={row.fingerprint}>
                                        <td className="value">{row.fingerprint}</td>
                                        <td>{row.scope}</td>
                                        <td className="value">{row.runs}</td>
                                        <td className="value">{row.updated}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    ) : null}
                    {bottomTab === "backtest" ? (
                        <table className="data-table">
                            <caption className="visually-hidden">回测（synthetic）</caption>
                            <thead>
                                <tr>
                                    <th scope="col">回测</th>
                                    <th scope="col">阶段</th>
                                    <th scope="col">状态</th>
                                    <th scope="col">策略 Revision</th>
                                </tr>
                            </thead>
                            <tbody>
                                {backtests.map((row) => (
                                    <tr key={row.id}>
                                        <td className="value">{row.id}</td>
                                        <td className="value">{row.stage}</td>
                                        <td>
                                            <span className={stateClass[row.state]}>
                                                {row.state}
                                            </span>
                                        </td>
                                        <td className="value">{row.revision}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    ) : null}
                </div>
            </section>
            {managerOpen ? (
                <DataSourceManager
                    variant="modal"
                    onClose={() => {
                        setManagerOpen(false);
                    }}
                />
            ) : null}
        </section>
    );
}
