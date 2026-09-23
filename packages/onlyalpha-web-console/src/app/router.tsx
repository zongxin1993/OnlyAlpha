import { Navigate, createBrowserRouter, type RouteObject } from "react-router-dom";
import { CompatibilityResultRedirect, CompatibilityStatisticsRedirect } from "./RouteRedirects";
import { WorkstationShell } from "./shell/WorkstationShell";
import { ResearchOpenPage } from "../features/research/open/ResearchOpenPage";
import { ResearchRunPage } from "../features/research/runs/ResearchRunPage";
import { ResearchRunsPage } from "../features/research/runs/ResearchRunsPage";
import { ResearchStudioPage } from "../features/research/studio/ResearchStudioPage";
import { ResultWorkspacePage } from "../features/research/results/ResultWorkspacePage";
import { StatisticsDetailPage } from "../features/research/statistics/StatisticsDetailPage";
import { ResearchAnalysisPage } from "../features/research/analysis/ResearchAnalysisPage";
import { ResearchInputsPage } from "../features/data/ResearchInputsPage";
import { ResearchLibraryPage } from "../features/research/library/ResearchLibraryPage";
import { StrategyPage } from "../features/strategies/StrategyPage";
import { BacktestPage } from "../features/backtest/BacktestPage";
import { SystemHealthPage } from "../features/system/SystemHealthPage";
import { FactorExplorerPage } from "../features/research/factors/FactorExplorerPage";
import { DataSourcesPage } from "../features/data/sources/DataSourcesPage";
import { NewDataSourcePage } from "../features/data/sources/NewDataSourcePage";
import { DataSourceDetailPage } from "../features/data/sources/DataSourceDetailPage";
import { WorkspacePage } from "../features/workspace/WorkspacePage";

export const researchRoutes: RouteObject[] = [
    {
        element: <WorkstationShell />,
        children: [
            { path: "/", element: <WorkspacePage /> },
            { path: "/research", element: <Navigate to="/research/new" replace /> },
            { path: "/research/new", element: <ResearchStudioPage /> },
            { path: "/research/analysis", element: <ResearchAnalysisPage /> },
            { path: "/research/library", element: <ResearchLibraryPage /> },
            { path: "/research/factors", element: <FactorExplorerPage /> },
            { path: "/data/inputs", element: <ResearchInputsPage /> },
            { path: "/data/sources", element: <DataSourcesPage /> },
            { path: "/data/sources/new", element: <NewDataSourcePage /> },
            { path: "/data/sources/:integrationId", element: <DataSourceDetailPage /> },
            { path: "/strategies", element: <StrategyPage /> },
            { path: "/strategies/:strategyFingerprint", element: <StrategyPage /> },
            { path: "/backtest/runs", element: <BacktestPage /> },
            { path: "/backtest/runs/:backtestRunId", element: <BacktestPage /> },
            { path: "/system/health", element: <SystemHealthPage /> },
            { path: "/research/runs", element: <ResearchRunsPage /> },
            { path: "/research/runs/:runId", element: <ResearchRunPage /> },
            { path: "/research/results", element: <ResearchOpenPage /> },
            {
                path: "/research/results/:researchResultFingerprint",
                element: <ResultWorkspacePage />
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
