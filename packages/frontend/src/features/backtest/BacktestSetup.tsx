import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, Button, Card, Descriptions, Empty, Form, Select, Spin, Typography } from "antd";
import { loadWorkflows } from "../strategies/api";
import * as api from "./api";

type Strategy = Awaited<ReturnType<typeof loadWorkflows>>["items"][number];
type Source = Awaited<ReturnType<typeof api.loadSources>>[number];
function sourceKey(source: Source) {
    return JSON.stringify([
        source.integration_id,
        source.integration_revision_fingerprint,
        source.source_id,
        source.environment
    ]);
}
function selectedOrigin(query: URLSearchParams): api.BacktestOrigin | null {
    const strategy = query.get("strategy_id"),
        revision = query.get("strategy_revision_fingerprint");
    const value =
        strategy !== null || revision !== null
            ? {
                  kind: "MANUAL_STRATEGY",
                  strategy_id: strategy,
                  strategy_revision_fingerprint: revision
              }
            : {
                  kind: "FROZEN_STRATEGY",
                  strategy_fingerprint: query.get("strategy_fingerprint"),
                  freeze_relation_fingerprint: query.get("freeze_relation_fingerprint"),
                  qualification_decision_fingerprint: query.get(
                      "qualification_decision_fingerprint"
                  ),
                  promotion_fingerprint: query.get("promotion_fingerprint")
              };
    const parsed = api.originSchema.safeParse(value);
    return parsed.success ? parsed.data : null;
}
interface SetupProps {
    query: string;
    busy: boolean;
    onPrepare: (action: () => Promise<api.BacktestPreparation>) => void;
}
export function BacktestSetup(props: SetupProps) {
    return <BacktestSetupSelection key={props.query} {...props} />;
}
function BacktestSetupSelection({ query, busy, onPrepare }: SetupProps) {
    const navigate = useNavigate();
    const origin = useMemo(() => selectedOrigin(new URLSearchParams(query)), [query]);
    const readContext = api.loadCreationContext,
        readSources = api.loadSources,
        readStrategies = loadWorkflows,
        findPending = api.pendingPreparation,
        prepare = api.prepareBacktest;
    const scope = useMemo(
        () => ({ origin, readContext, readSources, readStrategies, findPending, prepare }),
        [origin, readContext, readSources, readStrategies, findPending, prepare]
    );
    interface LoadedView {
        scope: typeof scope;
        strategies: Strategy[];
        context: api.BacktestCreation | null;
        sources: Source[];
        problem: string;
    }
    const [loaded, setLoaded] = useState<LoadedView | null>(null);
    const [selection, setSelection] = useState<{
        scope: typeof scope;
        source: Source | null;
    } | null>(null);
    // A result belongs to the exact query and API functions that read it.
    // Mask earlier results immediately, before the new request effect runs.
    const view = loaded?.scope === scope ? loaded : null;
    const strategies = view?.strategies ?? [],
        context = view?.context ?? null,
        sources = view?.sources ?? [],
        problem = view?.problem ?? "";
    const source = selection?.scope === scope ? selection.source : null;
    const loading = view === null;
    const pending = useMemo(
        () => (scope.origin === null ? null : scope.findPending(scope.origin)),
        [scope]
    );
    useEffect(() => {
        let current = true;
        const read = async () => {
            try {
                if (scope.origin === null) {
                    const value = await scope.readStrategies();
                    if (current)
                        setLoaded({
                            scope,
                            context: null,
                            sources: [],
                            problem: "",
                            strategies: value.items.filter(
                                (item) => item.authoring.current_revision_fingerprint !== null
                            )
                        });
                } else {
                    const [details, available] = await Promise.all([
                        scope.readContext(scope.origin),
                        scope.readSources()
                    ]);
                    if (current)
                        setLoaded({
                            scope,
                            context: details,
                            sources: available,
                            strategies: [],
                            problem: ""
                        });
                }
            } catch {
                if (current)
                    setLoaded({
                        scope,
                        context: null,
                        sources: [],
                        strategies: [],
                        problem: "暂时无法读取回测条件，已保存策略和回测记录仍然保留。请重新查看。"
                    });
            }
        };
        void read();
        return () => {
            current = false;
        };
    }, [scope]);
    if (origin === null)
        return (
            <Card title="选择回测策略" size="small">
                {problem && <Alert type="warning" showIcon title={problem} />}
                {loading ? (
                    <Spin description="正在读取已保存策略">
                        <div className="backtest-loading" />
                    </Spin>
                ) : strategies.length === 0 ? (
                    <Empty description="还没有可回测的策略">
                        <Link to="/strategies/new">选择因子创建策略</Link>
                    </Empty>
                ) : (
                    <Form layout="vertical">
                        <Form.Item label="策略">
                            <Select
                                aria-label="回测策略"
                                placeholder="请选择已保存策略"
                                options={strategies.map((item) => ({
                                    value: item.strategy_id,
                                    label: (item.authoring.draft?.description ?? "") || "已保存策略"
                                }))}
                                onChange={(id) => {
                                    const item = strategies.find(
                                            (value) => value.strategy_id === id
                                        ),
                                        revision = item?.authoring.current_revision_fingerprint;
                                    if (item && revision)
                                        void navigate(
                                            `/backtest/new?${new URLSearchParams({ strategy_id: item.strategy_id, strategy_revision_fingerprint: revision }).toString()}`
                                        );
                                }}
                            />
                        </Form.Item>
                    </Form>
                )}
            </Card>
        );
    return (
        <Card title="确认回测条件" size="small">
            {pending !== null && !busy && (
                <Alert
                    type="warning"
                    showIcon
                    title="有一项回测准备的结果尚未确认，请先查看原任务。"
                    action={
                        <Button
                            onClick={() => {
                                onPrepare(pending.observe);
                            }}
                        >
                            查看任务进度
                        </Button>
                    }
                />
            )}
            {context !== null && (
                <Typography.Title level={4}>{context.strategy_name}</Typography.Title>
            )}
            {problem && <Alert type="warning" showIcon title={problem} />}
            {loading && (
                <Spin description="正在读取回测条件">
                    <div className="backtest-loading" />
                </Spin>
            )}
            <Descriptions
                column={{ xs: 1, sm: 2 }}
                size="small"
                items={[
                    { key: "sample", label: "样本（UTC）", children: "2025-01-03 00:00 至 12:00" },
                    { key: "capital", label: "初始资金", children: "10,000 USDT" },
                    { key: "size", label: "仓位", children: "每笔 0.01 BTC，仅持有一笔多头" },
                    { key: "cost", label: "费用", children: "手续费每边 0.1%；滑点每边 0.02%" },
                    { key: "entry", label: "入场条件", children: "空仓且因子值 ≥ 0.001" },
                    { key: "exit", label: "离场条件", children: "持仓且因子值 ≤ 0，中间区间保持" }
                ]}
            />
            <Form layout="vertical">
                <Form.Item label="行情数据源">
                    <Select
                        aria-label="回测行情数据源"
                        placeholder="选择 Binance 现货行情"
                        value={source === null ? undefined : sourceKey(source)}
                        disabled={loading || busy || pending !== null}
                        options={sources.map((value) => ({
                            value: sourceKey(value),
                            label: value.display_name
                        }))}
                        onChange={(value) => {
                            setSelection({
                                scope,
                                source: sources.find((item) => sourceKey(item) === value) ?? null
                            });
                        }}
                    />
                </Form.Item>
            </Form>
            {!loading && problem === "" && sources.length === 0 && (
                <Alert
                    type="warning"
                    showIcon
                    title="暂无可用的 Binance 现货数据源，请到设置中添加或检查数据源。"
                />
            )}
            {context?.input_defaults.expected_active_generation === null && (
                <Alert
                    type="info"
                    showIcon
                    title={
                        context.input_defaults.origin.kind === "MANUAL_STRATEGY"
                            ? "首次使用将准备计算环境。"
                            : "尚未准备计算环境，当前无法准备回测。"
                    }
                />
            )}
            <Typography.Paragraph type="secondary">
                将验证因子和交易规则，并保存固定策略版本；这一步不会开始回测。准备完成后再确认开始。收盘信号最早在下一分钟开盘成交，不借币、不加仓。
            </Typography.Paragraph>
            {context !== null && context.limitations.length > 0 && (
                <Typography.Paragraph type="secondary">
                    {context.limitations.join(" ")}
                </Typography.Paragraph>
            )}
            <Button
                type="primary"
                disabled={
                    busy ||
                    loading ||
                    pending !== null ||
                    context === null ||
                    (context.input_defaults.origin.kind === "FROZEN_STRATEGY" &&
                        context.input_defaults.expected_active_generation === null) ||
                    source === null
                }
                loading={busy}
                onClick={() => {
                    if (context === null || source === null) return;
                    const selected: api.BacktestSource = {
                        integration_id: source.integration_id,
                        integration_revision_fingerprint: source.integration_revision_fingerprint,
                        expected_type_id: "binance.spot.market_data",
                        source_id: source.source_id,
                        environment: source.environment,
                        instrument_id: "BTCUSDT.BINANCE"
                    };
                    onPrepare(() => scope.prepare(context, selected));
                }}
            >
                确认策略并准备回测
            </Button>
        </Card>
    );
}
