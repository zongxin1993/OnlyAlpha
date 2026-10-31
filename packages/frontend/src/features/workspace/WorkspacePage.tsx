import { useOutletContext } from "react-router-dom";
import { createPortal } from "react-dom";
import type { WorkspaceShellSlots } from "../../app/shell/WorkstationShell";
import { WorkspaceLibraryControls } from "./WorkspaceLibraryControls";
import { useDefaultWorkspace } from "./useDefaultWorkspace";
import type { WorkspaceConfiguration } from "../../api/workspace/client";
import { sameChartBinding } from "../../api/chartStudies/client";
import { WatchlistPanel } from "./WatchlistPanel";
import { formatMarketDataDelay } from "./marketDataTiming";
import { useEffect, useRef, useState, useMemo } from "react";
import { SymbolSearch } from "./SymbolSearch";
import { useWatchlists } from "./useWatchlists";
import { TransientStudyPriceChart } from "./TransientStudyPriceChart";
import { useLocalReadCredentials, useMarketDataApi } from "../../app/providers";
import type { FinancialChartType } from "../../charts/lightweight/marketDataChartProjection";
import { DataSourceManager } from "../data/sources/DataSourceManager";
import { WorkspaceIcon, type WorkspaceIconName } from "../../shared/components/WorkspaceIcon";
import { useMarketDataChart } from "./useMarketDataChart";
import { LocalReadAccess } from "./LocalReadAccess";
import { ChartStudies } from "./ChartStudies";
import { onlyMarketDataChartContextKey } from "./marketDataChartContext";
import {
    fixedDurationMinutes,
    formatBarSemantic,
    marketDataSourceChoiceKey
} from "../../api/marketData/model";

