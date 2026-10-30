// Human-only preparation, separate confirmation and original Run observation.
import { useCallback, useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import { z } from "zod";
import { request, type Study } from "./api";
import {
    preparationContextSchema,
    preparationSchema,
    researchRunSchema,
    researchPendingSchema,
    confirmationSchema
} from "./researchApi";

type Preparation = z.infer<typeof preparationSchema>;
type Context = z.infer<typeof preparationContextSchema>;
type Run = z.infer<typeof researchRunSchema>;
type Pending = z.infer<typeof researchPendingSchema>;
export interface ResearchStudyActions {
    confirmResearch: () => Promise<void>;
}
interface Props {
    study: Study;
    newWorkBlocked: boolean;
    actionRef: Ref<ResearchStudyActions>;
    onSystemFeedback?: (text: string) => void;
}
const localSchema = z.strictObject({
    preparation: z.uuid().nullable(),
    run: z.uuid().nullable(),
    pending: researchPendingSchema.nullable()
});
function savedOperation(key: string): z.infer<typeof localSchema> {
    try {
        return localSchema.parse(JSON.parse(sessionStorage.getItem(key) ?? "null"));
    } catch {
        return { preparation: null, run: null, pending: null };
    }
}
function hasAcceptedOriginal(pending: Pending | null, actual: Preparation): boolean {
    if (pending?.kind === "prepare")
        return (
            pending.command === actual.command_id &&
            pending.body.study_proposal_fingerprint === actual.study_proposal_fingerprint &&
            pending.body.research_command_id === actual.research_command_id
        );
    return (
        matchesConfirmation(pending, actual) &&
        actual.research_outcome === "ACCEPTED" &&
        actual.run_id !== null
    );
}
function matchesConfirmation(pending: Pending | null, actual: Preparation): boolean {
    return (
        pending?.kind === "confirm" &&
        pending.command === actual.research_command_id &&
        pending.body.preparation_command_id === actual.command_id &&
        pending.body.prepared_study_fingerprint === actual.prepared_study_fingerprint
    );
}
function rejectedStaleConfirmation(actual: Preparation): boolean {
    const detail = z.object({ code: z.string() }).safeParse(actual.detail);
    return (
        actual.state === "BLOCKED" &&
        actual.phase === "STOPPED" &&
        actual.research_outcome === "NOT_SUBMITTED" &&
        actual.run_id === null &&
        detail.success &&
        ["FACTOR_STUDY_PROPOSAL_STALE", "RESEARCH_PREPARATION_STUDY_STALE"].includes(
            detail.data.code
        )
    );
}
const states: Record<string, string> = {
    ACCEPTED: "已登记准备任务",
    RUNNING: "正在准备",
    INPUT_PENDING: "等待所需输入",
    READY: "研究环境已就绪，等待你的第二次确认",
    BLOCKED: "准备被阻止",
    UNKNOWN: "原操作结果未知",
    CANCEL_REQUESTED: "正在停止原任务",
    CANCELLED: "已停止准备",
    QUEUED: "等待执行",
    COMPLETED: "研究完成",
    FAILED: "研究失败",
    CANCELED: "研究已取消"
};
const phaseNames: Record<string, string> = {
    VALIDATING: "核对已确认因子与研究条件",
    INPUTS: "准备不可变研究数据",
    ACQUISITION: "获取所需行情",
    CONFIRMING: "提交已明确确认的单次研究",
    READY_FOR_HUMAN_CONFIRMATION: "可确认本次研究",
    STOPPED: "已暂停",
    OWNER_DRAINED: "原执行者已停止",
    NOVELTY: "研究准入检查"
};
const runStates: Record<string, string> = {
    QUEUED: "研究排队中",
    RUNNING: "正在计算研究",
    CANCEL_REQUESTED: "正在请求取消",
    CANCELLED: "研究已取消",
    COMPLETED: "研究完成",
    FAILED: "研究失败"
};
const terminalRun = new Set(["COMPLETED", "FAILED", "CANCELLED", "CANCELED"]);
function message(e: unknown) {
    return e instanceof Error ? e.message : String(e);
}
export function ResearchStudyPanel({ study, newWorkBlocked, actionRef, onSystemFeedback }: Props) {
    const key = "onlyalpha.factor.research." + study.snapshot.factor_proposal_fingerprint;
    const [restored] = useState(() => savedOperation(key));
    const [context, setContext] = useState<Context | null>(null);
    const [preparation, setPreparation] = useState<Preparation | null>(null);
    const [run, setRun] = useState<Run | null>(null);
    const [pending, setPending] = useState<Pending | null>(restored.pending);
    const [reading, setReading] = useState(false);
    const readingRef = useRef(false);
    const [busy, setBusy] = useState(false),
        [error, setError] = useState(""),
        [fresh, setFresh] = useState(false);
    const selected = useRef<{ preparation: string | null; run: string | null }>({
        preparation: restored.preparation,
        run: restored.run
    });
    const pendingRef = useRef<Pending | null>(restored.pending),
        generation = useRef(0);
    const retain = useCallback(
        (p: Pending | null) => {
            pendingRef.current = p;
            setPending(p);
            sessionStorage.setItem(key, JSON.stringify({ ...selected.current, pending: p }));
        },
        [key]
    );
    const loadRun = useCallback(async (id: string) => {
        const tag = generation.current;
        const actual = await request(`/api/v2/research/runs/${id}`, researchRunSchema);
        if (tag !== generation.current) return actual;
        selected.current.run = actual.run_id;
        setRun(actual);
        return actual;
    }, []);
    const loadPreparation = useCallback(
        async (id: string) => {
            const tag = generation.current;
            const actual = await request(
                `/api/v2/factor-study-preparations/commands/${id}`,
                preparationSchema
            );
            if (tag !== generation.current) return actual;
            selected.current.preparation = actual.command_id;
            setPreparation(actual);
            if (
                hasAcceptedOriginal(pendingRef.current, actual) ||
                (matchesConfirmation(pendingRef.current, actual) &&
                    rejectedStaleConfirmation(actual))
            )
                retain(null);
            if (actual.run_id !== null) await loadRun(actual.run_id);
            else {
                selected.current.run = null;
                setRun(null);
            }
            return actual;
        },
        [loadRun, retain]
    );
    const refresh = useCallback(
        async (includeContext = true) => {
            const tag = ++generation.current;
            readingRef.current = true;
            setReading(true);
            try {
                // Reading a retained Run does not depend on new Source/context availability.
                const failures: string[] = [];
                if (selected.current.run !== null)
                    try {
                        await loadRun(selected.current.run);
                    } catch (e) {
                        failures.push(message(e));
                    }
                if (tag !== generation.current) return;
                if (selected.current.preparation !== null)
                    try {
                        await loadPreparation(selected.current.preparation);
                    } catch (e) {
                        failures.push(message(e));
                    }
                if (tag !== generation.current) return;
                if (includeContext) {
                    try {
                        const actual = await request(
                            `/api/v2/factor-study-preparation-context/${study.fingerprint}`,
                            preparationContextSchema
                        );
                        if (tag !== generation.current) return;
                        setContext(actual);
                        if (
                            selected.current.preparation === null &&
                            actual.existing_preparations.length > 0
                        ) {
                            // Display server-provided order; user can explicitly select another retained operation.
                            const matching = actual.existing_preparations.filter(
                                (p) => p.study_proposal_fingerprint === study.fingerprint
                            );
                            const first = [
                                ...(matching.length > 0 ? matching : actual.existing_preparations)
                            ].sort((a, b) => b.accepted_at.localeCompare(a.accepted_at))[0];
                            if (first !== undefined) await loadPreparation(first.command_id);
                        }
                    } catch (e) {
                        failures.push(message(e));
                    }
                }
                if (tag === generation.current) {
                    if (includeContext) {
                        setFresh(failures.length === 0);
                        setError(failures.join("；"));
                    } else if (failures.length > 0) {
                        setFresh(false);
                        setError((previous) =>
                            [
                                ...new Set([...previous.split("；").filter(Boolean), ...failures])
                            ].join("；")
                        );
                    }
                    sessionStorage.setItem(
                        key,
                        JSON.stringify({ ...selected.current, pending: pendingRef.current })
                    );
                }
            } finally {
                if (tag === generation.current) {
                    readingRef.current = false;
                    setReading(false);
                }
            }
        },
        [study.fingerprint, key, loadPreparation, loadRun]
    );
    useEffect(() => {
        if (!readingRef.current) void refresh();
    }, [refresh]);
    useEffect(() => {
        if (
            busy ||
            reading ||
            preparation === null ||
            (["READY", "BLOCKED", "UNKNOWN", "CANCELLED"].includes(preparation.state) &&
                (run === null || terminalRun.has(run.state)))
        )
            return;
        const timer = window.setTimeout(() => {
            if (!readingRef.current) void refresh(false);
        }, 1500);
        return () => {
            window.clearTimeout(timer);
        };
    }, [preparation, run, busy, reading, refresh]);
    const current = preparation?.study_proposal_fingerprint === study.fingerprint;
    const workerFailure = z
        .object({ state: z.enum(["UNKNOWN", "UNAVAILABLE"]), code: z.string() })
        .safeParse(run?.worker_observation);
    const blocked =
        busy ||
        pending !== null ||
        newWorkBlocked ||
        reading ||
        !fresh ||
        context?.new_work_status.state !== "AVAILABLE" ||
        !context.is_current ||
        context.withdrawn ||
        !study.is_current ||
        study.withdrawn;
    async function sendOriginal(p: Pending) {
        if (p.kind === "prepare") {
            const actual = await request(
                "/api/v2/factor-study-preparations",
                preparationSchema,
                p.body,
                p.command
            );
            selected.current.preparation = actual.command_id;
            selected.current.run = actual.run_id;
            setPreparation(actual);
            setRun(null);
        } else if (p.kind === "confirm") {
            const actual = await request(
                `/api/v2/factor-study-preparations/${p.body.preparation_command_id}/confirmation`,
                confirmationSchema,
                p.body,
                p.command
            );
            if (actual.state !== "ACCEPTED" || actual.run_id === null) {
                throw new Error("本次研究提交结果未知，请核对原研究操作；不会创建第二次研究。");
            }
            await loadRun(actual.run_id);
            onSystemFeedback?.("你已明确确认本次研究，backend 已接收单次 Research。");
        } else if (p.kind === "cancel-run") {
            const actual = await request(
                `/api/v2/research/runs/${p.body.run_id}/cancellation`,
                researchRunSchema,
                p.body,
                p.command
            );
            setRun(actual);
        } else {
            const endpoint = p.kind === "resume" ? "resume" : "cancellation";
            const actual = await request(
                `/api/v2/factor-study-preparations/${p.body.preparation_command_id}/${endpoint}`,
                preparationSchema,
                p.body,
                p.command
            );
            setPreparation(actual);
        }
        retain(null);
        await refresh();
    }
    async function act(p: Pending) {
        if (busy || pendingRef.current !== null) return;
        setBusy(true);
        setError("");
        retain(p);
        try {
            await sendOriginal(p);
        } catch (e) {
            setError(message(e));
        } finally {
            setBusy(false);
        }
    }
    async function prepare() {
        if (
            blocked ||
            (preparation !== null &&
                preparation.state !== "CANCELLED" &&
                (run === null || !terminalRun.has(run.state)))
        )
            return;
        const command = crypto.randomUUID(),
            research = crypto.randomUUID();
        await act({
            kind: "prepare",
            command,
            body: {
                schema_version: 1,
                study_proposal_fingerprint: study.fingerprint,
                release_manifest_fingerprint: context.release_manifest_fingerprint,
                expected_active_generation: context.expected_active_generation,
                initialize_fresh_runtime: context.initialize_fresh_runtime,
                research_command_id: research
            }
        });
    }
    async function confirmResearch() {
        if (
            blocked ||
            !current ||
            preparation.state !== "READY" ||
            preparation.readiness.state !== "VERIFIED" ||
            preparation.prepared_study_fingerprint === null ||
            preparation.research_outcome !== "NOT_SUBMITTED"
        ) {
            setError("请先完成研究环境准备，核对当前方案后再确认本次研究。");
            return;
        }
        await act({
            kind: "confirm",
            command: preparation.research_command_id,
            body: {
                schema_version: 1,
                preparation_command_id: preparation.command_id,
                prepared_study_fingerprint: preparation.prepared_study_fingerprint
            }
        });
    }
    useImperativeHandle(actionRef, () => ({ confirmResearch }));
    async function preparationAction(kind: "resume" | "cancel-preparation") {
        if (preparation === null) return;
        await act({
            kind,
            command: kind === "resume" ? preparation.command_id : crypto.randomUUID(),
            body: {
                schema_version: 1,
                preparation_command_id: preparation.command_id,
                expected_revision: preparation.revision
            }
        });
    }
    async function cancelRun() {
        if (run === null || terminalRun.has(run.state)) return;
        await act({
            kind: "cancel-run",
            command: crypto.randomUUID(),
            body: { schema_version: 1, run_id: run.run_id }
        });
    }
    async function selectPreparation(id: string) {
        if (busy || readingRef.current) return;
        const tag = ++generation.current;
        readingRef.current = true;
        setReading(true);
        setRun(null);
        selected.current.preparation = id;
        selected.current.run = null;
        try {
            await loadPreparation(id);
            if (tag !== generation.current) return;
            retain(pendingRef.current);
        } catch (e) {
            setError(message(e));
        } finally {
            if (tag === generation.current) {
                readingRef.current = false;
                setReading(false);
            }
        }
    }
    async function checkOriginal() {
        const p = pendingRef.current;
        if (p === null || busy || readingRef.current) return;
        const tag = ++generation.current;
        readingRef.current = true;
        setReading(true);
        setBusy(true);
        setError("");
        try {
            if (p.kind === "prepare") {
                const actual = await loadPreparation(p.command);
                if (tag !== generation.current) return;
                if (hasAcceptedOriginal(p, actual)) retain(null);
                else setError("原准备任务与保留的提交身份不匹配。请保留记录并核对原操作。");
            } else if (p.kind === "confirm") {
                const actual = await loadPreparation(p.body.preparation_command_id);
                if (tag !== generation.current) return;
                if (hasAcceptedOriginal(p, actual) && actual.run_id !== null) {
                    await loadRun(actual.run_id);
                    if (tag !== generation.current) return;
                    retain(null);
                    onSystemFeedback?.("backend 已核对原 Research 已接收。");
                } else if (matchesConfirmation(p, actual) && rejectedStaleConfirmation(actual)) {
                    retain(null);
                } else setError("原 Research 尚未证明接收；请保持原操作身份，不要另建研究。");
            } else {
                await refresh();
                setError(
                    "已刷新实际状态；如原操作回执仍未知，可明确重放同一个原命令核对，不会生成新身份。"
                );
            }
        } catch (e) {
            setError(message(e));
        } finally {
            setBusy(false);
            if (tag === generation.current) {
                readingRef.current = false;
                setReading(false);
            }
        }
    }
    return (
        <section aria-label="准备与运行研究">
            <h3>准备与运行研究</h3>
            <p>先准备并启用这版研究环境，再单独确认一次 Research。准备不会启动研究。</p>
            {context !== null && (
                <>
                    <p>
                        数据来源：{context.source_label ?? "原数据来源暂不可核对"} ·{" "}
                        {context.advice.source.instrument_id} · {context.advice.timeframe_minutes}{" "}
                        分钟
                    </p>
                    <details>
                        <summary>准备涉及哪些操作</summary>
                        <p>
                            使用已确认因子，准备不可变数据集，并启用所选版本的研究环境；受保护样本不会读取。
                        </p>
                        <p>backend {context.backend_version}</p>
                        <pre>
                            {JSON.stringify(
                                {
                                    release_manifest_fingerprint:
                                        context.release_manifest_fingerprint,
                                    algorithm_artifact_fingerprint:
                                        context.algorithm_artifact_fingerprint,
                                    expected_active_generation: context.expected_active_generation,
                                    initialize_fresh_runtime: context.initialize_fresh_runtime
                                },
                                null,
                                2
                            )}
                        </pre>
                    </details>
                </>
            )}
            {reading && <p role="status">正在核对研究状态…</p>}
            {error !== "" && <p role="alert">{error}</p>}
            {preparation !== null && rejectedStaleConfirmation(preparation) && (
                <p role="status">
                    原研究条件已过期，已核对本次研究未提交。可停止原准备任务，再载入最新建议，重新准备和确认。
                </p>
            )}
            {context?.new_work_status.state === "UNAVAILABLE" && (
                <p role="alert">
                    {context.new_work_status.code ===
                    "RESEARCH_PREPARATION_INSUFFICIENT_BLOCK_SCOPE"
                        ? "研究样本范围不足：开发样本与样本外区间各自至少覆盖 10 个期望区块对应的有效配对范围。请扩大样本范围，通过聊天修改建议后再准备。原报告仍可查看。"
                        : "当前数据来源或研究环境暂不可用，不能准备或确认新的研究。原运行记录仍可查看和取消。"}
                    <code>{context.new_work_status.code}</code>
                </p>
            )}
            {preparation?.readiness.state === "UNAVAILABLE" && (
                <p role="alert">
                    这份准备的输入证明暂不可核验，已阻止新的研究确认；请核对原准备任务。
                    <code>{preparation.readiness.code}</code>
                </p>
            )}
            <button
                type="button"
                disabled={busy || reading}
                onClick={() => {
                    if (!readingRef.current) void refresh();
                }}
            >
                刷新研究状态
            </button>
            {preparation !== null && (
                <>
                    {context !== null && context.existing_preparations.length > 1 && (
                        <label>
                            已登记的准备任务
                            <select
                                value={preparation.command_id}
                                disabled={busy || reading}
                                onChange={(e) => {
                                    void selectPreparation(e.target.value);
                                }}
                            >
                                {context.existing_preparations.map((p) => (
                                    <option key={p.command_id} value={p.command_id}>
                                        {p.accepted_at} · {states[p.state] ?? p.state}
                                    </option>
                                ))}
                            </select>
                        </label>
                    )}
                    <p role="status">
                        {states[preparation.state] ?? preparation.state} ·{" "}
                        {phaseNames[preparation.phase] ?? preparation.phase}
                    </p>
                    {!current && <p>正在查看另一版条件的原研究任务。修改条件后需要重新准备。</p>}
                </>
            )}
            {preparation === null ||
            preparation.state === "CANCELLED" ||
            (run !== null && terminalRun.has(run.state) && !current) ? (
                <button
                    type="button"
                    disabled={blocked}
                    onClick={() => {
                        void prepare();
                    }}
                >
                    准备并启用研究环境
                </button>
            ) : (
                <>
                    {preparation.state === "READY" &&
                        current &&
                        preparation.research_outcome === "NOT_SUBMITTED" && (
                            <>
                                <p>
                                    核对当前因子、数据、周期、开发/样本外区间和序列依赖修正后，可在聊天发送“确认本次研究”。只运行一次。
                                </p>
                                <button
                                    type="button"
                                    disabled={blocked || preparation.readiness.state !== "VERIFIED"}
                                    onClick={() => {
                                        void confirmResearch();
                                    }}
                                >
                                    确认本次研究
                                </button>
                            </>
                        )}
                    {["INPUT_PENDING", "BLOCKED", "UNKNOWN"].includes(preparation.state) && (
                        <button
                            type="button"
                            disabled={busy || pending !== null}
                            onClick={() => {
                                void preparationAction("resume");
                            }}
                        >
                            恢复原准备任务
                        </button>
                    )}
                    {!["CANCELLED", "CANCEL_REQUESTED"].includes(preparation.state) &&
                        run === null && (
                            <button
                                type="button"
                                disabled={busy || pending !== null}
                                onClick={() => {
                                    void preparationAction("cancel-preparation");
                                }}
                            >
                                停止原准备任务
                            </button>
                        )}
                    <details>
                        <summary>准备任务高级详情</summary>
                        <pre>{JSON.stringify(preparation, null, 2)}</pre>
                    </details>
                </>
            )}
            {pending !== null && (
                <div role="status">
                    <p>原操作尚未完成核对，不会重新创建操作。</p>
                    <button
                        type="button"
                        disabled={busy || reading}
                        onClick={() => {
                            void checkOriginal();
                        }}
                    >
                        核对原研究操作
                    </button>
                    <button
                        type="button"
                        disabled={busy}
                        onClick={() => {
                            setBusy(true);
                            void sendOriginal(pending)
                                .catch((e: unknown) => {
                                    setError(message(e));
                                })
                                .finally(() => {
                                    setBusy(false);
                                });
                        }}
                    >
                        重放同一原命令核对
                    </button>
                </div>
            )}
            {run !== null && (
                <>
                    <p role="status">{runStates[run.state] ?? run.state}</p>
                    {workerFailure.success && (
                        <p role="alert">
                            {workerFailure.data.state === "UNKNOWN"
                                ? "研究执行服务的结果未知"
                                : "研究执行服务暂不可用"}
                            。运行状态以原记录为准；仍可查看证据或取消已登记的研究。
                            <code>{workerFailure.data.code}</code>
                        </p>
                    )}
                    {run.failure !== null && <p role="alert">{JSON.stringify(run.failure)}</p>}
                    {!terminalRun.has(run.state) && (
                        <button
                            type="button"
                            disabled={busy || pending !== null}
                            onClick={() => {
                                void cancelRun();
                            }}
                        >
                            取消本次研究
                        </button>
                    )}
                    <ResearchReport run={run} />
                    <details>
                        <summary>运行高级详情</summary>
                        <pre>
                            {JSON.stringify(
                                {
                                    run_id: run.run_id,
                                    revision: run.revision,
                                    worker_observation: run.worker_observation
                                },
                                null,
                                2
                            )}
                        </pre>
                    </details>
                </>
            )}
        </section>
    );
}

type Sample = NonNullable<Run["report"]>["samples"][number];
const estimateStates: Record<string, string> = {
    AVAILABLE: "可用",
    INSUFFICIENT_PAIRS: "有效样本不足",
    ZERO_VARIANCE_FEATURE: "因子值没有变化",
    ZERO_VARIANCE_TARGET: "收益没有变化",
    GAPPED_AXIS: "时间轴存在缺口",
    INCOMPLETE_PAIRS: "配对样本不完整",
    INSUFFICIENT_BLOCKS: "独立区块数量不足",
    TAIL_RESOLUTION_INSUFFICIENT: "重采样次数不足以解析区间尾部",
    UNDEFINED_BOOTSTRAP_REPLICATES: "部分重采样无法估计",
    BOOTSTRAP_DISTRIBUTION_DEGENERATE: "重采样分布退化"
};
function Estimate({ label, estimate }: { label: string; estimate: Sample["pearson"] }) {
    return (
        <div className="research-estimate">
            <h4>{label}</h4>
            <p>
                相关系数：
                {estimate.point_status === "AVAILABLE" && estimate.value !== null
                    ? estimate.value
                    : `不可用（${estimateStates[estimate.point_status] ?? estimate.point_status}）`}
            </p>
            <p>
                序列依赖修正区间：
                {estimate.uncertainty_status === "AVAILABLE" && estimate.interval !== null
                    ? `${estimate.interval[0]} 至 ${estimate.interval[1]}`
                    : `不可用（${estimateStates[estimate.uncertainty_status] ?? estimate.uncertainty_status}）`}
            </p>
            {estimate.undefined_replicates > 0 && (
                <p>无法估计的重采样：{estimate.undefined_replicates} 次</p>
            )}
        </div>
    );
}
function ResearchReport({ run }: { run: Run }) {
    const report = run.report;
    if (report === null && run.report_status.state !== "UNAVAILABLE") return null;
    if (report === null)
        return (
            <p role="status">
                统计报告暂不可核验。运行状态不因此改变；请核对原研究，不要重复运行。
            </p>
        );
    const originalName =
        typeof run.name_snapshot.factor_name === "string"
            ? run.name_snapshot.factor_name
            : "原研究因子";
    return (
        <section aria-label="研究结果报告">
            <h3>{originalName} · 研究结果</h3>
            {run.current_name !== null && run.current_name !== originalName && (
                <p>当前名称：{run.current_name}</p>
            )}
            <p>输入名称以提交时快照为准；本次为相关性证据，不能单凭相关系数认定因子有效。</p>
            <h4>本报告原研究条件</h4>
            <dl>
                <dt>研究商品</dt>
                <dd>{report.instrument_id}</dd>
                <dt>K线周期</dt>
                <dd>{report.timeframe_minutes} 分钟</dd>
                <dt>预测期限</dt>
                <dd>未来 {report.horizon_bars} 根 K 线</dd>
            </dl>
            {run.decision_provenance.state !== "VERIFIED" && (
                <p role="alert">
                    历史准入证明暂不可完整核验；以下为仍可核验的原统计产物，不代表完整 Evidence
                    链或因子通过。
                </p>
            )}
            {report.samples.map((sample) => (
                <section
                    key={sample.role}
                    aria-label={sample.role === "DEVELOPMENT" ? "开发样本结果" : "样本外结果"}
                >
                    <h4>
                        {sample.role === "DEVELOPMENT"
                            ? "开发样本"
                            : sample.role === "OUT_OF_SAMPLE"
                              ? "固定样本外"
                              : sample.role}
                    </h4>
                    <p>
                        原样本区间（UTC，包含起点、不含终点）：{sample.start_at} 至 {sample.end_at}
                    </p>
                    <dl>
                        <dt>预期 / 实际观测</dt>
                        <dd>
                            {sample.diagnostics.expected_rows} / {sample.diagnostics.observed_rows}
                        </dd>
                        <dt>有效配对样本</dt>
                        <dd>{sample.diagnostics.complete_pairs}</dd>
                        <dt>边界排除</dt>
                        <dd>{sample.diagnostics.boundary_excluded}</dd>
                        <dt>缺少因子 / 未来收益</dt>
                        <dd>
                            {sample.diagnostics.missing_feature} /{" "}
                            {sample.diagnostics.missing_target}
                        </dd>
                        <dt>时间轴缺口</dt>
                        <dd>{sample.diagnostics.axis_gaps}</dd>
                    </dl>
                    <Estimate label="Pearson 线性相关" estimate={sample.pearson} />
                    <Estimate label="Spearman 秩相关" estimate={sample.spearman} />
                </section>
            ))}
            <p>
                置信水平 {report.confidence_bps / 100}%；期望区块长度 {report.expected_block_length}{" "}
                根；重采样 {report.replicates} 次；比较数量 {report.comparison_count}。
            </p>
            <ul>
                {report.limitations.map((limit) => (
                    <li key={limit}>{limit}</li>
                ))}
            </ul>
            <details>
                <summary>不可变证据与精确输入</summary>
                <dl>
                    <dt>结果身份</dt>
                    <dd>{report.research_result_fingerprint}</dd>
                    <dt>产物身份</dt>
                    <dd>{report.artifact_content_fingerprint}</dd>
                </dl>
                <h4>原始研究定义</h4>
                <pre>{report.canonical_specification}</pre>
                <h4>原始结果产物</h4>
                <pre>{report.canonical_artifact}</pre>
            </details>
        </section>
    );
}
