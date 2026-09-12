import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import type { ResearchApiClient } from "../../../api/research/client";
import { ResearchWebError } from "../../../api/research/errors";
import { AppProviders } from "../../../app/providers";
import { parseDecimalText } from "../../../domain/research/decimal";
import {
    parseResearchResultFingerprint,
    parseResearchRunId,
    parseStatisticsFingerprint
} from "../../../domain/research/identity";
import type {
    ResearchArtifactSummary,
    ResearchRunSummary,
    ResearchStatisticsDescriptor
} from "../../../domain/research/model";
import { parseUnixNanoseconds } from "../../../domain/research/time";
import { researchClient } from "../../../test/researchClient";
import { ResearchAnalysisPage } from "./ResearchAnalysisPage";

vi.mock("../../../visualization/scientific/echarts/ScientificEvidenceChart", () => ({
    ScientificEvidenceChart: () => (
        <div data-testid="scientific-chart">Published evidence chart</div>
    )
}));

afterEach(() => {
    vi.restoreAllMocks();
});

const result = parseResearchResultFingerprint("a".repeat(64));
const statisticsFingerprint = parseStatisticsFingerprint("b".repeat(64));
const summary: ResearchArtifactSummary = {
    researchResultFingerprint: result,
    researchResultPlanFingerprint: "c".repeat(64),
    researchResultContentFingerprint: "d".repeat(64),
    datasetSnapshotFingerprint: "e".repeat(64),
    artifactContentFingerprint: "f".repeat(64),
    researchResultSchemaVersion: 2,
    artifactProfile: "RESEARCH_SCIENTIFIC_V2",
    artifactSchemaVersion: 2,
    statisticsCount: 0,
    rowCount: 0,
    candidateCount: 2,
    publishedSeriesCount: 1,
    signalSeriesCount: 0,
    marketRowCount: 0,
    instrumentIds: ["EXAMPLE.XTEST"],
    createdAt: "2026-09-01T00:00:00Z"
};
const completedRun: ResearchRunSummary = {
    runId: parseResearchRunId("00000000-0000-4000-8000-000000000401"),
    revision: 2n,
    state: "COMPLETED",
    specificationSchemaVersion: 2,
    specificationFingerprint: "1".repeat(64),
    admissionResolutionFingerprint: "2".repeat(64),
    queuedAt: "2026-09-01T00:00:00Z",
    startedAt: "2026-09-01T00:00:01Z",
    cancelRequestedAt: null,
    finishedAt: "2026-09-01T00:00:02Z",
    resultRef: result,
    artifactRef: "f".repeat(64),
    failure: null
};
const descriptor: ResearchStatisticsDescriptor = {
    statisticsFingerprint,
    statisticsResultFingerprint: "3".repeat(64),
    resultContentFingerprint: "4".repeat(64),
    statisticsResultSchemaVersion: 1,
    rowCount: 1,
    feature: {
        calculationFingerprint: "5".repeat(64),
        nodeFingerprint: "6".repeat(64),
        outputName: "score"
    },
    target: {
        calculationFingerprint: "7".repeat(64),
        nodeFingerprint: "8".repeat(64),
        outputName: "forward_return"
    },
    definition: {
        method: "IC",
        minimumObservations: 2,
        pairingPolicy: "PAIRWISE_COMPLETE",
        universePolicy: "EXACT",
        rankTieMethod: "AVERAGE",
        weighting: "EQUAL",
        numeric: {
            representation: "DECIMAL",
            precision: 38,
            outputQuantum: parseDecimalText("0.000001"),
            rounding: "ROUND_HALF_EVEN"
        }
    }
};

function renderAnalysis(overrides: Partial<ResearchApiClient> = {}, entry = "/research/analysis") {
    const client = researchClient({
        listRuns: vi.fn<ResearchApiClient["listRuns"]>().mockResolvedValue({
            runs: [],
            hasMore: false,
            nextCursor: null
        }),
        getArtifactSummary: vi
            .fn<ResearchApiClient["getArtifactSummary"]>()
            .mockResolvedValue(summary),
        getStatisticsCatalog: vi.fn<ResearchApiClient["getStatisticsCatalog"]>().mockResolvedValue({
            researchResultFingerprint: result,
            statistics: []
        }),
        ...overrides
    });
    const getArtifactSummary = vi.spyOn(client, "getArtifactSummary");
    const getStatisticsCatalog = vi.spyOn(client, "getStatisticsCatalog");
    const router = createMemoryRouter(
        [
            { path: "/research/analysis", element: <ResearchAnalysisPage /> },
            { path: "/research/new", element: <h1>Research Builder</h1> },
            { path: "/research/runs", element: <h1>Research Runs</h1> },
            { path: "/research/results", element: <h1>Open exact Result</h1> },
            {
                path: "/research/results/:researchResultFingerprint",
                element: <h1>Full Result workspace</h1>
            }
        ],
        { initialEntries: [entry] }
    );
    render(
        <AppProviders client={client}>
            <RouterProvider router={router} />
        </AppProviders>
    );
    return { getArtifactSummary, getStatisticsCatalog, router };
}

