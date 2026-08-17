import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useState, type ReactNode } from "react";
import { FetchResearchApiClient, type ResearchApiClient } from "../api/research/client";

const ResearchApiContext = createContext<ResearchApiClient | null>(null);

export function useResearchApi(): ResearchApiClient {
    const client = useContext(ResearchApiContext);
    if (client === null) throw new Error("Research API provider is missing");
    return client;
}

export function AppProviders({
    children,
    client
}: {
    readonly children: ReactNode;
    readonly client?: ResearchApiClient;
}) {
    const [queryClient] = useState(
        () =>
            new QueryClient({
                defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } }
            })
    );
    const [apiClient] = useState<ResearchApiClient>(() => client ?? new FetchResearchApiClient());
    return (
        <ResearchApiContext value={apiClient}>
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        </ResearchApiContext>
    );
}
