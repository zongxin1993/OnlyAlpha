import { useParams } from "react-router-dom";
import { DataSourceManager } from "./DataSourceManager";

/** Deep-link shell that opens the shared Manager on one configured Integration. */
export function DataSourceDetailPage() {
    const { integrationId = "" } = useParams();
    return (
        <main className="page data-sources-page" aria-label="数据源">
            <DataSourceManager variant="page" initialIntegrationId={integrationId} />
        </main>
    );
}
