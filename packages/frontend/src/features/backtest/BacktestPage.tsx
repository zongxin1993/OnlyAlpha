import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
    Alert,
    Button,
    Card,
    Descriptions,
    Empty,
    Select,
    Space,
    Spin,
    Statistic,
    Table,
    Typography
} from "antd";
import { BacktestEquityChart } from "../../visualization/scientific/echarts/BacktestEquityChart";
import * as api from "./api";
import { BacktestSetup } from "./BacktestSetup";
import "./backtest.css";

type Run = Awaited<ReturnType<typeof api.loadRun>>;
type Preparation = Awaited<ReturnType<typeof api.loadPreparation>>;
type Result = Awaited<ReturnType<typeof api.loadResult>>;
type Models = Awaited<ReturnType<typeof api.loadModels>>["items"];
type Interpretation = Awaited<ReturnType<typeof api.interpretResult>>;
const completed = new Set(["COMPLETED", "FAILED", "CANCELLED"]);
const blocked = new Set(["BLOCKED", "UNKNOWN", "INPUT_PENDING"]);
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
function time(value: string): string {
    const date = new Date(value);
    return Number.isFinite(date.valueOf())
        ? date.toLocaleString("zh-CN", { timeZone: "UTC", hour12: false })
        : "时间暂不可用";
}
function nanos(value: string): string {
    try {
        return time(new Date(Number(BigInt(value) / 1_000_000n)).toISOString());
    } catch {
        return "时间暂不可用";
    }
}
function percentage(value: string | null): string {
    return value !== null && Number.isFinite(Number(value))
        ? `${(Number(value) * 100).toFixed(4)}%`
        : "暂不可用";
}
function label(state: string): string {
    return (
        (
            {
                QUEUED: "等待回测",
                RUNNING: "正在回测",
                COMPLETED: "已完成",
                FAILED: "未完成",
                CANCEL_REQUESTED: "正在取消",
                CANCELLED: "已取消",
                READY: "可以开始回测",
                BLOCKED: "准备暂时受阻",
                UNKNOWN: "结果尚未确认",
                INPUT_PENDING: "等待行情数据",
                ACCEPTED: "正在准备回测"
            } as Record<string, string>
        )[state] ?? "正在准备回测"
    );
}
function recoverable(value: unknown): value is Error & { observe: () => Promise<unknown> } {
    return value instanceof Error && "observe" in value && typeof value.observe === "function";
}
function EquityChart({ result }: { result: Result }) {
    const points = useMemo(
        () =>
            result.curve.map((point) => ({
                timeLabel: nanos(point.at_ns),
                equity: Number(point.nav),
                drawdownPercent: point.drawdown === null ? null : Number(point.drawdown) * 100
            })),
        [result]
    );
    return <BacktestEquityChart points={points} />;
}

export function BacktestPage() {
    const location = useLocation();
    const [refresh, setRefresh] = useState(0);
    return (
        <BacktestRoute
            key={JSON.stringify([location.pathname, location.search, refresh])}
            onRefresh={() => {
                setRefresh((value) => value + 1);
            }}
        />
    );
}

