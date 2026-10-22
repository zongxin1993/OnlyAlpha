import { WatchlistPanel } from "./WatchlistPanel";
import { formatMarketDataDelay } from "./marketDataTiming";
import { useEffect, useRef, useState } from "react";
import { SymbolSearch } from "./SymbolSearch";
import { useWatchlists } from "./useWatchlists";
import { TransientStudyPriceChart } from "./TransientStudyPriceChart";
import { useLocalReadCredentials, useMarketDataApi } from "../../app/providers";
import type {
    FinancialChartType,
    MarketDataChartSelection
} from "../../charts/lightweight/marketDataChartProjection";
import { DataSourceEntry } from "../data/sources/DataSourceEntry";
import { DataSourceManager } from "../data/sources/DataSourceManager";
import { useDataSourceOverview } from "../data/sources/overview";
import { WorkspaceIcon, type WorkspaceIconName } from "../../shared/components/WorkspaceIcon";
import { useMarketDataChart } from "./useMarketDataChart";
import { LocalReadAccess } from "./LocalReadAccess";
import { ChartStudies } from "./ChartStudies";
import { onlyMarketDataChartContextKey } from "./marketDataHistoryLoader";
import {
    fixedDurationMinutes,
    formatBarSemantic,
    marketDataBarSemantic,
    marketDataSourceChoiceKey
} from "../../api/marketData/model";

const realBarPresets = [1, 3, 5, 15, 30, 60, 120, 240] as const;
const CATALOG_NOTE = "图表指标仅供观察，不是正式研究结果";
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
];

