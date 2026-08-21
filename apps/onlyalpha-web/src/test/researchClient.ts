import type { ResearchApiClient } from "../api/research/client";

const unused = (): Promise<never> => Promise.reject(new Error("unused Research API method"));

export function researchClient(overrides: Partial<ResearchApiClient> = {}): ResearchApiClient {
    return {
        submitRun: unused,
        getRun: unused,
        listRuns: unused,
        cancelRun: unused,
        getArtifactSummary: unused,
        getStatisticsCatalog: unused,
        getStatisticSeries: unused,
        getCandidateCatalog: unused,
        getPublishedSeriesCatalog: unused,
        getMarketSeries: unused,
        getCandidateGraph: unused,
        getVariableSeries: unused,
        getSignalSeries: unused,
        getCalculationCatalog: unused,
        getUniverseCatalog: unused,
        getStatisticsCapabilityCatalog: unused,
        getDatasetFieldCatalog: unused,
        resolveDefinition: unused,
        ...overrides
    };
}
