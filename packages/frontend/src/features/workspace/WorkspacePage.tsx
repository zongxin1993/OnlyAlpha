import { Button, Tooltip, Dropdown } from "antd";
import { settingsChangedEvent, useSettings } from "../settings/SettingsProvider";
import { Link, useOutletContext } from "react-router-dom";
import { createPortal } from "react-dom";
import type { WorkspaceShellSlots } from "../../app/shell/WorkstationShell";
import { WorkspaceLibraryControls, type WorkspaceLibraryControl } from "./WorkspaceLibraryControls";
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
import { SealedDayControls } from "./SealedDayControls";
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
    const { chartSettingsHost, setChartAvailable, openSettings } = useSettings();
    useEffect(() => {
        setChartAvailable(true);
        return () => {
            setChartAvailable(false);
        };
    }, [setChartAvailable]);
    const slots = useOutletContext<WorkspaceShellSlots | null>();
    const toolbarHost = slots?.toolbarHost ?? null;
    const railHost = slots?.railHost ?? null;
    const [managementHost, setManagementHost] = useState<HTMLDivElement | null>(null);
    const [studyStatusHost, setStudyStatusHost] = useState<HTMLDivElement | null>(null);
    const [pickerHost, setPickerHost] = useState<HTMLDivElement | null>(null);
    const [studiesCardHost, setStudiesCardHost] = useState<HTMLDivElement | null>(null);
    const libraryControlRef = useRef<WorkspaceLibraryControl | null>(null);
    const [activeTool, setActiveTool] = useState<string>("pointer");
    const [bottomTab, setBottomTab] = useState<"runs" | "results">("runs");
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
    const { refreshSources } = marketData;
    useEffect(() => {
        window.addEventListener(settingsChangedEvent, refreshSources);
        return () => {
            window.removeEventListener(settingsChangedEvent, refreshSources);
        };
    }, [refreshSources]);
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
    const source = marketData.selectableSources.find(
        (s) => marketDataSourceChoiceKey(s) === marketData.sourceId
    );
    const dayMode = source?.historical_day_semantic !== undefined;
    const studyContext = useMemo(
        () =>
            marketData.reference === null || realInstrument === null || dayMode
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
        [marketData.reference, realInstrument, marketData.barSemantic, dayMode]
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
    const duration =
        marketData.barSemantic.formation.kind === "FIXED_DURATION"
            ? fixedDurationMinutes(marketData.barSemantic)
            : null;
    const preset = realBarPresets.includes(duration as (typeof realBarPresets)[number]);
    const statusCopy =
        marketData.message ??
        (marketData.status === "ready"
            ? dayMode
                ? "已加载封存日线"
                : `行情已加载 · ${
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
                  ...(dayMode
                      ? [{ label: "封存修订", value: marketData.sealedRevisionId ?? "尚未读取" }]
                      : [
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
                                value: formatMarketDataDelay(
                                    marketData.timing?.receiveDelayNs ?? null
                                )
                            },
                            {
                                label: "收盘到达延迟",
                                value: formatMarketDataDelay(
                                    marketData.timing?.closedArrivalDelayNs ?? null
                                )
                            }
                        ])
              ];

    const chartSettings = (
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
                                {item.is_current_revision ? "当前配置" : "历史配置"} ·{" "}
                                {item.new_work_status === "AVAILABLE" ? "可采集" : "仅封存历史"}
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
                    if (chartSettingsHost === null) setManagerOpen(true);
                    else openSettings("sources");
                }}
            >
                <WorkspaceIcon name="database" />
                <span>管理数据源</span>
                <span className="workspace-settings__chevron">
                    <WorkspaceIcon name="expand" />
                </span>
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
                <WorkspaceIcon name="search" /> {realInstrument?.display_symbol ?? "搜索商品"}
            </button>
            <div className="chart-region__controls">
                <div className="chart-region__search">
                    <select
                        className="chart-region__timeframe"
                        aria-label="时间周期"
                        value={
                            dayMode ? "day" : preset && !customBarOpen ? String(duration) : "custom"
                        }
                        disabled={marketData.reference === null}
                        onChange={(event) => {
                            if (event.target.value === "custom") setCustomBarOpen(true);
                            else {
                                setCustomBarOpen(false);
                                void marketData.selectBarDuration(Number(event.target.value));
                            }
                        }}
                    >
                        {dayMode ? (
                            <option value="day">1 日 · 封存历史</option>
                        ) : (
                            realBarPresets.map((minutes) => (
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
                            ))
                        )}
                        {!dayMode && <option value="custom">自定义…</option>}
                    </select>
                    {!dayMode && (customBarOpen || !preset) ? (
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
            <Dropdown
                trigger={["click"]}
                menu={{
                    selectedKeys: [chartType],
                    items: [
                        {
                            key: "CANDLESTICK",
                            label: "蜡烛图",
                            icon: <WorkspaceIcon name="candles" />
                        },
                        { key: "LINE", label: "收盘线", icon: <WorkspaceIcon name="line" /> }
                    ],
                    onClick: ({ key }) => {
                        if (key === "CANDLESTICK" || key === "LINE") setChartType(key);
                    }
                }}
            >
                <Button type="text" aria-label="图表类型" className="chart-region__chart-type">
                    <WorkspaceIcon name={chartType === "CANDLESTICK" ? "candles" : "line"} />
                    <WorkspaceIcon name="down" />
                </Button>
            </Dropdown>
            <div className="workspace-study-picker" ref={setPickerHost} />
            <div className="workspace-management-host" ref={setManagementHost} />
        </div>
    );

    return (
        <section
            className="chart-workspace"
            aria-label="图表工作区"
            data-external-rail={railHost !== null}
            data-tools-collapsed="true"
            data-bottom-collapsed={bottomCollapsed}
        >
            <div
                className="workspace-rail"
                role="toolbar"
                aria-label="图表工具"
                aria-orientation="vertical"
            >
                {tools.map((tool) => (
                    <Tooltip key={tool.id} title={tool.label} placement="right">
                        <Button
                            type="text"
                            className="rail-button"
                            aria-pressed={activeTool === tool.id}
                            title={tool.label}
                            onClick={() => {
                                setActiveTool(tool.id);
                            }}
                        >
                            <WorkspaceIcon name={tool.icon} />
                            <span className="visually-hidden">{tool.label}</span>
                        </Button>
                    </Tooltip>
                ))}
            </div>
            {chartSettingsHost !== null ? (
                createPortal(chartSettings, chartSettingsHost)
            ) : (
                <details className="workspace-settings">
                    <summary aria-label="设置">图表设置</summary>
                    {chartSettings}
                </details>
            )}
            <aside className="workspace-watch-column" aria-label="自选">
                <WatchlistPanel
                    controller={watchlists}
                    market={market}
                    sources={marketData.selectableSources}
                    enabled={true}
                    onSelect={marketData.selectWatchlistInstrument}
                    onSearch={openSearch}
                />
                <details className="watch-column__inspector" aria-label="行情检查器">
                    <summary>行情检查器</summary>
                    {inspector.length === 0 ? (
                        <p className="panel-note">尚未选择行情上下文</p>
                    ) : (
                        <table className="data-table">
                            <caption className="visually-hidden">行情检查器明细</caption>
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
                </details>
            </aside>
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
                {dayMode && (
                    <SealedDayControls
                        key={marketData.sourceId}
                        chart={marketData}
                        source={source}
                    />
                )}
                <ChartStudies
                    toolbarTarget={pickerHost}
                    studiesCardTarget={studiesCardHost}
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
                                        notice={
                                            dayMode
                                                ? "1 日封存历史无法保存为工作区，可用原采集编号恢复。"
                                                : restoreNotice
                                        }
                                        openControlRef={libraryControlRef}
                                    />
                                ) : (
                                    createPortal(
                                        <WorkspaceLibraryControls
                                            workspace={workspace}
                                            configuration={workspaceConfiguration}
                                            ready={configurationReady}
                                            dirty={workspaceDirty}
                                            notice={
                                                dayMode
                                                    ? "1 日封存历史无法保存为工作区，可用原采集编号恢复。"
                                                    : restoreNotice
                                            }
                                            openControlRef={libraryControlRef}
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
                                    data-sealed-revision-id={marketData.sealedRevisionId ?? ""}
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
                                      realInstrument !== null &&
                                      duration !== null &&
                                      !dayMode ? (
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
                                            if (!dayMode) void marketData.loadOlderHistory();
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
                <div className="workspace-under-chart">
                    <div ref={setStudiesCardHost} />
                    <section className="workspace-summary-card" aria-label="工作区">
                        <header>
                            <h2>工作区</h2>
                            <button
                                type="button"
                                onClick={(event) => {
                                    libraryControlRef.current?.open("save", event.currentTarget);
                                }}
                            >
                                保存副本
                            </button>
                        </header>
                        <p>
                            {workspace.activeWorkspace?.name ??
                                "还没有保存的工作区，“保存副本”可保存当前布局与绘图。"}
                        </p>
                        <p className="faint">布局与绘图随工作区持久化</p>
                    </section>
                </div>
            </section>
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
                        <Link className="panel-tab" to="/backtest">
                            回测
                        </Link>
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
                        {bottomTab === "runs" ? "研究运行尚未实现" : "研究结果尚未实现"}
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