it("renders the workstation regions with honest unavailable market context and no invented advice", async () => {
    const browserFetch = vi.spyOn(globalThis, "fetch");
    const { getArtifactSummary, getStatisticsCatalog } = renderAnalysis();
    expect(screen.getByRole("main", { name: "Research analysis workstation" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "AI Opportunity Radar" })).toBeInTheDocument();
    expect(screen.getByRole("tablist", { name: "Analysis views" })).toBeInTheDocument();
    expect(screen.getByRole("form", { name: "Analysis controls" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Analysis canvas" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Market context" })).toBeInTheDocument();
    const recent = screen.getByRole("complementary", { name: "Recent Research" });
    expect(await within(recent).findByText("No Research Runs yet")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "OnlyAlpha Analysis" })).toBeInTheDocument();
    expect(screen.getByText(/not AI recommendations or trading signals/)).toBeInTheDocument();
    expect(screen.getByText(/does not generate AI trading advice/)).toBeInTheDocument();
    expect(screen.getByText("Event feed unavailable")).toBeInTheDocument();
    expect(
        within(screen.getByRole("region", { name: "Market ticker" })).getAllByText("—")
    ).toHaveLength(5);
    expect(
        within(screen.getByRole("region", { name: "Market Pulse" })).getAllByText("Unavailable")
    ).toHaveLength(9);
    expect(screen.getByRole("button", { name: "Open Analysis" })).toBeDisabled();
    expect(getArtifactSummary).not.toHaveBeenCalled();
    expect(getStatisticsCatalog).not.toHaveBeenCalled();
    expect(browserFetch).not.toHaveBeenCalled();
});

it("switches analysis tabs with click, arrows, Home and End while preserving keyboard focus", async () => {
    renderAnalysis();
    await screen.findByText("No Research Runs yet");
    const user = userEvent.setup();
    const instant = screen.getByRole("tab", { name: "Instant Analysis" });
    const research = screen.getByRole("tab", { name: "Research" });
    const assertPanelSelection = (selectedTab: HTMLElement) => {
        const panel = screen.getByRole("tabpanel");
        expect(panel.id).not.toBe("");
        expect(panel).toHaveAttribute("aria-labelledby", selectedTab.id);
        for (const tab of [instant, research]) {
            expect(tab).toHaveAttribute("aria-controls", panel.id);
            expect(document.getElementById(tab.getAttribute("aria-controls") ?? "")).toBe(panel);
        }
    };
    expect(instant).toHaveAttribute("aria-selected", "true");
    expect(research).toHaveAttribute("tabindex", "-1");
    assertPanelSelection(instant);
    await user.click(research);
    expect(screen.getByRole("heading", { name: "Your Research workflow" })).toBeInTheDocument();
    expect(screen.getByRole("tabpanel", { name: "Research" })).toBeInTheDocument();
    assertPanelSelection(research);
    await user.keyboard("{ArrowRight}");
    expect(instant).toHaveFocus();
    expect(instant).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Instant Analysis" })).toBeInTheDocument();
    assertPanelSelection(instant);
    await user.keyboard("{ArrowLeft}");
    expect(research).toHaveFocus();
    expect(research).toHaveAttribute("aria-selected", "true");
    assertPanelSelection(research);
    await user.keyboard("{Home}");
    expect(instant).toHaveFocus();
    assertPanelSelection(instant);
    await user.keyboard("{End}");
    expect(research).toHaveFocus();
    expect(research).toHaveAttribute("tabindex", "0");
    assertPanelSelection(research);
});

