import { expect, test, type Page } from "@playwright/test";

const result = "a".repeat(64);
const candidate = "1".repeat(64);
const calculation = "3".repeat(64);
const node = "5".repeat(64);
const graph = "7".repeat(64);
const ic = "9".repeat(64);
const rankIc = "b".repeat(64);
const runId = "10000000-0000-4000-8000-000000000001";
const firstStock = "AAA.XNAS";
const secondStock = "BBB.XNAS";
const firstTime = "1709164800000000000";
const secondTime = "1709251200000000000";
const factorType = "example.factor.momentum";
const factorKey = `FACTOR:${factorType}@1.0.0`;
const artifactPath = `/api/v2/research/artifacts/${result}`;
const variablePath = `${artifactPath}/variables/${calculation}/${node}/score/series`;

const pricePort = {
    name: "price",
    data_type: "DECIMAL",
    nullable: false,
    semantic_type: "PRICE",
    dimensions: ["INSTRUMENT", "TIME"],
    unit: "PRICE"
};
const scorePort = {
    name: "score",
    data_type: "DECIMAL",
    nullable: true,
    semantic_type: "FACTOR_SCORE",
    dimensions: ["INSTRUMENT", "TIME"],
    unit: null
};
function catalogItem(version: string, indicator = false) {
    const kind = indicator ? "INDICATOR" : "FACTOR";
    return {
        kind,
        type_reference: {
            kind,
            type_id: indicator ? "example.indicator.sma" : factorType,
            semantic_version: version
        },
        parameters: [],
        inputs: [pricePort],
        outputs: [indicator ? { ...scorePort, semantic_type: "INDICATOR_VALUE" } : scorePort],
        parameter_sweep_allowed: true
    };
}
function statistic(fingerprint: string, method: string) {
    return {
        statistics_fingerprint: fingerprint,
        statistics_result_fingerprint: "c".repeat(64),
        result_content_fingerprint: "d".repeat(64),
        statistics_result_schema_version: 1,
        row_count: 2,
        feature: {
            calculation_fingerprint: calculation,
            node_fingerprint: node,
            output_name: "score"
        },
        target: {
            calculation_fingerprint: "e".repeat(64),
            node_fingerprint: "f".repeat(64),
            output_name: "forward_return"
        },
        definition: {
            method,
            minimum_observations: 2,
            pairing_policy: "PAIRWISE_COMPLETE",
            universe_policy: "OBSERVED_PAIRWISE",
            rank_tie_method: "AVERAGE",
            weighting: "EQUAL",
            numeric: {
                representation: "DECIMAL",
                precision: 38,
                output_quantum: "0.000000000001",
                rounding: "ROUND_HALF_EVEN"
            }
        }
    };
}

function inRequestedRange(timestamp: string, url: URL): boolean {
    const point = BigInt(timestamp);
    const from = url.searchParams.get("from_ts_event_ns");
    const to = url.searchParams.get("to_ts_event_ns");
    const after = url.searchParams.get("after_ts_event_ns");
    return (
        (from === null || point >= BigInt(from)) &&
        (to === null || point < BigInt(to)) &&
        (after === null || point > BigInt(after))
    );
}

