import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useState, useSyncExternalStore, type ReactNode } from "react";
import { LocalReadCredentials } from "../api/marketData/localReadCredentials";
import { FetchIntegrationApiClient, type IntegrationApiClient } from "../api/integrations/client";
import { FetchMarketDataApiClient, type MarketDataApiClient } from "../api/marketData/client";
import { FetchResearchApiClient, type ResearchApiClient } from "../api/research/client";

const ResearchApiContext = createContext<ResearchApiClient | null>(null);
const IntegrationApiContext = createContext<IntegrationApiClient | null>(null);
const MarketDataApiContext = createContext<MarketDataApiClient | null>(null);
const LocalReadCredentialsContext = createContext<LocalReadCredentials | null>(null);

export function useLocalReadCredentials(): LocalReadCredentials {
    const value = useContext(LocalReadCredentialsContext);
    if (value === null) throw new Error("Local read credentials provider is missing");
    return value;
}

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

export function useMarketDataApi(): MarketDataApiClient {
    const client = useContext(MarketDataApiContext);
    if (client === null) throw new Error("Market Data API provider is missing");
    return client;
}

export function AppProviders({
    children,
    client,
    integrationClient,
    marketDataClient
}: {
    readonly children: ReactNode;
    readonly client?: ResearchApiClient;
    readonly integrationClient?: IntegrationApiClient;
    readonly marketDataClient?: MarketDataApiClient;
}) {
    const [credentials] = useState(
        () => new LocalReadCredentials(import.meta.env.VITE_ONLYALPHA_LOCAL_SESSION === "true")
    );
    const authGeneration = useSyncExternalStore(credentials.subscribe, credentials.getGeneration);
    const [apiClient] = useState<ResearchApiClient>(() => client ?? new FetchResearchApiClient());
    const [integrationApiClient] = useState<IntegrationApiClient>(
        () => integrationClient ?? new FetchIntegrationApiClient()
    );
    const [marketDataApiClient] = useState<MarketDataApiClient>(
        () => marketDataClient ?? new FetchMarketDataApiClient(credentials)
    );
    return (
        <ResearchApiContext value={apiClient}>
            <IntegrationApiContext value={integrationApiClient}>
                <MarketDataApiContext value={marketDataApiClient}>
                    <LocalReadCredentialsContext value={credentials}>
                        <SessionQueries key={authGeneration}>{children}</SessionQueries>
                    </LocalReadCredentialsContext>
                </MarketDataApiContext>
            </IntegrationApiContext>
        </ResearchApiContext>
    );
}

// A changed authentication generation discards both cached queries and old presentation state.
function SessionQueries({ children }: { readonly children: ReactNode }) {
    const [client] = useState(
        () =>
            new QueryClient({
                defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } }
            })
    );
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
