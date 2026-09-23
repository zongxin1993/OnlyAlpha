import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useIntegrationApi } from "../../../app/providers";
import type { IntegrationSummary } from "../../../api/integrations/model";

const short = (value: string | null | undefined) => value?.slice(0, 10) ?? "—";

function DataSourceRow({ item }: { readonly item: IntegrationSummary }) {
    const client = useIntegrationApi();
    const operational = useQuery({
        queryKey: ["integrations", item.integration_id, "operational-status"],
        queryFn: ({ signal }) => client.getOperationalStatus(item.integration_id, signal)
    });
    return (
        <tr>
            <td>
                <Link to={`/data/sources/${item.integration_id}`}>{item.display_name}</Link>
            </td>
            <td>{item.type_id}</td>
            <td>{item.lifecycle_state}</td>
            <td>
                <code>{short(item.current_revision_fingerprint)}</code>
            </td>
            <td>
                {operational.data?.status ?? (operational.isPending ? "Loading…" : "Unavailable")}
            </td>
            <td>{operational.data?.checked_at ?? "Never"}</td>
        </tr>
    );
}

export function DataSourcesPage() {
    const client = useIntegrationApi();
    const integrations = useQuery({
        queryKey: ["integrations", "data-sources"],
        queryFn: ({ signal }) => client.listDataSources(signal)
    });
    return (
        <main className="page data-sources-page">
            <header className="workspace-header">
                <div>
                    <h1>Data Sources</h1>
                    <p className="lede">
                        Published provider configuration and exact-revision operational
                        observations.
                    </p>
                </div>
                <Link className="button-link" to="/data/sources/new">
                    Add Data Source
                </Link>
            </header>
            {integrations.isPending ? (
                <p role="status">Loading Data Sources…</p>
            ) : integrations.isError ? (
                <p role="alert">Unable to load Data Sources.</p>
            ) : integrations.data.length === 0 ? (
                <p>No Data Sources are configured.</p>
            ) : (
                <div className="table-scroll">
                    <table>
                        <thead>
                            <tr>
                                <th>Display Name</th>
                                <th>Provider / Type</th>
                                <th>Lifecycle</th>
                                <th>Current Revision</th>
                                <th>Operational Status</th>
                                <th>Last Probe Time</th>
                            </tr>
                        </thead>
                        <tbody>
                            {integrations.data.map((item) => (
                                <DataSourceRow key={item.integration_id} item={item} />
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </main>
    );
}