const realBarPresets = [1, 3, 5, 15, 30, 60, 120, 240] as const;
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
    const slots = useOutletContext<WorkspaceShellSlots | null>();
    const toolbarHost = slots?.toolbarHost ?? null;
    const railHost = slots?.railHost ?? null;
    const [managementHost, setManagementHost] = useState<HTMLDivElement | null>(null);
    const [studyStatusHost, setStudyStatusHost] = useState<HTMLDivElement | null>(null);
    const [pickerHost, setPickerHost] = useState<HTMLDivElement | null>(null);
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
    const credentials = useLocalReadCredentials();
    const workspace = useDefaultWorkspace(credentials);
    const startup = !credentials.localSession
        ? "default"
        : workspace.restoration === null
          ? "pending"
          : workspace.restoration.configuration === null
            ? "default"
            : "restore";
    const marketData = useMarketDataChart({ startup });
    const studyRestoration = useMemo(() => {
        const saved = workspace.restoration;
        return saved?.configuration == null
            ? null
            : {
                  key: saved.key,
                  contextKey: onlyMarketDataChartContextKey(
                      saved.configuration.source,
                      saved.configuration.instrument_id,
                      saved.configuration.bar_semantic
                  ),
                  studies: saved.configuration.studies
              };
    }, [workspace.restoration]);
    const [restoreOutcome, setRestoreOutcome] = useState<{
        key: string;
        message: string | null;
    } | null>(null);
    const restoreNotice =
        restoreOutcome?.key === workspace.restoration?.key
            ? (restoreOutcome?.message ?? null)
            : null;
    const restoreKey = useRef<string | null>(null);
    const { catalogStatus, restoreSelection } = marketData;
    useEffect(() => {
        const saved = workspace.restoration;
        if (saved === null || restoreKey.current === saved.key || catalogStatus === "loading")
            return;
        restoreKey.current = saved.key;
        if (saved.configuration === null) return;
        const config = saved.configuration;
        void restoreSelection(config.source, config.instrument_id, config.bar_semantic).then(
            (restored) => {
                if (restoreKey.current === saved.key)
                    setRestoreOutcome({
                        key: saved.key,
                        message: restored
                            ? null
                            : "保存的行情上下文未恢复；请检查精确来源、标的和周期，不会自动换源。"
                    });
            }
        );
    }, [catalogStatus, restoreSelection, workspace.restoration]);
    const market = useMarketDataApi();
    const watchlists = useWatchlists(credentials);
    const realInstrument = marketData.instrument;
    const studyContext = useMemo(
        () =>
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
                  },
        [marketData.reference, realInstrument, marketData.barSemantic]
    );
    const latestBar = marketData.liveBar ?? marketData.bars.at(-1);
    const olderHistoryCopy =
        marketData.olderHistoryStatus === "loading"
            ? "正在加载更早临时行情…"
            : marketData.olderHistoryStatus === "failed"
              ? (marketData.olderHistoryMessage ?? "更早行情加载失败")
              : marketData.olderHistoryStatus === "empty"
                ? "当前范围暂无更早临时行情，可重试"
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
                      label: "Temporary window",
                      value: marketData.windowFingerprint ?? "尚未验证"
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

    const tray = (
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
                ref={panelToggle}
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
    );
    const toolbar = (
        <div className="workspace-chart-toolbar" role="toolbar" aria-label="图表工作条">
            <button
                type="button"
                className="chart-region__symbol-search"
                aria-label="搜索商品"
                title={realInstrument?.instrument_id}
                onClick={openSearch}
            >
                <span aria-hidden="true">⌕</span> {realInstrument?.display_symbol ?? "搜索商品"}
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
                                void marketData.selectBarDuration(Number(event.target.value));
                            }
                        }}
                    >
                        {realBarPresets.map((minutes) => (
                            <option
                                key={minutes}
                                value={minutes}
                                disabled={
                                    marketData.barCapability === null ||
                                    minutes < marketData.barCapability.minimum_window_minutes ||
                                    minutes > marketData.barCapability.maximum_window_minutes
                                }
                            >
                                {minutes < 60
                                    ? `${String(minutes)} 分钟`
                                    : `${String(minutes / 60)} 小时`}
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
                                        (marketData.barCapability?.minimum_window_minutes ?? 1) &&
                                    minutes <=
                                        (marketData.barCapability?.maximum_window_minutes ?? 0)
                                )
                                    void marketData.selectBarDuration(minutes);
                            }}
                        >
                            <input
                                aria-label="自定义周期分钟数"
                                type="number"
                                min="1"
                                max={marketData.barCapability?.maximum_window_minutes ?? 240}
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
            </div>
            <details
                className="chart-region__chart-type"
                onKeyDown={(event) => {
                    if (event.key === "Escape") {
                        event.currentTarget.open = false;
                        event.currentTarget.querySelector("summary")?.focus();
                    }
                }}
            >
                <summary aria-label="图表类型" title="图表类型">
                    <WorkspaceIcon name={chartType === "CANDLESTICK" ? "candles" : "line"} />
                    <WorkspaceIcon name="down" />
                </summary>
                <div className="chart-type-options">
                    {(
                        [
                            { value: "CANDLESTICK", label: "蜡烛图", icon: "candles" },
                            { value: "LINE", label: "收盘线", icon: "line" }
                        ] as const
                    ).map((item) => (
                        <button
                            type="button"
                            key={item.value}
                            aria-label={item.label}
                            title={item.label}
                            aria-pressed={chartType === item.value}
                            onClick={(event) => {
                                setChartType(item.value);
                                const menu = event.currentTarget.closest("details");
                                if (menu) {
                                    menu.open = false;
                                    menu.querySelector("summary")?.focus();
                                }
                            }}
                        >
                            <WorkspaceIcon name={item.icon} />
                        </button>
                    ))}
                </div>
            </details>
            <div className="workspace-study-picker" ref={setPickerHost} />
            <div className="workspace-management-host" ref={setManagementHost} />
            <details
                className="workspace-settings"
                onKeyDown={(event) => {
                    if (event.key === "Escape") {
                        event.currentTarget.open = false;
                        event.currentTarget.querySelector("summary")?.focus();
                    }
                }}
            >
                <summary aria-label="设置" title="设置">
                    <WorkspaceIcon name="settings" />
                </summary>
                <div className="workspace-settings__menu">
                    <p className="workspace-settings__heading">图表设置</p>
                    <details className="chart-region__settings">
                        <summary className="workspace-settings__action">
                            <WorkspaceIcon name="candles" />
                            <span>行情设置</span>
                            <span className="workspace-settings__chevron">
                                <WorkspaceIcon name="down" />
                            </span>
                        </summary>
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
                    <details className="workspace-indicator-status">
                        <summary className="workspace-settings__action">
                            <WorkspaceIcon name="analysis" />
                            <span>指标状态</span>
                            <span className="workspace-settings__chevron">
                                <WorkspaceIcon name="down" />
                            </span>
                        </summary>
                        <div className="workspace-settings__panel" ref={setStudyStatusHost} />
                    </details>
                    <hr className="workspace-settings__divider" />
                    <button
                        type="button"
                        className="workspace-settings__action"
                        onClick={() => {
                            setManagerOpen(true);
                        }}
                    >
                        <WorkspaceIcon name="database" />
                        <span>管理数据源</span>
                        <span className="workspace-settings__chevron">
                            <WorkspaceIcon name="expand" />
                        </span>
                    </button>
                </div>
            </details>
        </div>
    );

    return (
        <section
            className="chart-workspace"
            aria-label="图表工作区"
            data-external-rail={railHost !== null}
            data-tools-collapsed="true"
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
            </div>
            <section className="chart-region" aria-label="主图">
                {toolbarHost === null ? toolbar : createPortal(toolbar, toolbarHost)}
                <header className="chart-region__header" hidden={credentials.localSession}>
                    {!credentials.localSession ? (
                        <details>
                            <summary>本地只读访问</summary>
                            <LocalReadAccess />
                        </details>
                    ) : null}
                </header>
                <ChartStudies
                    toolbarTarget={pickerHost}
                    context={studyContext}
                    restoration={studyRestoration}
                    {...(credentials.capture().bearer === null && !credentials.localSession
                        ? {}
                        : { credentials })}
                >
                    {({
                        instances,
                        selectedId,
                        incarnationKey,
                        onTransientRevalidated,
                        configurationIntents,
                        configurationReady
                    }) => {
                        const workspaceConfiguration: WorkspaceConfiguration | null =
                            studyContext === null
                                ? null
                                : {
                                      source: {
                                          ...studyContext.source,
                                          expected_type_id:
                                              studyContext.source.expected_type_id ?? ""
                                      },
                                      instrument_id: studyContext.instrumentId,
                                      bar_semantic: studyContext.barSemantic,
                                      studies: [...configurationIntents]
                                  };
                        const workspaceDirty =
                            workspaceConfiguration !== null &&
                            !sameChartBinding(
                                workspaceConfiguration,
                                workspace.activeWorkspace?.configuration
                            );
                        return (
                            <>
                                {managementHost === null ? (
                                    <WorkspaceLibraryControls
                                        workspace={workspace}
                                        configuration={workspaceConfiguration}
                                        ready={configurationReady}
                                        dirty={workspaceDirty}
                                        notice={restoreNotice}
                                    />
                                ) : (
                                    createPortal(
                                        <WorkspaceLibraryControls
                                            workspace={workspace}
                                            configuration={workspaceConfiguration}
                                            ready={configurationReady}
                                            dirty={workspaceDirty}
                                            notice={restoreNotice}
                                        />,
                                        managementHost
                                    )
                                )}

                                <p
                                    className="chart-region__status"
                                    hidden={
                                        marketData.status === "ready" &&
                                        marketData.realtimeStatus === "ready" &&
                                        olderHistoryCopy === null &&
                                        !marketData.pageReloadRequired
                                    }
                                    role="status"
                                    data-status={marketData.status}
                                    data-temporary-window-fingerprint={
                                        marketData.windowFingerprint ?? ""
                                    }
                                    data-loaded-bar-count={marketData.loadedClosedBarCount}
                                    data-older-history-status={marketData.olderHistoryStatus}
                                    data-testid="market-data-status"
                                >
                                    {marketData.pageReloadRequired
                                        ? "本地会话已失效；请重新载入页面后继续。"
                                        : statusCopy}
                                    {olderHistoryCopy === null ? null : ` · ${olderHistoryCopy}`}
                                    {credentials.localSession && marketData.pageReloadRequired ? (
                                        <a href="/">重新载入页面</a>
                                    ) : credentials.localSession &&
                                      (marketData.status === "incomplete" ||
                                          marketData.status === "failed" ||
                                          marketData.realtimeStatus === "failed") &&
                                      realInstrument !== null ? (
                                        <button
                                            type="button"
                                            onClick={() => {
                                                void marketData.selectBarDuration(duration);
                                            }}
                                        >
                                            重新读取临时行情
                                        </button>
                                    ) : null}
                                </p>
                                <div className="chart-region__body">
                                    <TransientStudyPriceChart
                                        statusTarget={studyStatusHost}
                                        context={studyContext}
                                        pageId={marketData.pageId}
                                        onTransientRevalidated={onTransientRevalidated}
                                        dataGeneration={marketData.windowFingerprint}
                                        continuityReady={marketData.realtimeStatus === "ready"}
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
                        );
                    }}
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
            {railHost === null ? tray : createPortal(tray, railHost)}
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
