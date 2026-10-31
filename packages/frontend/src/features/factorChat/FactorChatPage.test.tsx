import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { z } from "zod";
import { FactorChatPage } from "./FactorChatPage";
import { accessKey, request } from "./api";

vi.mock(import("./api"), async (original) => ({
    ...(await original()),
    request: vi.fn()
}));
const sid = "00000000-0000-4000-8000-000000000001";
const cid = "00000000-0000-4000-8000-000000000002";
const studyCid = "00000000-0000-4000-8000-000000000003";
const factorFp = "a".repeat(64),
    studyFp = "b".repeat(64),
    newStudyFp = "c".repeat(64);
const factorHead = "d".repeat(64),
    studyHead = "e".repeat(64),
    newHead = "f".repeat(64);
const access = {
    schema_version: 1,
    token: "agent-only",
    expires_at: 4_000_000_000,
    subject: "owner",
    agent_url: "https://agent.example",
    binding: "a".repeat(64)
};
const advice = {
    source: {
        integration_id: cid,
        integration_revision_fingerprint: factorFp,
        expected_type_id: "binance.spot.source",
        source_id: "spot",
        environment: "public",
        instrument_id: "BTCUSDT"
    },
    timeframe_minutes: 15,
    start_at: "2026-01-01T00:00:00Z",
    development_end_at: "2026-03-01T00:00:00Z",
    end_at: "2026-04-01T00:00:00Z",
    protected_start_at: "2026-04-01T00:00:00Z",
    protected_end_at: "2026-05-01T00:00:00Z",
    horizon_bars: 1,
    expected_block_length: 4,
    replicates: 4096,
    confidence_bps: 9500,
    seed: factorFp,
    rationale: "固定样本和序列依赖修正"
};
const preview = {
    name: "已确认因子",
    purpose: "观察价格持续性",
    hypothesis: "价格动量可能延续",
    formula: "close / lag(close,20) - 1",
    expression: { input: "close" },
    dependencies: {},
    draft: {
        source_text: "def calculate(api): return api.close()",
        input_contract: {},
        parameter_contract: {},
        output_contract: {}
    },
    draft_fingerprint: factorFp,
    execution_admitted: false
};
beforeEach(() => {
    sessionStorage.setItem(accessKey, JSON.stringify(access));
    localStorage.setItem("onlyalpha.agent.chat.selected", sid);
});
afterEach(() => {
    cleanup();
    vi.resetAllMocks();
    sessionStorage.clear();
    localStorage.clear();
});

