import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useState, useSyncExternalStore, type ReactNode } from "react";
import { LocalReadCredentials } from "../api/marketData/localReadCredentials";
import { FetchIntegrationApiClient, type IntegrationApiClient } from "../api/integrations/client";
import { FetchMarketDataApiClient, type MarketDataApiClient } from "../api/marketData/client";

const IntegrationApiContext = createContext<IntegrationApiClient | null>(null);
const MarketDataApiContext = createContext<MarketDataApiClient | null>(null);
const LocalReadCredentialsContext = createContext<LocalReadCredentials | null>(null);

export function useLocalReadCredentials(): LocalReadCredentials {
    const value = useContext(LocalReadCredentialsContext);
    if (value === null) throw new Error("Local read credentials provider is missing");
    return value;
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
    integrationClient,
    marketDataClient
}: {
    readonly children: ReactNode;
    readonly integrationClient?: IntegrationApiClient;
    readonly marketDataClient?: MarketDataApiClient;
}) {
    const [credentials] = useState(
        () => new LocalReadCredentials(import.meta.env.VITE_ONLYALPHA_LOCAL_SESSION === "true")
    );
    const authGeneration = useSyncExternalStore(credentials.subscribe, credentials.getGeneration);
    const [integrationApiClient] = useState<IntegrationApiClient>(
        () => integrationClient ?? new FetchIntegrationApiClient()
    );
    const [marketDataApiClient] = useState<MarketDataApiClient>(
        () => marketDataClient ?? new FetchMarketDataApiClient(credentials)
    );
    return (
        <IntegrationApiContext value={integrationApiClient}>
            <MarketDataApiContext value={marketDataApiClient}>
                <LocalReadCredentialsContext value={credentials}>
                    <SessionQueries key={authGeneration}>{children}</SessionQueries>
                </LocalReadCredentialsContext>
            </MarketDataApiContext>
        </IntegrationApiContext>
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
