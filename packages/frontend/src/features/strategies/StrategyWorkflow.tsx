import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
    Alert,
    Button,
    Card,
    Descriptions,
    Empty,
    Form,
    Input,
    Space,
    Spin,
    Steps,
    Table,
    Typography
} from "antd";
import * as api from "./api";
import { ManualStrategyWorkflow } from "./ManualStrategyWorkflow";
import "./strategyWorkflow.css";

type Context = Awaited<ReturnType<typeof api.loadCreationContext>>;
type Authoring = Awaited<ReturnType<typeof api.saveDefinition>>;
type Preparation = Awaited<ReturnType<typeof api.loadPreparation>>;
type Research = Awaited<ReturnType<typeof api.loadResearch>>;
type Frozen = Awaited<ReturnType<typeof api.freezeStrategy>>;
type Workflow = Awaited<ReturnType<typeof api.loadWorkflows>>["items"][number];
type Action =
    | "save"
    | "freeze"
    | "resume"
    | "cancel-preparation"
    | "cancel-research";
const terminalPreparation = new Set(["READY", "BLOCKED", "CANCELLED"]);
const terminalResearch = new Set(["COMPLETED", "FAILED", "CANCELLED"]);
function description(error: unknown): string {
    if (error instanceof Error && "observe" in error)
        return "结果尚未确认，正在自动查询原操作。请保持此页面打开。";
    return "暂时无法完成此操作，已保留当前策略和研究记录。请稍后重新查看。";
}
function resumable(error: unknown): error is Error & { observe: () => Promise<unknown> } {
    return error instanceof Error && "observe" in error && typeof error.observe === "function";
}
function preparationLabel(value: Preparation): string {
    if (value.run_id !== null) return "已有策略研究";
    return (
        (
            {
                READY: "研究准备已完成",
                BLOCKED: "研究准备暂时受阻",
                INPUT_PENDING: "等待历史行情",
                CANCEL_REQUESTED: "正在取消研究准备",
                CANCELLED: "研究准备已取消",
                UNKNOWN: "准备结果尚未确认"
            } as Record<string, string>
        )[value.state] ?? "正在准备策略研究"
    );
}
function workflowLink(id: string, preparation?: Preparation): string {
    const query = new URLSearchParams();
    if (preparation !== undefined) {
        query.set("preparation", preparation.command_id);
        if (preparation.run_id !== null) query.set("run", preparation.run_id);
    }
    return `/strategies/${encodeURIComponent(id)}${query.size === 0 ? "" : `?${query.toString()}`}`;
}
export function StrategyWorkflow() {
    const location = useLocation();
    const query = new URLSearchParams(location.search);
    const selected = location.pathname.split("/").filter(Boolean)[1];
    const retainedDefinition = query.has("study") && selected !== undefined && selected !== "new";
    return query.has("preparation") || query.has("run") || retainedDefinition ? (
        <ResearchStrategyWorkflow />
    ) : (
        <ManualStrategyWorkflow />
    );
}
function ResearchStrategyWorkflow() {
    const location = useLocation();
    const navigate = useNavigate();
    const parameters = new URLSearchParams(location.search);
    const factor = parameters.get("factor") ?? "";
    const study = parameters.get("study") ?? "";
    const originalPreparation = parameters.get("preparation");
    const originalRun = parameters.get("run");
    const pathId = decodeURIComponent(location.pathname.split("/").filter(Boolean)[1] ?? "");
    const strategyId = pathId && pathId !== "new" ? pathId : undefined;
    const [context, setContext] = useState<Context | null>(null);
    const [authoring, setAuthoring] = useState<Authoring | null>(null);
    const [preparation, setPreparation] = useState<Preparation | null>(null);
    const [preparationLoaded, setPreparationLoaded] = useState(false);
    const [research, setResearch] = useState<Research | null>(null);
    const [frozen, setFrozen] = useState<Frozen | null>(null);
    const [workflows, setWorkflows] = useState<Workflow[]>([]);
    const [history, setHistory] = useState<Preparation[]>([]);
    const [historyLoaded, setHistoryLoaded] = useState(false);
    const [name, setName] = useState("");
    const [loading, setLoading] = useState(false);
    const [contextProblem, setContextProblem] = useState("");
    const [problem, setProblem] = useState("");
    const [busy, setBusy] = useState<Action | null>(null);
    const [revision, setRevision] = useState(0);
    const available = /^[0-9a-f]{64}$/.test(factor) && /^[0-9a-f]{64}$/.test(study);
    const inventory =
        location.pathname.replace(/\/$/, "") === "/strategies" &&
        !available &&
        originalPreparation === null &&
        originalRun === null;
    const runId = preparation === null ? originalRun : preparation.run_id;
    const mounted = useRef(true);
    const activeStrategy = useRef<string | null>(null);
    const loadedRoute = useRef("");
    const selectionEpoch = useRef(0);
    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
        };
    }, []);
    const remember = useCallback(
        (command: string | null, run: string | null, path = location.pathname) => {
            const query = new URLSearchParams(location.search);
            if (command !== null) query.set("preparation", command);
            if (run !== null) query.set("run", run);
            loadedRoute.current = JSON.stringify([path, query.toString(), revision]);
            void navigate({ pathname: path, search: query.toString() }, { replace: true });
        },
        [location.pathname, location.search, navigate, revision]
    );
    const apply = (kind: Action, value: unknown) => {
        if (kind === "save") setAuthoring(value as Authoring);
        else if (["resume", "cancel-preparation"].includes(kind)) {
            const result = value as Preparation;
            setPreparation(result);
            setPreparationLoaded(true);
            // Keep display projections in agreement with this actual reply.
            // They provide no Source permission or backend command authority.
            setContext((value) =>
                value === null
                    ? value
                    : {
                          ...value,
                          existing_preparations: [
                              result,
                              ...value.existing_preparations.filter(
                                  (item) => item.command_id !== result.command_id
                              )
                          ]
                      }
            );
            setHistory((value) => [
                result,
                ...value.filter((item) => item.command_id !== result.command_id)
            ]);
            remember(result.command_id, result.run_id);
        } else if (kind === "cancel-research") setResearch(value as Research);
        else setFrozen(value as Frozen);
    };
    useEffect(() => {
        const route = JSON.stringify([
            location.pathname,
            new URLSearchParams(location.search).toString(),
            revision
        ]);
        if (loadedRoute.current === route) return;
        loadedRoute.current = route;
        selectionEpoch.current += 1;
        let current = true;
        const isCurrent = () => current;
        activeStrategy.current = strategyId ?? null;
        setContext(null);
        setAuthoring(null);
        setPreparation(null);
        setResearch(null);
        setFrozen(null);
        setPreparationLoaded(false);
        setHistory([]);
        setHistoryLoaded(false);
        setWorkflows([]);
        setBusy(null);
        setProblem("");
        setContextProblem("");
        setLoading(true);
        const observePreparation = async (command: string) => {
            try {
                const value = await api.loadPreparation(command);
                if (isCurrent()) {
                    setPreparation(value);
                    setPreparationLoaded(true);
                }
            } catch {
                if (isCurrent()) {
                    setPreparationLoaded(false);
                    setProblem("原研究准备暂时无法读取，请稍后重新查看。");
                }
            }
        };
        // Original history is read independently of permission for new work.
        // A query reference selects a server read; it never implies acceptance.
        const reads: Promise<unknown>[] = [];
        if (originalPreparation !== null) reads.push(observePreparation(originalPreparation));
        if (inventory)
            reads.push(
                (async () => {
                    try {
                        const value = await api.loadWorkflows();
                        if (isCurrent()) setWorkflows(value.items);
                    } catch {
                        if (isCurrent()) setProblem("策略记录暂时无法读取，请稍后重新查看。");
                    }
                })()
            );
        if (strategyId !== undefined)
            reads.push(
                (async () => {
                    try {
                        const value = await api.loadWorkflow(strategyId);
                        if (!isCurrent()) return;
                        setAuthoring(value.authoring);
                        setHistory(value.preparations);
                        setHistoryLoaded(true);
                        if (
                            originalPreparation === null &&
                            originalRun === null &&
                            value.preparations[0]
                        )
                            await observePreparation(value.preparations[0].command_id);
                    } catch {
                        if (isCurrent()) setProblem("已保存策略暂时无法读取，正在保留原研究记录。");
                    }
                })()
            );
        if (available)
            reads.push(
                api
                    .loadCreationContext(factor, study, strategyId)
                    .then(async (value) => {
                        if (!isCurrent()) return;
                        activeStrategy.current = value.draft.strategy_id;
                        setContext(value);
                        setName(value.draft.description || `${value.factor_name}策略`);
                        const original = value.existing_preparations[0];
                        if (originalPreparation === null && originalRun === null && original)
                            await observePreparation(original.command_id);
                    })
                    .catch(() => {
                        if (isCurrent())
                            setContextProblem(
                                "当前条件暂不支持新的研究操作。已有研究记录仍可查看。"
                            );
                    })
            );
        void Promise.all(reads).finally(() => {
            if (isCurrent()) setLoading(false);
        });
        return () => {
            current = false;
            if (loadedRoute.current === route) loadedRoute.current = "";
        };
    }, [
        available,
        factor,
        study,
        strategyId,
        originalPreparation,
        originalRun,
        revision,
        location.pathname,
        location.search,
        inventory
    ]);
    useEffect(() => {
        if (
            preparation === null ||
            (terminalPreparation.has(preparation.state) &&
                preparation.research_outcome !== "OUTCOME_UNKNOWN")
        )
            return;
        let current = true;
        const isCurrent = () => current;
        const timer = window.setTimeout(() => {
            void api
                .loadPreparation(preparation.command_id)
                .then((value) => {
                    if (isCurrent()) {
                        setPreparation(value);
                        setPreparationLoaded(true);
                        setProblem("");
                    }
                })
                .catch(() => {
                    if (isCurrent()) {
                        setPreparationLoaded(false);
                        setProblem("准备进度暂时无法读取，正在保留并核查原任务。");
                    }
                });
        }, 2000);
        return () => {
            current = false;
            window.clearTimeout(timer);
        };
    }, [preparation]);
    useEffect(() => {
        if (runId === null) return;
        let current = true;
        const isCurrent = () => current;
        let timer: number | undefined;
        const observe = async () => {
            try {
                const value = await api.loadResearch(runId);
                if (!isCurrent()) return;
                setResearch(value);
                setProblem("");
                if (!terminalResearch.has(value.state))
                    timer = window.setTimeout(() => {
                        void observe();
                    }, 2000);
            } catch {
                if (isCurrent()) {
                    setProblem("研究进度暂时无法读取，系统会继续核查原研究。");
                    timer = window.setTimeout(() => {
                        void observe();
                    }, 2000);
                }
            }
        };
        void observe();
        return () => {
            current = false;
            window.clearTimeout(timer);
        };
    }, [runId]);
    const act = async (kind: Action, operation: () => Promise<unknown>) => {
        if (busy !== null) return;
        setBusy(kind);
        setProblem("");
        let next = operation;
        const selected = activeStrategy.current;
        const epoch = selectionEpoch.current;
        const isSelected = () =>
            mounted.current &&
            activeStrategy.current === selected &&
            selectionEpoch.current === epoch;
        while (isSelected()) {
            try {
                const result = await next();
                if (isSelected()) {
                    apply(kind, result);
                    setBusy(null);
                }
                return;
            } catch (error) {
                if (!isSelected()) return;
                setProblem(description(error));
                if (!resumable(error)) {
                    setBusy(null);
                    return;
                }
                next = error.observe;
                // Observation is a Query of the original operation, never a new
                // submission. This timer controls polling, not trading truth.
                await new Promise<void>((resolve) => window.setTimeout(resolve, 2000));
            }
        }
    };
    const saved = authoring?.current_revision_fingerprint != null;
    const manualBacktest =
        authoring !== null && authoring.current_revision_fingerprint !== null
            ? `/backtest/new?${new URLSearchParams({ strategy_id: authoring.strategy_id, strategy_revision_fingerprint: authoring.current_revision_fingerprint }).toString()}`
            : "/strategies/new";
    const selectedHistory = [...history, ...(context?.existing_preparations ?? [])];
    const historyKnown = historyLoaded || context !== null;
    const ownerId = strategyId ?? context?.draft.strategy_id;
    const selectedPreparationRead =
        originalPreparation === null ||
        (preparationLoaded && preparation?.command_id === originalPreparation);
    // A collection may precede submission. Only a successful read of this exact
    // original preparation supplies its later accepted Run, never another row.
    const originalObserved =
        preparationLoaded &&
        preparation !== null &&
        selectedHistory.some((item) => item.command_id === preparation.command_id);
    const observedHistory = originalObserved
        ? [
              preparation,
              ...selectedHistory.filter((item) => item.command_id !== preparation.command_id)
          ]
        : selectedHistory;
    const contradictory =
        preparationLoaded &&
        preparation !== null &&
        selectedHistory.some(
            (item) =>
                item.command_id === preparation.command_id &&
                item.research_outcome === "ACCEPTED" &&
                item.run_id !== null &&
                item.run_id !== preparation.run_id
        );
    const mismatched =
        historyKnown &&
        ((originalPreparation !== null &&
            !selectedHistory.some((item) => item.command_id === originalPreparation)) ||
            (selectedPreparationRead &&
                originalRun !== null &&
                !observedHistory.some(
                    (item) =>
                        item.run_id === originalRun &&
                        (originalPreparation === null || item.command_id === originalPreparation)
                )) ||
            (preparation?.strategy_id !== undefined && preparation.strategy_id !== ownerId) ||
            (selectedPreparationRead &&
                preparation !== null &&
                originalRun !== null &&
                preparation.run_id !== originalRun) ||
            contradictory);
    const ready =
        preparation?.state === "READY" &&
        preparation.readiness.state === "VERIFIED" &&
        preparation.prepared_study_fingerprint !== null &&
        preparation.research_outcome === "NOT_SUBMITTED";
    const verified =
        research?.state === "COMPLETED" &&
        research.report_status?.state === "VERIFIED" &&
        research.report?.execution_graph_verified === true;
    const canResume =
        preparation !== null &&
        preparation.run_id === null &&
        preparation.research_outcome === "NOT_SUBMITTED" &&
        ["BLOCKED", "INPUT_PENDING", "UNKNOWN"].includes(preparation.state);
    const canCancelPreparation =
        preparation !== null &&
        preparation.run_id === null &&
        preparation.research_outcome === "NOT_SUBMITTED" &&
        !["CANCEL_REQUESTED", "CANCELLED"].includes(preparation.state);
    const current =
        frozen !== null ? 3 : research !== null || preparation?.run_id != null ? 2 : saved ? 1 : 0;
    if (inventory)
        return (
            <main className="strategy-workflow" aria-label="策略记录">
                <header className="strategy-workflow-header">
                    <Typography.Title level={2}>我的策略</Typography.Title>
                    <Link to="/factor-research">从因子研究创建策略</Link>
                </header>
                {problem && (
                    <Alert
                        type="warning"
                        showIcon
                        title={problem}
                        action={
                            <Button
                                onClick={() => {
                                    setRevision((value) => value + 1);
                                }}
                            >
                                重新查看
                            </Button>
                        }
                    />
                )}
                <Table<Workflow>
                    loading={loading}
                    rowKey="strategy_id"
                    pagination={false}
                    dataSource={workflows}
                    locale={{ emptyText: <Empty description="还没有保存的策略" /> }}
                    columns={[
                        {
                            title: "策略",
                            key: "name",
                            render: (_: unknown, item: Workflow) =>
                                (item.authoring.draft?.description ?? "") || "已保存策略"
                        },
                        {
                            title: "研究进度",
                            key: "progress",
                            render: (_: unknown, item: Workflow) =>
                                item.preparations[0]
                                    ? preparationLabel(item.preparations[0])
                                    : "尚未准备研究"
                        },
                        {
                            title: "操作",
                            key: "open",
                            render: (_: unknown, item: Workflow) => (
                                <Link to={workflowLink(item.strategy_id, item.preparations[0])}>
                                    查看策略
                                </Link>
                            )
                        }
                    ]}
                />
            </main>
        );
    if (
        !available &&
        strategyId === undefined &&
        originalPreparation === null &&
        originalRun === null
    )
        return (
            <section className="strategy-workflow">
                <Empty description="从已确认的因子和研究条件创建策略" />
                <Link to="/factor-research">前往因子研究</Link>
            </section>
        );
    return (
        <main className="strategy-workflow" aria-label="策略创建与验证">
            <header className="strategy-workflow-header">
                <div>
                    <Typography.Title level={2}>策略验证</Typography.Title>
                    <Typography.Paragraph type="secondary">
                        查看已有研究进度、报告和冻结记录，或继续普通回测。
                    </Typography.Paragraph>
                </div>
                <Link to="/factor-research">返回因子研究</Link>
            </header>
            <Link to="/strategies">查看全部策略</Link>
            <Alert
                type="info"
                showIcon
                title="新的策略研究暂未开放，已有记录仍可查看。"
                action={<Link to={manualBacktest}>配置普通回测</Link>}
            />
            <Steps
                current={current}
                status={frozen === null ? "process" : "finish"}
                items={[
                    { title: "策略定义" },
                    { title: "研究准备" },
                    { title: "策略研究" },
                    { title: "冻结版本" }
                ]}
            />
            {mismatched && (
                <Alert
                    type="warning"
                    showIcon
                    title="所选研究与当前策略不一致，请从研究记录重新选择。"
                />
            )}
            {!mismatched && !selectedPreparationRead && (
                <Alert
                    type="info"
                    showIcon
                    title={loading ? "正在核对原研究准备" : "原研究准备暂时无法核验，请重新查看。"}
                    action={
                        <Button
                            onClick={() => {
                                setRevision((value) => value + 1);
                            }}
                        >
                            重新查看
                        </Button>
                    }
                />
            )}
            {contextProblem && (
                <Alert
                    type="warning"
                    showIcon
                    title={contextProblem}
                    action={
                        busy === null ? (
                            <Button
                                onClick={() => {
                                    setRevision((value) => value + 1);
                                }}
                            >
                                重新查看
                            </Button>
                        ) : undefined
                    }
                />
            )}
            {problem && (
                <Alert
                    type="warning"
                    showIcon
                    title={problem}
                    action={
                        busy === null ? (
                            <Button
                                onClick={() => {
                                    setRevision((value) => value + 1);
                                }}
                            >
                                重新查看
                            </Button>
                        ) : undefined
                    }
                />
            )}
            {loading && (
                <Spin description="正在载入策略资料">
                    <div className="strategy-workflow-loading" />
                </Spin>
            )}
            {strategyId !== undefined && history.length > 0 && (
                <Card title="研究记录" size="small">
                    <Table<Preparation>
                        rowKey="command_id"
                        pagination={false}
                        size="small"
                        dataSource={history}
                        columns={[
                            {
                                title: "准备时间（UTC）",
                                key: "time",
                                render: (_: unknown, item: Preparation) =>
                                    typeof item.accepted_at === "string" &&
                                    Number.isFinite(Date.parse(item.accepted_at))
                                        ? new Date(item.accepted_at).toLocaleString("zh-CN", {
                                              timeZone: "UTC",
                                              hour12: false
                                          })
                                        : "时间暂不可用"
                            },
                            {
                                title: "准备与研究状态",
                                key: "state",
                                render: (_: unknown, item: Preparation) => preparationLabel(item)
                            },
                            {
                                title: "操作",
                                key: "open",
                                render: (_: unknown, item: Preparation) => (
                                    <Link to={workflowLink(strategyId, item)}>查看研究</Link>
                                )
                            }
                        ]}
                    />
                </Card>
            )}
            {context && (
                <>
                    <Card title="确认策略规则" size="small">
                        <Typography.Title level={4}>{context.factor_name}</Typography.Title>
                        <Typography.Paragraph>{context.formula}</Typography.Paragraph>
                        <Descriptions
                            size="small"
                            column={{ xs: 1, sm: 2 }}
                            items={[
                                {
                                    key: "instrument",
                                    label: "交易标的",
                                    children: "Binance 现货 BTCUSDT"
                                },
                                {
                                    key: "bar",
                                    label: "信号频率",
                                    children: "1 分钟，仅使用已收盘行情"
                                },
                                {
                                    key: "entry",
                                    label: "入场条件",
                                    children: "空仓且因子值 ≥ 0.001 时入场"
                                },
                                {
                                    key: "exit",
                                    label: "离场条件",
                                    children: "持仓且因子值 ≤ 0 时离场，中间区间保持"
                                }
                            ]}
                        />
                        <Typography.Paragraph type="secondary">
                            只持有一笔多头，不加仓、不做空；预热不足、缺值和除零时不产生新入场信号。资金、费用及成交设置在后续回测中单独确认。
                        </Typography.Paragraph>
                        <Form layout="vertical">
                            <Form.Item label="策略名称">
                                <Input
                                    value={name}
                                    disabled={saved || busy !== null}
                                    maxLength={120}
                                    onChange={(event) => {
                                        setName(event.target.value);
                                    }}
                                />
                            </Form.Item>
                        </Form>
                        <Space wrap>
                            <Button
                                type="primary"
                                disabled={
                                    mismatched || saved || name.trim() === "" || busy !== null
                                }
                                loading={busy === "save"}
                                onClick={() => {
                                    const id = context.draft.strategy_id;
                                    if (strategyId !== id) {
                                        remember(
                                            null,
                                            null,
                                            `/strategies/${encodeURIComponent(id)}`
                                        );
                                    }
                                    void act("save", () =>
                                        api.saveDefinition({
                                            ...context,
                                            draft: { ...context.draft, description: name.trim() }
                                        })
                                    );
                                }}
                            >
                                保存策略定义
                            </Button>
                            {saved && (
                                <Typography.Text type="success">策略定义已保存</Typography.Text>
                            )}
                        </Space>
                    </Card>
                </>
            )}
            {(context !== null || preparation !== null) && (
                <>
                    <Card title="独立样本验证" size="small">
                        <Descriptions
                            size="small"
                            column={1}
                            items={[
                                {
                                    key: "sample",
                                    label: "研究样本（UTC）",
                                    children: "2025-01-02 12:00 至 2025-01-03 00:00"
                                },
                                {
                                    key: "holdout",
                                    label: "保留样本",
                                    children: "2025-01-05 至 06 不读取"
                                },
                                {
                                    key: "warmup",
                                    label: "预热",
                                    children: "由完整计算图确定，单独保留，不计作观测收益"
                                }
                            ]}
                        />
                        <Typography.Paragraph type="secondary">
                            这里保留原研究的样本和准备状态。已有任务可继续准备或取消，不会启动新的策略研究。
                        </Typography.Paragraph>
                        <Space wrap>
                            {canResume && (
                                <Button
                                    disabled={mismatched || busy !== null}
                                    loading={busy === "resume"}
                                    onClick={() => {
                                        if (!mismatched)
                                            void act("resume", () =>
                                                api.resumePreparation(preparation)
                                            );
                                    }}
                                >
                                    继续准备
                                </Button>
                            )}
                            {canCancelPreparation && (
                                <Button
                                    danger
                                    disabled={mismatched || busy !== null}
                                    loading={busy === "cancel-preparation"}
                                    onClick={() => {
                                        if (!mismatched)
                                            void act("cancel-preparation", () =>
                                                api.cancelPreparation(preparation)
                                            );
                                    }}
                                >
                                    取消准备
                                </Button>
                            )}
                        </Space>
                        {preparation !== null && runId === null && (
                            <Alert
                                type={ready ? "success" : "info"}
                                showIcon
                                title={
                                    ready
                                        ? "原研究准备已完成"
                                        : preparationLabel(preparation)
                                }
                            />
                        )}
                    </Card>
                </>
            )}
            <Card title="研究报告与冻结" size="small">
                {mismatched ? (
                    <Typography.Paragraph>
                        未展示其他策略的研究报告，请重新选择本策略的记录。
                    </Typography.Paragraph>
                ) : !selectedPreparationRead ? (
                    <Typography.Paragraph>
                        核验原研究准备与本次报告的关系后，将显示验证结果。
                    </Typography.Paragraph>
                ) : research === null ? (
                    <Typography.Paragraph>
                        暂无这项研究的报告，可查看已有记录或配置普通回测。
                    </Typography.Paragraph>
                ) : !terminalResearch.has(research.state) ? (
                    <Alert
                        type="info"
                        showIcon
                        title={
                            research.state === "CANCEL_REQUESTED"
                                ? "正在取消策略研究"
                                : "正在验证策略"
                        }
                        description="系统会保留进度。刷新后仍会读取同一次研究。"
                    />
                ) : research.state === "COMPLETED" && !verified ? (
                    <Alert
                        type="warning"
                        showIcon
                        title="研究结果暂时无法核验"
                        description="完整策略证据恢复并通过核验后，才能冻结此策略。已有因子统计报告不能代替本次验证。"
                    />
                ) : research.state !== "COMPLETED" ? (
                    <Alert
                        type="warning"
                        title={
                            research.state === "CANCELLED" ? "策略研究已取消" : "策略研究尚未完成"
                        }
                        description="已保留原研究记录，当前不能冻结。"
                    />
                ) : (
                    <>
                        <Alert type="success" showIcon title="完整策略规则验证通过" />
                        <Descriptions
                            size="small"
                            column={{ xs: 1, sm: 2 }}
                            items={[
                                {
                                    key: "observations",
                                    label: "有效观测",
                                    children: research.report?.observation_count
                                },
                                {
                                    key: "warmup",
                                    label: "预热K线",
                                    children: research.report?.warmup_bars
                                },
                                {
                                    key: "nodes",
                                    label: "已验证计算环节",
                                    children: research.report?.node_count
                                },
                                { key: "consistent", label: "逐条计算一致性", children: "已通过" }
                            ]}
                        />
                        {research.report?.limitations.map((limit, index) => (
                            <Typography.Paragraph
                                type="secondary"
                                key={`${String(index)}-${limit}`}
                            >
                                {limit}
                            </Typography.Paragraph>
                        ))}
                    </>
                )}
                {research !== null &&
                    !terminalResearch.has(research.state) &&
                    research.state !== "CANCEL_REQUESTED" && (
                        <Button
                            danger
                            disabled={mismatched || busy !== null}
                            loading={busy === "cancel-research"}
                            onClick={() => {
                                if (!mismatched)
                                    void act("cancel-research", () => api.cancelResearch(research));
                            }}
                        >
                            取消研究
                        </Button>
                    )}
                <Space wrap>
                    <Button
                        type="primary"
                        disabled={
                            mismatched ||
                            !selectedPreparationRead ||
                            !historyKnown ||
                            !verified ||
                            frozen !== null ||
                            busy !== null
                        }
                        loading={busy === "freeze"}
                        onClick={() => {
                            if (!mismatched && selectedPreparationRead && historyKnown && research)
                                void act("freeze", () => api.freezeStrategy(research));
                        }}
                    >
                        冻结策略
                    </Button>
                    {frozen !== null && (
                        <Typography.Text type="success">
                            策略已冻结，可继续配置实验性回测
                        </Typography.Text>
                    )}
                </Space>
                {frozen !== null && research !== null && (
                    <p>
                        <Link
                            to={
                                strategyId !== undefined &&
                                typeof preparation?.strategy_revision_fingerprint === "string" &&
                                /^[0-9a-f]{64}$/.test(preparation.strategy_revision_fingerprint)
                                    ? `/backtest/new?${new URLSearchParams({ strategy_id: strategyId, strategy_revision_fingerprint: preparation.strategy_revision_fingerprint }).toString()}`
                                    : strategyId === undefined
                                      ? "/strategies"
                                      : `/strategies/${encodeURIComponent(strategyId)}`
                            }
                        >
                            配置回测
                        </Link>
                    </p>
                )}
                <Typography.Paragraph type="secondary">
                    计算和规则一致性通过不代表盈利。冻结会保留本次验证对应的固定策略版本，后续修改需创建新版本；本步骤不授权模拟盘或实盘交易。
                </Typography.Paragraph>
            </Card>
        </main>
    );
}
