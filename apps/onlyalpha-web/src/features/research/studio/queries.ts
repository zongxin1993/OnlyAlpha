import { queryOptions } from "@tanstack/react-query";
import type { ResearchApiClient } from "../../../api/research/client";

export const studioQueryKeys = {
    calculations: ["research", "studio", "calculations"] as const,
    universes: ["research", "studio", "universes"] as const,
    statistics: ["research", "studio", "statistics"] as const,
    datasetFields: ["research", "studio", "dataset-fields"] as const
};

export const calculationCatalogOptions = (client: ResearchApiClient) =>
    queryOptions({
        queryKey: studioQueryKeys.calculations,
        queryFn: ({ signal }) => client.getCalculationCatalog(signal),
        staleTime: Number.POSITIVE_INFINITY
    });
export const universeCatalogOptions = (client: ResearchApiClient) =>
    queryOptions({
        queryKey: studioQueryKeys.universes,
        queryFn: ({ signal }) => client.getUniverseCatalog(signal),
        staleTime: Number.POSITIVE_INFINITY
    });
export const statisticsCapabilityOptions = (client: ResearchApiClient) =>
    queryOptions({
        queryKey: studioQueryKeys.statistics,
        queryFn: ({ signal }) => client.getStatisticsCapabilityCatalog(signal),
        staleTime: Number.POSITIVE_INFINITY
    });
export const datasetFieldOptions = (client: ResearchApiClient) =>
    queryOptions({
        queryKey: studioQueryKeys.datasetFields,
        queryFn: ({ signal }) => client.getDatasetFieldCatalog(signal),
        staleTime: Number.POSITIVE_INFINITY
    });
