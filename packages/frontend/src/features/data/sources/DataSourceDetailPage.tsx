import { useParams } from "react-router-dom";
import { PageHeader } from "../../../app/shell/PageHeader";
import { DataSourceManager } from "./DataSourceManager";

/** Deep-link shell that opens the shared Manager on one configured Integration. */
export function DataSourceDetailPage() {
    const { integrationId = "" } = useParams();
    return (
        <div className="page-with-head">
            <PageHeader title="数据" subtitle="数据源接入与授权" />
            <main className="page data-sources-page" aria-label="数据源">
                <DataSourceManager variant="page" initialIntegrationId={integrationId} />
            </main>
        </div>
    );
}
