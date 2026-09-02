import { expect, test } from "@playwright/test";
import { existsSync, writeFileSync } from "node:fs";

const required = (name: string): string => {
    const value = process.env[name];
    if (value === undefined || value === "") throw new Error(`${name} is required`);
    return value;
};

const barrier = required("ONLYALPHA_REAL_E2E_ALLOW_WORKER");
const workerStarted = required("ONLYALPHA_REAL_E2E_WORKER_STARTED");
const evidencePath = required("ONLYALPHA_REAL_E2E_EVIDENCE");
const instruments = required("ONLYALPHA_REAL_E2E_INSTRUMENTS");
const start = required("ONLYALPHA_REAL_E2E_START");
const end = required("ONLYALPHA_REAL_E2E_END");

interface RunDto {
    readonly state: string;
    readonly result_ref: string;
    readonly artifact_ref: string;
}

interface SummaryDto {
    readonly candidate_count: number;
    readonly instrument_ids: string[];
}

interface CandidateDto {
    readonly candidate_fingerprint: string;
    readonly signal_roles: string[];
}

interface SeriesDto {
    readonly candidate_fingerprint: string;
    readonly calculation_fingerprint: string;
    readonly node_fingerprint: string;
    readonly output_name: string;
}

interface StatisticDto {
    readonly statistics_fingerprint: string;
}

interface GraphNodeDto {
    readonly node_fingerprint: string;
    readonly definition: { readonly type_id: string };
}

interface PointsDto {
    readonly points: { readonly decimal_value?: string | null }[];
}

const parsed = async <T>(response: { text(): Promise<string> }): Promise<T> => {
    const value: unknown = JSON.parse(await response.text()) as unknown;
    return value as T;
};

