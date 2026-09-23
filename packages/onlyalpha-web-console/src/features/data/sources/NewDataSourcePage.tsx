import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { isIndeterminateMutationError } from "../../../api/integrations/client";
import { createUuidV4, MutationSubmissionIntent } from "../../../api/integrations/submissionIntent";
import { useIntegrationApi } from "../../../app/providers";

export function NewDataSourcePage() {
    const client = useIntegrationApi();
    const navigate = useNavigate();
    const types = useQuery({
        queryKey: ["integration-types", "DATA_SOURCE"],
        queryFn: ({ signal }) => client.listTypes(signal)
    });
    const [typeId, setTypeId] = useState("");
    const [displayName, setDisplayName] = useState("");
    const [error, setError] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const intent = useRef(new MutationSubmissionIntent());
    const pending = useRef<{ readonly key: string; readonly integrationId: string } | null>(null);
    return (
        <main className="page narrow">
            <h1>Add Data Source</h1>
            <p className="lede">
                Choose a server-published DataSource type. Configuration follows its declared
                contract.
            </p>
            {types.isPending ? (
                <p role="status">Loading Integration Types…</p>
            ) : types.isError ? (
                <p role="alert">Unable to load Integration Types.</p>
            ) : (
                <form
                    aria-label="Add Data Source"
                    onSubmit={(event) => {
                        event.preventDefault();
                        const key = JSON.stringify({ typeId, displayName });
                        if (pending.current !== null && pending.current.key !== key) {
                            intent.current.definitive(pending.current.key);
                        }
                        const integrationId =
                            pending.current?.key === key
                                ? pending.current.integrationId
                                : createUuidV4();
                        pending.current = { key, integrationId };
                        const commandId = intent.current.commandFor(key);
                        setSubmitting(true);
                        setError("");
                        void client
                            .createIntegration(
                                {
                                    integration_id: integrationId,
                                    type_id: typeId,
                                    display_name: displayName
                                },
                                commandId
                            )
                            .then(() => {
                                intent.current.definitive(key);
                                pending.current = null;
                                void navigate(`/data/sources/${integrationId}`);
                            })
                            .catch((value: unknown) => {
                                if (!isIndeterminateMutationError(value)) {
                                    intent.current.definitive(key);
                                    pending.current = null;
                                }
                                setError(value instanceof Error ? value.message : "Create failed");
                            })
                            .finally(() => {
                                setSubmitting(false);
                            });
                    }}
                >
                    <label>
                        Data Source type
                        <select
                            value={typeId}
                            required
                            onChange={(event) => {
                                setTypeId(event.target.value);
                            }}
                        >
                            <option value="">Select…</option>
                            {types.data.map((item) => (
                                <option key={item.type_id} value={item.type_id}>
                                    {item.display_name} · {item.provider_id}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label>
                        Display name
                        <input
                            value={displayName}
                            required
                            onChange={(event) => {
                                setDisplayName(event.target.value);
                            }}
                        />
                    </label>
                    {error ? <p role="alert">{error}</p> : null}
                    <div className="workspace-actions">
                        <button disabled={submitting}>
                            {submitting ? "Creating…" : "Create Data Source"}
                        </button>
                        <Link to="/data/sources">Cancel</Link>
                    </div>
                </form>
            )}
        </main>
    );
}
