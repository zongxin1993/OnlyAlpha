import { createBrowserRouter, type RouteObject } from "react-router-dom";
import { DeferredFeaturePage } from "./DeferredFeaturePage";
import { WorkstationShell } from "./shell/WorkstationShell";
import { FactorChatPage } from "../features/factorChat/FactorChatPage";
import { StrategyWorkflow } from "../features/strategies/StrategyWorkflow";
import { BacktestPage } from "../features/backtest/BacktestPage";
import { WorkspacePage } from "../features/workspace/WorkspacePage";

export const workstationRoutes: RouteObject[] = [
    {
        element: <WorkstationShell />,
        children: [
            { path: "/factor-research", element: <FactorChatPage /> },
            { path: "/", element: <WorkspacePage /> },
            { path: "/research/*", element: <DeferredFeaturePage feature="研究" /> },
            { path: "/data/*", element: <DeferredFeaturePage feature="数据" /> },
            { path: "/strategies/*", element: <StrategyWorkflow /> },
            { path: "/backtest/*", element: <BacktestPage /> },
            { path: "/system/*", element: <DeferredFeaturePage feature="系统" /> },
            { path: "*", element: <DeferredFeaturePage /> }
        ]
    }
];

export const router = createBrowserRouter(workstationRoutes);
