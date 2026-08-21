import { Navigate, createBrowserRouter, type RouteObject } from "react-router-dom";
import { CompatibilityResultRedirect, CompatibilityStatisticsRedirect } from "./RouteRedirects";
import { WorkstationShell } from "./shell/WorkstationShell";
import { ArtifactOverviewPage } from "../features/research/artifact/ArtifactOverviewPage";
import { ResearchOpenPage } from "../features/research/open/ResearchOpenPage";
import { ResearchRunPage } from "../features/research/runs/ResearchRunPage";
import { ResearchRunsPage } from "../features/research/runs/ResearchRunsPage";
import { ResearchStudioPage } from "../features/research/studio/ResearchStudioPage";
import { StatisticsDetailPage } from "../features/research/statistics/StatisticsDetailPage";

export const researchRoutes: RouteObject[] = [
    {
        element: <WorkstationShell />,
        children: [
            { path: "/", element: <Navigate to="/research/new" replace /> },
            { path: "/research", element: <Navigate to="/research/new" replace /> },
            { path: "/research/new", element: <ResearchStudioPage /> },
            { path: "/research/runs", element: <ResearchRunsPage /> },
            { path: "/research/runs/:runId", element: <ResearchRunPage /> },
            { path: "/research/results", element: <ResearchOpenPage /> },
            {
                path: "/research/results/:researchResultFingerprint",
                element: <ArtifactOverviewPage />
            },
            {
                path: "/research/results/:researchResultFingerprint/statistics/:statisticsFingerprint",
                element: <StatisticsDetailPage />
            },
            {
                path: "/research/:researchResultFingerprint",
                element: <CompatibilityResultRedirect />
            },
            {
                path: "/research/:researchResultFingerprint/statistics/:statisticsFingerprint",
                element: <CompatibilityStatisticsRedirect />
            }
        ]
    }
];

export const router = createBrowserRouter(researchRoutes);