export function WorkspacePage() {
    const [toolsCollapsed, setToolsCollapsed] = useState(false);
    const [activeTool, setActiveTool] = useState<string>("pointer");
    const [panelTab, setPanelTab] = useState<"watchlist" | "inspector">("watchlist");
    const [panelOpen, setPanelOpen] = useState(() =>
        typeof window.matchMedia === "function"
            ? window.matchMedia("(min-width: 1280px)").matches
            : true
    );
    useEffect(() => {
        if (typeof window.matchMedia !== "function") return;
        const layout = window.matchMedia("(min-width: 1280px)");
        const onLayoutChange = (event: MediaQueryListEvent) => {
            setPanelOpen(event.matches);
        };
        if (typeof layout.addEventListener === "function") {
            layout.addEventListener("change", onLayoutChange);
        }
        return () => {
            if (typeof layout.removeEventListener === "function") {
                layout.removeEventListener("change", onLayoutChange);
            }
        };
    }, []);
    const panelToggle = useRef<HTMLButtonElement>(null);
    const [bottomTab, setBottomTab] = useState<"runs" | "results" | "backtest">("runs");
    const [bottomCollapsed, setBottomCollapsed] = useState(true);
    const [chartType, setChartType] = useState<FinancialChartType>("CANDLESTICK");
    const [selection, setSelection] = useState<MarketDataChartSelection | null>(null);
    const [customBarDuration, setCustomBarDuration] = useState("7");
    const [customBarOpen, setCustomBarOpen] = useState(false);
    const [searchOpen, setSearchOpen] = useState(false);
    const [searchReturnFocus, setSearchReturnFocus] = useState<HTMLElement | null>(null);
    const openSearch = () => {
        setSearchReturnFocus(
            document.activeElement instanceof HTMLElement ? document.activeElement : null
        );
        setSearchOpen(true);
    };
    const [managerOpen, setManagerOpen] = useState(false);
    const dataSources = useDataSourceOverview();
    const marketData = useMarketDataChart();
    const credentials = useLocalReadCredentials();
    const market = useMarketDataApi();
    const watchlists = useWatchlists(credentials);
    const realInstrument = marketData.instrument;
    const studyContext =
        marketData.reference === null || realInstrument === null
            ? null
            : {
                  key: onlyMarketDataChartContextKey(
                      marketData.reference,
                      realInstrument.instrument_id,
                      marketData.barSemantic
                  ),
                  source: marketData.reference,
                  instrumentId: realInstrument.instrument_id,
                  barSemantic: marketData.barSemantic
              };
    const selectedBar =
        selection?.contextKey === marketData.chartContextKey
            ? marketData.liveBar?.barStartNs === selection.barStartNs
                ? marketData.liveBar
                : marketData.bars.find((bar) => bar.barStartNs === selection.barStartNs)
            : undefined;
    const latestBar = marketData.liveBar ?? marketData.bars.at(-1);
    const observation = selectedBar ?? latestBar;
    const observationMode =
        observation == null
            ? "unavailable"
            : selectedBar != null
              ? "crosshair"
              : observation.closed
                ? "latest-closed"
                : "preview";
    const olderHistoryCopy =
        marketData.olderHistoryStatus === "loading"
            ? "正在加载更早行情…"
            : marketData.olderHistoryStatus === "acquiring"
              ? "正在补齐更早行情…"
              : marketData.olderHistoryStatus === "failed"
                ? (marketData.olderHistoryMessage ?? "更早行情加载失败")
                : marketData.olderHistoryStatus === "exhausted"
                  ? "已到达可用历史起点"
                  : null;
    const duration = fixedDurationMinutes(marketData.barSemantic);
    const preset = realBarPresets.includes(duration as (typeof realBarPresets)[number]);
    const statusCopy =
        marketData.message ??
        (marketData.status === "ready"
            ? `行情已加载 · ${
                  marketData.realtimeStatus === "ready"
                      ? "● 实时"
                      : marketData.realtimeStatus === "recovering"
                        ? "● 恢复中"
                        : marketData.realtimeStatus === "degraded"
                          ? "● 行情中断"
                          : marketData.realtimeStatus === "failed"
                            ? `● 实时失败${marketData.streamError === null ? "" : `：${marketData.streamError}`}`
                            : "● 连接中"
              }`
            : marketData.status === "loading"
              ? "正在加载行情…"
              : marketData.reference === null
                ? "请选择数据源"
                : "请选择服务器提供的标的");
    const inspector =
        marketData.reference === null
            ? []
            : [
                  { label: "标的", value: realInstrument?.instrument_id ?? "未选择" },
                  { label: "Integration", value: marketData.reference.integration_id },
                  {
                      label: "Integration Revision",
                      value: marketData.reference.integration_revision_fingerprint
                  },
                  { label: "Source", value: marketData.resolvedSourceId ?? "尚未读取行情" },
                  { label: "Bar semantic", value: formatBarSemantic(marketData.barSemantic) },
                  { label: "Coverage", value: marketData.coverage?.status ?? "尚未查询" },
                  {
                      label: "History projection",
                      value: marketData.historyProjectionFingerprint ?? "尚未验证"
                  },
                  { label: "Realtime", value: marketData.realtimeStatus },
                  {
                      label: "延迟样本",
                      value:
                          marketData.timing === null
                              ? "暂无实时样本"
                              : marketData.realtimeStatus === "ready" &&
                                  marketData.timing.currentConnection
                                ? "当前连接样本"
                                : "最后样本 · 非当前"
                  },
                  {
                      label: "接收延迟",
                      value: formatMarketDataDelay(marketData.timing?.receiveDelayNs ?? null)
                  },
                  {
                      label: "收盘到达延迟",
                      value: formatMarketDataDelay(marketData.timing?.closedArrivalDelayNs ?? null)
                  }
              ];

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
                    {!credentials.localSession ? (
                        <details>
                            <summary>本地只读访问</summary>
                            <LocalReadAccess />
                        </details>
                    ) : null}
                    <button
                        type="button"
                        className="chart-region__symbol-search"
                        aria-label="搜索商品"
                        title={realInstrument?.instrument_id}
                        onClick={openSearch}
                    >
                        <span aria-hidden="true">⌕</span>{" "}
                        {realInstrument?.display_symbol ?? "搜索商品"}
                    </button>
                    <div className="chart-region__controls">
                        <div className="chart-region__search">
                            <select
                                className="chart-region__timeframe"
                                aria-label="时间周期"
                                value={preset && !customBarOpen ? String(duration) : "custom"}
                                disabled={marketData.reference === null}
                                onChange={(event) => {
                                    if (event.target.value === "custom") setCustomBarOpen(true);
                                    else {
                                        setCustomBarOpen(false);
                                        void marketData.selectBarDuration(
                                            Number(event.target.value)
                                        );
                                    }
                                }}
                            >
                                {realBarPresets.map((minutes) => (
                                    <option
                                        key={minutes}
                                        value={minutes}
                                        disabled={
                                            marketData.barCapability === null ||
                                            minutes <
                                                marketData.barCapability.minimum_window_minutes ||
                                            minutes >
                                                marketData.barCapability.maximum_window_minutes
                                        }
                                    >
                                        {formatBarSemantic(marketDataBarSemantic(minutes))}
                                    </option>
                                ))}
                                <option value="custom">自定义…</option>
                            </select>
                            {customBarOpen || !preset ? (
                                <form
                                    onSubmit={(event) => {
                                        event.preventDefault();
                                        const minutes = Number(customBarDuration);
                                        if (
                                            Number.isInteger(minutes) &&
                                            minutes >=
                                                (marketData.barCapability?.minimum_window_minutes ??
                                                    1) &&
                                            minutes <=
                                                (marketData.barCapability?.maximum_window_minutes ??
                                                    0)
                                        )
                                            void marketData.selectBarDuration(minutes);
                                    }}
                                >
                                    <input
                                        aria-label="自定义周期分钟数"
                                        type="number"
                                        min="1"
                                        max={
                                            marketData.barCapability?.maximum_window_minutes ?? 240
                                        }
                                        step="1"
                                        required
                                        value={customBarDuration}
                                        onChange={(event) => {
                                            setCustomBarDuration(event.target.value);
                                        }}
                                    />
                                    <button type="submit">应用</button>
                                </form>
                            ) : null}
                        </div>
                        <select
                            className="chart-region__chart-type"
                            aria-label="图表类型"
                            value={chartType}
                            onChange={(event) => {
                                setChartType(event.target.value as FinancialChartType);
                            }}
                        >
                            <option value="CANDLESTICK">蜡烛图</option>
                            <option value="LINE">收盘线</option>
                        </select>
                    </div>
                    <span className="chart-region__spacer">
                        <details className="chart-region__settings">
                            <summary>行情设置</summary>
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
                                        <option
                                            key={marketDataSourceChoiceKey(item)}
                                            value={marketDataSourceChoiceKey(item)}
                                        >
                                            {item.display_name} ·{" "}
                                            {item.is_current_revision
                                                ? "当前 Revision"
                                                : "历史 Revision"}{" "}
                                            · {item.integration_revision_fingerprint.slice(0, 8)} ·{" "}
                                            {item.new_work_status === "AVAILABLE"
                                                ? "可采集"
                                                : "仅封存历史"}
                                        </option>
                                    ))}
                                </select>
                            </label>
                        </details>
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
                        ) : null}
                        <button
                            type="button"
                            className="panel-toggle"
                            ref={panelToggle}
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
                <ChartStudies
                    context={studyContext}
                    {...(credentials.capture().bearer === null && !credentials.localSession
                        ? {}
                        : { credentials })}
                >
                    {({ instances, selectedId, incarnationKey, onTransientRevalidated }) => (
                        <>
                            {instances.length === 0 ? null : (
                                <p
                                    className="chart-region__overlay-note"
                                    data-testid="real-overlay-note"
                                >
                                    {instances.length === 0
                                        ? CATALOG_NOTE
                                        : instances.some(
                                                (instance) =>
                                                    instance.selection.source ===
                                                    "CHART_STUDY_TRANSIENT"
                                            )
                                          ? "图表指标 · 仅供观察，不是正式研究结果"
                                          : "指标尚未接入计算"}
                                </p>
                            )}
                            <p
                                className="chart-region__status"
                                role="status"
                                data-status={marketData.status}
                                data-history-projection-fingerprint={
                                    marketData.historyProjectionFingerprint ?? ""
                                }
                                data-loaded-bar-count={marketData.loadedClosedBarCount}
                                data-older-history-status={marketData.olderHistoryStatus}
                                data-testid="market-data-status"
                            >
                                {statusCopy}
                                {olderHistoryCopy === null ? null : ` · ${olderHistoryCopy}`}
                                {credentials.localSession &&
                                (marketData.status === "incomplete" ||
                                    marketData.status === "failed") &&
                                realInstrument !== null ? (
                                    <button
                                        type="button"
                                        onClick={() => {
                                            void marketData.selectBarDuration(duration);
                                        }}
                                    >
                                        重新读取历史
                                    </button>
                                ) : null}
                            </p>
                            <div
                                className="chart-observation"
                                data-testid="market-data-observation"
                                data-observation-mode={observationMode}
                                data-bar-start-ns={observation?.barStartNs ?? ""}
                                data-chart-context-key={marketData.chartContextKey ?? ""}
                            >
                                <span>
                                    {observation == null
                                        ? "UTC —"
                                        : new Date(observation.time * 1000)
                                              .toISOString()
                                              .replace("T", " ")
                                              .replace(".000Z", " UTC")}
                                </span>
                                {(["open", "high", "low", "close", "volume"] as const).map(
                                    (field) => (
                                        <span key={field}>
                                            {
                                                {
                                                    open: "O",
                                                    high: "H",
                                                    low: "L",
                                                    close: "C",
                                                    volume: "V"
                                                }[field]
                                            }{" "}
                                            <span data-observation-field={field}>
                                                {observation?.[field] ?? "—"}
                                            </span>
                                        </span>
                                    )
                                )}
                                <span>
                                    {observationMode === "crosshair"
                                        ? "十字线"
                                        : observationMode === "preview"
                                          ? "实时预览"
                                          : observationMode === "latest-closed"
                                            ? "最新已关闭"
                                            : "不可用"}
                                </span>
                            </div>
                            <div className="chart-region__body">
                                <TransientStudyPriceChart
                                    context={studyContext}
                                    previewStreamId={
                                        marketData.realtimeStatus === "ready"
                                            ? marketData.streamId
                                            : null
                                    }
                                    onTransientRevalidated={onTransientRevalidated}
                                    dataGeneration={marketData.historyProjectionFingerprint}
                                    expectedSourceId={marketData.resolvedSourceId}
                                    expectedEnvironment={
                                        marketData.selectableSources.find(
                                            (source) =>
                                                marketDataSourceChoiceKey(source) ===
                                                marketData.sourceId
                                        )?.environment ?? null
                                    }
                                    studies={instances}
                                    selectedStudyId={selectedId}
                                    incarnationKey={incarnationKey}
                                    chartType={chartType}
                                    onSelection={setSelection}
                                    barSemantic={marketData.barSemantic}
                                    bars={marketData.bars}
                                    liveBar={marketData.liveBar}
                                    contextKey={marketData.chartContextKey}
                                    onNearLeftEdge={() => {
                                        void marketData.loadOlderHistory();
                                    }}
                                />
                                {latestBar == null ? (
                                    <div className="chart-region__empty" aria-label="行情空态">
                                        <p>{statusCopy}</p>
                                        <button
                                            type="button"
                                            className="button-secondary"
                                            onClick={() => {
                                                setManagerOpen(true);
                                            }}
                                        >
                                            管理数据源
                                        </button>
                                    </div>
                                ) : null}
                            </div>
                        </>
                    )}
                </ChartStudies>
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
                    <button
                        type="button"
                        className="panel-toggle context-panel__close"
                        aria-label="收起上下文面板"
                        onClick={() => {
                            setPanelOpen(false);
                            panelToggle.current?.focus();
                        }}
                    >
                        <WorkspaceIcon name="menu" />
                    </button>
                </div>
                <div className="panel-scroll">
                    {panelTab === "watchlist" ? (
                        <WatchlistPanel
                            controller={watchlists}
                            market={market}
                            sources={marketData.selectableSources}
                            enabled={panelOpen}
                            onSelect={marketData.selectWatchlistInstrument}
                            onSearch={openSearch}
                        />
                    ) : inspector.length === 0 ? (
                        <p className="panel-note">尚未选择行情上下文</p>
                    ) : (
                        <table className="data-table">
                            <caption className="visually-hidden">行情检查器</caption>
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
                    <p className="panel-note">
                        {bottomTab === "runs"
                            ? "研究运行尚未实现"
                            : bottomTab === "results"
                              ? "研究结果尚未实现"
                              : "回测尚未实现"}
                    </p>
                </div>
            </section>
            {searchOpen ? (
                <SymbolSearch
                    market={market}
                    controller={watchlists}
                    sources={marketData.selectableSources}
                    returnFocus={searchReturnFocus}
                    onClose={() => {
                        setSearchOpen(false);
                    }}
                    onSelect={marketData.selectWatchlistInstrument}
                />
            ) : null}
            {managerOpen ? (
                <DataSourceManager
                    variant="modal"
                    onClose={() => {
                        setManagerOpen(false);
                        marketData.refreshSources();
                    }}
                />
            ) : null}
        </section>
    );
}
