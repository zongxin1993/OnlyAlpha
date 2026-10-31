import {
    act as reactAct,
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor
} from "@testing-library/react";
import { createRef } from "react";
import { z } from "zod";
import { afterEach, expect, it, vi } from "vitest";
import { request, type Study } from "./api";
import { ResearchStudyPanel, type ResearchStudyActions } from "./ResearchStudyPanel";
import { preparationContextSchema, preparationSchema, researchRunSchema } from "./researchApi";
vi.mock(import("./api"), async (original) => ({ ...(await original()), request: vi.fn() }));
const uuid = "00000000-0000-4000-8000-000000000001",
    future = "00000000-0000-4000-8000-000000000002",
    runId = "00000000-0000-4000-8000-000000000003";
const sha = "a".repeat(64),
    studyFp = "b".repeat(64);
const advice = {
    source: {
        integration_id: uuid,
        integration_revision_fingerprint: sha,
        expected_type_id: "binance.spot.market_data",
        source_id: "binance.spot.market_data.live",
        environment: "GLOBAL",
        instrument_id: "BTCUSDT.BINANCE"
    },
    timeframe_minutes: 15,
    start_at: "2026-01-01T06:00:00Z",
    development_end_at: "2026-01-03T22:00:00Z",
    end_at: "2026-01-06T14:00:00Z",
    protected_start_at: "2026-01-07T00:00:00Z",
    protected_end_at: "2026-01-09T16:00:00Z",
    horizon_bars: 1,
    expected_block_length: 12,
    replicates: 4096,
    confidence_bps: 9500,
    seed: sha,
    rationale: "fixed"
};
const study: Study = {
    schema_version: 1,
    fingerprint: studyFp,
    is_current: true,
    withdrawn: false,
    snapshot: {
        schema_version: 1,
        owner: "owner",
        factor_proposal_fingerprint: sha,
        origin: { session_id: uuid, event_fingerprint: sha },
        advice
    }
};
const ready = {
    schema_version: 1,
    command_id: uuid,
    revision: "9007199254740993",
    state: "READY",
    phase: "READY_FOR_HUMAN_CONFIRMATION",
    readiness: { state: "VERIFIED", code: null },
    study_proposal_fingerprint: studyFp,
    research_command_id: future,
    reserved_run_id: runId,
    prepared_study_fingerprint: sha,
    research_outcome: "NOT_SUBMITTED",
    run_id: null,
    accepted_at: "2026-10-22T00:00:00Z",
    advice,
    detail: null
};
function context(
    operations: Pick<
        typeof ready,
        "command_id" | "revision" | "state" | "study_proposal_fingerprint" | "accepted_at"
    >[] = [ready]
) {
    return {
        schema_version: 1,
        study_proposal_fingerprint: studyFp,
        factor_proposal_fingerprint: sha,
        factor_name: "submitted name",
        usage_summary: "purpose",
        source_label: "source name",
        new_work_status: { state: "AVAILABLE", code: null },
        advice,
        is_current: true,
        withdrawn: false,
        release_manifest_fingerprint: sha,
        backend_version: "1",
        algorithm_artifact_fingerprint: sha,
        expected_active_generation: sha,
        initialize_fresh_runtime: false,
        profile: {},
        policy: {},
        existing_preparations: operations.map(
            ({ command_id, revision, state, study_proposal_fingerprint, accepted_at }) => ({
                command_id,
                revision,
                state,
                study_proposal_fingerprint,
                accepted_at
            })
        )
    };
}
const estimate = {
    point_status: "AVAILABLE",
    value: "0.12345678901234567890123456789",
    uncertainty_status: "INSUFFICIENT_BLOCKS",
    interval: null,
    undefined_replicates: 0
};
function completed() {
    return {
        schema_version: 1,
        run_id: runId,
        state: "COMPLETED",
        revision: "9007199254740994",
        name_snapshot: {
            factor_name: "submitted name",
            usage_summary: "purpose",
            display_version: 1
        },
        current_name: "current renamed factor",
        accepted_at: "2026-10-22T00:00:00Z",
        specification_fingerprint: sha,
        runtime_generation_fingerprint: sha,
        failure: null,
        worker_observation: { state: "IDLE" },
        report_status: { state: "VERIFIED", code: null },
        decision_provenance: {
            state: "UNAVAILABLE",
            code: "HISTORICAL_PROOF_UNAVAILABLE",
            command_id: future,
            group_fingerprint: sha,
            policy_id: "policy",
            policy_version: "1"
        },
        report: {
            research_result_fingerprint: sha,
            artifact_content_fingerprint: sha,
            instrument_id: "ETHUSDT.BINANCE",
            timeframe_minutes: 60,
            horizon_bars: 4,
            samples: [
                {
                    role: "DEVELOPMENT",
                    start_at: "2024-01-01T00:00:00Z",
                    end_at: "2024-01-11T16:00:00Z",
                    diagnostics: {
                        expected_rows: 256,
                        observed_rows: 256,
                        boundary_excluded: 1,
                        complete_pairs: 255,
                        missing_feature: 0,
                        missing_target: 0,
                        axis_gaps: 0
                    },
                    pearson: estimate,
                    spearman: { ...estimate, point_status: "ZERO_VARIANCE_FEATURE", value: null }
                }
            ],
            confidence_bps: 9500,
            expected_block_length: 12,
            replicates: 4096,
            comparison_count: 4,
            limitations: ["correlation is not causation"],
            canonical_artifact: '{"timestamp":1792627200000000001}',
            canonical_specification: '{"exact":9007199254740993}'
        }
    };
}
afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.resetAllMocks();
    sessionStorage.clear();
});
it("reconciles an explicitly rejected stale confirmation before allowing the old preparation to be stopped", async () => {
    let rejected = false;
    vi.mocked(request).mockImplementation((path) =>
        Promise.resolve().then(() => {
            const actual = rejected
                ? {
                      ...ready,
                      state: "BLOCKED",
                      phase: "STOPPED",
                      detail: { code: "FACTOR_STUDY_PROPOSAL_STALE" }
                  }
                : ready;
            if (path.includes("preparation-context"))
                return { ...context([actual]), is_current: !rejected } as never;
            if (path.includes("preparations/commands")) return actual as never;
            if (path.endsWith("/confirmation")) {
                rejected = true;
                throw new Error("FACTOR_STUDY_PROPOSAL_STALE");
            }
            throw new Error(path);
        })
    );
    render(<ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={createRef()} />);
    const confirm = await screen.findByRole("button", { name: "确认本次研究" });
    await waitFor(() => {
        expect(confirm).toBeEnabled();
    });
    fireEvent.click(confirm);
    await screen.findByRole("button", { name: "核对原研究操作" });
    fireEvent.click(screen.getByRole("button", { name: "核对原研究操作" }));
    await waitFor(() => {
        expect(screen.queryByRole("button", { name: "核对原研究操作" })).not.toBeInTheDocument();
    });
    expect(screen.getByText(/原研究条件已过期，已核对本次研究未提交/)).toBeVisible();
    expect(screen.getByRole("button", { name: "停止原准备任务" })).toBeEnabled();
    expect(
        vi.mocked(request).mock.calls.filter(([path]) => path.endsWith("/confirmation"))
    ).toHaveLength(1);
});
it.each([
    ["unknown", { state: "UNKNOWN" }],
    ["unobserved", { research_outcome: "UNOBSERVED" }],
    ["ready", { state: "READY" }],
    ["other rejection", { detail: { code: "RESEARCH_INPUT_UNAVAILABLE" } }],
    ["different command", { research_command_id: uuid }],
    ["different prepared input", { prepared_study_fingerprint: "c".repeat(64) }],
    ["unfinished phase", { phase: "CONFIRMING" }]
])("keeps the original confirmation pending for %s", async (_name, change) => {
    const actual = {
        ...ready,
        state: "BLOCKED",
        phase: "STOPPED",
        detail: { code: "FACTOR_STUDY_PROPOSAL_STALE" },
        ...change
    };
    sessionStorage.setItem(
        "onlyalpha.factor.research." + sha,
        JSON.stringify({
            preparation: uuid,
            run: null,
            pending: {
                kind: "confirm",
                command: future,
                body: {
                    schema_version: 1,
                    preparation_command_id: uuid,
                    prepared_study_fingerprint: sha
                }
            }
        })
    );
    vi.mocked(request).mockImplementation((path) =>
        Promise.resolve().then(() => {
            if (path.includes("preparation-context")) return context([actual]) as never;
            if (path.includes("preparations/commands")) return actual as never;
            throw new Error(path);
        })
    );
    render(<ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={createRef()} />);
    const reconcile = await screen.findByRole("button", { name: "核对原研究操作" });
    await waitFor(() => {
        expect(reconcile).toBeEnabled();
    });
    fireEvent.click(reconcile);
    await screen.findByText(/原研究是否已接收尚未确认/);
    expect(reconcile).toBeVisible();
    expect(vi.mocked(request).mock.calls.every(([, , body]) => body === undefined)).toBe(true);
});
it("confirms directly with the reserved Human command and preserves exact statistics when decision proof is unavailable", async () => {
    let submitted = false;
    vi.mocked(request).mockImplementation((path, _schema, body, command) =>
        Promise.resolve().then(() => {
            if (path.includes("preparation-context")) return context() as never;
            if (path.includes("preparations/commands"))
                return {
                    ...ready,
                    research_outcome: submitted ? "ACCEPTED" : "NOT_SUBMITTED",
                    run_id: submitted ? runId : null
                } as never;
            if (path.endsWith("/confirmation")) {
                expect(command).toBe(future);
                expect(body).toEqual({
                    schema_version: 1,
                    preparation_command_id: uuid,
                    prepared_study_fingerprint: sha
                });
                submitted = true;
                return {
                    schema_version: 1,
                    research_command_id: future,
                    state: "ACCEPTED",
                    run_id: runId
                } as never;
            }
            if (path.endsWith(`/runs/${runId}`))
                return researchRunSchema.parse(completed()) as never;
            throw new Error(path);
        })
    );
    const ref = createRef<ResearchStudyActions>();
    render(<ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={ref} />);
    await waitFor(() => {
        expect(screen.getByRole("button", { name: "确认本次研究" })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "确认本次研究" }));
    await screen.findByRole("region", { name: "研究结果报告" });
    expect(screen.getByText("submitted name · 研究结果")).toBeVisible();
    expect(screen.getByText("当前名称：current renamed factor")).toBeVisible();
    expect(screen.getByText("本报告原研究条件")).toBeVisible();
    expect(screen.getByText("ETHUSDT.BINANCE")).toBeVisible();
    expect(screen.getByText("60 分钟")).toBeVisible();
    expect(screen.getByText("未来 4 根 K 线")).toBeVisible();
    expect(screen.getByText(/2024-01-01T00:00:00Z 至 2024-01-11T16:00:00Z/)).toBeVisible();
    expect(screen.getByText(/历史准入证明暂不可完整核验/)).toBeVisible();
    expect(screen.getByText("相关系数：0.12345678901234567890123456789")).toBeVisible();
    expect(screen.getAllByText(/独立区块数量不足/)).toHaveLength(2);
    expect(screen.getByText(/因子值没有变化/)).toBeVisible();
    expect(screen.getByText('{"exact":9007199254740993}')).toHaveTextContent("9007199254740993");
    expect(vi.mocked(request).mock.calls.every(([path]) => path.startsWith("/api/v2/"))).toBe(true);
});
it("restores an unknown preparation using only the original command after remount", async () => {
    let original: { command: string; body: object } | undefined;
    let acknowledged = false;
    function acceptedOriginal() {
        if (original === undefined) throw new Error("original request required");
        return {
            ...ready,
            command_id: original.command,
            research_command_id: z.object({ research_command_id: z.uuid() }).parse(original.body)
                .research_command_id
        };
    }
    vi.mocked(request).mockImplementation((path, _schema, body, command) =>
        Promise.resolve().then(() => {
            if (path.includes("preparation-context"))
                return context(acknowledged ? [acceptedOriginal()] : []) as never;
            if (path === "/api/v2/factor-study-preparations") {
                if (command === undefined || body === undefined)
                    throw new Error("original command required");
                original = { command, body };
                throw new Error("lost acknowledgement");
            }
            if (original !== undefined && path.endsWith(`/commands/${original.command}`)) {
                acknowledged = true;
                return acceptedOriginal() as never;
            }
            throw new Error(path);
        })
    );
    const view = render(
        <ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={createRef()} />
    );
    fireEvent.click(await screen.findByRole("button", { name: "准备并启用研究环境" }));
    await screen.findByText("暂时无法核对研究状态，请稍后刷新；原操作仍会保留，不会重复提交。");
    expect(original).toBeDefined();
    view.unmount();
    render(<ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={createRef()} />);
    fireEvent.click(await screen.findByRole("button", { name: "核对原研究操作" }));
    await waitFor(() => {
        expect(screen.queryByRole("button", { name: "核对原研究操作" })).not.toBeInTheDocument();
    });
    expect(
        vi
            .mocked(request)
            .mock.calls.filter(([path]) => path === "/api/v2/factor-study-preparations")
    ).toHaveLength(1);
});
it("allows original Run cancellation while new work is blocked and reads the final report after a completed-wins response", async () => {
    let cancelCommand: string | undefined,
        cancelled = false;
    const reads: string[] = [];
    vi.mocked(request).mockImplementation((path, _schema, body, command) =>
        Promise.resolve().then(() => {
            if (path.includes("preparation-context"))
                return {
                    ...context([ready]),
                    source_label: null,
                    algorithm_artifact_fingerprint: null,
                    new_work_status: { state: "UNAVAILABLE", code: "SOURCE_UNAVAILABLE" }
                } as never;
            if (path.includes("preparations/commands"))
                return { ...ready, research_outcome: "ACCEPTED", run_id: runId } as never;
            if (path.endsWith("/cancellation")) {
                expect(body).toEqual({ schema_version: 1, run_id: runId });
                cancelCommand = command;
                cancelled = true;
                return {
                    ...completed(),
                    report: null,
                    report_status: { state: "NOT_APPLICABLE", code: null },
                    decision_provenance: {
                        ...completed().decision_provenance,
                        state: "NOT_CHECKED",
                        code: null
                    }
                } as never;
            }
            if (path.endsWith(`/runs/${runId}`)) {
                reads.push(path);
                return cancelled
                    ? (completed() as never)
                    : ({
                          ...completed(),
                          state: "RUNNING",
                          worker_observation: {
                              state: "UNAVAILABLE",
                              code: "RESEARCH_EXECUTION_STORE_UNAVAILABLE"
                          },
                          report: null,
                          report_status: { state: "NOT_APPLICABLE", code: null },
                          decision_provenance: {
                              ...completed().decision_provenance,
                              state: "NOT_CHECKED",
                              code: null
                          }
                      } as never);
            }
            throw new Error(path);
        })
    );
    render(<ResearchStudyPanel study={study} newWorkBlocked actionRef={createRef()} />);
    const cancel = await screen.findByRole("button", { name: "取消本次研究" });
    await screen.findByText(/研究执行服务暂不可用/);
    expect(cancel).toBeEnabled();
    fireEvent.click(cancel);
    await screen.findByRole("region", { name: "研究结果报告" });
    expect(cancelCommand).toBeDefined();
    expect(reads.length).toBeGreaterThan(1);
});
it("keeps an unsubmitted preparation visible but blocks confirmation until its exact readiness proof is restored", async () => {
    let available = false;
    vi.mocked(request).mockImplementation((path) =>
        Promise.resolve().then(() => {
            const actual = {
                ...ready,
                readiness: {
                    state: available ? "VERIFIED" : "UNAVAILABLE",
                    code: available ? null : "INPUT_PROOF_UNAVAILABLE"
                }
            };
            if (path.includes("preparation-context")) return context([actual]) as never;
            if (path.includes("preparations/commands")) return actual as never;
            throw new Error(path);
        })
    );
    render(<ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={createRef()} />);
    await screen.findByText(/这份准备的输入证明暂不可核验/);
    expect(screen.getByRole("button", { name: "确认本次研究" })).toBeDisabled();
    available = true;
    fireEvent.click(screen.getByRole("button", { name: "刷新研究状态" }));
    await waitFor(() => {
        expect(screen.getByRole("button", { name: "确认本次研究" })).toBeEnabled();
    });
    expect(vi.mocked(request).mock.calls.every(([, , body]) => body === undefined)).toBe(true);
});
it("reconciles only an exact accepted Human confirmation by read-only proof so UNKNOWN cannot block original Run cancellation", async () => {
    const original = {
        kind: "confirm",
        command: future,
        body: { schema_version: 1, preparation_command_id: uuid, prepared_study_fingerprint: sha }
    };
    sessionStorage.setItem(
        "onlyalpha.factor.research." + sha,
        JSON.stringify({ preparation: uuid, run: null, pending: original })
    );
    const accepted = { ...ready, research_outcome: "ACCEPTED", run_id: runId };
    vi.mocked(request).mockImplementation((path) =>
        Promise.resolve().then(() => {
            if (path.includes("preparation-context")) return context([accepted]) as never;
            if (path.includes("preparations/commands")) return accepted as never;
            if (path.endsWith(`/runs/${runId}`))
                return {
                    ...completed(),
                    state: "RUNNING",
                    report: null,
                    report_status: { state: "NOT_APPLICABLE", code: null }
                } as never;
            throw new Error(path);
        })
    );
    render(<ResearchStudyPanel study={study} newWorkBlocked actionRef={createRef()} />);
    await waitFor(() => {
        expect(screen.getByRole("button", { name: "取消本次研究" })).toBeEnabled();
    });
    expect(screen.queryByRole("button", { name: "核对原研究操作" })).not.toBeInTheDocument();
    expect(vi.mocked(request).mock.calls.every(([, , body]) => body === undefined)).toBe(true);
    const saved = JSON.parse(
        sessionStorage.getItem("onlyalpha.factor.research." + sha) ?? "null"
    ) as { pending: unknown };
    expect(saved.pending).toBeNull();
});
it.each(["command", "fingerprint", "cancel"])(
    "does not resolve a different or unproved original %s outcome from an accepted Run",
    async (mismatch) => {
        const original =
            mismatch === "cancel"
                ? {
                      kind: "cancel-run",
                      command: future,
                      body: { schema_version: 1, run_id: runId }
                  }
                : {
                      kind: "confirm",
                      command: mismatch === "command" ? runId : future,
                      body: {
                          schema_version: 1,
                          preparation_command_id: uuid,
                          prepared_study_fingerprint: mismatch === "fingerprint" ? studyFp : sha
                      }
                  };
        sessionStorage.setItem(
            "onlyalpha.factor.research." + sha,
            JSON.stringify({ preparation: uuid, run: null, pending: original })
        );
        const accepted = { ...ready, research_outcome: "ACCEPTED", run_id: runId };
        vi.mocked(request).mockImplementation((path) =>
            Promise.resolve().then(() => {
                if (path.includes("preparation-context")) return context([accepted]) as never;
                if (path.includes("preparations/commands")) return accepted as never;
                if (path.endsWith(`/runs/${runId}`)) return completed() as never;
                throw new Error(path);
            })
        );
        render(<ResearchStudyPanel study={study} newWorkBlocked actionRef={createRef()} />);
        await screen.findByRole("region", { name: "研究结果报告" });
        expect(screen.getByRole("button", { name: "核对原研究操作" })).toBeVisible();
        fireEvent.click(screen.getByRole("button", { name: "核对原研究操作" }));
        if (mismatch !== "cancel")
            await screen.findByText("原研究是否已接收尚未确认，请核对原操作，不要重复创建研究。");
        else
            await screen.findByText(
                "已刷新实际状态；如原操作回执仍未知，可明确重放同一个原命令核对，不会生成新身份。"
            );
        expect(screen.getByRole("button", { name: "核对原研究操作" })).toBeVisible();
        expect(vi.mocked(request).mock.calls.every(([, , body]) => body === undefined)).toBe(true);
    }
);
it("reconciles only the exact accepted preparation query even when new work and physical readiness are unavailable", async () => {
    const original = {
        kind: "prepare",
        command: uuid,
        body: {
            schema_version: 1,
            study_proposal_fingerprint: studyFp,
            release_manifest_fingerprint: sha,
            expected_active_generation: sha,
            initialize_fresh_runtime: false,
            research_command_id: future
        }
    };
    sessionStorage.setItem(
        "onlyalpha.factor.research." + sha,
        JSON.stringify({ preparation: null, run: null, pending: original })
    );
    const actual = {
        ...ready,
        readiness: { state: "UNAVAILABLE", code: "INPUT_PROOF_UNAVAILABLE" }
    };
    vi.mocked(request).mockImplementation((path) =>
        Promise.resolve().then(() => {
            if (path.includes("preparation-context"))
                return {
                    ...context([actual]),
                    new_work_status: { state: "UNAVAILABLE", code: "SOURCE_UNAVAILABLE" }
                } as never;
            if (path.includes("preparations/commands")) return actual as never;
            throw new Error(path);
        })
    );
    render(<ResearchStudyPanel study={study} newWorkBlocked actionRef={createRef()} />);
    await waitFor(() => {
        expect(screen.getByRole("button", { name: "停止原准备任务" })).toBeEnabled();
    });
    expect(screen.getByRole("button", { name: "确认本次研究" })).toBeDisabled();
    expect(vi.mocked(request).mock.calls.every(([, , body]) => body === undefined)).toBe(true);
});
it("retains an unknown preparation with a different Study identity even after explicit original-command lookup", async () => {
    const original = {
        kind: "prepare",
        command: uuid,
        body: {
            schema_version: 1,
            study_proposal_fingerprint: "c".repeat(64),
            release_manifest_fingerprint: sha,
            expected_active_generation: sha,
            initialize_fresh_runtime: false,
            research_command_id: future
        }
    };
    sessionStorage.setItem(
        "onlyalpha.factor.research." + sha,
        JSON.stringify({ preparation: uuid, run: null, pending: original })
    );
    vi.mocked(request).mockImplementation((path) =>
        Promise.resolve().then(() => {
            if (path.includes("preparation-context")) return context([ready]) as never;
            if (path.includes("preparations/commands")) return ready as never;
            throw new Error(path);
        })
    );
    render(<ResearchStudyPanel study={study} newWorkBlocked actionRef={createRef()} />);
    await screen.findByRole("button", { name: "确认本次研究" });
    fireEvent.click(screen.getByRole("button", { name: "核对原研究操作" }));
    await screen.findByText("原准备任务与保留的提交身份不匹配。请保留记录并核对原操作。");
    expect(screen.getByRole("button", { name: "核对原研究操作" })).toBeVisible();
    expect(vi.mocked(request).mock.calls.every(([, , body]) => body === undefined)).toBe(true);
});
it("does not start another refresh while an accepted original Run response is held beyond the polling interval", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    let release: ((value: ReturnType<typeof completed>) => void) | undefined;
    const held = new Promise<ReturnType<typeof completed>>((resolve) => {
        release = resolve;
    });
    const accepted = { ...ready, state: "RUNNING", research_outcome: "ACCEPTED", run_id: runId };
    let reads = 0;
    vi.mocked(request).mockImplementation((path) => {
        if (path.includes("preparation-context")) return Promise.resolve(context([accepted]));
        if (path.includes("preparations/commands")) return Promise.resolve(accepted);
        if (path.endsWith(`/runs/${runId}`)) {
            reads++;
            return held;
        }
        throw new Error(path);
    });
    await reactAct(() => {
        render(<ResearchStudyPanel study={study} newWorkBlocked actionRef={createRef()} />);
        return Promise.resolve();
    });
    expect(reads).toBe(1);
    await reactAct(async () => {
        await vi.advanceTimersByTimeAsync(3000);
    });
    expect(reads).toBe(1);
    const complete = release;
    if (complete === undefined) throw new Error("Run barrier missing");
    await reactAct(() => {
        complete(completed());
        return Promise.resolve();
    });
    expect(screen.getByRole("region", { name: "研究结果报告" })).toBeVisible();
    expect(screen.getByRole("button", { name: "刷新研究状态" })).toBeEnabled();
});
it("keeps history selection and its nested Run read inside the same polling exclusion window", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const other = "00000000-0000-4000-8000-000000000009",
        otherRun = "00000000-0000-4000-8000-000000000008";
    const initial = { ...ready, research_outcome: "ACCEPTED", run_id: runId };
    const next = {
        ...ready,
        command_id: other,
        research_command_id: other,
        accepted_at: "2026-10-21T00:00:00Z",
        reserved_run_id: otherRun,
        state: "RUNNING",
        research_outcome: "ACCEPTED",
        run_id: otherRun
    };
    let release: ((value: ReturnType<typeof completed>) => void) | undefined;
    const held = new Promise<ReturnType<typeof completed>>((resolve) => {
        release = resolve;
    });
    let reads = 0;
    vi.mocked(request).mockImplementation((path) => {
        if (path.includes("preparation-context")) return Promise.resolve(context([initial, next]));
        if (path.endsWith(`/commands/${uuid}`)) return Promise.resolve(initial);
        if (path.endsWith(`/commands/${other}`)) return Promise.resolve(next);
        if (path.endsWith(`/runs/${runId}`)) return Promise.resolve(completed());
        if (path.endsWith(`/runs/${otherRun}`)) {
            reads++;
            return held;
        }
        throw new Error(path);
    });
    await reactAct(() => {
        render(<ResearchStudyPanel study={study} newWorkBlocked actionRef={createRef()} />);
        return Promise.resolve();
    });
    await reactAct(() => {
        fireEvent.change(screen.getByRole("combobox", { name: "已登记的准备任务" }), {
            target: { value: other }
        });
        return Promise.resolve();
    });
    await reactAct(async () => {
        await vi.advanceTimersByTimeAsync(3000);
    });
    expect(reads).toBe(1);
    expect(screen.getByRole("combobox", { name: "已登记的准备任务" })).toBeDisabled();
    const complete = release;
    if (complete === undefined) throw new Error("Run barrier missing");
    await reactAct(() => {
        complete({ ...completed(), run_id: otherRun });
        return Promise.resolve();
    });
    expect(screen.getByRole("region", { name: "研究结果报告" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "已登记的准备任务" })).toBeEnabled();
});
it("lets original Run cancellation supersede a held refresh without the older chain borrowing its generation", async () => {
    type View = Omit<ReturnType<typeof completed>, "report"> & {
        report: ReturnType<typeof completed>["report"] | null;
    };
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    let oldRelease: ((value: View) => void) | undefined,
        newRelease: ((value: View) => void) | undefined;
    const oldRead = new Promise<View>((resolve) => {
            oldRelease = resolve;
        }),
        newRead = new Promise<View>((resolve) => {
            newRelease = resolve;
        });
    const accepted = { ...ready, state: "RUNNING", research_outcome: "ACCEPTED", run_id: runId };
    let reads = 0,
        preparations = 0,
        cancelled = false;
    const cancelledView = () => ({
        ...completed(),
        state: "CANCELLED",
        report: null,
        report_status: { state: "NOT_APPLICABLE", code: null }
    });
    vi.mocked(request).mockImplementation((path) => {
        if (path.includes("preparation-context")) return Promise.resolve(context([accepted]));
        if (path.includes("preparations/commands")) {
            preparations++;
            return Promise.resolve(accepted);
        }
        if (path.endsWith("/cancellation")) {
            cancelled = true;
            return Promise.resolve(cancelledView());
        }
        if (path.endsWith(`/runs/${runId}`)) {
            reads++;
            if (reads === 2) return oldRead;
            if (reads === 3) return newRead;
            return Promise.resolve(
                cancelled ? cancelledView() : { ...completed(), state: "RUNNING", report: null }
            );
        }
        throw new Error(path);
    });
    await reactAct(() => {
        render(<ResearchStudyPanel study={study} newWorkBlocked actionRef={createRef()} />);
        return Promise.resolve();
    });
    await reactAct(async () => {
        await vi.advanceTimersByTimeAsync(1500);
    });
    expect(reads).toBe(2);
    expect(screen.getByRole("button", { name: "取消本次研究" })).toBeEnabled();
    await reactAct(() => {
        fireEvent.click(screen.getByRole("button", { name: "取消本次研究" }));
        return Promise.resolve();
    });
    expect(reads).toBe(3);
    const before = preparations;
    const releaseOld = oldRelease,
        releaseNew = newRelease;
    if (releaseOld === undefined || releaseNew === undefined)
        throw new Error("Read barriers missing");
    await reactAct(() => {
        releaseOld({ ...completed(), state: "RUNNING", report: null });
        return Promise.resolve();
    });
    expect(preparations).toBe(before);
    expect(screen.getByText("正在核对研究状态…")).toBeVisible();
    expect(screen.queryByText("正在计算研究")).not.toBeInTheDocument();
    await reactAct(() => {
        releaseNew(cancelledView());
        return Promise.resolve();
    });
    expect(screen.getByText("研究已取消")).toBeVisible();
    expect(screen.queryByText("正在核对研究状态…")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "刷新研究状态" })).toBeEnabled();
});
it("explains insufficient block scope before preparation while retaining the original accepted report", async () => {
    const shortFp = "c".repeat(64);
    const shortAdvice = {
        ...advice,
        start_at: "2026-01-01T06:00:00Z",
        development_end_at: "2026-01-01T06:30:00Z",
        end_at: "2026-01-01T07:00:00Z"
    };
    const short = {
        ...study,
        fingerprint: shortFp,
        snapshot: { ...study.snapshot, advice: shortAdvice }
    };
    const accepted = { ...ready, research_outcome: "ACCEPTED", run_id: runId };
    vi.mocked(request).mockImplementation((path) =>
        Promise.resolve().then(() => {
            if (path.includes("preparation-context"))
                return {
                    ...context([accepted]),
                    study_proposal_fingerprint: shortFp,
                    advice: shortAdvice,
                    new_work_status: {
                        state: "UNAVAILABLE",
                        code: "RESEARCH_PREPARATION_INSUFFICIENT_BLOCK_SCOPE"
                    }
                } as never;
            if (path.includes("preparations/commands")) return accepted as never;
            if (path.endsWith(`/runs/${runId}`)) return completed() as never;
            throw new Error(path);
        })
    );
    render(<ResearchStudyPanel study={short} newWorkBlocked={false} actionRef={createRef()} />);
    await screen.findByRole("region", { name: "研究结果报告" });
    expect(screen.getByText(/研究样本范围不足/)).toHaveTextContent("研究样本范围不足");
    expect(screen.getByText(/研究样本范围不足/)).toHaveTextContent("各自至少覆盖 10 个期望区块");
    expect(screen.getByText(/研究样本范围不足/)).toHaveTextContent(
        "RESEARCH_PREPARATION_INSUFFICIENT_BLOCK_SCOPE"
    );
    expect(screen.getByRole("button", { name: "准备并启用研究环境" })).toBeDisabled();
    expect(screen.queryByText(/当前数据来源或研究环境暂不可用/)).not.toBeInTheDocument();
    expect(vi.mocked(request).mock.calls.every(([, , body]) => body === undefined)).toBe(true);
});
it("observation polling reads only the original operation and keeps its deferred response single-flight", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const running = { ...ready, state: "RUNNING", phase: "INPUTS" };
    let release: ((value: typeof ready) => void) | undefined;
    const held = new Promise<typeof ready>((resolve) => {
        release = resolve;
    });
    let contexts = 0,
        preparations = 0;
    vi.mocked(request).mockImplementation((path) => {
        if (path.includes("preparation-context")) {
            contexts++;
            return Promise.resolve(context([running]));
        }
        if (path.includes("preparations/commands")) {
            preparations++;
            return preparations === 2 ? held : Promise.resolve(running);
        }
        throw new Error(path);
    });
    await reactAct(() => {
        render(<ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={createRef()} />);
        return Promise.resolve();
    });
    expect(contexts).toBe(1);
    await reactAct(async () => {
        await vi.advanceTimersByTimeAsync(1500);
    });
    expect(preparations).toBe(2);
    await reactAct(async () => {
        await vi.advanceTimersByTimeAsync(3000);
    });
    expect(preparations).toBe(2);
    expect(contexts).toBe(1);
    const complete = release;
    if (complete === undefined) throw new Error("Original preparation barrier missing");
    await reactAct(() => {
        complete(ready);
        return Promise.resolve();
    });
    expect(contexts).toBe(1);
    expect(screen.getByRole("button", { name: "确认本次研究" })).toBeEnabled();
    expect(screen.queryByText("正在核对研究状态…")).not.toBeInTheDocument();
});
it("observation polling cannot repair a failed full context or erase its error before explicit refresh", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const running = { ...ready, state: "RUNNING", phase: "INPUTS" };
    let contexts = 0,
        preparations = 0;
    vi.mocked(request).mockImplementation((path) => {
        if (path.includes("preparation-context")) {
            contexts++;
            return contexts === 2
                ? Promise.reject(new Error("full context unavailable"))
                : Promise.resolve(context([ready]));
        }
        if (path.includes("preparations/commands")) {
            preparations++;
            return Promise.resolve(preparations < 3 ? running : ready);
        }
        throw new Error(path);
    });
    await reactAct(() => {
        render(<ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={createRef()} />);
        return Promise.resolve();
    });
    await reactAct(() => {
        fireEvent.click(screen.getByRole("button", { name: "刷新研究状态" }));
        return Promise.resolve();
    });
    expect(contexts).toBe(2);
    expect(screen.getByRole("alert")).toHaveTextContent(
        "暂时无法核对研究状态，请稍后刷新；原操作仍会保留，不会重复提交。"
    );
    await reactAct(async () => {
        await vi.advanceTimersByTimeAsync(1500);
    });
    expect(preparations).toBe(3);
    expect(contexts).toBe(2);
    expect(screen.getByRole("alert")).toHaveTextContent(
        "暂时无法核对研究状态，请稍后刷新；原操作仍会保留，不会重复提交。"
    );
    expect(screen.getByRole("button", { name: "确认本次研究" })).toBeDisabled();
    await reactAct(() => {
        fireEvent.click(screen.getByRole("button", { name: "刷新研究状态" }));
        return Promise.resolve();
    });
    expect(contexts).toBe(3);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认本次研究" })).toBeEnabled();
});
it("observation polling preserves full-context failure while original Run cancellation remains available", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const accepted = { ...ready, state: "RUNNING", research_outcome: "ACCEPTED", run_id: runId };
    let contexts = 0,
        cancelled = false;
    vi.mocked(request).mockImplementation((path) => {
        if (path.includes("preparation-context")) {
            contexts++;
            return contexts === 1
                ? Promise.resolve(context([accepted]))
                : Promise.reject(new Error("source context unavailable"));
        }
        if (path.includes("preparations/commands")) return Promise.resolve(accepted);
        if (path.endsWith("/cancellation")) {
            cancelled = true;
            return Promise.resolve({ ...completed(), state: "CANCELLED", report: null });
        }
        if (path.endsWith(`/runs/${runId}`))
            return Promise.resolve({
                ...completed(),
                state: cancelled ? "CANCELLED" : "RUNNING",
                report: null
            });
        throw new Error(path);
    });
    await reactAct(() => {
        render(<ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={createRef()} />);
        return Promise.resolve();
    });
    await reactAct(() => {
        fireEvent.click(screen.getByRole("button", { name: "刷新研究状态" }));
        return Promise.resolve();
    });
    await reactAct(async () => {
        await vi.advanceTimersByTimeAsync(1500);
    });
    expect(contexts).toBe(2);
    expect(screen.getByRole("alert")).toHaveTextContent(
        "暂时无法核对研究状态，请稍后刷新；原操作仍会保留，不会重复提交。"
    );
    expect(screen.getByRole("button", { name: "取消本次研究" })).toBeEnabled();
    await reactAct(() => {
        fireEvent.click(screen.getByRole("button", { name: "取消本次研究" }));
        return Promise.resolve();
    });
    expect(cancelled).toBe(true);
    expect(screen.getByText("研究已取消")).toBeVisible();
    expect(
        vi.mocked(request).mock.calls.filter(([path]) => path.endsWith("/cancellation"))
    ).toHaveLength(1);
});

