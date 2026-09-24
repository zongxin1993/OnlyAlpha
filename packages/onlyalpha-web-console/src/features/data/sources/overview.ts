import { useQueries, useQuery } from "@tanstack/react-query";
import type {
    IntegrationOperationalStatus,
    IntegrationSummary,
    IntegrationType
} from "../../../api/integrations/model";
import { useIntegrationApi } from "../../../app/providers";
import { summarizeSources, type SourceSummary } from "./status";

export interface DataSourceOverview {
    readonly sources: readonly IntegrationSummary[];
    readonly types: readonly IntegrationType[];
    readonly operational: ReadonlyMap<string, IntegrationOperationalStatus>;
    readonly summary: SourceSummary;
    readonly pending: boolean;
    readonly failed: boolean;
}

/**
 * Composed from existing formal Product API reads: there is no aggregate endpoint, and
 * this task does not add one. Request count stays bounded by the configured source count.
 */
export function useDataSourceOverview(): DataSourceOverview {
    const client = useIntegrationApi();
    const sources = useQuery({
        queryKey: ["integrations", "data-sources"],
        queryFn: ({ signal }) => client.listDataSources(signal)
    });
    const types = useQuery({
        queryKey: ["integration-types", "DATA_SOURCE"],
        queryFn: ({ signal }) => client.listTypes(signal)
    });
    const list = sources.data ?? [];
    const statuses = useQueries({
        queries: list.map((item) => ({
            queryKey: ["integrations", item.integration_id, "operational-status"],
            queryFn: ({ signal }: { signal: AbortSignal }) =>
                client.getOperationalStatus(item.integration_id, signal)
        }))
    });
    const operational = new Map<string, IntegrationOperationalStatus>();
    list.forEach((item, index) => {
        const value = statuses[index]?.data;
        if (value !== undefined) operational.set(item.integration_id, value);
    });
    return {
        sources: list,
        types: types.data ?? [],
        operational,
        summary: summarizeSources(
            list.map((item) => ({
                lifecycle_state: item.lifecycle_state,
                status: operational.get(item.integration_id)?.status
            }))
        ),
        pending: sources.isPending || types.isPending,
        failed: sources.isError || types.isError
    };
}

export function typeDescriptor(
    types: readonly IntegrationType[],
    typeId: string
): IntegrationType | undefined {
    return types.find((item) => item.type_id === typeId);
}
