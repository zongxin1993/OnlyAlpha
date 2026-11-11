import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
    Alert,
    Button,
    Card,
    Descriptions,
    Empty,
    Form,
    Input,
    Select,
    Space,
    Spin,
    Table,
    Typography
} from "antd";
import * as api from "./manualApi";
import type { Authoring } from "./api";
import { PageHeader } from "../../app/shell/PageHeader";
import "./strategyWorkflow.css";
type Factor = Awaited<ReturnType<typeof api.loadFactors>>[number];
type Workflow = Awaited<ReturnType<typeof api.loadWorkflow>>;
type WorkflowItem = Awaited<ReturnType<typeof api.loadWorkflows>>["items"][number];
function backtestLink(id: string, revision: string) {
    return `/backtest/new?${new URLSearchParams({ strategy_id: id, strategy_revision_fingerprint: revision }).toString()}`;
}
function researchLink(item: WorkflowItem) {
    const first = item.preparations[0];
    if (first === undefined) return null;
    const query = new URLSearchParams({ preparation: first.command_id });
    if (first.run_id !== null) query.set("run", first.run_id);
    return `/strategies/${encodeURIComponent(item.strategy_id)}?${query.toString()}`;
}
function preparationLabel(state: string) {
    return (
        (
            {
                READY: "等待开始回测",
                BLOCKED: "准备暂时受阻",
                UNKNOWN: "结果尚未确认",
                INPUT_PENDING: "等待历史行情",
                CANCEL_REQUESTED: "正在取消准备",
                CANCELLED: "准备已取消"
            } as Record<string, string>
        )[state] ?? "正在准备回测"
    );
}
function Rules() {
    return (
        <>
            <Typography.Paragraph>
                因子使用当前收盘价、20 分钟前收盘价、当前成交量与最近 20
                分钟平均成交量，均来自已收盘的一分钟行情。
            </Typography.Paragraph>
            <Descriptions
                size="small"
                column={{ xs: 1, sm: 2 }}
                items={[
                    { key: "instrument", label: "交易标的", children: "Binance 现货 BTCUSDT" },
                    { key: "bar", label: "信号频率", children: "1 分钟，仅使用已收盘行情" },
                    { key: "entry", label: "入场条件", children: "空仓且因子值 ≥ 0.001 时入场" },
                    {
                        key: "exit",
                        label: "离场条件",
                        children: "持仓且因子值 ≤ 0 时离场，中间区间保持"
                    }
                ]}
            />
            <Typography.Paragraph type="secondary">
                仅持有一笔多头，不加仓、不做空。预热不足、缺值及除零时不产生新入场信号；资金、数量和费用在回测页确认。
            </Typography.Paragraph>
        </>
    );
}
export function ManualStrategyWorkflow() {
    const location = useLocation(),
        navigate = useNavigate();
    const parts = location.pathname.split("/").filter(Boolean);
    const creating = parts[1] === "new";
    const id = parts[1] && !creating ? decodeURIComponent(parts[1]) : undefined;
    const target = creating
        ? (new URLSearchParams(location.search).get("strategy_id") ?? undefined)
        : id;
    const inventory = !creating && id === undefined;
    const [factors, setFactors] = useState<Factor[]>([]),
        [factor, setFactor] = useState<Factor | null>(null);
    const [context, setContext] = useState<api.ManualContext | null>(null),
        [authoring, setAuthoring] = useState<Authoring | null>(null);
    const [workflows, setWorkflows] = useState<
            Awaited<ReturnType<typeof api.loadWorkflows>>["items"]
        >([]),
        [workflow, setWorkflow] = useState<Workflow | null>(null);
    const [name, setName] = useState(""),
        [problem, setProblem] = useState(""),
        [loading, setLoading] = useState(true),
        [saving, setSaving] = useState(false),
        [refresh, setRefresh] = useState(0);
    const [recovery, setRecovery] = useState<(() => Promise<Authoring>) | null>(null);
    const epoch = useRef(0);
    const canonicalizing = useRef<string | null>(null);
    useEffect(
        () => () => {
            epoch.current += 1;
        },
        []
    );
    useEffect(() => {
        if (creating && target !== undefined && canonicalizing.current === target) {
            canonicalizing.current = null;
            // Fixing the URL keeps the just-read form and keyboard focus. Any
            // later navigation still invalidates every in-flight observation.
            return;
        }
        epoch.current += 1;
        let current = true;
        setContext(null);
        setFactor(null);
        setFactors([]);
        setName("");
        setWorkflows([]);
        setAuthoring(null);
        setWorkflow(null);
        setProblem("");
        setRecovery(null);
        setSaving(false);
        setLoading(true);
        const read = async () => {
            try {
                if (inventory) {
                    const value = await api.loadWorkflows();
                    if (current) setWorkflows(value.items);
                } else if (creating) {
                    const original =
                        target === undefined ? null : api.pendingManualDefinition(target);
                    if (original !== null) {
                        if (current) {
                            setName(original.name);
                            setRecovery(() => original.observe);
                            setProblem(
                                "保存结果尚未确认，请查看原保存进度。不会重复提交未确认的操作。"
                            );
                        }
                        return;
                    }
                    const value = await api.loadFactors();
                    if (current) setFactors(value);
                } else if (id !== undefined) {
                    const value = await api.loadWorkflow(id);
                    if (current) {
                        setWorkflow(value);
                        setAuthoring(value.authoring);
                    }
                }
            } catch {
                if (current) setProblem("暂时无法读取策略资料，已保存的记录仍然保留。请重新查看。");
            } finally {
                if (current) setLoading(false);
            }
        };
        void read();
        return () => {
            current = false;
        };
    }, [creating, id, inventory, location.pathname, location.search, target, refresh]);
    const choose = (selected: Factor | undefined) => {
        const selection = ++epoch.current;
        setFactor(selected ?? null);
        setContext(null);
        setAuthoring(null);
        setProblem("");
        setRecovery(null);
        if (selected === undefined) return;
        setLoading(true);
        void api
            .loadManualContext(selected.locator, target)
            .then((value) => {
                if (epoch.current === selection) {
                    setContext(value);
                    setName(value.draft.description || `${value.factor_name} 多头策略`);
                    setLoading(false);
                    if (target !== value.draft.strategy_id) {
                        canonicalizing.current = value.draft.strategy_id;
                        const query = new URLSearchParams(location.search);
                        query.set("strategy_id", value.draft.strategy_id);
                        void navigate(`/strategies/new?${query.toString()}`, { replace: true });
                    }
                }
            })
            .catch(() => {
                if (epoch.current === selection)
                    setProblem("这个因子暂时无法用于当前回测，请重新选择或查看因子设置。");
            })
            .finally(() => {
                if (epoch.current === selection) setLoading(false);
            });
    };
    const acceptSaved = (value: Authoring) => {
        if (value.current_revision_fingerprint === null) throw new Error("策略版本尚未确认。");
        setAuthoring(value);
        setSaving(false);
        setRecovery(null);
        void navigate(`/strategies/${encodeURIComponent(value.strategy_id)}`);
    };
    const save = async (observe?: () => Promise<Authoring>) => {
        const action =
            observe ?? (context === null ? null : () => api.saveManualDefinition(context, name));
        if (saving || action === null) return;
        const selection = epoch.current;
        setSaving(true);
        setProblem("");
        try {
            const value = await action();
            if (epoch.current === selection) acceptSaved(value);
        } catch (error) {
            if (epoch.current === selection) {
                if (
                    error instanceof Error &&
                    "observe" in error &&
                    typeof error.observe === "function"
                ) {
                    setRecovery(() => error.observe as () => Promise<Authoring>);
                    setProblem("保存结果尚未确认，正在保留原操作。请查看保存进度。");
                } else setProblem("策略暂未保存成功。请重新查看资料后继续。");
            }
        } finally {
            if (epoch.current === selection) setSaving(false);
        }
    };
    const revision = authoring?.current_revision_fingerprint ?? null;
    return (
        <div className="page-with-head">
            <PageHeader title="策略" subtitle="草稿、冻结版本与晋级" />
            <main className="strategy-workflow" aria-label={inventory ? "策略记录" : "策略定义"}>
                <header className="strategy-workflow-header">
                    <div>
                        <Typography.Title level={2}>
                            {inventory
                                ? "我的策略"
                                : creating
                                  ? "新建回测策略"
                                  : (authoring?.draft?.description ?? "") || "策略定义"}
                        </Typography.Title>
                        <Typography.Paragraph type="secondary">
                            选择已保存因子，确认交易规则，再准备回测。无需先创建研究报告。
                        </Typography.Paragraph>
                    </div>
                    <Space wrap>
                        {!inventory && <Link to="/strategies">我的策略</Link>}
                        <Link to="/backtest">回测记录</Link>
                        {inventory && <Link to="/strategies/new">新建策略</Link>}
                        <Button
                            disabled={saving || recovery !== null}
                            onClick={() => {
                                setRefresh((value) => value + 1);
                            }}
                        >
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
                            recovery !== null ? (
                                <Button
                                    disabled={saving}
                                    onClick={() => {
                                        void save(recovery);
                                    }}
                                >
                                    查看保存进度
                                </Button>
                            ) : undefined
                        }
                    />
                )}
                {loading && (
                    <Spin description="正在读取策略资料">
                        <div className="strategy-workflow-loading" />
                    </Spin>
                )}
                {inventory && (
                    <Table
                        loading={loading}
                        rowKey="strategy_id"
                        scroll={{ x: 600 }}
                        dataSource={workflows}
                        pagination={{ pageSize: 12 }}
                        locale={{
                            emptyText: (
                                <Empty description="还没有保存的策略">
                                    <Link to="/strategies/new">选择因子创建策略</Link>
                                </Empty>
                            )
                        }}
                        columns={[
                            {
                                title: "策略",
                                render: (_: unknown, item: WorkflowItem) =>
                                    (item.authoring.draft?.description ?? "") || "已保存策略"
                            },
                            {
                                title: "回测进度",
                                render: (_: unknown, item: WorkflowItem) =>
                                    item.backtest_preparations[0]
                                        ? item.backtest_preparations[0].run_id === null
                                            ? preparationLabel(item.backtest_preparations[0].state)
                                            : "已创建回测"
                                        : "尚未准备回测"
                            },
                            {
                                title: "操作",
                                render: (_: unknown, item: WorkflowItem) => {
                                    const legacy = researchLink(item);
                                    return (
                                        <Space wrap>
                                            <Link
                                                to={`/strategies/${encodeURIComponent(item.strategy_id)}`}
                                            >
                                                查看策略
                                            </Link>
                                            {item.authoring.current_revision_fingerprint !==
                                                null && (
                                                <Link
                                                    to={backtestLink(
                                                        item.strategy_id,
                                                        item.authoring.current_revision_fingerprint
                                                    )}
                                                >
                                                    配置回测
                                                </Link>
                                            )}
                                            {legacy && <Link to={legacy}>查看研究</Link>}
                                        </Space>
                                    );
                                }
                            }
                        ]}
                    />
                )}
                {creating && context === null && recovery !== null && (
                    <Card title="正在保存的策略" size="small">
                        <Typography.Text>{name}</Typography.Text>
                    </Card>
                )}
                {creating && (context !== null || recovery === null) && (
                    <Card title="选择因子" size="small">
                        <Form layout="vertical">
                            <Form.Item label="已保存因子">
                                <Select
                                    aria-label="已保存因子"
                                    placeholder="请选择已保存的因子"
                                    value={
                                        factor === null ? undefined : JSON.stringify(factor.locator)
                                    }
                                    disabled={saving || recovery !== null}
                                    options={factors.map((value) => ({
                                        value: JSON.stringify(value.locator),
                                        label: value.name
                                    }))}
                                    onChange={(value) => {
                                        choose(
                                            factors.find(
                                                (item) => JSON.stringify(item.locator) === value
                                            )
                                        );
                                    }}
                                />
                            </Form.Item>
                        </Form>
                        {!loading && factors.length === 0 && (
                            <Empty description="尚无可用的已保存因子" />
                        )}
                        {factor && (
                            <Typography.Paragraph type="secondary">
                                {factor.summary}
                            </Typography.Paragraph>
                        )}
                    </Card>
                )}
                {creating && context !== null && (
                    <Card title="确认策略规则" size="small">
                        <Typography.Title level={4}>{context.factor_name}</Typography.Title>
                        {context.formula !== null && (
                            <Typography.Paragraph>{context.formula}</Typography.Paragraph>
                        )}
                        <Rules />
                        <Form layout="vertical">
                            <Form.Item label="策略名称">
                                <Input
                                    aria-label="策略名称"
                                    value={name}
                                    disabled={saving || recovery !== null}
                                    maxLength={120}
                                    onChange={(event) => {
                                        setName(event.target.value);
                                    }}
                                />
                            </Form.Item>
                        </Form>
                        <Button
                            type="primary"
                            disabled={loading || saving || name.trim() === "" || recovery !== null}
                            loading={saving}
                            onClick={() => void save()}
                        >
                            保存策略定义
                        </Button>
                    </Card>
                )}
                {!inventory && !creating && authoring !== null && (
                    <Card title="已保存策略" size="small">
                        <Rules />
                        {revision !== null ? (
                            <>
                                <Typography.Paragraph type="success">
                                    策略定义已保存。准备回测时会验证计算并保留固定策略版本，尚未开始回测。
                                </Typography.Paragraph>
                                <Link to={backtestLink(authoring.strategy_id, revision)}>
                                    配置回测
                                </Link>
                            </>
                        ) : (
                            <>
                                <Typography.Paragraph>
                                    策略还没有保存为可用版本，请选择原因子继续保存。
                                </Typography.Paragraph>
                                <Link
                                    to={`/strategies/new?${new URLSearchParams({ strategy_id: authoring.strategy_id }).toString()}`}
                                >
                                    选择因子继续保存
                                </Link>
                            </>
                        )}
                    </Card>
                )}
                {!creating && workflow !== null && workflow.backtest_preparations.length > 0 && (
                    <Card title="回测准备记录" size="small">
                        <Table
                            rowKey="command_id"
                            scroll={{ x: 520 }}
                            pagination={false}
                            dataSource={workflow.backtest_preparations}
                            columns={[
                                {
                                    title: "准备时间（UTC）",
                                    render: (
                                        _: unknown,
                                        value: Workflow["backtest_preparations"][number]
                                    ) =>
                                        new Date(value.accepted_at).toLocaleString("zh-CN", {
                                            timeZone: "UTC",
                                            hour12: false
                                        })
                                },
                                {
                                    title: "进度",
                                    render: (
                                        _: unknown,
                                        value: Workflow["backtest_preparations"][number]
                                    ) =>
                                        value.run_id === null
                                            ? preparationLabel(value.state)
                                            : "已创建回测"
                                },
                                {
                                    title: "操作",
                                    render: (
                                        _: unknown,
                                        value: Workflow["backtest_preparations"][number]
                                    ) => (
                                        <Link
                                            to={
                                                value.run_id === null
                                                    ? `/backtest/preparations/${value.command_id}`
                                                    : `/backtest/runs/${value.run_id}`
                                            }
                                        >
                                            {value.run_id === null ? "查看准备" : "查看回测"}
                                        </Link>
                                    )
                                }
                            ]}
                        />
                    </Card>
                )}
                {!creating && workflow !== null && researchLink(workflow) !== null && (
                    <Link to={researchLink(workflow) ?? "/strategies"}>查看已有研究记录</Link>
                )}
            </main>
        </div>
    );
}