function BacktestRoute({ onRefresh }: { onRefresh: () => void }) {
    const location = useLocation();
    const navigate = useNavigate();
    const parts = location.pathname.split("/").filter(Boolean);
    const id = parts[2] ?? "";
    const fresh = parts[1] === "new";
    const runRoute = parts[1] === "runs" && uuid.test(id);
    const preparationRoute = parts[1] === "preparations" && uuid.test(id);
    const inventory = parts.length === 1;
    const [runs, setRuns] = useState<Run[]>([]),
        [run, setRun] = useState<Run | null>(null);
    const [preparation, setPreparation] = useState<Preparation | null>(null),
        [result, setResult] = useState<Result | null>(null);
    const [models, setModels] = useState<Models>([]),
        [model, setModel] = useState<string | undefined>();
    const [interpretation, setInterpretation] = useState<Interpretation | null>(null),
        [analysisProblem, setAnalysisProblem] = useState("");
    const [problem, setProblem] = useState(""),
        [busy, setBusy] = useState<string | null>(null),
        [loading, setLoading] = useState(inventory || runRoute || preparationRoute);
    const [notStarted, setNotStarted] = useState<api.PreparationNotStarted | null>(null);
    const [recovery, setRecovery] = useState<{
        action: string;
        observe: () => Promise<unknown>;
    } | null>(null);
    const epoch = useRef(0);
    useEffect(() => {
        const selected = ++epoch.current;
        let current = true;
        const isCurrent = () => current;
        let timer: ReturnType<typeof setTimeout> | undefined;
        if (!inventory && !fresh && !runRoute && !preparationRoute) return;
        const read = async () => {
            try {
                if (inventory) {
                    const value = await api.loadRuns();
                    if (isCurrent()) setRuns(value.items);
                }
                if (preparationRoute) {
                    const value = await api.loadPreparation(id);
                    if (!isCurrent()) return;
                    setPreparation(value);
                    if (value.run_id !== null) {
                        void navigate(`/backtest/runs/${value.run_id}`, {
                            replace: true
                        });
                        return;
                    }
                    if (
                        value.backtest_outcome === "OUTCOME_UNKNOWN" ||
                        !["READY", "CANCELLED", "BLOCKED", "UNKNOWN"].includes(value.state)
                    )
                        timer = setTimeout(() => {
                            setLoading(true);
                            void read();
                        }, 3000);
                }
                if (runRoute) {
                    const value = await api.loadRun(id);
                    if (!isCurrent()) return;
                    setRun(value);
                    if (value.report_status.state === "VERIFIED") {
                        const original = await api.loadResult(id);
                        if (!isCurrent()) return;
                        if (original.strategy_fingerprint !== value.strategy_fingerprint)
                            throw new Error("回测结果与原策略不一致。");
                        setResult(original);
                    }
                    if (!completed.has(value.state))
                        timer = setTimeout(() => {
                            setLoading(true);
                            void read();
                        }, 3000);
                }
            } catch {
                if (isCurrent())
                    setProblem("暂时无法读取当前记录。已有策略与回测仍然保留，请重新查看。");
            } finally {
                if (isCurrent()) setLoading(false);
            }
        };
        void read();
        if (runRoute) {
            void api
                .loadModels()
                .then((value) => {
                    if (isCurrent()) {
                        setModels(value.items);
                        setModel(value.items.length === 1 ? value.items[0]?.revision : undefined);
                    }
                })
                .catch(() => {
                    if (isCurrent())
                        setAnalysisProblem("模型暂时无法加载，请在设置中查看模型配置。");
                });
            void api
                .loadInterpretation(id)
                .then((value) => {
                    if (isCurrent()) setInterpretation(value);
                })
                .catch(() => {
                    if (isCurrent())
                        setAnalysisProblem(
                            "原解读暂时无法读取，已保留记录。请重新查看，系统不会自动再次调用模型。"
                        );
                });
        }
        return () => {
            current = false;
            if (timer !== undefined) clearTimeout(timer);
            if (epoch.current === selected) epoch.current += 1;
        };
    }, [
        location.pathname,
        location.search,
        inventory,
        fresh,
        runRoute,
        preparationRoute,
        id,
        navigate
    ]);
    const act = async (name: string, action: () => Promise<unknown>) => {
        if (busy !== null) return;
        const selected = epoch.current;
        setBusy(name);
        setProblem("");
        setNotStarted(null);
        try {
            const value = await action();
            if (epoch.current !== selected) return;
            if (name === "start") {
                const accepted = value as Awaited<ReturnType<typeof api.confirmBacktest>>;
                if (accepted.run_id !== null) void navigate(`/backtest/runs/${accepted.run_id}`);
            } else if (name === "cancel-run") setRun(value as Run);
            else {
                const actual = value as Preparation;
                setRecovery(null);
                setPreparation(actual);
                if (actual.run_id !== null) void navigate(`/backtest/runs/${actual.run_id}`);
                else
                    void navigate(`/backtest/preparations/${actual.command_id}`, { replace: true });
            }
        } catch (error) {
            if (epoch.current === selected) {
                if (api.isPreparationNotStarted(error)) {
                    setRecovery(null);
                    setNotStarted(error);
                    setProblem(error.message);
                } else if (recoverable(error)) {
                    setRecovery({
                        action: name,
                        observe: error.observe
                    });
                    setProblem("操作结果尚未确认，请查看原任务的进度。");
                } else setProblem("本次操作暂未完成。已有记录仍然保留，请重新查看当前进度。");
            }
        } finally {
            if (epoch.current === selected) setBusy(null);
        }
    };
    const reviewConditions = async (original: api.PreparationNotStarted) => {
        if (busy !== null) return;
        const selected = epoch.current;
        setBusy("review-conditions");
        try {
            const actual = await original.reviewConditions();
            if (epoch.current !== selected) return;
            setNotStarted(null);
            setRecovery(null);
            setProblem("");
            if (actual === null) onRefresh();
            else {
                setPreparation(actual);
                if (actual.run_id !== null) void navigate(`/backtest/runs/${actual.run_id}`);
                else
                    void navigate(`/backtest/preparations/${actual.command_id}`, { replace: true });
            }
        } catch (error) {
            if (epoch.current !== selected) return;
            if (recoverable(error)) {
                setNotStarted(null);
                setRecovery({ action: "prepare", observe: error.observe });
                setProblem("操作结果尚未确认，请查看原任务的进度。");
            } else setProblem("原请求记录已变化，请重新查看原任务。");
        } finally {
            if (epoch.current === selected) setBusy(null);
        }
    };
    const ready =
        preparation?.state === "READY" &&
        preparation.readiness.state === "VERIFIED" &&
        preparation.preparation_fingerprint !== null &&
        preparation.backtest_outcome === "NOT_SUBMITTED";
    const submissionUnknown = preparation?.backtest_outcome === "OUTCOME_UNKNOWN";
    const workerWarning =
        run === null || completed.has(run.state)
            ? undefined
            : run.worker_observation?.state === "UNKNOWN"
              ? "回测执行状态尚未确认"
              : run.worker_observation?.state === "UNAVAILABLE"
                ? "回测执行服务暂不可用"
                : run.worker_observation?.state === "STOPPED"
                  ? "回测执行服务已停止"
                  : undefined;
    return (
        <main className="backtest-page" aria-label="策略回测">
            <header className="backtest-page-header">
                <div>
                    <Typography.Title level={2}>
                        {result ? "回测结果" : "策略回测"}
                    </Typography.Title>
                    <Typography.Text type="secondary">
                        Binance 现货 · BTCUSDT · 1 分钟
                    </Typography.Text>
                </div>
                <Space wrap>
                    <Link to="/strategies">我的策略</Link>
                    {!fresh && <Link to="/backtest/new">新建回测</Link>}
                    {!inventory && <Link to="/backtest">回测记录</Link>}
                    <Button onClick={onRefresh} disabled={busy !== null}>
                        重新查看
                    </Button>
                </Space>
            </header>
            {problem && (
                <Alert
                    type="warning"
                    showIcon
                    title={problem}
                    action={
                        notStarted !== null ? (
                            <Button
                                disabled={busy !== null}
                                onClick={() => {
                                    void reviewConditions(notStarted);
                                }}
                            >
                                返回条件重新确认
                            </Button>
                        ) : recovery !== null ? (
                            <Space>
                                <Button
                                    disabled={busy !== null}
                                    onClick={() => {
                                        void act(recovery.action, recovery.observe);
                                    }}
                                >
                                    查看任务进度
                                </Button>
                            </Space>
                        ) : undefined
                    }
                />
            )}
            {!inventory && !fresh && !runRoute && !preparationRoute && (
                <Empty description="请选择已有回测，或选择已保存的策略开始" />
            )}
            {loading && (
                <Spin description="正在读取回测记录">
                    <div className="backtest-loading" />
                </Spin>
            )}
            {inventory && (
                <Table<Run>
                    rowKey="run_id"
                    loading={loading}
                    pagination={{ pageSize: 12 }}
                    dataSource={runs}
                    locale={{
                        emptyText: (
                            <Empty description="尚无回测记录">
                                <Link to="/backtest/new">选择策略准备回测</Link>
                            </Empty>
                        )
                    }}
                    columns={[
                        {
                            title: "创建时间（UTC）",
                            render: (_: unknown, value: Run) => time(value.accepted_at)
                        },
                        {
                            title: "进度",
                            render: (_: unknown, value: Run) => label(value.state)
                        },
                        {
                            title: "操作",
                            render: (_: unknown, value: Run) => (
                                <Link to={`/backtest/runs/${value.run_id}`}>查看回测</Link>
                            )
                        }
                    ]}
                />
            )}
            {fresh && preparation === null && (
                <BacktestSetup
                    query={location.search}
                    busy={busy !== null || recovery !== null}
                    onPrepare={(action) => {
                        void act("prepare", action);
                    }}
                />
            )}
            {preparation !== null && (
                <Card title="确认回测条件" size="small">
                    <Descriptions
                        column={{ xs: 1, sm: 2 }}
                        size="small"
                        items={[
                            {
                                key: "sample",
                                label: "样本（UTC）",
                                children: "2025-01-03 00:00 至 12:00"
                            },
                            {
                                key: "capital",
                                label: "初始资金",
                                children: "10,000 USDT"
                            },
                            {
                                key: "size",
                                label: "仓位",
                                children: "每笔 0.01 BTC，仅持有一笔多头"
                            },
                            {
                                key: "cost",
                                label: "费用",
                                children: "手续费每边 0.1%；滑点每边 0.02%"
                            }
                        ]}
                    />
                    <Typography.Paragraph type="secondary">
                        使用固定的完整交易规则和已封存行情，收盘信号最早在下一分钟开盘成交。不借币、不加仓。准备完成后再确认开始回测。
                    </Typography.Paragraph>
                    <Alert
                        type={
                            ready
                                ? "success"
                                : submissionUnknown || blocked.has(preparation.state)
                                  ? "warning"
                                  : "info"
                        }
                        showIcon
                        title={
                            submissionUnknown
                                ? "结果尚未确认，正在读取原任务"
                                : preparation.state === "READY" && !ready
                                  ? "当前回测环境暂不可用，请重新查看"
                                  : label(preparation.state)
                        }
                    />
                    <Space wrap>
                        <Button
                            type="primary"
                            disabled={!ready || busy !== null}
                            loading={busy === "start"}
                            onClick={() => {
                                void act("start", () => api.confirmBacktest(preparation));
                            }}
                        >
                            开始回测
                        </Button>
                        {preparation.run_id === null && blocked.has(preparation.state) && (
                            <Button
                                disabled={busy !== null}
                                onClick={() => {
                                    void act("resume", () => api.resumePreparation(preparation));
                                }}
                            >
                                继续准备
                            </Button>
                        )}
                        {preparation.run_id === null &&
                            !["CANCEL_REQUESTED", "CANCELLED"].includes(preparation.state) && (
                                <Button
                                    danger
                                    disabled={busy !== null}
                                    onClick={() => {
                                        void act("cancel", () =>
                                            api.cancelPreparation(preparation)
                                        );
                                    }}
                                >
                                    取消准备
                                </Button>
                            )}
                    </Space>
                </Card>
            )}
            {run && result === null && (
                <Card title="回测进度">
                    {workerWarning !== undefined && (
                        <Alert
                            type="warning"
                            showIcon
                            title={workerWarning}
                            description="原回测记录仍然保留，系统会继续查询同一任务，不会自动重新提交。"
                        />
                    )}
                    <Alert
                        showIcon
                        type={completed.has(run.state) ? "warning" : "info"}
                        title={label(run.state)}
                        description={
                            run.report_status.state === "UNAVAILABLE"
                                ? "结果暂时无法核验，原任务仍然保留。请稍后重新查看。"
                                : "页面刷新后仍会读取同一次回测。"
                        }
                    />
                    {!completed.has(run.state) && run.state !== "CANCEL_REQUESTED" && (
                        <Button
                            danger
                            disabled={busy !== null}
                            onClick={() => {
                                void act("cancel-run", () => api.cancelBacktest(run));
                            }}
                        >
                            取消回测
                        </Button>
                    )}
                </Card>
            )}
            {result && (
                <>
                    <Alert
                        type="info"
                        showIcon
                        title={
                            result.state === "CANCELLED"
                                ? "回测已取消，以下为已完成部分的结果"
                                : "探索性回测"
                        }
                        description={result.limitations.join(" ")}
                    />
                    <div className="backtest-metrics">
                        {[
                            ["净收益（USDT）", result.metrics.net_pnl],
                            ["区间收益率", percentage(result.metrics.return_since_start)],
                            ["最大回撤", percentage(result.metrics.maximum_drawdown)],
                            ["手续费（USDT）", result.metrics.fees],
                            ["成交笔数", result.metrics.fill_count],
                            ["完整交易次数", result.metrics.roundtrip_count]
                        ].map(([title, value]) => (
                            <Card key={title} size="small">
                                <Statistic
                                    title={title}
                                    value={value ?? "暂不可用"}
                                    formatter={() => String(value ?? "暂不可用")}
                                />
                            </Card>
                        ))}
                    </div>
                    <Card title="账户权益与回撤" size="small">
                        <EquityChart result={result} />
                        {result.baseline && (
                            <Typography.Paragraph type="secondary">
                                同一时段买入并持有 0.01 BTC，采用相同费用和滑点假设：期末权益{" "}
                                {result.baseline.final_equity} USDT，区间收益率{" "}
                                {percentage(result.baseline.return_since_start)}
                                。这是一项估算参照。
                            </Typography.Paragraph>
                        )}
                    </Card>
                    <Card title="成交明细" size="small">
                        <Table<Result["trades"][number]>
                            rowKey="ordinal"
                            dataSource={result.trades}
                            size="small"
                            scroll={{ x: 760 }}
                            pagination={{ pageSize: 10 }}
                            columns={[
                                {
                                    title: "成交时间（UTC）",
                                    render: (_: unknown, value: Result["trades"][number]) =>
                                        nanos(value.time_ns)
                                },
                                {
                                    title: "方向",
                                    render: (_: unknown, value: Result["trades"][number]) =>
                                        value.side === "BUY" ? "买入" : "卖出"
                                },
                                { title: "数量（BTC）", dataIndex: "quantity" },
                                { title: "成交价（USDT）", dataIndex: "price" },
                                { title: "手续费（USDT）", dataIndex: "fee" },
                                {
                                    title: "交易原因",
                                    render: (_: unknown, value: Result["trades"][number]) => (
                                        <>
                                            {value.signal}
                                            <br />
                                            <Typography.Text type="secondary">
                                                信号形成于 {nanos(value.signal_time_ns)} UTC
                                            </Typography.Text>
                                        </>
                                    )
                                }
                            ]}
                        />
                    </Card>
                    <Card title="期末持仓" size="small">
                        <Table<Result["positions"][number]>
                            rowKey="instrument"
                            pagination={false}
                            dataSource={result.positions}
                            size="small"
                            columns={[
                                { title: "标的", render: () => "BTCUSDT" },
                                {
                                    title: "持仓数量（BTC）",
                                    dataIndex: "quantity"
                                },
                                {
                                    title: "持仓均价（USDT）",
                                    render: (_: unknown, value: Result["positions"][number]) =>
                                        value.average_price ?? "—"
                                },
                                {
                                    title: "状态",
                                    render: (_: unknown, value: Result["positions"][number]) =>
                                        value.state === "CLOSED"
                                            ? "已平仓"
                                            : value.state === "OPEN"
                                              ? "持有多头"
                                              : "正在核对持仓"
                                }
                            ]}
                        />
                    </Card>
                    <Card title="结果解读" size="small">
                        {interpretation ? (
                            <>
                                <Typography.Paragraph className="backtest-interpretation">
                                    {interpretation.message}
                                </Typography.Paragraph>
                                {interpretation.provenance && (
                                    <Typography.Text type="secondary">
                                        {interpretation.provenance.model.name} ·{" "}
                                        {interpretation.provenance.model.model_id} ·{" "}
                                        {interpretation.provenance.model.model_version}
                                    </Typography.Text>
                                )}
                            </>
                        ) : (
                            <>
                                <Typography.Paragraph type="secondary">
                                    使用已配置的模型分析本次结果。模型解读不能代替统计验证，也不会更改策略。
                                </Typography.Paragraph>
                                {analysisProblem && (
                                    <Alert type="warning" title={analysisProblem} />
                                )}
                                <Space wrap>
                                    <Select
                                        aria-label="解读模型"
                                        placeholder="选择模型"
                                        value={model}
                                        onChange={setModel}
                                        disabled={busy !== null}
                                        options={models.map((value) => ({
                                            value: value.revision,
                                            label: value.name
                                        }))}
                                    />
                                    <Button
                                        aria-label={
                                            busy === "interpret" ? "正在解读" : "解读本次结果"
                                        }
                                        aria-busy={busy === "interpret"}
                                        disabled={
                                            model === undefined ||
                                            busy !== null ||
                                            result.state !== "COMPLETED"
                                        }
                                        loading={busy === "interpret"}
                                        onClick={() => {
                                            if (model === undefined) return;
                                            const selected = epoch.current;
                                            setBusy("interpret");
                                            setAnalysisProblem("");
                                            void api
                                                .interpretResult(result, model)
                                                .then((value) => {
                                                    if (epoch.current === selected)
                                                        setInterpretation(value);
                                                })
                                                .catch(() => {
                                                    if (epoch.current === selected)
                                                        setAnalysisProblem(
                                                            "解读结果暂未取得，请重新查看原记录。系统不会自动再次调用模型。"
                                                        );
                                                })
                                                .finally(() => {
                                                    if (epoch.current === selected) setBusy(null);
                                                });
                                        }}
                                    >
                                        {busy === "interpret" ? "正在解读" : "解读本次结果"}
                                    </Button>
                                </Space>
                            </>
                        )}
                    </Card>
                    <Descriptions
                        size="small"
                        column={{ xs: 1, sm: 2 }}
                        items={[
                            {
                                key: "initial",
                                label: "初始资金（USDT）",
                                children: result.metrics.initial_equity
                            },
                            {
                                key: "final",
                                label: "期末权益（USDT）",
                                children: result.metrics.final_equity
                            },
                            {
                                key: "realized",
                                label: "已实现盈亏（USDT）",
                                children: result.metrics.realized_pnl
                            },
                            {
                                key: "unrealized",
                                label: "未实现盈亏（USDT）",
                                children: result.metrics.unrealized_pnl
                            },
                            {
                                key: "sample",
                                label: "样本（UTC）",
                                children: `${time(result.sample.start_at)} 至 ${time(result.sample.end_at)}`
                            },
                            {
                                key: "rules",
                                label: "交易规则获取时间（UTC）",
                                children: time(result.sample.rule_observed_at)
                            }
                        ]}
                    />
                </>
            )}
        </main>
    );
}