it("opens a completed Run's exact Result in the URL and displays only admitted Artifact facts", async () => {
    const running: ResearchRunSummary = {
        ...completedRun,
        runId: parseResearchRunId("00000000-0000-4000-8000-000000000402"),
        state: "RUNNING",
        finishedAt: null,
        resultRef: null,
        artifactRef: null
    };
    const { getArtifactSummary, getStatisticsCatalog, router } = renderAnalysis(
        {
            listRuns: () =>
                Promise.resolve({ runs: [running, completedRun], hasMore: false, nextCursor: null })
        },
        "/research/analysis?context=keep"
    );
    const user = userEvent.setup();
    const selector = screen.getByRole("combobox", { name: "Completed Research Run" });
    await screen.findByRole("option", { name: new RegExp(completedRun.runId) });
    expect(
        within(selector).queryByRole("option", { name: new RegExp(running.runId) })
    ).not.toBeInTheDocument();
    expect(getArtifactSummary).not.toHaveBeenCalled();
    await user.selectOptions(selector, completedRun.runId);
    await user.click(screen.getByRole("button", { name: "Open Analysis" }));
    expect(await screen.findByRole("heading", { name: "Research evidence" })).toBeInTheDocument();
    expect(new URLSearchParams(router.state.location.search).get("result")).toBe(result);
    expect(new URLSearchParams(router.state.location.search).get("context")).toBe("keep");
    expect(screen.getByText("EXAMPLE.XTEST")).toBeInTheDocument();
    expect(screen.getByText(summary.artifactProfile)).toBeInTheDocument();
    expect(screen.getByText("This Artifact contains no Statistics evidence.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Full workspace" })).toHaveAttribute(
        "href",
        `/research/results/${result}`
    );
    expect(getArtifactSummary).toHaveBeenCalledWith(result, expect.any(AbortSignal));
    expect(getStatisticsCatalog).toHaveBeenCalledWith(result, expect.any(AbortSignal));
});

it("opens exact Result references from loaded completed Runs without a new Result catalog", async () => {
    const listRuns = vi.fn<ResearchApiClient["listRuns"]>().mockResolvedValue({
        runs: [completedRun],
        hasMore: false,
        nextCursor: null
    });
    const { router } = renderAnalysis({ listRuns });
    const recent = screen.getByRole("complementary", { name: "Recent Research" });
    const reference = await within(recent).findByRole("link", {
        name: /Open authoritative evidence/
    });
    await userEvent.click(reference);
    expect(await screen.findByRole("heading", { name: "Research evidence" })).toBeInTheDocument();
    expect(new URLSearchParams(router.state.location.search).get("result")).toBe(result);
    expect(listRuns).toHaveBeenCalledTimes(1);
});

