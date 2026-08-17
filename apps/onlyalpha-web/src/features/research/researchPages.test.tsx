import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import type { ResearchApiClient, StatisticSeriesRequest } from "../../api/research/client";
import { ResearchWebError } from "../../api/research/errors";
import { AppProviders } from "../../app/providers";
import { parseDecimalText } from "../../domain/research/decimal";
import {
    parseResearchResultFingerprint,
    parseStatisticsFingerprint
} from "../../domain/research/identity";
import type {
    ResearchArtifactSummary,
    ResearchStatisticsCatalog
} from "../../domain/research/model";
import { parseUnixNanoseconds } from "../../domain/research/time";
import { ArtifactOverviewPage } from "./artifact/ArtifactOverviewPage";
import { ResearchOpenPage } from "./open/ResearchOpenPage";
import { StatisticsDetailPage } from "./statistics/StatisticsDetailPage";

vi.mock("../../charts/lightweight/ResearchSeriesChart", () => ({
    ResearchSeriesChart: () => <div data-testid="research-chart">chart</div>
}));

const result = parseResearchResultFingerprint("a".repeat(64));
const statistics = parseStatisticsFingerprint("b".repeat(64));
const summary: ResearchArtifactSummary = {
    researchResultFingerprint: result,
    researchResultPlanFingerprint: "c".repeat(64),
    researchResultContentFingerprint: "d".repeat(64),
    datasetSnapshotFingerprint: "e".repeat(64),
    artifactContentFingerprint: "f".repeat(64),
    researchResultSchemaVersion: 1,
    artifactProfile: "research-statistics-v1",
    artifactSchemaVersion: 1,
    statisticsCount: 1,
    rowCount: 2,
    createdAt: "2026-08-16T00:00:00Z"
};
const catalog: ResearchStatisticsCatalog = {
    researchResultFingerprint: result,
    statistics: [
        {
            statisticsFingerprint: statistics,
            statisticsResultFingerprint: "1".repeat(64),
            resultContentFingerprint: "2".repeat(64),
            statisticsResultSchemaVersion: 1,
            rowCount: 2,
            feature: {
                calculationFingerprint: "3".repeat(64),
                nodeFingerprint: "4".repeat(64),
                outputName: "score"
            },
            target: {
                calculationFingerprint: "5".repeat(64),
                nodeFingerprint: "6".repeat(64),
                outputName: "forward_return"
            },
            definition: {
                method: "INFORMATION_COEFFICIENT",
                minimumObservations: 2,
                pairingPolicy: "PAIRWISE_COMPLETE",
                universePolicy: "EXACT_INTERSECTION",
                rankTieMethod: "AVERAGE",
                weighting: "EQUAL",
                numeric: {
                    representation: "DECIMAL",
                    precision: 38,
                    outputQuantum: parseDecimalText("0.000000000001"),
                    rounding: "ROUND_HALF_EVEN"
                }
            }
        }
    ]
};

class SuccessClient implements ResearchApiClient {
    getArtifactSummary() {
        return Promise.resolve(summary);
    }
    getStatisticsCatalog() {
        return Promise.resolve(catalog);
    }
    getStatisticSeries(request: StatisticSeriesRequest) {
        const second = request.afterTsEventNs !== undefined;
        return Promise.resolve({
            researchResultFingerprint: result,
            statisticsFingerprint: statistics,
            points: [
                {
                    tsEventNs: parseUnixNanoseconds(second ? "2000000000" : "1000000000"),
                    statisticValue: second ? null : parseDecimalText("0.25"),
                    sampleCount: 3,
                    status: "OK"
                }
            ],
            hasMore: !second,
            nextAfterTsEventNs: second ? null : parseUnixNanoseconds("1000000000")
        });
    }
}

function renderRoute(
    path: string,
    element: React.ReactNode,
    client: ResearchApiClient = new SuccessClient()
) {
    const router = createMemoryRouter(
        [
            {
                path: "/research/:researchResultFingerprint/statistics/:statisticsFingerprint",
                element
            },
            { path: "/research/:researchResultFingerprint", element },
            { path: "/research", element }
        ],
        { initialEntries: [path] }
    );
    return render(
        <AppProviders client={client}>
            <RouterProvider router={router} />
        </AppProviders>
    );
}

it("validates fingerprint locally and navigates by URL", async () => {
    const router = createMemoryRouter(
        [
            { path: "/research", element: <ResearchOpenPage /> },
            { path: "/research/:researchResultFingerprint", element: <p>opened exact result</p> }
        ],
        { initialEntries: ["/research"] }
    );
    render(
        <AppProviders client={new SuccessClient()}>
            <RouterProvider router={router} />
        </AppProviders>
    );
    const input = screen.getByLabelText("Research Result fingerprint");
    await userEvent.type(input, "BAD");
    await userEvent.click(screen.getByRole("button", { name: "Open exact result" }));
    expect(screen.getByRole("alert")).toHaveTextContent("lower-case SHA256");
    await userEvent.clear(input);
    await userEvent.type(input, result);
    await userEvent.click(screen.getByRole("button", { name: "Open exact result" }));
    expect(await screen.findByText("opened exact result")).toBeInTheDocument();
});

it("renders summary and exact Statistics catalog", async () => {
    renderRoute(`/research/${result}`, <ArtifactOverviewPage />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(await screen.findByRole("heading", { name: "Artifact overview" })).toBeInTheDocument();
    expect(screen.getByText(result)).toBeInTheDocument();
    expect(screen.getByText("INFORMATION_COEFFICIENT")).toBeInTheDocument();
});

it("renders exact table, chart, and manually loads another page", async () => {
    renderRoute(`/research/${result}/statistics/${statistics}`, <StatisticsDetailPage />);
    expect(await screen.findByTestId("research-chart")).toBeInTheDocument();
    expect(screen.getByText("1000000000")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() => {
        expect(screen.getByText("2000000000")).toBeInTheDocument();
    });
    expect(screen.getByText("NULL")).toBeInTheDocument();
    expect(screen.getByText("2 / 2")).toBeInTheDocument();
});

it("shows corrupt authority explicitly with user-triggered retry", async () => {
    const client = new SuccessClient();
    client.getArtifactSummary = () =>
        Promise.reject(
            new ResearchWebError("RESEARCH_ARTIFACT_CORRUPT", "verification failed", 500)
        );
    renderRoute(`/research/${result}`, <ArtifactOverviewPage />, client);
    expect(await screen.findByRole("alert")).toHaveTextContent("RESEARCH_ARTIFACT_CORRUPT");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});
