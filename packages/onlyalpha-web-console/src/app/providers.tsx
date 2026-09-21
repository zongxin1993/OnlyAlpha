import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useState, type ReactNode } from "react";
import { FetchIntegrationApiClient, type IntegrationApiClient } from "../api/integrations/client";
import { FetchResearchApiClient, type ResearchApiClient } from "../api/research/client";

const ResearchApiContext = createContext<ResearchApiClient | null>(null);
const IntegrationApiContext = createContext<IntegrationApiClient | null>(null);

export function useResearchApi(): ResearchApiClient {
    const client = useContext(ResearchApiContext);
    if (client === null) throw new Error("Research API provider is missing");
    return client;
}

export function useIntegrationApi(): IntegrationApiClient {
    const client = useContext(IntegrationApiContext);
    if (client === null) throw new Error("Integration API provider is missing");
    return client;
}

export function AppProviders({
    children,
    client,
    integrationClient
}: {
    readonly children: ReactNode;
    readonly client?: ResearchApiClient;
    readonly integrationClient?: IntegrationApiClient;
}) {
    const [queryClient] = useState(
        () =>
            new QueryClient({
                defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } }
            })
    );
    const [apiClient] = useState<ResearchApiClient>(() => client ?? new FetchResearchApiClient());
    const [integrationApiClient] = useState<IntegrationApiClient>(
        () => integrationClient ?? new FetchIntegrationApiClient()
    );
    return (
        <ResearchApiContext value={apiClient}>
            <IntegrationApiContext value={integrationApiClient}>
                <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
            </IntegrationApiContext>
        </ResearchApiContext>
    );
}