async function mockFactorEvidence(page: Page) {
    const requests: { method: string; url: URL }[] = [];
    const unexpected: string[] = [];
    const external: string[] = [];
    page.on("request", (request) => {
        const url = new URL(request.url());
        if (url.protocol.startsWith("http") && url.origin !== "http://127.0.0.1:4173")
            external.push(request.url());
    });
    await page.route("**/api/v2/research/**", async (route) => {
        const url = new URL(route.request().url());
        const path = url.pathname;
        requests.push({ method: route.request().method(), url });
        const json = (body: unknown, status = 200) =>
            route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
        if (route.request().method() !== "GET") {
            unexpected.push(`${route.request().method()} ${path}`);
            await json(
                {
                    schema_version: 2,
                    code: "INVALID_QUERY",
                    detail: "Read-only fixture rejects commands"
                },
                400
            );
            return;
        }
        if (path === "/api/v2/research/catalog/calculations") {
            await json({
                schema_version: 2,
                calculations: [
                    catalogItem("1.0.0"),
                    catalogItem("2.0.0"),
                    catalogItem("1.0.0", true)
                ]
            });
            return;
        }
        if (path === "/api/v2/research/catalog/universes") {
            await json({
                schema_version: 2,
                selection_kinds: ["SINGLE_INSTRUMENT", "EXPLICIT_INSTRUMENT_SET"],
                registered_universes: []
            });
            return;
        }
        if (path === "/api/v2/research/catalog/statistics") {
            await json({
                schema_version: 2,
                statistics: ["IC", "RANK_IC"].map((method) => ({
                    statistic_type: method,
                    variable_kinds: ["FACTOR"],
                    variable_semantic_roles: ["FACTOR_SCORE"],
                    target_semantic_roles: ["TARGET_VALUE"],
                    target_required: true,
                    executable: true
                }))
            });
            return;
        }
        if (path === "/api/v2/research/catalog/dataset-fields") {
            await json({
                schema_version: 2,
                dataset_fields: [
                    {
                        source: "bar.close",
                        field_name: "close",
                        data_type: "DECIMAL",
                        semantic_roles: ["PRICE"],
                        dimensions: ["INSTRUMENT", "TIME"],
                        unit: "PRICE"
                    }
                ]
            });
            return;
        }
        if (path === "/api/v2/research/runs") {
            await json({
                schema_version: 2,
                runs: [
                    {
                        schema_version: 2,
                        run_id: runId,
                        revision: "2",
                        state: "COMPLETED",
                        specification_schema_version: 2,
                        specification_fingerprint: "c".repeat(64),
                        admission_resolution_fingerprint: "d".repeat(64),
                        queued_at: "2024-03-02T00:00:00Z",
                        started_at: "2024-03-02T00:00:01Z",
                        cancel_requested_at: null,
                        finished_at: "2024-03-02T00:00:02Z",
                        result_ref: result,
                        artifact_ref: "f".repeat(64),
                        failure: null
                    }
                ],
                has_more: false,
                next_cursor: null
            });
            return;
        }
        if (path === artifactPath) {
            await json({
                schema_version: 2,
                research_result_fingerprint: result,
                research_result_plan_fingerprint: "c".repeat(64),
                research_result_content_fingerprint: "d".repeat(64),
                dataset_snapshot_fingerprint: "e".repeat(64),
                artifact_content_fingerprint: "f".repeat(64),
                research_result_schema_version: 2,
                artifact_profile: "RESEARCH_SCIENTIFIC_V2",
                artifact_schema_version: 2,
                statistics_count: 2,
                row_count: 4,
                candidate_count: 1,
                published_series_count: 1,
                signal_series_count: 0,
                market_row_count: 4,
                instrument_ids: [firstStock, secondStock],
                created_at: "2024-03-02T00:00:00Z"
            });
            return;
        }
        if (path === `${artifactPath}/candidates`) {
            await json({
                schema_version: 2,
                research_result_fingerprint: result,
                candidates: [
                    {
                        candidate_fingerprint: candidate,
                        candidate_calculation_id: "momentum",
                        assignment: {},
                        assignment_types: {},
                        calculation_fingerprint: calculation,
                        graph_fingerprint: graph,
                        statistics_fingerprints: [ic, rankIc],
                        signal_roles: []
                    }
                ]
            });
            return;
        }
        if (path === `${artifactPath}/variables`) {
            await json({
                schema_version: 2,
                research_result_fingerprint: result,
                series: [
                    {
                        candidate_fingerprint: candidate,
                        calculation_fingerprint: calculation,
                        node_fingerprint: node,
                        output_name: "score",
                        value_kind: "DECIMAL"
                    }
                ]
            });
            return;
        }
        if (path === `${artifactPath}/candidates/${candidate}/graph`) {
            await json({
                schema_version: 2,
                research_result_fingerprint: result,
                candidate_fingerprint: candidate,
                calculation_fingerprint: calculation,
                graph_fingerprint: graph,
                graph: {
                    schema_version: 1,
                    nodes: [
                        {
                            node_fingerprint: node,
                            alias: "Momentum",
                            definition: {
                                schema_version: 2,
                                kind: "FACTOR",
                                type_id: factorType,
                                semantic_version: "1.0.0",
                                parameters: {},
                                inputs: [pricePort],
                                input_bindings: {
                                    price: {
                                        node_fingerprint: null,
                                        output_name: "close",
                                        source: "bar.close"
                                    }
                                },
                                outputs: [scorePort],
                                warmup: {
                                    minimum_observations: 1,
                                    ready_condition: "READY",
                                    pre_ready_output: "NULL",
                                    initialization: "FIRST_OBSERVATION"
                                },
                                missing_values: "PROPAGATE",
                                timestamp: "OBSERVATION_TIME",
                                numeric: {
                                    representation: "DECIMAL",
                                    precision: 38,
                                    output_quantum: "0.000000000001",
                                    rounding: "ROUND_HALF_EVEN"
                                },
                                factor_kind: "CROSS_SECTION",
                                extensions: {}
                            }
                        }
                    ]
                }
            });
            return;
        }
        if (path === `${artifactPath}/statistics`) {
            await json({
                schema_version: 2,
                research_result_fingerprint: result,
                statistics: [statistic(ic, "IC"), statistic(rankIc, "RANK_IC")]
            });
            return;
        }
        if (path === `${artifactPath}/market/series` || path === variablePath) {
            const instrument = url.searchParams.get("instrument_id");
            if (instrument !== firstStock && instrument !== secondStock) {
                unexpected.push(`Unknown instrument: ${String(instrument)}`);
                await json(
                    {
                        schema_version: 2,
                        code: "INVALID_QUERY",
                        detail: "Unknown fixture instrument"
                    },
                    400
                );
                return;
            }
            const points = [firstTime, secondTime]
                .filter((timestamp) => inRequestedRange(timestamp, url))
                .map((timestamp) =>
                    path === variablePath
                        ? {
                              instrument_id: instrument,
                              ts_event_ns: timestamp,
                              value_kind: "DECIMAL",
                              decimal_value:
                                  timestamp === secondTime
                                      ? null
                                      : instrument === firstStock
                                        ? "-0.000000000001"
                                        : "0.125000000000",
                              integer_value: null,
                              boolean_value: null,
                              string_value: null
                          }
                        : {
                              instrument_id: instrument,
                              ts_event_ns: timestamp,
                              open: "100.000000000000",
                              high: "112.000000000000",
                              low: "95.000000000000",
                              close:
                                  timestamp === firstTime ? "105.000000000000" : "110.000000000000",
                              volume: "1000.000000000000"
                          }
                );
            await json({
                schema_version: 2,
                research_result_fingerprint: result,
                points,
                has_more: false,
                next_after_ts_event_ns: null
            });
            return;
        }
        if (
            path === `${artifactPath}/statistics/${ic}/series` ||
            path === `${artifactPath}/statistics/${rankIc}/series`
        ) {
            const selected = path.includes(rankIc) ? rankIc : ic;
            await json({
                schema_version: 2,
                research_result_fingerprint: result,
                statistics_fingerprint: selected,
                points: [firstTime, secondTime]
                    .filter((timestamp) => inRequestedRange(timestamp, url))
                    .map((timestamp) => ({
                        ts_event_ns: timestamp,
                        statistic_value: timestamp === secondTime ? null : "1.000000000000",
                        sample_count: timestamp === secondTime ? 1 : 2,
                        status: timestamp === secondTime ? "INSUFFICIENT_OBSERVATIONS" : "VALID"
                    })),
                has_more: false,
                next_after_ts_event_ns: null
            });
            return;
        }
        unexpected.push(path);
        await json(
            { schema_version: 2, code: "INVALID_QUERY", detail: "Unexpected fixture request" },
            400
        );
    });
    return { requests, unexpected, external };
}

