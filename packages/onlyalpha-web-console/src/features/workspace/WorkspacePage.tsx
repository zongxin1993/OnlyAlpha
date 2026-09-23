import { useState } from "react";
import { PriceChart } from "../../charts/lightweight/PriceChart";
import { type Timeframe } from "../../charts/lightweight/placeholderBars";
import { WorkspaceIcon, type WorkspaceIconName } from "../../shared/components/WorkspaceIcon";

const timeframes: readonly Timeframe[] = ["1m", "5m", "15m", "1H", "1D", "1W"];

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
                    <span className="chart-region__title">600519.SH · 贵州茅台</span>
                    <div className="segmented-control" role="group" aria-label="时间周期">
                        {timeframes.map((item) => (
                            <button
                                key={item}
                                type="button"
                                aria-pressed={timeframe === item}
                                onClick={() => {
                                    setTimeframe(item);
                                }}
                            >
                                {item}
                            </button>
                        ))}
                    </div>
                    <span className="chart-region__spacer">
                        <span className="synthetic-tag">synthetic</span>
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
                <div className="chart-region__body">
                    <PriceChart timeframe={timeframe} />
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
        </section>
    );
}
