import { DataSourceManager } from "./DataSourceManager";

/** Deep-link shell for the shared Data Source Manager surface. */
export function DataSourcesPage() {
    return (
        <main className="page data-sources-page" aria-label="数据源">
            <DataSourceManager variant="page" />
        </main>
    );
}
