import { createBrowserRouter, type RouteObject } from "react-router-dom";
import { DeferredFeaturePage } from "./DeferredFeaturePage";
import { WorkstationShell } from "./shell/WorkstationShell";
import { FactorChatPage } from "../features/factorChat/FactorChatPage";
import { WorkspacePage } from "../features/workspace/WorkspacePage";

export const workstationRoutes: RouteObject[] = [
    {
        element: <WorkstationShell />,
        children: [
            { path: "/factor-research", element: <FactorChatPage /> },
            { path: "/", element: <WorkspacePage /> },
            { path: "/research/*", element: <DeferredFeaturePage feature="研究" /> },
            { path: "/data/*", element: <DeferredFeaturePage feature="数据" /> },
            { path: "/strategies/*", element: <DeferredFeaturePage feature="策略" /> },
            { path: "/backtest/*", element: <DeferredFeaturePage feature="回测" /> },
            { path: "/system/*", element: <DeferredFeaturePage feature="系统" /> },
            { path: "*", element: <DeferredFeaturePage /> }
        ]
    }
];

export const router = createBrowserRouter(workstationRoutes);
