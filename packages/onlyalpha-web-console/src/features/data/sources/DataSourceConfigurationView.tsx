import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
    IntegrationWebError,
    isIndeterminateMutationError
} from "../../../api/integrations/client";
import type { IntegrationProbeAttempt } from "../../../api/integrations/model";
import { MutationSubmissionIntent } from "../../../api/integrations/submissionIntent";
import { useIntegrationApi } from "../../../app/providers";
import { CapabilityTags } from "./CapabilityTags";
import { IntegrationConfigurationForm } from "./IntegrationConfigurationForm";
import { ProbeCheckList } from "./ProbeCheckList";
import { ProviderIcon } from "./ProviderIcon";
import {
    describeError,
    formatTimestamp,
    probeDurationMs,
    probeSupport,
    shortFingerprint,
    sourcePresentation
} from "./status";

export function DataSourceConfigurationView({
    integrationId,
    onBack
}: {
    readonly integrationId: string;
    readonly onBack?: (() => void) | undefined;
}) {
    const client = useIntegrationApi();
    const cache = useQueryClient();
    const integration = useQuery({
        queryKey: ["integrations", integrationId],
        queryFn: ({ signal }) => client.getIntegration(integrationId, signal)
    });
    const draft = useQuery({
        queryKey: ["integrations", integrationId, "draft"],
        queryFn: ({ signal }) => client.getDraft(integrationId, signal)
    });
    const operational = useQuery({
        queryKey: ["integrations", integrationId, "operational-status"],
        queryFn: ({ signal }) => client.getOperationalStatus(integrationId, signal)
    });
    const attempts = useQuery({
        queryKey: ["integrations", integrationId, "probe-attempts"],
        queryFn: ({ signal }) => client.listProbeAttempts(integrationId, signal)
    });
    const revisions = useQuery({
        queryKey: ["integrations", integrationId, "revisions"],
        queryFn: ({ signal }) => client.listRevisions(integrationId, signal)
    });
    const [valueEdits, setValueEdits] = useState<Record<string, unknown> | null>(null);
    const [probeEdits, setProbeEdits] = useState<Record<string, unknown> | null | undefined>();
    const [selectedAttemptId, setSelectedAttemptId] = useState<string | null>(null);
    const selectedAttempt = useQuery({
        queryKey: ["integrations", integrationId, "probe-attempts", selectedAttemptId],
        queryFn: ({ signal }) =>
            client.getProbeAttempt(integrationId, selectedAttemptId ?? "", signal),
        enabled: selectedAttemptId !== null
    });
    const [error, setError] = useState("");
    const [busy, setBusy] = useState("");
    const intent = useRef(new MutationSubmissionIntent());
    const archived = integration.data?.lifecycle_state === "ARCHIVED";
    const refresh = async () => {
        await cache.invalidateQueries({ queryKey: ["integrations"] });
    };
    const mutate = async (
        label: string,
        key: string,
        operation: (commandId: string) => Promise<unknown>,
        resetEdits = false,
        rethrowTransport = false
    ) => {
        setBusy(label);
        setError("");
        try {
            await operation(intent.current.commandFor(key));
            intent.current.definitive(key);
            if (resetEdits) {
                setValueEdits(null);
                setProbeEdits(undefined);
            }
            await refresh();
        } catch (value) {
            const unknownOutcome = isIndeterminateMutationError(value);
            if (!unknownOutcome) intent.current.definitive(key);
            setError(
                value instanceof IntegrationWebError ? describeError(value) : "Integration 请求失败"
            );
            if (unknownOutcome && rethrowTransport) throw value;
        } finally {
            setBusy("");
        }
    };

    if (integration.isPending || draft.isPending) {
        return <p role="status">正在读取数据源…</p>;
    }
    if (integration.isError || draft.isError) {
        return (
            <p className="error" role="alert">
                无法读取该数据源。
            </p>
        );
    }
    const model = integration.data;
    const working = draft.data;
    const values = valueEdits ?? working.public_configuration;
    const probeValues = probeEdits === undefined ? working.probe_configuration : probeEdits;
    const editedInstrument = probeValues?.instrument;
    const probeInstrument =
        typeof editedInstrument === "string"
            ? editedInstrument
            : (working.type_descriptor.probe_contract?.default_probe_instrument ?? "");
    const currentAttempt: IntegrationProbeAttempt | undefined = attempts.data?.find(
        (attempt) => attempt.revision_fingerprint === model.current_revision_fingerprint
    );
    const support = probeSupport(
        working.type_descriptor.probe_contract != null,
        operational.data?.probe_supported
    );
    const presentation = sourcePresentation(model.lifecycle_state, operational.data?.status);
    const declaredChecks = working.type_descriptor.probe_contract?.probe_checks ?? [];
    const probeReason =
        support.notice ??
        (model.current_revision_fingerprint === null ? "需要先发布一个 Revision 才能测试连接" : "");

    return (
        <div className="configuration-view">
            <div className="configuration-view__head">
                {onBack ? (
                    <button type="button" className="button-subtle" onClick={onBack}>
                        ← 返回列表
                    </button>
                ) : null}
                <ProviderIcon providerId={working.type_descriptor.provider_id} size="lg" />
                <div className="configuration-view__identity">
                    <h3>{model.display_name}</h3>
                    <p className="muted value">
                        {model.type_id} · 已发布 revision{" "}
                        {shortFingerprint(model.current_revision_fingerprint)} · 草稿 v
                        {working.draft_version}
                    </p>
                </div>
                <span className={`state-badge state-badge--${presentation.tone}`}>
                    <i className="state-mark" aria-hidden="true" />
                    {presentation.label}
                </span>
            </div>
            {error ? (
                <p className="error" role="alert">
                    {error}
                    {error.includes("INTEGRATION_TYPE_CHANGED")
                        ? " 已保留现有 Draft，请显式使用「重置契约」。"
                        : ""}
                    {error.includes("UNKNOWN_OUTCOME") || error.includes("TRANSPORT_ERROR")
                        ? " 本次命令结果未确认，请用同一操作重试；系统不会变更 command 身份。"
                        : ""}
                </p>
            ) : null}
            {archived ? (
                <p className="warning">
                    已归档的数据源为只读；历史 Revision 与 Probe Attempt 仍然可读。
                </p>
            ) : null}
            <div className="configuration-view__grid">
                <section className="configuration-view__form" aria-labelledby="working-draft">
                    <h4 id="working-draft" className="section-title">
                        工作草稿
                    </h4>
                    <p className="muted">
                        契约{" "}
                        <span className="value">
                            {shortFingerprint(working.pinned_type_descriptor_fingerprint)}
                        </span>
                    </p>
                    <IntegrationConfigurationForm
                        descriptor={working.type_descriptor}
                        values={values}
                        secretStatuses={working.secret_statuses}
                        readOnly={archived}
                        onChange={(fieldId, value) => {
                            setValueEdits({ ...values, [fieldId]: value });
                        }}
                        onReplaceSecret={(fieldId, secret) =>
                            mutate(
                                "secret",
                                JSON.stringify(["secret", fieldId, working.draft_version, secret]),
                                (commandId) =>
                                    client.setSecret(
                                        integrationId,
                                        fieldId,
                                        working.draft_version,
                                        secret,
                                        commandId
                                    ),
                                false,
                                true
                            )
                        }
                        onClearSecret={(fieldId) =>
                            mutate(
                                "secret",
                                JSON.stringify(["clear", fieldId, working.draft_version]),
                                (commandId) =>
                                    client.clearSecret(
                                        integrationId,
                                        fieldId,
                                        working.draft_version,
                                        commandId
                                    )
                            )
                        }
                    />
                    {working.type_descriptor.probe_contract?.user_selectable_probe_instrument ? (
                        <label>
                            探测标的
                            <input
                                value={probeInstrument}
                                disabled={archived}
                                onChange={(event) => {
                                    setProbeEdits({ instrument: event.target.value });
                                }}
                            />
                        </label>
                    ) : null}
                    <div className="configuration-view__actions">
                        <button
                            type="button"
                            disabled={archived || busy !== ""}
                            onClick={() =>
                                void mutate(
                                    "save",
                                    JSON.stringify(["save", working.draft_version, values]),
                                    (commandId) =>
                                        client.updateDraft(
                                            integrationId,
                                            {
                                                expected_draft_version: working.draft_version,
                                                public_configuration: values,
                                                probe_configuration: probeValues
                                            },
                                            commandId
                                        ),
                                    true
                                )
                            }
                        >
                            {busy === "save" ? "保存中…" : "保存草稿"}
                        </button>
                        <button
                            type="button"
                            className="button-secondary"
                            disabled={archived || busy !== ""}
                            onClick={() =>
                                void mutate(
                                    "publish",
                                    JSON.stringify(["publish", working.draft_version]),
                                    (commandId) =>
                                        client.publish(
                                            integrationId,
                                            working.draft_version,
                                            commandId
                                        ),
                                    true
                                )
                            }
                        >
                            {busy === "publish" ? "发布中…" : "发布 Revision"}
                        </button>
                        <button
                            type="button"
                            className="button-subtle"
                            disabled={archived || busy !== ""}
                            onClick={() =>
                                void mutate(
                                    "reset",
                                    JSON.stringify(["reset", working.draft_version]),
                                    (commandId) =>
                                        client.resetDraftContract(
                                            integrationId,
                                            working.draft_version,
                                            commandId
                                        ),
                                    true
                                )
                            }
                        >
                            重置契约
                        </button>
                    </div>
                </section>
                <aside className="configuration-view__probe" aria-label="连接测试与运行状态">
                    <section className="probe-panel">
                        <header className="probe-panel__head">
                            <h4>连接测试</h4>
                            {currentAttempt ? (
                                <span className="muted value">
                                    {String(probeDurationMs(currentAttempt))} ms ·{" "}
                                    {formatTimestamp(currentAttempt.completed_at)}
                                </span>
                            ) : null}
                        </header>
                        {support.canProbe ? (
                            <button
                                type="button"
                                className="button-secondary"
                                data-testid="probe-action"
                                disabled={
                                    archived ||
                                    model.current_revision_fingerprint === null ||
                                    busy !== ""
                                }
                                aria-description={probeReason === "" ? undefined : probeReason}
                                title={probeReason === "" ? undefined : probeReason}
                                onClick={() => {
                                    if (model.current_revision_fingerprint !== null)
                                        void mutate(
                                            "probe",
                                            JSON.stringify([
                                                "probe",
                                                model.current_revision_fingerprint
                                            ]),
                                            () =>
                                                client.probe(
                                                    integrationId,
                                                    model.current_revision_fingerprint ?? ""
                                                )
                                        );
                                }}
                            >
                                {busy === "probe" ? "测试中…" : "测试连接"}
                            </button>
                        ) : (
                            <p className={`probe-notice probe-notice--${support.tone}`}>
                                {support.notice}
                            </p>
                        )}
                        {probeReason !== "" && support.canProbe ? (
                            <p className="muted">{probeReason}</p>
                        ) : null}
                        <ProbeCheckList declared={declaredChecks} attempt={currentAttempt} />
                        {currentAttempt ? (
                            <p className="muted value">
                                尝试 {currentAttempt.probe_attempt_id} · 探测标的{" "}
                                {currentAttempt.probe_instrument ?? "—"}
                            </p>
                        ) : null}
                    </section>
                    <section className="inspector-facts" aria-label="运行状态">
                        <dl>
                            <dt>生命周期</dt>
                            <dd className="value">{model.lifecycle_state}</dd>
                            <dt>运行状态</dt>
                            <dd>
                                <span className="value">
                                    {operational.data?.status ?? "UNKNOWN"}
                                </span>{" "}
                                {presentation.label}
                            </dd>
                            <dt>当前 Revision</dt>
                            <dd className="value">
                                {model.current_revision_fingerprint ?? "未发布"}
                            </dd>
                            <dt>草稿版本</dt>
                            <dd className="value">{working.draft_version}</dd>
                            <dt>能力</dt>
                            <dd>
                                <CapabilityTags
                                    capabilities={working.type_descriptor.capabilities}
                                />
                            </dd>
                        </dl>
                    </section>
                    {!archived ? (
                        <section className="lifecycle-actions" aria-label="生命周期操作">
                            <button
                                type="button"
                                className="button-subtle"
                                disabled={busy !== "" || model.lifecycle_state === "ACTIVE"}
                                onClick={() =>
                                    void mutate(
                                        "lifecycle",
                                        JSON.stringify([
                                            "lifecycle",
                                            model.lifecycle_state,
                                            "ACTIVE"
                                        ]),
                                        (commandId) =>
                                            client.setLifecycle(
                                                integrationId,
                                                model.lifecycle_state,
                                                "ACTIVE",
                                                commandId
                                            )
                                    )
                                }
                            >
                                启用
                            </button>
                            <button
                                type="button"
                                className="button-subtle"
                                disabled={busy !== "" || model.lifecycle_state === "DISABLED"}
                                onClick={() =>
                                    void mutate(
                                        "lifecycle",
                                        JSON.stringify([
                                            "lifecycle",
                                            model.lifecycle_state,
                                            "DISABLED"
                                        ]),
                                        (commandId) =>
                                            client.setLifecycle(
                                                integrationId,
                                                model.lifecycle_state,
                                                "DISABLED",
                                                commandId
                                            )
                                    )
                                }
                            >
                                禁用
                            </button>
                            <button
                                type="button"
                                className="button-subtle"
                                disabled={busy !== ""}
                                onClick={() =>
                                    void mutate(
                                        "lifecycle",
                                        JSON.stringify([
                                            "lifecycle",
                                            model.lifecycle_state,
                                            "ARCHIVED"
                                        ]),
                                        (commandId) =>
                                            client.setLifecycle(
                                                integrationId,
                                                model.lifecycle_state,
                                                "ARCHIVED",
                                                commandId
                                            )
                                    )
                                }
                            >
                                归档（保留历史与凭据）
                            </button>
                        </section>
                    ) : null}
                </aside>
            </div>
            <section className="history-section">
                <h4>Probe 历史</h4>
                {attempts.data?.length ? (
                    <div className="table-scroll">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th scope="col">完成时间</th>
                                    <th scope="col">Revision</th>
                                    <th scope="col">状态</th>
                                    <th scope="col">探测标的</th>
                                    <th scope="col">耗时</th>
                                    <th scope="col">检查</th>
                                </tr>
                            </thead>
                            <tbody>
                                {attempts.data.map((attempt) => (
                                    <tr key={attempt.probe_attempt_id}>
                                        <td className="value">
                                            {formatTimestamp(attempt.completed_at)}
                                        </td>
                                        <td className="value">
                                            {shortFingerprint(attempt.revision_fingerprint)}
                                        </td>
                                        <td>{attempt.overall_status}</td>
                                        <td>{attempt.probe_instrument ?? "—"}</td>
                                        <td className="value">
                                            {String(probeDurationMs(attempt))} ms
                                        </td>
                                        <td>
                                            <button
                                                type="button"
                                                className="button-subtle"
                                                onClick={() => {
                                                    setSelectedAttemptId(attempt.probe_attempt_id);
                                                }}
                                            >
                                                查看
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <p className="muted">尚无 Probe Attempt。</p>
                )}
                {selectedAttempt.data ? (
                    <div aria-label="精确 Probe Attempt">
                        <p className="muted value">
                            {selectedAttempt.data.probe_attempt_id} ·{" "}
                            {selectedAttempt.data.overall_status} ·{" "}
                            {selectedAttempt.data.probe_instrument ?? "—"}
                        </p>
                        <ProbeCheckList declared={declaredChecks} attempt={selectedAttempt.data} />
                    </div>
                ) : null}
            </section>
            <section className="history-section">
                <h4>Revision 历史</h4>
                {revisions.data?.length ? (
                    <ul className="plain-list">
                        {revisions.data.map((revision) => (
                            <li key={revision.revision_fingerprint}>
                                <span className="value">
                                    {shortFingerprint(revision.revision_fingerprint)}
                                </span>
                                <span>
                                    R{revision.revision_sequence} ·{" "}
                                    {formatTimestamp(revision.created_at)}
                                </span>
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p className="muted">尚无已发布 Revision。</p>
                )}
            </section>
        </div>
    );
}