async function openSelectedFactor(page: Page) {
    const catalog = page.getByRole("complementary", { name: "Registered Factor catalog" });
    await catalog.getByRole("button", { name: /1\.0\.0.*example\.factor\.momentum/ }).click();
    await page.getByLabel("Completed Factor Research Run").selectOption(runId);
    const first = page.getByRole("region", { name: `${firstStock} Factor evidence` });
    await expect(
        first.getByRole("figure", { name: "Financial evidence chart with independent Factor pane" })
    ).toBeVisible();
    await expect(first.getByTestId("financial-chart").locator("canvas").first()).toBeVisible();
    await page.getByLabel("Correlation statistic").selectOption(ic);
    const correlation = page.getByRole("region", { name: "Factor / Target correlation" });
    await expect(correlation.getByTestId("scientific-chart")).toBeVisible();
    const originalRow = correlation.locator("tbody tr").filter({ hasText: firstTime });
    await expect(originalRow.getByRole("cell", { name: "2", exact: true })).toBeVisible();
    return { first, correlation, originalRow };
}

async function noPageOverflow(page: Page) {
    const dimensions = await page.evaluate(() => ({
        width: document.documentElement.scrollWidth,
        viewport: window.innerWidth
    }));
    expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
}

test("desktop Factor catalog, real independent panes, original-population IC, UTC range and explicit Builder seed", async ({
    page
}, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const observations = await mockFactorEvidence(page);
    await page.goto("/research/factors");
    await expect(page.getByRole("link", { name: "Factor Explorer", exact: true })).toBeVisible();
    const catalog = page.getByRole("complementary", { name: "Registered Factor catalog" });
    await expect(catalog.getByRole("button", { name: /example\.factor\.momentum/ })).toHaveCount(2);
    await expect(catalog.getByText("example.indicator.sma", { exact: true })).toHaveCount(0);
    await page.getByLabel("Search registered Factors").fill("momentum 2.0.0");
    await expect(catalog.getByRole("button", { name: /example\.factor\.momentum/ })).toHaveCount(1);
    await expect(
        catalog.getByRole("button", { name: /2\.0\.0.*example\.factor\.momentum/ })
    ).toBeVisible();
    await page.getByLabel("Search registered Factors").fill("");
    const { first, correlation, originalRow } = await openSelectedFactor(page);
    await expect(page.getByRole("checkbox", { name: firstStock, exact: true })).toBeChecked();
    await expect(page.getByRole("checkbox", { name: secondStock, exact: true })).not.toBeChecked();
    await expect(
        correlation.getByText(/Statistics population: original Research universe/)
    ).toBeVisible();
    await expect(correlation.getByRole("cell", { name: "NULL", exact: true })).toBeVisible();
    await expect(
        correlation.getByRole("cell", { name: "INSUFFICIENT_OBSERVATIONS", exact: true })
    ).toBeVisible();
    await first.getByText("Exact Factor data (2 rows)", { exact: true }).click();
    await expect(
        first
            .getByRole("table", { name: `${firstStock} exact Factor evidence` })
            .getByRole("cell", { name: "NULL", exact: true })
    ).toBeVisible();
    await expect(first.getByRole("cell", { name: "-0.000000000001", exact: true })).toBeVisible();
    await page.getByRole("checkbox", { name: secondStock, exact: true }).check();
    await expect(
        page.getByRole("figure", { name: "Financial evidence chart with independent Factor pane" })
    ).toHaveCount(2);
    await expect(originalRow.getByRole("cell", { name: "2", exact: true })).toBeVisible();
    await page.getByRole("checkbox", { name: firstStock, exact: true }).uncheck();
    await expect(
        page.getByRole("figure", { name: "Financial evidence chart with independent Factor pane" })
    ).toHaveCount(1);
    await expect(originalRow.getByRole("cell", { name: "2", exact: true })).toBeVisible();
    await page.getByRole("checkbox", { name: firstStock, exact: true }).check();
    await expect(
        page.getByRole("figure", { name: "Financial evidence chart with independent Factor pane" })
    ).toHaveCount(2);
    await first.getByText("Exact Factor data (2 rows)", { exact: true }).click();
    await expect(
        first
            .getByRole("table", { name: `${firstStock} exact Factor evidence` })
            .getByRole("cell", { name: "NULL", exact: true })
    ).toBeVisible();
    await noPageOverflow(page);
    await page.screenshot({ path: testInfo.outputPath("factor-desktop.png"), fullPage: true });

    await page.getByLabel("From UTC (inclusive)").fill("2024-02-29");
    await page.getByLabel("To UTC (exclusive)").fill("2024-03-01");
    await page.getByRole("button", { name: "Apply time window" }).click();
    for (const stock of [firstStock, secondStock]) {
        await expect(
            page
                .getByRole("region", { name: `${stock} Factor evidence` })
                .getByText(/1 Market rows · 1 Factor rows loaded/)
        ).toBeVisible();
    }
    await expect(correlation.locator("tbody tr")).toHaveCount(1);
    await expect(correlation.getByRole("cell", { name: secondTime, exact: true })).toHaveCount(0);
    await expect(
        correlation.getByRole("cell", { name: "1.000000000000", exact: true })
    ).toBeVisible();
    const ranged = observations.requests.filter(
        ({ url }) =>
            url.searchParams.get("from_ts_event_ns") === firstTime &&
            url.searchParams.get("to_ts_event_ns") === secondTime
    );
    for (const stock of [firstStock, secondStock]) {
        expect(
            ranged.some(
                ({ url }) =>
                    url.pathname === `${artifactPath}/market/series` &&
                    url.searchParams.get("instrument_id") === stock
            )
        ).toBe(true);
        expect(
            ranged.some(
                ({ url }) =>
                    url.pathname === variablePath &&
                    url.searchParams.get("instrument_id") === stock &&
                    url.searchParams.get("candidate_fingerprint") === candidate
            )
        ).toBe(true);
    }
    expect(
        ranged.some(({ url }) => url.pathname === `${artifactPath}/statistics/${ic}/series`)
    ).toBe(true);
    await page.getByLabel("Correlation statistic").selectOption(rankIc);
    await expect(
        correlation.getByText(/Rank IC · average-rank Spearman cross-sectional correlation/)
    ).toBeVisible();
    await expect(
        correlation.getByRole("cell", { name: "1.000000000000", exact: true })
    ).toBeVisible();
    expect(new URL(page.url()).searchParams.get("statistic")).toBe(rankIc);
    expect(
        observations.requests.some(
            ({ url }) =>
                url.pathname === `${artifactPath}/statistics/${rankIc}/series` &&
                url.searchParams.get("from_ts_event_ns") === firstTime &&
                url.searchParams.get("to_ts_event_ns") === secondTime
        )
    ).toBe(true);

    await page.getByRole("link", { name: "Research this selection →", exact: true }).click();
    await expect(page.getByRole("heading", { name: "New Research", exact: true })).toBeVisible();
    const seed = new URL(page.url()).searchParams;
    expect(seed.get("factor")).toBe(factorKey);
    expect(seed.getAll("instrument").sort()).toEqual([firstStock, secondStock]);
    expect(seed.get("from")).toBe("2024-02-29");
    expect(seed.get("to")).toBe("2024-03-01");
    await expect(page.getByLabel("Instrument IDs")).toHaveValue("");
    await page.getByRole("button", { name: "Apply Factor Explorer selection" }).click();
    await expect(page.getByLabel("Instrument IDs")).toHaveValue(`${secondStock}, ${firstStock}`);
    await expect(page.getByLabel("Start", { exact: true })).toHaveValue("2024-02-29T00:00:00Z");
    await expect(page.getByLabel("End", { exact: true })).toHaveValue("2024-03-01T00:00:00Z");
    await expect(page.getByRole("combobox", { name: "Input · price", exact: true })).toHaveValue(
        ""
    );
    await expect(page.getByRole("button", { name: "Run", exact: true })).toBeDisabled();
    await expect(page.getByLabel("Method", { exact: true })).toHaveCount(0);
    expect(observations.requests.every(({ method }) => method === "GET")).toBe(true);
    expect(observations.unexpected).toEqual([]);
    expect(observations.external).toEqual([]);
});

