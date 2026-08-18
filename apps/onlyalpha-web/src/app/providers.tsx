import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useState, type ReactNode } from "react";
import { FetchResearchApiClient, type ResearchArtifactApiClient } from "../api/research/client";

const ResearchApiContext = createContext<ResearchArtifactApiClient | null>(null);

export function useResearchApi(): ResearchArtifactApiClient {
    const client = useContext(ResearchApiContext);
    if (client === null) throw new Error("Research API provider is missing");
    return client;
}

export function AppProviders({
    children,
    client
}: {
    readonly children: ReactNode;
    readonly client?: ResearchArtifactApiClient;
}) {
    const [queryClient] = useState(
        () =>
            new QueryClient({
                defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } }
            })
    );
    const [apiClient] = useState<ResearchArtifactApiClient>(
        () => client ?? new FetchResearchApiClient()
    );
    return (
        <ResearchApiContext value={apiClient}>
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        </ResearchApiContext>
    );
}
