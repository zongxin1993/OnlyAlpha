import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
    IntegrationWebError,
    isIndeterminateMutationError
} from "../../../api/integrations/client";
import { MutationSubmissionIntent } from "../../../api/integrations/submissionIntent";
import { useIntegrationApi } from "../../../app/providers";
import { IntegrationConfigurationForm } from "./IntegrationConfigurationForm";

const short = (value: string | null | undefined) => value?.slice(0, 12) ?? "—";

export function DataSourceDetailPage() {
    const { integrationId = "" } = useParams();
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
    const [selectedAttemptId, setSelectedAttemptId] = useState<string | null>(null);
    const selectedAttempt = useQuery({
        queryKey: ["integrations", integrationId, "probe-attempts", selectedAttemptId],
        queryFn: ({ signal }) =>
            client.getProbeAttempt(integrationId, selectedAttemptId ?? "", signal),
        enabled: selectedAttemptId !== null
    });
    const [valueEdits, setValueEdits] = useState<Record<string, unknown> | null>(null);
    const [probeEdits, setProbeEdits] = useState<Record<string, unknown> | null | undefined>();
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
        rethrowTransport = false,
        resetEdits = false
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
                value instanceof IntegrationWebError
                    ? `${value.code}: ${value.message}`
                    : "Integration request failed"
            );
            if (unknownOutcome && rethrowTransport) throw value;
        } finally {
            setBusy("");
        }
    };
    if (integration.isPending || draft.isPending)
        return (
            <main className="page">
                <p role="status">Loading Data Source…</p>
            </main>
        );
    if (integration.isError || draft.isError)
        return (
            <main className="page">
                <p role="alert">Unable to load Data Source.</p>
            </main>
        );
    const model = integration.data;
    const working = draft.data;
    const values = valueEdits ?? working.public_configuration;
    const probeValues = probeEdits === undefined ? working.probe_configuration : probeEdits;
    const editedInstrument = probeValues?.instrument;
    const probeInstrument =
        typeof editedInstrument === "string"
            ? editedInstrument
            : (working.type_descriptor.probe_contract?.default_probe_instrument ?? "");
    const currentAttempt = attempts.data?.find(
        (attempt) => attempt.revision_fingerprint === model.current_revision_fingerprint
    );
    return (
        <main className="page data-source-detail">
            <header className="workspace-header">
                <div>
                    <p className="eyebrow">Data Source · {model.type_id}</p>
                    <h1>{model.display_name}</h1>
                    <p className="lede">
                        Published Revision and Working Draft remain separate authorities.
                    </p>
                </div>
                <Link to="/data/sources">← Data Sources</Link>
            </header>
            {error ? (
                <p
                    className={
                        error.includes("CONFLICT") || error.includes("TYPE_CHANGED")
                            ? "warning"
                            : "error"
                    }
                    role="alert"
                >
                    {error}
                    {error.includes("INTEGRATION_TYPE_CHANGED")
                        ? " Existing Draft was preserved. Use Contract Reset explicitly."
                        : ""}
                </p>
            ) : null}
            {archived ? (
                <p className="warning">
                    Archived Integration is read-only. Historical revisions and Probe Attempts
                    remain available.
                </p>
            ) : null}
            <div className="data-source-layout">
                <section className="builder-section" aria-labelledby="working-draft">
                    <div className="builder-title">
                        <span>01</span>
                        <h2 id="working-draft">Working Draft</h2>
                    </div>
                    <p>
                        Draft version {working.draft_version} · contract{" "}
                        <code>{short(working.pinned_type_descriptor_fingerprint)}</code>
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
                            Probe instrument
                            <input
                                value={probeInstrument}
                                disabled={archived}
                                onChange={(event) => {
                                    setProbeEdits({ instrument: event.target.value });
                                }}
                            />
                        </label>
                    ) : null}
                    <div className="workspace-actions">
                        <button
                            type="button"
                            disabled={archived || Boolean(busy)}
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
                                    false,
                                    true
                                )
                            }
                        >
                            {busy === "save" ? "Saving…" : "Save Draft"}
                        </button>
                        <button
                            type="button"
                            className="button-secondary"
                            disabled={archived || Boolean(busy)}
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
                                    false,
                                    true
                                )
                            }
                        >
                            {busy === "publish" ? "Publishing…" : "Publish"}
                        </button>
                        <button
                            type="button"
                            className="button-subtle"
                            disabled={archived || Boolean(busy)}
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
                                    false,
                                    true
                                )
                            }
                        >
                            Contract Reset
                        </button>
                    </div>
                </section>
                <aside className="context-inspector" aria-label="Operational inspector">
                    <h2>Operational inspector</h2>
                    <dl className="inspector-facts">
                        <dt>Lifecycle</dt>
                        <dd>{model.lifecycle_state}</dd>
                        <dt>Current Revision</dt>
                        <dd>{model.current_revision_fingerprint ?? "Not published"}</dd>
                        <dt>Draft Version</dt>
                        <dd>{working.draft_version}</dd>
                        <dt>Operational Status</dt>
                        <dd>{operational.data?.status ?? "UNKNOWN"}</dd>
                        <dt>Revision scope</dt>
                        <dd>{short(operational.data?.revision_fingerprint)}</dd>
                        <dt>Last checked</dt>
                        <dd>{operational.data?.checked_at ?? "Not tested"}</dd>
                        <dt>Probe instrument</dt>
                        <dd>{currentAttempt?.probe_instrument ?? "—"}</dd>
                    </dl>
                    {operational.data?.probe_supported ? (
                        <button
                            type="button"
                            disabled={
                                archived || !model.current_revision_fingerprint || busy === "probe"
                            }
                            onClick={() => {
                                if (model.current_revision_fingerprint)
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
                            {busy === "probe" ? "Testing…" : "Test connection"}
                        </button>
                    ) : (
                        <p>Probe unavailable for this provider</p>
                    )}
                    {currentAttempt ? (
                        <ul className="plain-list" aria-label="Latest Probe checks">
                            {currentAttempt.checks.map((check) => (
                                <li key={check.check}>
                                    {check.check.replaceAll("_", " ")}
                                    <span>{check.status}</span>
                                </li>
                            ))}
                        </ul>
                    ) : null}
                    {!archived ? (
                        <div className="workspace-actions lifecycle-actions">
                            <button
                                type="button"
                                className="button-subtle"
                                disabled={Boolean(busy) || model.lifecycle_state === "ACTIVE"}
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
                                Activate
                            </button>
                            <button
                                type="button"
                                className="button-subtle"
                                disabled={Boolean(busy) || model.lifecycle_state === "DISABLED"}
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
                                Disable
                            </button>
                            <button
                                type="button"
                                className="button-danger"
                                disabled={Boolean(busy)}
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
                                Archive
                            </button>
                        </div>
                    ) : null}
                </aside>
            </div>
            <section className="exact-section">
                <h2>Probe history</h2>
                {attempts.data?.length ? (
                    <div className="table-scroll">
                        <table>
                            <thead>
                                <tr>
                                    <th>Attempt time</th>
                                    <th>Revision</th>
                                    <th>Status</th>
                                    <th>Instrument</th>
                                    <th>Duration</th>
                                    <th>Details</th>
                                </tr>
                            </thead>
                            <tbody>
                                {attempts.data.map((attempt) => (
                                    <tr key={attempt.probe_attempt_id}>
                                        <td>{attempt.completed_at}</td>
                                        <td>
                                            <code>{short(attempt.revision_fingerprint)}</code>
                                        </td>
                                        <td>{attempt.overall_status}</td>
                                        <td>{attempt.probe_instrument ?? "—"}</td>
                                        <td>
                                            {new Date(attempt.completed_at).getTime() -
                                                new Date(attempt.started_at).getTime()}{" "}
                                            ms
                                        </td>
                                        <td>
                                            <button
                                                type="button"
                                                className="button-subtle"
                                                onClick={() => {
                                                    setSelectedAttemptId(attempt.probe_attempt_id);
                                                }}
                                            >
                                                Inspect
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <p>No Probe Attempts.</p>
                )}
                {selectedAttempt.data ? (
                    <div aria-label="Exact Probe Attempt">
                        <h3>Exact Probe Attempt</h3>
                        <p>
                            Attempt <code>{selectedAttempt.data.probe_attempt_id}</code>
                        </p>
                        <ul className="plain-list">
                            {selectedAttempt.data.checks.map((check) => (
                                <li key={check.check}>
                                    {check.check.replaceAll("_", " ")}
                                    <span>{check.status}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                ) : null}
            </section>
            <section className="exact-section">
                <h2>Revision history</h2>
                {revisions.data?.length ? (
                    <ul className="plain-list">
                        {revisions.data.map((revision) => (
                            <li key={revision.revision_fingerprint}>
                                <code>{short(revision.revision_fingerprint)}</code>
                                <span>
                                    R{revision.revision_sequence} · {revision.created_at}
                                </span>
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p>No published Revisions.</p>
                )}
            </section>
        </main>
    );
}
