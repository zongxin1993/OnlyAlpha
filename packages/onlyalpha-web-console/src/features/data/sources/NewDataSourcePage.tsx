import { DataSourceManager } from "./DataSourceManager";

/** Deep-link shell that opens the shared Manager on the Add Data Source tab. */
export function NewDataSourcePage() {
    return (
        <main className="page data-sources-page" aria-label="数据源">
            <DataSourceManager variant="page" initialTab="add" />
        </main>
    );
}
