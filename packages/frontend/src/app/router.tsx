import { createBrowserRouter, Navigate, type RouteObject } from "react-router-dom";
import { DeferredFeaturePage } from "./DeferredFeaturePage";
import { OverviewPlaceholder } from "./OverviewPlaceholder";
import { WorkstationShell } from "./shell/WorkstationShell";
import { StrategyWorkflow } from "../features/strategies/StrategyWorkflow";
import { BacktestPage } from "../features/backtest/BacktestPage";
import { WorkspacePage } from "../features/workspace/WorkspacePage";
import { DataSourceDetailPage } from "../features/data/sources/DataSourceDetailPage";
import { DataSourcesPage } from "../features/data/sources/DataSourcesPage";
import { NewDataSourcePage } from "../features/data/sources/NewDataSourcePage";
import { SystemHealthPage } from "../features/system/SystemHealthPage";

export const workstationRoutes: RouteObject[] = [
    {
        element: <WorkstationShell />,
        children: [
            { path: "/", element: <WorkspacePage /> },
            { path: "/overview", element: <OverviewPlaceholder /> },
            { path: "/research/*", element: <DeferredFeaturePage feature="研究" /> },
            { path: "/data", element: <Navigate to="/data/inputs" replace /> },
            { path: "/data/inputs", element: <DataSourcesPage /> },
            { path: "/data/sources", element: <DataSourcesPage /> },
            { path: "/data/sources/new", element: <NewDataSourcePage /> },
            { path: "/data/sources/:integrationId", element: <DataSourceDetailPage /> },
            { path: "/strategies/*", element: <StrategyWorkflow /> },
            { path: "/backtest/*", element: <BacktestPage /> },
            { path: "/system", element: <Navigate to="/system/health" replace /> },
            { path: "/system/health", element: <SystemHealthPage /> },
            { path: "*", element: <DeferredFeaturePage /> }
        ]
    }
];

export const router = createBrowserRouter(workstationRoutes);