test("390px Factor navigation and real stock-basket evidence remain usable without page overflow", async ({
    page
}, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const observations = await mockFactorEvidence(page);
    await page.goto("/research/results");
    await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page.getByRole("link", { name: "Factor Explorer", exact: true }).click();
    await expect(page).toHaveURL("/research/factors");
    await expect(page.getByRole("button", { name: "Toggle navigation" })).toHaveAttribute(
        "aria-expanded",
        "false"
    );
    const { first, correlation, originalRow } = await openSelectedFactor(page);
    await page.getByRole("checkbox", { name: secondStock, exact: true }).check();
    await expect(
        page.getByRole("figure", { name: "Financial evidence chart with independent Factor pane" })
    ).toHaveCount(2);
    await expect(originalRow.getByRole("cell", { name: "2", exact: true })).toBeVisible();
    await first.getByText("Exact Factor data (2 rows)", { exact: true }).click();
    await expect(
        first
            .getByRole("table", { name: `${firstStock} exact Factor evidence` })
            .getByRole("cell", { name: "NULL", exact: true })
    ).toBeVisible();
    await expect(
        correlation.getByText(/not a single-stock temporal correlation coefficient/)
    ).toBeVisible();
    await noPageOverflow(page);
    await page.screenshot({ path: testInfo.outputPath("factor-mobile.png"), fullPage: true });
    expect(observations.requests.every(({ method }) => method === "GET")).toBe(true);
    expect(observations.unexpected).toEqual([]);
    expect(observations.external).toEqual([]);
});
