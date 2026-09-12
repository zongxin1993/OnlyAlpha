import { researchRoutes } from "./router";

it("owns stable Research deep-link routes and narrow compatibility redirects", () => {
    const paths = researchRoutes.flatMap(
        (route) => route.children?.map((child) => child.path) ?? []
    );
    expect(paths).toEqual(
        expect.arrayContaining([
            "/research/new",
            "/research/analysis",
            "/research/library",
            "/data/inputs",
            "/strategies",
            "/strategies/:strategyFingerprint",
            "/backtest/runs",
            "/backtest/runs/:backtestRunId",
            "/system/health",
            "/research/runs",
            "/research/runs/:runId",
            "/research/results",
            "/research/results/:researchResultFingerprint",
            "/research/results/:researchResultFingerprint/statistics/:statisticsFingerprint",
            "/research/:researchResultFingerprint",
            "/research/:researchResultFingerprint/statistics/:statisticsFingerprint"
        ])
    );
});