it("preparation summaries contain only navigation facts and cannot serve as selected readiness proof", () => {
    const summary = {
        command_id: ready.command_id,
        revision: ready.revision,
        state: ready.state,
        study_proposal_fingerprint: ready.study_proposal_fingerprint,
        accepted_at: ready.accepted_at
    };
    expect(
        preparationContextSchema.safeParse({ ...context(), existing_preparations: [summary] })
            .success
    ).toBe(true);
    expect(
        preparationContextSchema.safeParse({
            ...context(),
            existing_preparations: [{ ...summary, readiness: ready.readiness }]
        }).success
    ).toBe(false);
    expect(preparationSchema.safeParse(summary).success).toBe(false);
});
it("preparation summaries always fetch complete proof for automatic and explicit history selection", async () => {
    const other = "00000000-0000-4000-8000-000000000009";
    const second = {
        ...ready,
        command_id: other,
        research_command_id: "00000000-0000-4000-8000-00000000000a",
        reserved_run_id: "00000000-0000-4000-8000-00000000000b",
        accepted_at: "2026-10-21T00:00:00Z"
    };
    const summaries = [ready, second].map(
        ({ command_id, revision, state, study_proposal_fingerprint, accepted_at }) => ({
            command_id,
            revision,
            state,
            study_proposal_fingerprint,
            accepted_at
        })
    );
    type FirstProof = Omit<typeof ready, "readiness"> & {
        readiness: { state: string; code: string | null };
    };
    let releaseFirst: ((value: FirstProof) => void) | undefined,
        releaseSecond: ((value: typeof second) => void) | undefined;
    const first = new Promise<FirstProof>((resolve) => {
            releaseFirst = resolve;
        }),
        next = new Promise<typeof second>((resolve) => {
            releaseSecond = resolve;
        });
    const reads: string[] = [];
    vi.mocked(request).mockImplementation((path) => {
        if (path.includes("preparation-context"))
            return Promise.resolve(
                preparationContextSchema.parse({ ...context(), existing_preparations: summaries })
            );
        if (path.endsWith(`/commands/${uuid}`)) {
            reads.push(uuid);
            return first;
        }
        if (path.endsWith(`/commands/${other}`)) {
            reads.push(other);
            return next;
        }
        throw new Error(path);
    });
    await reactAct(() => {
        render(<ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={createRef()} />);
        return Promise.resolve();
    });
    expect(reads).toEqual([uuid]);
    expect(screen.queryByRole("button", { name: "确认本次研究" })).not.toBeInTheDocument();
    const firstResponse = releaseFirst,
        secondResponse = releaseSecond;
    if (firstResponse === undefined || secondResponse === undefined)
        throw new Error("Selected proof barriers missing");
    await reactAct(() => {
        firstResponse({ ...ready, readiness: { state: "UNAVAILABLE", code: "PROOF_UNAVAILABLE" } });
        return Promise.resolve();
    });
    expect(
        screen.getByRole("combobox", { name: "已登记的准备任务" }).querySelectorAll("option")
    ).toHaveLength(2);
    expect(screen.getByRole("button", { name: "确认本次研究" })).toBeDisabled();
    await reactAct(() => {
        fireEvent.change(screen.getByRole("combobox", { name: "已登记的准备任务" }), {
            target: { value: other }
        });
        return Promise.resolve();
    });
    expect(reads).toEqual([uuid, other]);
    expect(screen.getByRole("button", { name: "确认本次研究" })).toBeDisabled();
    await reactAct(() => {
        secondResponse(second);
        return Promise.resolve();
    });
    expect(screen.getByRole("button", { name: "确认本次研究" })).toBeEnabled();
    expect(vi.mocked(request).mock.calls.every(([, , body]) => body === undefined)).toBe(true);
});
it.each([
    "RESEARCH_STORE_UNAVAILABLE",
    '{"error":"PRIVATE_INTERNAL_CODE"}',
    '中文说明 {"secret":"hidden"}'
])("shows readable feedback instead of a raw service error: %s", async (detail) => {
    vi.mocked(request).mockRejectedValue(new Error(detail));
    render(<ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={createRef()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
        "暂时无法核对研究状态，请稍后刷新；原操作仍会保留，不会重复提交。"
    );
    expect(screen.queryByText(detail, { exact: true })).not.toBeInTheDocument();
});
it("preserves useful Chinese recovery guidance from a local failure", async () => {
    vi.mocked(request).mockRejectedValue(new Error("原准备任务暂不可核对，请保留记录。"));
    render(<ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={createRef()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
        "原准备任务暂不可核对，请保留记录。"
    );
});
it("keeps service codes and failure payloads in collapsed diagnostics", async () => {
    vi.mocked(request).mockImplementation((path) =>
        Promise.resolve().then(() => {
            if (path.includes("preparation-context")) return context() as never;
            if (path.includes("preparations/commands"))
                return { ...ready, research_outcome: "ACCEPTED", run_id: runId } as never;
            if (path.includes("/research/runs/"))
                return {
                    ...completed(),
                    state: "FAILED",
                    failure: { code: "PRIVATE_FAILURE_CODE" },
                    worker_observation: { state: "UNAVAILABLE", code: "PRIVATE_WORKER_CODE" }
                } as never;
            throw new Error(path);
        })
    );
    render(<ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={createRef()} />);
    expect(
        await screen.findByText("研究未能完成。可查看下方诊断详情，并保留本次研究记录。")
    ).toBeVisible();
    const failure = screen.getByText(/PRIVATE_FAILURE_CODE/);
    expect(failure.closest("details")).not.toHaveAttribute("open");
    expect(failure).not.toBeVisible();
    const workerCode = screen.getByText("PRIVATE_WORKER_CODE");
    expect(workerCode.closest("details")).not.toHaveAttribute("open");
    expect(workerCode).not.toBeVisible();
});
it("keeps readiness and source diagnostics collapsed while showing recovery guidance", async () => {
    vi.mocked(request).mockImplementation((path) =>
        Promise.resolve().then(() => {
            if (path.includes("preparation-context"))
                return {
                    ...context(),
                    new_work_status: { state: "UNAVAILABLE", code: "PRIVATE_SOURCE_CODE" }
                } as never;
            if (path.includes("preparations/commands"))
                return {
                    ...ready,
                    readiness: { state: "UNAVAILABLE", code: "PRIVATE_INPUT_CODE" }
                } as never;
            throw new Error(path);
        })
    );
    render(<ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={createRef()} />);
    await screen.findByText(/这份准备的输入证明暂不可核验/);
    for (const code of ["PRIVATE_SOURCE_CODE", "PRIVATE_INPUT_CODE"]) {
        const detail = screen.getByText(code);
        expect(detail.closest("details")).not.toHaveAttribute("open");
        expect(detail).not.toBeVisible();
    }
    expect(screen.getByRole("button", { name: "确认本次研究" })).toBeDisabled();
});

it("reads a retained completed Run once and stops polling its unfinished preparation before another Study", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const old = {
        ...ready,
        state: "RUNNING",
        phase: "CONFIRMING",
        study_proposal_fingerprint: "c".repeat(64),
        research_outcome: "ACCEPTED",
        run_id: runId
    };
    sessionStorage.setItem(
        "onlyalpha.factor.research." + sha,
        JSON.stringify({ preparation: uuid, run: runId, pending: null })
    );
    vi.mocked(request).mockImplementation((path) =>
        Promise.resolve().then(() => {
            if (path.includes("preparation-context")) return context([old]);
            if (path.includes("preparations/commands")) return old;
            if (path.includes("/research/runs/")) return completed();
            throw new Error(path);
        })
    );
    render(<ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={createRef()} />);
    await reactAct(async () => {
        await Promise.resolve();
    });
    expect(screen.getByRole("button", { name: "准备并启用研究环境" })).toBeEnabled();
    expect(
        vi.mocked(request).mock.calls.filter(([path]) => path.includes("/research/runs/"))
    ).toHaveLength(1);
    const reads = vi.mocked(request).mock.calls.length;
    await reactAct(async () => {
        await vi.advanceTimersByTimeAsync(3000);
    });
    expect(vi.mocked(request).mock.calls).toHaveLength(reads);
});

it.each(["preparation-unavailable", "first-run-unavailable", "different-run"] as const)(
    "preserves independent Run observation while deduplicating only a successful same-refresh read: %s",
    async (scenario) => {
        const nextRun = "00000000-0000-4000-8000-000000000004";
        const old = {
            ...ready,
            state: "RUNNING",
            phase: "CONFIRMING",
            research_outcome: "ACCEPTED",
            run_id: scenario === "different-run" ? nextRun : runId
        };
        sessionStorage.setItem(
            "onlyalpha.factor.research." + sha,
            JSON.stringify({ preparation: uuid, run: runId, pending: null })
        );
        const reads: string[] = [];
        vi.mocked(request).mockImplementation((path) =>
            Promise.resolve().then(() => {
                if (path.includes("preparation-context")) return context([old]);
                if (path.includes("preparations/commands")) {
                    if (scenario === "preparation-unavailable") throw new Error("unavailable");
                    return old;
                }
                if (path.includes("/research/runs/")) {
                    reads.push(path);
                    if (scenario === "first-run-unavailable" && reads.length === 1)
                        throw new Error("unavailable");
                    return { ...completed(), run_id: path.endsWith(nextRun) ? nextRun : runId };
                }
                throw new Error(path);
            })
        );
        render(<ResearchStudyPanel study={study} newWorkBlocked={false} actionRef={createRef()} />);
        await screen.findByRole("heading", { name: "submitted name · 研究结果" });
        expect(reads).toEqual(
            scenario === "preparation-unavailable"
                ? ["/api/v2/research/runs/" + runId]
                : [
                      "/api/v2/research/runs/" + runId,
                      "/api/v2/research/runs/" + (scenario === "different-run" ? nextRun : runId)
                  ]
        );
    }
);
