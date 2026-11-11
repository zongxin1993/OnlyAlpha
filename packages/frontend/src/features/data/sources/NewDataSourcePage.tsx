import { PageHeader } from "../../../app/shell/PageHeader";
import { DataSourceManager } from "./DataSourceManager";

/** Deep-link shell that opens the shared Manager on the Add Data Source tab. */
export function NewDataSourcePage() {
    return (
        <div className="page-with-head">
            <PageHeader title="数据" subtitle="数据源接入与授权" />
            <main className="page data-sources-page" aria-label="数据源">
                <DataSourceManager variant="page" initialTab="add" />
            </main>
        </div>
    );
}