test("real Browser to PostgreSQL Worker Engine Artifact and Viewer product vertical", async ({
    page,
    context
}) => {
    await page.goto("/research/new");
    await page.getByLabel("Universe kind").selectOption("EXPLICIT_INSTRUMENT_SET");
    await page.getByLabel("Instrument IDs").fill(instruments);
    await page.getByLabel("Start").fill(start);
    await page.getByLabel("End").fill(end);

    const calculations = page.getByLabel("Add Calculations");
    const calculationSection = calculations.locator("xpath=ancestor::section");

    await calculations.selectOption({ label: "onlyalpha.indicator.rsi" });
    await calculationSection.getByRole("button", { name: "Add" }).click();
    const rsi = calculationSection
        .locator("article")
        .filter({ hasText: "onlyalpha.indicator.rsi" });
    await rsi.getByLabel("onlyalpha.indicator.rsi instance key").fill("feature_rsi");
    const period = rsi.locator(".parameter-row").filter({ hasText: "period" });
    await period.getByLabel("Mode").selectOption("SWEEP");
    await rsi.getByLabel("feature_rsi period").fill("2, 3");
    await rsi.getByLabel("Input · value").selectOption("bar.close");

    for (const [key, rollingPeriod] of [
        ["returns_short", "1"],
        ["returns_long", "2"]
    ] as const) {
        await calculations.selectOption({ label: "onlyalpha.indicator.rolling_return" });
        await calculationSection.getByRole("button", { name: "Add" }).click();
        const rolling = calculationSection
            .locator("article")
            .filter({ hasText: "onlyalpha.indicator.rolling_return" })
            .last();
        await rolling.getByLabel("onlyalpha.indicator.rolling_return instance key").fill(key);
        await rolling.getByLabel(`${key} period`).fill(rollingPeriod);
        await rolling.getByLabel("Input · value").selectOption("bar.close");
    }

    await calculations.selectOption({ label: "onlyalpha.factor.momentum" });
    await calculationSection.getByRole("button", { name: "Add" }).click();
    const factor = calculationSection
        .locator("article")
        .filter({ hasText: "onlyalpha.factor.momentum" });
    await factor.getByLabel("onlyalpha.factor.momentum instance key").fill("momentum");
    await factor.getByLabel("Input · return_short").selectOption("returns_short.value");
    await factor.getByLabel("Input · return_long").selectOption("returns_long.value");

    const eligibility = page
        .getByRole("heading", { name: "Eligibility" })
        .locator("xpath=ancestor::section");
    await eligibility.getByRole("button", { name: "Add expression" }).click();
    for (const title of ["Entry", "Exit"]) {
        const block = page.locator(".expression-block").filter({ hasText: title });
        await block.getByRole("button", { name: "Add expression" }).click();
    }

    const targets = page.getByLabel("Add Targets");
    const targetSection = targets.locator("xpath=ancestor::section");
    await targets.selectOption({ label: "onlyalpha.target.forward_return" });
    await targetSection.getByRole("button", { name: "Add" }).click();
    const target = targetSection
        .locator("article")
        .filter({ hasText: "onlyalpha.target.forward_return" });
    await target.getByLabel("onlyalpha.target.forward_return instance key").fill("forward_return");
    await target.getByLabel("forward_return exit_offset").fill("1");
    await target.getByLabel("Input · entry_price").selectOption("bar.close");
    await target.getByLabel("Input · exit_price").selectOption("bar.close");

    await page.getByRole("button", { name: "Add Statistics" }).click();
    const statisticsSection = page
        .getByRole("heading", { name: "Statistics", exact: true })
        .locator("xpath=ancestor::section");
    const statisticsSelectors = statisticsSection.getByRole("combobox");
    await statisticsSelectors.nth(0).selectOption("momentum.factor_value");
    await statisticsSelectors.nth(1).selectOption("forward_return");
    await page.getByRole("button", { name: "Resolve" }).click();
    await expect(page.getByText("RESOLVED", { exact: true })).toBeVisible();
    await expect(page.getByText("2", { exact: true }).first()).toBeVisible();

    await page.getByRole("button", { name: "Run" }).click();
    await expect(page).toHaveURL(/\/research\/runs\/[0-9a-f-]+$/);
    const runUrl = page.url();
    const runId = runUrl.split("/").pop();
    if (runId === undefined) throw new Error("Run ID is unavailable");
    await expect(page.getByText("QUEUED", { exact: true }).first()).toBeVisible();

    await page.reload();
    await expect(page).toHaveURL(runUrl);
    await expect(page.getByText("QUEUED", { exact: true }).first()).toBeVisible();

    await page.close();
    writeFileSync(barrier, runId, { encoding: "utf8", flag: "wx" });
    await expect.poll(() => existsSync(workerStarted)).toBe(true);

    const reopened = await context.newPage();
    await reopened.goto(runUrl);
    await expect(reopened.getByText("COMPLETED", { exact: true }).first()).toBeVisible({
        timeout: 60_000
    });
    const runResponse = await reopened.request.get(`/api/v2/research/runs/${runId}`);
    expect(runResponse.ok()).toBeTruthy();
    const run = await parsed<RunDto>(runResponse);
    expect(run.state).toBe("COMPLETED");
    expect(run.result_ref).toMatch(/^[0-9a-f]{64}$/);
    expect(run.artifact_ref).toMatch(/^[0-9a-f]{64}$/);

    await reopened.getByRole("link", { name: "Open exact Result" }).click();
    await expect(reopened.getByRole("heading", { name: "Scientific Workstation" })).toBeVisible();
    const result = run.result_ref;
    const response = async <T>(path: string): Promise<T> => {
        const current = await reopened.request.get(path);
        expect(current.ok(), path).toBeTruthy();
        return parsed<T>(current);
    };
    const summary = await response<SummaryDto>(`/api/v2/research/artifacts/${result}`);
    const candidates = await response<{ readonly candidates: CandidateDto[] }>(
        `/api/v2/research/artifacts/${result}/candidates`
    );
    const variables = await response<{ readonly series: SeriesDto[] }>(
        `/api/v2/research/artifacts/${result}/variables`
    );
    const statistics = await response<{ readonly statistics: StatisticDto[] }>(
        `/api/v2/research/artifacts/${result}/statistics`
    );
    expect(summary.candidate_count).toBe(2);
    expect(summary.instrument_ids).toEqual(["A.XNAS", "B.XNAS"]);
    expect(candidates.candidates.length).toBe(2);
    expect(variables.series.length).toBeGreaterThanOrEqual(4);
    expect(statistics.statistics.length).toBe(2);

    const candidate = [...candidates.candidates].shift();
    if (candidate === undefined) throw new Error("Candidate is unavailable");
    const candidateGraph = await response<{
        readonly graph: { readonly nodes: GraphNodeDto[] };
    }>(`/api/v2/research/artifacts/${result}/candidates/${candidate.candidate_fingerprint}/graph`);
    const rsiNode = candidateGraph.graph.nodes.find(
        (node) => node.definition.type_id === "onlyalpha.indicator.rsi"
    );
    if (rsiNode === undefined) throw new Error("RSI Feature node is unavailable");
    const candidateSeries = variables.series.filter(
        (item) => item.candidate_fingerprint === candidate.candidate_fingerprint
    );
    const featureSeries = candidateSeries.find(
        (item) => item.node_fingerprint === rsiNode.node_fingerprint && item.output_name === "value"
    );
    const factorSeries = candidateSeries.find((item) => item.output_name === "factor_value");
    if (featureSeries === undefined || factorSeries === undefined)
        throw new Error("Feature or Factor published series is unavailable");
    const variablePage = async (series: SeriesDto): Promise<PointsDto> => {
        const query = new URLSearchParams({
            instrument_id: "A.XNAS",
            candidate_fingerprint: candidate.candidate_fingerprint,
            limit: "100"
        });
        return response<PointsDto>(
            `/api/v2/research/artifacts/${result}/variables/${series.calculation_fingerprint}/${series.node_fingerprint}/${series.output_name}/series?${query}`
        );
    };
    const featurePage = await variablePage(featureSeries);
    const factorPage = await variablePage(factorSeries);
    const featureValue = featurePage.points.find(
        (point) => typeof point.decimal_value === "string"
    )?.decimal_value;
    const factorValue = factorPage.points.find(
        (point) => typeof point.decimal_value === "string"
    )?.decimal_value;
    expect(typeof featureValue).toBe("string");
    expect(typeof factorValue).toBe("string");

    expect(candidate.signal_roles).toContain("ENTRY_SIGNAL");
    const signalPage = await response<{ readonly points: unknown[] }>(
        `/api/v2/research/artifacts/${result}/signals/${candidate.candidate_fingerprint}/ENTRY_SIGNAL/series?instrument_id=A.XNAS&limit=100`
    );
    expect(signalPage.points.length).toBeGreaterThan(0);
    const statistic = [...statistics.statistics].shift();
    if (statistic === undefined) throw new Error("Statistics descriptor is unavailable");
    const statisticsPage = await response<{ readonly points: unknown[] }>(
        `/api/v2/research/artifacts/${result}/statistics/${statistic.statistics_fingerprint}/series?limit=100`
    );
    expect(statisticsPage.points.length).toBeGreaterThan(0);

    const overview = reopened
        .getByRole("heading", { name: "Scientific evidence overview" })
        .locator("..");
    await expect(overview).toContainText("2Candidates");
    const seriesKey = (series: SeriesDto): string =>
        [
            series.candidate_fingerprint,
            series.calculation_fingerprint,
            series.node_fingerprint,
            series.output_name
        ].join(":");
    await reopened.getByRole("tab", { name: "Market" }).click();
    await reopened.getByLabel("Published series").selectOption(seriesKey(featureSeries));
    await reopened.getByRole("tab", { name: "Exact Data" }).click();
    await expect(reopened.getByRole("heading", { name: "Exact Data Inspector" })).toBeVisible();
    await expect(reopened.getByText(String(featureValue), { exact: true }).first()).toBeVisible();
    await reopened.getByRole("tab", { name: "Market" }).click();
    await reopened.getByLabel("Published series").selectOption(seriesKey(factorSeries));
    await reopened.getByRole("tab", { name: "Exact Data" }).click();
    await expect(reopened.getByText(String(factorValue), { exact: true }).first()).toBeVisible();
    await expect(reopened.getByRole("heading", { name: "Signal · ENTRY_SIGNAL" })).toBeVisible();
    await expect(reopened.getByRole("heading", { name: "Statistics · IC" })).toBeVisible();

    writeFileSync(
        evidencePath,
        JSON.stringify(
            {
                run_id: runId,
                result,
                artifact: run.artifact_ref,
                candidate_count: summary.candidate_count,
                instruments: summary.instrument_ids,
                feature_value: featureValue,
                factor_value: factorValue,
                published_output: featureSeries.output_name,
                signal_points: signalPage.points.length,
                statistics_points: statisticsPage.points.length
            },
            undefined,
            2
        ),
        { encoding: "utf8", flag: "wx" }
    );
});
