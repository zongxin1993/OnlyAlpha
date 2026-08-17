import { Navigate, createBrowserRouter } from "react-router-dom";
import { ArtifactOverviewPage } from "../features/research/artifact/ArtifactOverviewPage";
import { ResearchOpenPage } from "../features/research/open/ResearchOpenPage";
import { StatisticsDetailPage } from "../features/research/statistics/StatisticsDetailPage";

export const router = createBrowserRouter([
    { path: "/", element: <Navigate to="/research" replace /> },
    { path: "/research", element: <ResearchOpenPage /> },
    { path: "/research/:researchResultFingerprint", element: <ArtifactOverviewPage /> },
    {
        path: "/research/:researchResultFingerprint/statistics/:statisticsFingerprint",
        element: <StatisticsDetailPage />
    }
]);