it("returns to the evidence canvas when a Result reference is opened from the Research tab", async () => {
    const { router } = renderAnalysis({
        listRuns: () => Promise.resolve({ runs: [completedRun], hasMore: false, nextCursor: null })
    });
    const recent = screen.getByRole("complementary", { name: "Recent Research" });
    const reference = await within(recent).findByRole("link", {
        name: /Open authoritative evidence/
    });
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Research" }));
    expect(screen.getByRole("heading", { name: "Your Research workflow" })).toBeInTheDocument();
    await user.click(reference);
    expect(await screen.findByRole("heading", { name: "Research evidence" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Instant Analysis" })).toHaveAttribute(
        "aria-selected",
        "true"
    );
    expect(screen.getByRole("tabpanel", { name: "Instant Analysis" })).toBeInTheDocument();
    expect(
        screen.queryByRole("heading", { name: "Your Research workflow" })
    ).not.toBeInTheDocument();
    expect(new URLSearchParams(router.state.location.search).get("result")).toBe(result);
});

it("rejects an invalid deep-link fingerprint before any Artifact query", async () => {
    const { getArtifactSummary, getStatisticsCatalog } = renderAnalysis(
        {},
        "/research/analysis?result=not-an-exact-result"
    );
    expect(screen.getByRole("alert")).toHaveTextContent("INVALID_QUERY");
    await screen.findByText("No Research Runs yet");
    expect(screen.getByRole("heading", { name: "OnlyAlpha Analysis" })).toBeInTheDocument();
    expect(getArtifactSummary).not.toHaveBeenCalled();
    expect(getStatisticsCatalog).not.toHaveBeenCalled();
});

it("rejects invalid manual input without replacing the URL or issuing a command", async () => {
    const submitRun = vi.fn<ResearchApiClient["submitRun"]>();
    const resolveDefinition = vi.fn<ResearchApiClient["resolveDefinition"]>();
    const { getArtifactSummary, getStatisticsCatalog, router } = renderAnalysis({
        submitRun,
        resolveDefinition
    });
    await screen.findByText("No Research Runs yet");
    const user = userEvent.setup();
    await user.click(screen.getByText("Use an exact Result fingerprint"));
    await user.type(screen.getByLabelText("Research Result fingerprint"), "invalid");
    await user.click(screen.getByRole("button", { name: "Open Analysis" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter an exact lower-case SHA256");
    expect(router.state.location.search).toBe("");
    expect(getArtifactSummary).not.toHaveBeenCalled();
    expect(getStatisticsCatalog).not.toHaveBeenCalled();
    expect(submitRun).not.toHaveBeenCalled();
    expect(resolveDefinition).not.toHaveBeenCalled();
});

it("distinguishes unavailable Runs from empty Runs and still opens an independently known exact Result", async () => {
    const { getArtifactSummary, router } = renderAnalysis({
        listRuns: () =>
            Promise.reject(new ResearchWebError("TRANSPORT_ERROR", "Run API is unavailable"))
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Run API is unavailable");
    expect(screen.getByText("Run data is unavailable.")).toBeInTheDocument();
    expect(screen.getByText("Result references unavailable.")).toBeInTheDocument();
    expect(screen.queryByText("No Research Runs yet")).not.toBeInTheDocument();
    expect(
        screen.queryByText("No completed Result references in this Run page.")
    ).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByText("Use an exact Result fingerprint"));
    await user.type(screen.getByLabelText("Research Result fingerprint"), result);
    await user.click(screen.getByRole("button", { name: "Open Analysis" }));
    expect(await screen.findByRole("heading", { name: "Research evidence" })).toBeInTheDocument();
    expect(new URLSearchParams(router.state.location.search).get("result")).toBe(result);
    expect(getArtifactSummary).toHaveBeenCalledWith(result, expect.any(AbortSignal));
    expect(screen.getByRole("alert")).toHaveTextContent("Run API is unavailable");
});

it("presents an existing exact Statistics value through the shared chart adapter without recomputation", async () => {
    const getStatisticSeries = vi.fn<ResearchApiClient["getStatisticSeries"]>().mockResolvedValue({
        researchResultFingerprint: result,
        statisticsFingerprint,
        points: [
            {
                tsEventNs: parseUnixNanoseconds("1760000000000000000"),
                statisticValue: parseDecimalText("0.123456"),
                sampleCount: 10,
                status: "VALID"
            }
        ],
        hasMore: false,
        nextAfterTsEventNs: null
    });
    const submitRun = vi.fn<ResearchApiClient["submitRun"]>();
    const getMarketSeries = vi.fn<ResearchApiClient["getMarketSeries"]>();
    renderAnalysis(
        {
            getArtifactSummary: () =>
                Promise.resolve({ ...summary, statisticsCount: 1, rowCount: 1 }),
            getStatisticsCatalog: () =>
                Promise.resolve({ researchResultFingerprint: result, statistics: [descriptor] }),
            getStatisticSeries,
            submitRun,
            getMarketSeries
        },
        `/research/analysis?result=${result}`
    );
    expect(await screen.findByTestId("scientific-chart")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "0.123456" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "1760000000000000000" })).toBeInTheDocument();
    expect(getStatisticSeries).toHaveBeenCalledWith(
        expect.objectContaining({
            researchResultFingerprint: result,
            statisticsFingerprint,
            limit: 500
        }),
        expect.any(AbortSignal)
    );
    expect(submitRun).not.toHaveBeenCalled();
    expect(getMarketSeries).not.toHaveBeenCalled();
});

it("fails closed on unavailable exact Artifact evidence", async () => {
    renderAnalysis(
        {
            getArtifactSummary: () =>
                Promise.reject(
                    new ResearchWebError(
                        "RESEARCH_ARTIFACT_CORRUPT",
                        "Artifact verification failed",
                        500
                    )
                )
        },
        `/research/analysis?result=${result}`
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Artifact verification failed");
    expect(screen.queryByRole("heading", { name: "Research evidence" })).not.toBeInTheDocument();
    expect(screen.queryByText("EXAMPLE.XTEST")).not.toBeInTheDocument();
    expect(screen.queryByTestId("scientific-chart")).not.toBeInTheDocument();
});
