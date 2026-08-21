import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { AppProviders } from "../../../app/providers";
import { parseResearchRunId } from "../../../domain/research/identity";
import type { ResearchRun } from "../../../domain/research/model";
import { researchClient } from "../../../test/researchClient";
import { ResearchRunPage } from "./ResearchRunPage";

const runId = parseResearchRunId("00000000-0000-4000-8000-000000000201");
const running: ResearchRun = {
    runId,
    revision: 1n,
    state: "RUNNING",
    specificationSchemaVersion: 2,
    specificationFingerprint: "a".repeat(64),
    admissionResolutionFingerprint: "b".repeat(64),
    queuedAt: "2026-08-21T00:00:00Z",
    startedAt: "2026-08-21T00:00:01Z",
    cancelRequestedAt: null,
    finishedAt: null,
    resultRef: null,
    artifactRef: null,
    failure: null,
    specification: { schema_version: 2 }
};

it("renders the authoritative cancellation response without forcing CANCELLED", async () => {
    const completed: ResearchRun = {
        ...running,
        revision: 2n,
        state: "COMPLETED",
        finishedAt: "2026-08-21T00:00:03Z",
        resultRef: "c".repeat(64),
        artifactRef: "d".repeat(64)
    };
    const cancelRun = vi.fn(() => Promise.resolve(completed));
    const client = researchClient({ getRun: () => Promise.resolve(running), cancelRun });
    const router = createMemoryRouter(
        [
            { path: "/research/runs/:runId", element: <ResearchRunPage /> },
            { path: "/research/results/:researchResultFingerprint", element: <p>exact result</p> }
        ],
        { initialEntries: [`/research/runs/${runId}`] }
    );
    render(
        <AppProviders client={client}>
            <RouterProvider router={router} />
        </AppProviders>
    );
    expect(await screen.findByText("RUNNING", { selector: ".run-state" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Request cancellation" }));
    expect(await screen.findByText("COMPLETED", { selector: ".run-state" })).toBeInTheDocument();
    expect(screen.queryByText("CANCELLED")).not.toBeInTheDocument();
    const resultRef = completed.resultRef;
    if (resultRef === null) throw new Error("Completed fixture requires Result reference");
    expect(screen.getByRole("link", { name: "Open exact Result" })).toHaveAttribute(
        "href",
        `/research/results/${resultRef}`
    );
});

it("renders exact operational failure evidence", async () => {
    const failed: ResearchRun = {
        ...running,
        state: "FAILED",
        finishedAt: "2026-08-21T00:00:02Z",
        failure: {
            phase: "EXECUTION",
            code: "RESEARCH_WORKER_FAILED",
            detail: "deterministic failure"
        }
    };
    const router = createMemoryRouter(
        [{ path: "/research/runs/:runId", element: <ResearchRunPage /> }],
        { initialEntries: [`/research/runs/${runId}`] }
    );
    render(
        <AppProviders client={researchClient({ getRun: () => Promise.resolve(failed) })}>
            <RouterProvider router={router} />
        </AppProviders>
    );
    expect(await screen.findByText("EXECUTION · RESEARCH_WORKER_FAILED")).toBeInTheDocument();
    expect(screen.getByText("deterministic failure")).toBeInTheDocument();
});