it("keeps Factor confirmation across Study heads and withdraws only the Study when its conditions change", async () => {
    let current = {
        id: sid,
        workflow: factorFp,
        model_revision: studyFp,
        head: studyHead,
        consumed: 2,
        model_call_limit: 10,
        messages: [],
        status: "READY",
        topic: "STUDY",
        candidate: null,
        study: advice,
        factor_reference: { command: cid, head: factorHead, fingerprint: factorFp },
        study_reference: { command: studyCid, head: studyHead, fingerprint: studyFp },
        execution_admitted: false
    };
    let selectedStudy = studyFp;
    let withdrawn = false;
    vi.mocked(request).mockImplementation((path, _schema, body, command) =>
        Promise.resolve().then(() => {
            if (path === "/api/v1/agent/models") return { items: [] } as never;
            if (path === "/api/v1/agent/sessions") return { items: [current] } as never;
            if (path === "/api/v2/agent-connection")
                return {
                    schema_version: 1,
                    connection: {
                        schema_version: 1,
                        agent_url: access.agent_url,
                        grant_id: cid,
                        service_subject: "discovery",
                        credential_sha256: factorFp
                    },
                    grant_state: "ACTIVE"
                } as never;
            if (path === `/api/v2/factor-proposals/${factorFp}`)
                return {
                    schema_version: 1,
                    fingerprint: factorFp,
                    is_current: true,
                    withdrawn: false,
                    snapshot: {
                        schema_version: 1,
                        owner: "owner",
                        factor_id: "private.factor",
                        origin: { session_id: sid, event_fingerprint: factorHead },
                        preview
                    },
                    confirmation: {
                        schema_version: 1,
                        command_id: cid,
                        operation_fingerprint: factorFp,
                        effect: { proposal_fingerprint: factorFp }
                    }
                } as never;
            if (path === `/api/v2/factor-studies/${selectedStudy}`)
                return {
                    schema_version: 1,
                    fingerprint: selectedStudy,
                    is_current: true,
                    withdrawn,
                    snapshot: {
                        schema_version: 1,
                        owner: "owner",
                        factor_proposal_fingerprint: factorFp,
                        origin: {
                            session_id: sid,
                            event_fingerprint: current.study_reference.head
                        },
                        advice: current.study
                    }
                } as never;
            if (path === `/api/v2/factor-studies/${studyFp}/withdrawal`) {
                withdrawn = true;
                return {
                    schema_version: 1,
                    command_id: command,
                    operation_fingerprint: factorFp,
                    effect: { proposal_fingerprint: studyFp }
                } as never;
            }
            if (path === `/api/v1/agent/sessions/${sid}/messages`) {
                expect(body).toEqual({
                    expected: studyHead,
                    text: "把预测期限改成3根",
                    topic: "STUDY",
                    factor_proposal_fingerprint: factorFp
                });
                current = {
                    ...current,
                    head: newHead,
                    consumed: 3,
                    study: { ...advice, horizon_bars: 3, rationale: "新的研究条件" }
                };
                return current as never;
            }
            if (path === `/api/v1/agent/sessions/${sid}/proposals`) {
                selectedStudy = newStudyFp;
                withdrawn = false;
                current = {
                    ...current,
                    study_reference: {
                        command: command ?? studyCid,
                        head: newHead,
                        fingerprint: newStudyFp
                    }
                };
                return {
                    status: "REGISTERED",
                    backend_command: studyCid,
                    receipt: {
                        schema_version: 1,
                        command_id: studyCid,
                        operation_fingerprint: factorFp,
                        effect: { proposal_fingerprint: newStudyFp }
                    }
                } as never;
            }
            throw new Error("unexpected request " + path);
        })
    );
    render(<FactorChatPage />);
    await screen.findByRole("heading", { name: "已确认因子" });
    expect(screen.getByText("计算内容已确认并保存")).toBeVisible();
    await screen.findByText("固定样本和序列依赖修正");
    fireEvent.change(screen.getByRole("textbox", { name: "告诉助手你的想法" }), {
        target: { value: "把预测期限改成3根" }
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByText("新的研究条件");
    expect(screen.getByText("计算内容已确认并保存")).toBeVisible();
    expect(
        vi
            .mocked(request)
            .mock.calls.some(([path]) => path === `/api/v2/factor-proposals/${factorFp}/withdrawal`)
    ).toBe(false);
    expect(
        vi.mocked(request).mock.calls.filter(([path]) => path.endsWith("/withdrawal"))
    ).toHaveLength(1);
    await waitFor(() => {
        expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
    });
});

it.each([false, true])(
    "uses the owning Study grant and one fixed message (existing grant: %s)",
    async (existing) => {
        let current = {
            id: sid,
            workflow: factorFp,
            model_revision: studyFp,
            head: factorHead,
            consumed: 1,
            model_call_limit: 10,
            messages: [],
            status: "READY",
            topic: "FACTOR",
            candidate: null,
            study: null as typeof advice | null,
            factor_reference: { command: cid, head: factorHead, fingerprint: factorFp },
            study_reference: null as { command: string; head: string; fingerprint: string } | null,
            execution_admitted: false
        };
        let grantPosts = 0,
            messagePosts = 0;
        let grantCommand = "",
            grantId = existing ? cid : "";
        let originalMessage: unknown;
        vi.mocked(request).mockImplementation((path, _schema, body, command) =>
            Promise.resolve().then(() => {
                if (path === "/api/v1/agent/models") return { items: [] } as never;
                if (path === "/api/v1/agent/sessions") return { items: [current] } as never;
                if (path === "/api/v2/agent-connection")
                    return {
                        schema_version: 1,
                        connection: {
                            schema_version: 1,
                            agent_url: access.agent_url,
                            grant_id: cid,
                            service_subject: "discovery",
                            credential_sha256: factorFp
                        },
                        grant_state: "ACTIVE"
                    } as never;
                if (path === `/api/v2/factor-proposals/${factorFp}`)
                    return {
                        schema_version: 1,
                        fingerprint: factorFp,
                        is_current: true,
                        withdrawn: false,
                        snapshot: {
                            schema_version: 1,
                            owner: "owner",
                            factor_id: "private.factor",
                            origin: { session_id: sid, event_fingerprint: factorHead },
                            preview
                        },
                        confirmation: {
                            schema_version: 1,
                            command_id: cid,
                            operation_fingerprint: factorFp,
                            effect: { proposal_fingerprint: factorFp }
                        }
                    } as never;
                if (path === `/api/v2/factor-study-context/${factorFp}`)
                    return {
                        schema_version: 1,
                        owner: "owner",
                        service_subject: "discovery",
                        factor_proposal_fingerprint: factorFp,
                        factor: preview,
                        study_proposal_fingerprint: null,
                        sources: [
                            Object.fromEntries(
                                Object.entries(advice.source).filter(
                                    ([key]) => key !== "instrument_id"
                                )
                            )
                        ],
                        supported_profile: {
                            study_grant_id: grantId || null,
                            study_grant_state: grantId ? "ACTIVE" : "ABSENT",
                            remaining_proposals: grantId ? 10 : 0
                        }
                    } as never;
                if (path === "/api/v2/factor-study-grants") {
                    grantPosts++;
                    grantCommand = command ?? "";
                    grantId = (body as { grant_id: string }).grant_id;
                    expect(body).toEqual({
                        schema_version: 1,
                        factor_proposal_fingerprint: factorFp,
                        grant_id: grantId,
                        proposal_limit: 10
                    });
                    originalMessage = z
                        .object({ message: z.unknown() })
                        .parse(
                            JSON.parse(
                                sessionStorage.getItem("onlyalpha.agent.chat.pending") ?? "null"
                            )
                        ).message;
                    throw new Error("controlled lost grant acknowledgement");
                }
                if (path === `/api/v2/factor-studies/commands/${grantCommand}`)
                    return {
                        schema_version: 1,
                        command_id: grantCommand,
                        operation_fingerprint: factorFp,
                        effect: { study_grant_id: grantId, study_grant_fingerprint: studyFp }
                    } as never;
                if (path === `/api/v1/agent/sessions/${sid}/messages`) {
                    messagePosts++;
                    if (existing)
                        expect(body).toEqual({
                            expected: factorHead,
                            text: "请建议当前因子的研究条件",
                            topic: "STUDY",
                            factor_proposal_fingerprint: factorFp
                        });
                    else
                        expect({ resource: sid, command, binding: access.binding, body }).toEqual(
                            originalMessage
                        );
                    current = {
                        ...current,
                        head: studyHead,
                        consumed: 2,
                        topic: "STUDY",
                        study: advice
                    };
                    return current as never;
                }
                if (path === `/api/v1/agent/sessions/${sid}/proposals`) {
                    current = {
                        ...current,
                        study_reference: {
                            command: command ?? studyCid,
                            head: studyHead,
                            fingerprint: studyFp
                        }
                    };
                    return {
                        status: "REGISTERED",
                        backend_command: studyCid,
                        receipt: {
                            schema_version: 1,
                            command_id: studyCid,
                            operation_fingerprint: factorFp,
                            effect: { proposal_fingerprint: studyFp }
                        }
                    } as never;
                }
                if (path === `/api/v2/factor-studies/${studyFp}`)
                    return {
                        schema_version: 1,
                        fingerprint: studyFp,
                        is_current: true,
                        withdrawn: false,
                        snapshot: {
                            schema_version: 1,
                            owner: "owner",
                            factor_proposal_fingerprint: factorFp,
                            origin: { session_id: sid, event_fingerprint: studyHead },
                            advice
                        }
                    } as never;
                throw new Error("unexpected request " + path);
            })
        );
        const first = render(<FactorChatPage />);
        await screen.findByRole("heading", { name: "已确认因子" });
        fireEvent.click(screen.getByRole("button", { name: "讨论研究条件" }));
        if (existing) {
            await screen.findByText(advice.rationale);
            expect(grantPosts).toBe(0);
            expect(messagePosts).toBe(1);
            return;
        }
        await screen.findByRole("button", { name: "再次提交同一授权" });
        expect(messagePosts).toBe(0);
        first.unmount();
        render(<FactorChatPage />);
        await screen.findByRole("heading", { name: "已确认因子" });
        fireEvent.click(screen.getByRole("button", { name: "更多研究操作" }));
        fireEvent.click(screen.getByRole("button", { name: "核对并重新载入" }));
        await screen.findByText(advice.rationale);
        expect(grantPosts).toBe(1);
        expect(messagePosts).toBe(1);
        expect(screen.getByText("计算内容已确认并保存")).toBeVisible();
    }
);
it.each([true, false])(
    "sends Human Research confirmation without a model call (Agent available: %s)",
    async (agentAvailable) => {
        if (!agentAvailable) {
            localStorage.setItem(
                "onlyalpha.agent.chat.proposals",
                JSON.stringify({ [sid]: { fingerprint: factorFp, head: factorHead } })
            );
            localStorage.setItem(
                "onlyalpha.agent.chat.studies",
                JSON.stringify({ [sid]: { fingerprint: studyFp, head: studyHead } })
            );
        }
        const pendingRun = "00000000-0000-4000-8000-000000000010";
        const preparation = {
            schema_version: 1,
            command_id: cid,
            revision: "1",
            state: "READY",
            phase: "READY_FOR_HUMAN_CONFIRMATION",
            readiness: { state: "VERIFIED", code: null },
            study_proposal_fingerprint: studyFp,
            research_command_id: studyCid,
            reserved_run_id: pendingRun,
            prepared_study_fingerprint: factorFp,
            research_outcome: "NOT_SUBMITTED",
            run_id: null,
            accepted_at: "2026-10-22T00:00:00Z",
            advice,
            detail: null
        };
        vi.mocked(request).mockImplementation((path, _schema, body, command) =>
            Promise.resolve().then(() => {
                if (path === "/api/v1/agent/models") {
                    if (!agentAvailable) throw new Error("unavailable");
                    return { items: [] } as never;
                }
                if (path === "/api/v1/agent/sessions")
                    return {
                        items: [
                            {
                                id: sid,
                                workflow: factorFp,
                                model_revision: studyFp,
                                head: studyHead,
                                consumed: 2,
                                model_call_limit: 10,
                                messages: [],
                                status: "READY",
                                topic: "STUDY",
                                candidate: null,
                                study: advice,
                                factor_reference: {
                                    command: cid,
                                    head: factorHead,
                                    fingerprint: factorFp
                                },
                                study_reference: {
                                    command: studyCid,
                                    head: studyHead,
                                    fingerprint: studyFp
                                },
                                execution_admitted: false
                            }
                        ]
                    } as never;
                if (path === "/api/v2/agent-connection")
                    return {
                        schema_version: 1,
                        connection: {
                            schema_version: 1,
                            agent_url: access.agent_url,
                            grant_id: cid,
                            service_subject: "discovery",
                            credential_sha256: factorFp
                        },
                        grant_state: "ACTIVE"
                    } as never;
                if (path === `/api/v2/factor-proposals/${factorFp}`)
                    return {
                        schema_version: 1,
                        fingerprint: factorFp,
                        is_current: true,
                        withdrawn: false,
                        snapshot: {
                            schema_version: 1,
                            owner: "owner",
                            factor_id: "factor",
                            origin: { session_id: sid, event_fingerprint: factorHead },
                            preview
                        },
                        confirmation: {
                            schema_version: 1,
                            command_id: cid,
                            operation_fingerprint: factorFp,
                            effect: { proposal_fingerprint: factorFp }
                        }
                    } as never;
                if (path === `/api/v2/factor-studies/${studyFp}`)
                    return {
                        schema_version: 1,
                        fingerprint: studyFp,
                        is_current: true,
                        withdrawn: false,
                        snapshot: {
                            schema_version: 1,
                            owner: "owner",
                            factor_proposal_fingerprint: factorFp,
                            origin: { session_id: sid, event_fingerprint: studyHead },
                            advice
                        }
                    } as never;
                if (path.includes("preparation-context"))
                    return {
                        schema_version: 1,
                        study_proposal_fingerprint: studyFp,
                        factor_proposal_fingerprint: factorFp,
                        factor_name: preview.name,
                        usage_summary: preview.purpose,
                        source_label: "controlled market",
                        advice,
                        is_current: true,
                        withdrawn: false,
                        release_manifest_fingerprint: factorFp,
                        backend_version: "1",
                        algorithm_artifact_fingerprint: factorFp,
                        expected_active_generation: factorFp,
                        initialize_fresh_runtime: false,
                        profile: {},
                        policy: {},
                        new_work_status: { state: "AVAILABLE", code: null },
                        existing_preparations: [
                            {
                                command_id: preparation.command_id,
                                revision: preparation.revision,
                                state: preparation.state,
                                study_proposal_fingerprint: preparation.study_proposal_fingerprint,
                                accepted_at: preparation.accepted_at
                            }
                        ]
                    } as never;
                if (path.includes("preparations/commands")) return preparation as never;
                if (path.endsWith("/confirmation")) {
                    expect(command).toBe(studyCid);
                    expect(body).toEqual({
                        schema_version: 1,
                        preparation_command_id: cid,
                        prepared_study_fingerprint: factorFp
                    });
                    return {
                        schema_version: 1,
                        research_command_id: studyCid,
                        state: "ACCEPTED",
                        run_id: pendingRun
                    } as never;
                }
                if (path.endsWith(`/runs/${pendingRun}`))
                    return {
                        schema_version: 1,
                        run_id: pendingRun,
                        state: "QUEUED",
                        revision: "1",
                        name_snapshot: { factor_name: preview.name },
                        current_name: preview.name,
                        accepted_at: "2026-10-22T00:00:00Z",
                        specification_fingerprint: factorFp,
                        runtime_generation_fingerprint: factorFp,
                        report: null,
                        failure: null,
                        worker_observation: { state: "IDLE" },
                        report_status: { state: "NOT_APPLICABLE", code: null },
                        decision_provenance: {
                            state: "NOT_CHECKED",
                            code: null,
                            command_id: studyCid,
                            group_fingerprint: factorFp,
                            policy_id: "policy",
                            policy_version: "1"
                        }
                    } as never;
                throw new Error(path);
            })
        );
        render(<FactorChatPage />);
        await waitFor(() => {
            expect(screen.getByRole("button", { name: "确认本次研究" })).toBeEnabled();
        });
        fireEvent.change(screen.getByRole("textbox", { name: "告诉助手你的想法" }), {
            target: { value: "确认本次研究" }
        });
        fireEvent.click(screen.getByRole("button", { name: "发送" }));
        await waitFor(() => {
            expect(
                vi
                    .mocked(request)
                    .mock.calls.some(([path]) =>
                        path.endsWith(`/factor-study-preparations/${cid}/confirmation`)
                    )
            ).toBe(true);
        });
        expect(
            vi
                .mocked(request)
                .mock.calls.filter(
                    ([path]) => path.endsWith("/messages") || path.endsWith("/withdrawal")
                )
        ).toEqual([]);
    }
);
