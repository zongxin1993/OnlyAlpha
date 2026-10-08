import { useState } from "react";
import { PriceChart } from "../../charts/lightweight/PriceChart";
import type {
    FinancialChartType,
    MarketDataChartSelection
} from "../../charts/lightweight/marketDataChartProjection";
import { DataSourceEntry } from "../data/sources/DataSourceEntry";
import { DataSourceManager } from "../data/sources/DataSourceManager";
import { useDataSourceOverview } from "../data/sources/overview";
import { WorkspaceIcon, type WorkspaceIconName } from "../../shared/components/WorkspaceIcon";
import { useMarketDataChart } from "./useMarketDataChart";
import { ChartStudies } from "./ChartStudies";
import { onlyMarketDataChartContextKey } from "./marketDataHistoryLoader";
import {
    fixedDurationMinutes,
    formatBarSemantic,
    marketDataBarSemantic
} from "../../api/marketData/model";

const realBarPresets = [1, 5, 15, 30, 60, 240] as const;
const CATALOG_NOTE = "指标/因子仅选择正式目录；尚未执行计算";
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
    const [panelOpen, setPanelOpen] = useState(false);
    const [bottomTab, setBottomTab] = useState<"runs" | "results" | "backtest">("runs");
    const [bottomCollapsed, setBottomCollapsed] = useState(false);
    const [chartType, setChartType] = useState<FinancialChartType>("CANDLESTICK");
    const [selection, setSelection] = useState<MarketDataChartSelection | null>(null);
    const [customBarDuration, setCustomBarDuration] = useState("7");
    const [customBarOpen, setCustomBarOpen] = useState(false);
    const [symbolQuery, setSymbolQuery] = useState("");
    const [managerOpen, setManagerOpen] = useState(false);
    const dataSources = useDataSourceOverview();
    const marketData = useMarketDataChart();
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
            ? `${marketData.resolvedSourceId ?? "真实数据源"} · 历史投影 ${marketData.historyProjectionFingerprint?.slice(0, 12) ?? "—"} · ${
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
                  { label: "Realtime", value: marketData.realtimeStatus }
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
                    <span className="chart-region__title" title={realInstrument?.instrument_id}>
                        {realInstrument?.display_symbol ?? "行情工作区"} ·{" "}
                        {formatBarSemantic(marketData.barSemantic)}
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
                                placeholder="搜索服务器标的"
                                aria-label="搜索标的"
                                value={symbolQuery}
                                disabled={marketData.reference === null}
                                onChange={(event) => {
                                    setSymbolQuery(event.target.value);
                                }}
                                onKeyDown={(event) => {
                                    if (event.key === "Enter")
                                        void marketData.searchInstruments(symbolQuery);
                                }}
                            />
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
                        {symbolQuery.trim() === "" || marketData.instruments.length === 0 ? null : (
                            <ul className="chart-region__suggestions">
                                {marketData.instruments.map((item) => (
                                    <li key={item.instrument_id}>
                                        <button
                                            type="button"
                                            onClick={() => {
                                                void marketData.selectInstrument(item);
                                                setSymbolQuery("");
                                            }}
                                        >
                                            <span className="value">{item.instrument_id}</span>
                                            <span>
                                                {item.display_symbol} · {item.market}
                                            </span>
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
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
                        ) : null}
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
                <ChartStudies key={studyContext?.key ?? "no-chart-context"} context={studyContext}>
                    {({ instances, selectedId, incarnationKey }) => (
                        <>
                            <p
                                className="chart-region__overlay-note"
                                data-testid="real-overlay-note"
                            >
                                {CATALOG_NOTE}
                            </p>
                            <p
                                className="chart-region__status"
                                role="status"
                                data-status={marketData.status}
                                data-loaded-bar-count={marketData.loadedClosedBarCount}
                                data-older-history-status={marketData.olderHistoryStatus}
                                data-testid="market-data-status"
                            >
                                {statusCopy}
                                {olderHistoryCopy === null ? null : ` · ${olderHistoryCopy}`}
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
                                <PriceChart
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
                </div>
                <div className="panel-scroll">
                    {panelTab === "watchlist" ? (
                        realInstrument === null ? (
                            <p className="panel-note">选择真实标的后显示当前行情</p>
                        ) : (
                            <table className="data-table">
                                <caption className="visually-hidden">当前标的行情</caption>
                                <thead>
                                    <tr>
                                        <th scope="col">标的</th>
                                        <th scope="col">K 线收盘</th>
                                        <th scope="col">状态</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr>
                                        <td className="value">{realInstrument.instrument_id}</td>
                                        <td className="value">{latestBar?.close ?? "—"}</td>
                                        <td>
                                            {latestBar == null
                                                ? "不可用"
                                                : latestBar.closed
                                                  ? "已关闭"
                                                  : "实时预览"}
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        )
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
                <p className="panel-note">行情来自服务端 Product API；不推导交易或研究事实。</p>
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
                            ? "研究运行尚未接入工作区"
                            : bottomTab === "results"
                              ? "研究结果尚未接入工作区"
                              : "回测尚未接入工作区"}
                    </p>
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
