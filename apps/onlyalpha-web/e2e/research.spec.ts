import { expect, test, type Page } from "@playwright/test";

const result = "c1c188880821de9790dfcc84a075c8bdd615f273c27f9fa75bcccc1e812d33cc";
const statistics = "a23de5e058ec65fe9251b525f10c9b4d8a4b7a4b62d478214a1f0a7c50eef411";
const runId = "00000000-0000-4000-8000-000000000301";
const exactSpecification = { schema_version: 2, exact: "authoritative-e2e-specification" };
const candidateA = "1".repeat(64);
const candidateB = "2".repeat(64);
const calculationA = "3".repeat(64);
const calculationB = "4".repeat(64);
const nodeA = "5".repeat(64);
const nodeB = "6".repeat(64);
const graphA = "7".repeat(64);
const graphB = "8".repeat(64);
const statisticB = "9".repeat(64);

async function mockScientificWorkstation(page: Page, multipleCandidates: boolean) {
    const candidates = [
        {
            candidate_fingerprint: candidateA,
            candidate_calculation_id: "decision",
            assignment: { period: 14 },
            assignment_types: { period: "INTEGER" },
            calculation_fingerprint: calculationA,
            graph_fingerprint: graphA,
            statistics_fingerprints: [statistics],
            signal_roles: ["ENTRY_SIGNAL", "EXIT_SIGNAL"]
        },
        ...(multipleCandidates
            ? [
                  {
                      candidate_fingerprint: candidateB,
                      candidate_calculation_id: "decision",
                      assignment: { period: 28 },
                      assignment_types: { period: "INTEGER" },
                      calculation_fingerprint: calculationB,
                      graph_fingerprint: graphB,
                      statistics_fingerprints: [statisticB],
                      signal_roles: ["ENTRY_SIGNAL", "EXIT_SIGNAL"]
                  }
              ]
            : [])
    ];
    const descriptor = (fingerprint: string, calculation: string, node: string) => ({
        statistics_fingerprint: fingerprint,
        statistics_result_fingerprint: "a".repeat(64),
        result_content_fingerprint: "b".repeat(64),
        statistics_result_schema_version: 1,
        row_count: 1,
        feature: {
            calculation_fingerprint: calculation,
            node_fingerprint: node,
            output_name: "rsi"
        },
        target: {
            calculation_fingerprint: calculation,
            node_fingerprint: node,
            output_name: "forward_return"
        },
        definition: {
            method: "IC",
            minimum_observations: 2,
            pairing_policy: "PAIRWISE_COMPLETE",
            universe_policy: "EXACT",
            rank_tie_method: "AVERAGE",
            weighting: "EQUAL",
            numeric: {
                representation: "DECIMAL",
                precision: 38,
                output_quantum: "0.0001",
                rounding: "ROUND_HALF_EVEN"
            }
        }
    });
    await page.route(`**/api/v2/research/artifacts/${result}`, async (route) => {
        const path = new URL(route.request().url()).pathname;
        if (path !== `/api/v2/research/artifacts/${result}`) return route.fallback();
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                schema_version: 2,
                research_result_plan_fingerprint: "c".repeat(64),
                research_result_content_fingerprint: "d".repeat(64),
                research_result_fingerprint: result,
                dataset_snapshot_fingerprint: "e".repeat(64),
                artifact_content_fingerprint: "f".repeat(64),
                research_result_schema_version: 2,
                artifact_profile: "RESEARCH_SCIENTIFIC_V2",
                artifact_schema_version: 2,
                statistics_count: candidates.length,
                row_count: candidates.length,
                candidate_count: candidates.length,
                published_series_count: candidates.length,
                signal_series_count: candidates.length * 2,
                market_row_count: 2,
                instrument_ids: ["510300"],
                created_at: "2026-08-21T00:00:00Z"
            })
        });
    });
    await page.route(`**/api/v2/research/artifacts/${result}/candidates`, (route) =>
        route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                schema_version: 2,
                research_result_fingerprint: result,
                candidates
            })
        })
    );
    await page.route(`**/api/v2/research/artifacts/${result}/variables`, (route) =>
        route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                schema_version: 2,
                research_result_fingerprint: result,
                series: candidates.map((candidate, index) => ({
                    candidate_fingerprint: candidate.candidate_fingerprint,
                    calculation_fingerprint: candidate.calculation_fingerprint,
                    node_fingerprint: index === 0 ? nodeA : nodeB,
                    output_name: "rsi",
                    value_kind: "DECIMAL"
                }))
            })
        })
    );
    await page.route(`**/api/v2/research/artifacts/${result}/statistics`, (route) =>
        route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                schema_version: 2,
                research_result_fingerprint: result,
                statistics: [
                    descriptor(statistics, calculationA, nodeA),
                    ...(multipleCandidates ? [descriptor(statisticB, calculationB, nodeB)] : [])
                ]
            })
        })
    );
    await page.route(
        `**/api/v2/research/artifacts/${result}/statistics/*/series**`,
        async (route) => {
            const second = new URL(route.request().url()).pathname.includes(statisticB);
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    schema_version: 2,
                    research_result_fingerprint: result,
                    statistics_fingerprint: second ? statisticB : statistics,
                    points: [
                        {
                            ts_event_ns: "2000000000",
                            statistic_value: second ? "0.2" : "0.1",
                            sample_count: 300,
                            status: "VALID"
                        }
                    ],
                    has_more: false,
                    next_after_ts_event_ns: null
                })
            });
        }
    );
    await page.route(`**/api/v2/research/artifacts/${result}/market/series**`, (route) =>
        route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                schema_version: 2,
                research_result_fingerprint: result,
                points: [
                    {
                        instrument_id: "510300",
                        ts_event_ns: "1000000000",
                        open: "10",
                        high: "12",
                        low: "9",
                        close: "11",
                        volume: "100"
                    },
                    {
                        instrument_id: "510300",
                        ts_event_ns: "2000000000",
                        open: "11",
                        high: "13",
                        low: "10",
                        close: "12",
                        volume: "110"
                    }
                ],
                has_more: false,
                next_after_ts_event_ns: null
            })
        })
    );
    await page.route(`**/api/v2/research/artifacts/${result}/variables/*/*/rsi/series**`, (route) =>
        route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                schema_version: 2,
                research_result_fingerprint: result,
                points: [
                    {
                        instrument_id: "510300",
                        ts_event_ns: "1000000000",
                        value_kind: "DECIMAL",
                        decimal_value: "29.5",
                        integer_value: null,
                        boolean_value: null,
                        string_value: null
                    }
                ],
                has_more: false,
                next_after_ts_event_ns: null
            })
        })
    );
    await page.route(
        `**/api/v2/research/artifacts/${result}/signals/*/*/series**`,
        async (route) => {
            const entry = new URL(route.request().url()).pathname.includes("ENTRY_SIGNAL");
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    schema_version: 2,
                    research_result_fingerprint: result,
                    points: [
                        {
                            instrument_id: "510300",
                            ts_event_ns: "1000000000",
                            value: entry ? true : null
                        },
                        { instrument_id: "510300", ts_event_ns: "2000000000", value: false }
                    ],
                    has_more: false,
                    next_after_ts_event_ns: null
                })
            });
        }
    );
    await page.route(`**/api/v2/research/artifacts/${result}/candidates/*/graph`, async (route) => {
        const second = new URL(route.request().url()).pathname.includes(candidateB);
        const candidate = second ? candidateB : candidateA;
        const calculation = second ? calculationB : calculationA;
        const node = second ? nodeB : nodeA;
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                schema_version: 2,
                research_result_fingerprint: result,
                candidate_fingerprint: candidate,
                calculation_fingerprint: calculation,
                graph_fingerprint: second ? graphB : graphA,
                graph: {
                    schema_version: 1,
                    nodes: [graphNode(node)]
                }
            })
        });
    });
}

function graphNode(nodeFingerprint: string) {
    return {
        node_fingerprint: nodeFingerprint,
        alias: "rsi",
        definition: {
            schema_version: 2,
            kind: "INDICATOR",
            type_id: "onlyalpha.indicator.rsi",
            semantic_version: "1",
            parameters: { period: { type: "INTEGER", value: 14 } },
            inputs: [],
            input_bindings: {},
            outputs: [
                {
                    name: "rsi",
                    data_type: "DECIMAL",
                    nullable: true,
                    dimensions: ["TIME"],
                    semantic_type: "INDICATOR_VALUE",
                    unit: null
                }
            ],
            warmup: {
                minimum_observations: 14,
                ready_condition: "READY",
                pre_ready_output: "NULL",
                initialization: "WINDOW"
            },
            missing_values: "PROPAGATE",
            timestamp: "EVENT_TIME",
            numeric: {
                representation: "DECIMAL",
                precision: 38,
                output_quantum: null,
                rounding: "CONTEXT"
            },
            factor_kind: null,
            extensions: {}
        }
    };
}

const catalogs = {
    calculations: {
        schema_version: 2,
        calculations: [
            {
                kind: "FACTOR",
                type_reference: { kind: "FACTOR", type_id: "e2e.factor", semantic_version: "1" },
                parameters: [],
                inputs: [],
                outputs: [
                    {
                        name: "score",
                        data_type: "DECIMAL",
                        nullable: true,
                        semantic_type: "FACTOR_SCORE",
                        dimensions: ["INSTRUMENT", "TIME"],
                        unit: null
                    }
                ],
                parameter_sweep_allowed: true
            },
            {
                kind: "TARGET",
                type_reference: { kind: "TARGET", type_id: "e2e.target", semantic_version: "1" },
                parameters: [],
                inputs: [
                    {
                        name: "price",
                        data_type: "DECIMAL",
                        nullable: false,
                        semantic_type: "PRICE",
                        dimensions: ["INSTRUMENT", "TIME"],
                        unit: null
                    }
                ],
                outputs: [
                    {
                        name: "target_value",
                        data_type: "DECIMAL",
                        nullable: true,
                        semantic_type: "TARGET_VALUE",
                        dimensions: ["INSTRUMENT", "TIME"],
                        unit: null
                    }
                ],
                parameter_sweep_allowed: false
            }
        ]
    },
    universes: {
        schema_version: 2,
        selection_kinds: ["SINGLE_INSTRUMENT", "EXPLICIT_INSTRUMENT_SET"],
        registered_universes: []
    },
    statistics: {
        schema_version: 2,
        statistics: [
            {
                statistic_type: "IC",
                variable_kinds: ["FACTOR"],
                variable_semantic_roles: ["FACTOR_SCORE"],
                target_semantic_roles: ["TARGET_VALUE"],
                target_required: true,
                executable: true
            }
        ]
    },
    "dataset-fields": {
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
    }
} as const;

const resolution = {
    schema_version: 2,
    authoring_definition_fingerprint: "a".repeat(64),
    resolved_definition_fingerprint: "b".repeat(64),
    dataset_snapshot_fingerprint: "c".repeat(64),
    specification_fingerprint: "d".repeat(64),
    resolved_dataset_definition: {},
    instrument_count: 1,
    candidate_count: 1,
    candidates: [],
    published_variables: [
        {
            instance_key: "factor_1",
            output_name: "score",
            data_type: "DECIMAL",
            semantic_type: "FACTOR_SCORE"
        }
    ],
    exact_specification: exactSpecification,
    diagnostics: []
};

async function mockStudioCatalogs(page: Page) {
    await page.route("**/api/v2/research/catalog/**", async (route) => {
        const parts = new URL(route.request().url()).pathname.split("/");
        const name = parts[parts.length - 1];
        if (
            name !== "calculations" &&
            name !== "universes" &&
            name !== "statistics" &&
            name !== "dataset-fields"
        )
            throw new Error(`Unexpected catalog route: ${name}`);
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(catalogs[name])
        });
    });
    await page.route("**/api/v2/research/definitions/resolve", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(resolution)
        });
    });
}

async function completeMinimalResearch(page: Page) {
    await page.getByLabel("Instrument IDs").fill("A.XNAS");
    await page.getByLabel("Start").fill("2026-01-01T00:00:00Z");
    await page.getByLabel("End").fill("2026-06-01T00:00:00Z");
    await page
        .getByLabel("Add Calculations")
        .locator("xpath=ancestor::section")
        .getByRole("button", { name: "Add" })
        .click();
    await page
        .getByLabel("Add Targets")
        .locator("xpath=ancestor::section")
        .getByRole("button", { name: "Add" })
        .click();
    await page.getByLabel("Input · price").selectOption("bar.close");
    await page.getByRole("button", { name: "Add Statistics" }).click();
}

test("portable Artifact to API v2 to browser exact vertical slice", async ({ page }) => {
    await page.goto("/research/results");
    await page.getByLabel("Research Result fingerprint").fill(result);
    await page.getByRole("button", { name: "Open exact result" }).click();
    await expect(page.getByRole("heading", { name: "Scientific Workstation" })).toBeVisible();
    await expect(page.getByText(result).first()).toBeVisible();
    await page.getByRole("tab", { name: "Statistics" }).click();
    await expect(page.getByTestId("scientific-chart")).toBeVisible();
    await page.reload();
    await expect(page).toHaveURL(`/research/results/${result}`);
    await page.getByRole("tab", { name: "Statistics" }).click();
    await expect(page.getByTestId("scientific-chart")).toBeVisible();
    await expect(page.locator("table").filter({ hasText: "Raw ts_event_ns" })).toBeVisible();
    await expect(page.getByRole("cell", { name: /^176/ }).first()).toBeVisible();
});

test("Research Definition resolve lifecycle invalidates stale evidence after edit", async ({
    page
}) => {
    await mockStudioCatalogs(page);
    await page.goto("/research/new");
    await completeMinimalResearch(page);
    await page.getByRole("button", { name: "Resolve" }).click();
    await expect(page.getByText("RESOLVED", { exact: true })).toBeVisible();
    await expect(page.getByText("1", { exact: true }).nth(0)).toBeVisible();
    await expect(page.getByText("d".repeat(64))).toBeVisible();
    await page.getByLabel("Instrument IDs").fill("A.XNAS, B.XNAS");
    await expect(page.getByText("UNRESOLVED", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Run" })).toBeDisabled();
});

test("uncertain Run submission retry preserves one Idempotency-Key", async ({ page }) => {
    await mockStudioCatalogs(page);
    const submissionKeys: string[] = [];
    let attempts = 0;
    await page.route("**/api/v2/research/runs", async (route) => {
        if (route.request().method() !== "POST") return route.fallback();
        attempts += 1;
        const key = route.request().headers()["idempotency-key"];
        submissionKeys.push(key);
        if (attempts === 1) {
            await route.fulfill({
                status: 500,
                contentType: "application/json",
                body: JSON.stringify({ unexpected: "uncertain response" })
            });
            return;
        }
        await route.fulfill({
            status: 202,
            contentType: "application/json",
            body: JSON.stringify({
                submission_disposition: "CREATED",
                run: {
                    schema_version: 2,
                    run_id: runId,
                    revision: "0",
                    state: "QUEUED",
                    specification_schema_version: 2,
                    specification_fingerprint: "d".repeat(64),
                    admission_resolution_fingerprint: "e".repeat(64),
                    queued_at: "2026-08-21T00:00:00Z",
                    started_at: null,
                    cancel_requested_at: null,
                    finished_at: null,
                    result_ref: null,
                    artifact_ref: null,
                    failure: null,
                    specification: exactSpecification
                }
            })
        });
    });
    await page.goto("/research/new");
    await completeMinimalResearch(page);
    await page.getByRole("button", { name: "Resolve" }).click();
    await page.getByRole("button", { name: "Run" }).click();
    await expect(page.getByRole("alert")).toContainText("CONTRACT_ERROR");
    await page.getByRole("button", { name: "Run" }).click();
    await expect(page).toHaveURL(`/research/runs/${runId}`);

    expect(submissionKeys).toHaveLength(2);
    expect(submissionKeys[1]).toBe(submissionKeys[0]);
});

test("exact resolved Specification submits to durable Run and opens exact Result", async ({
    page
}) => {
    await mockStudioCatalogs(page);
    let getCount = 0;
    const run = (state: "QUEUED" | "RUNNING" | "COMPLETED") => ({
        schema_version: 2,
        run_id: runId,
        revision: state === "COMPLETED" ? "2" : state === "RUNNING" ? "1" : "0",
        state,
        specification_schema_version: 2,
        specification_fingerprint: "d".repeat(64),
        admission_resolution_fingerprint: "e".repeat(64),
        queued_at: "2026-08-21T00:00:00Z",
        started_at: state === "QUEUED" ? null : "2026-08-21T00:00:01Z",
        cancel_requested_at: null,
        finished_at: state === "COMPLETED" ? "2026-08-21T00:00:02Z" : null,
        result_ref: state === "COMPLETED" ? result : null,
        artifact_ref: state === "COMPLETED" ? result : null,
        failure: null,
        specification: exactSpecification
    });
    await page.route("**/api/v2/research/runs", async (route) => {
        if (route.request().method() !== "POST") return route.fallback();
        const submitted: unknown = await route.request().postDataJSON();
        expect(submitted).toEqual({ specification: exactSpecification });
        await route.fulfill({
            status: 202,
            contentType: "application/json",
            body: JSON.stringify({ submission_disposition: "CREATED", run: run("QUEUED") })
        });
    });
    await page.route(`**/api/v2/research/runs/${runId}`, async (route) => {
        getCount += 1;
        const state = getCount === 1 ? "RUNNING" : "COMPLETED";
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(run(state))
        });
    });
    await page.goto("/research/new");
    await completeMinimalResearch(page);
    await page.getByRole("button", { name: "Resolve" }).click();
    await page.getByRole("button", { name: "Run" }).click();
    await expect(page).toHaveURL(`/research/runs/${runId}`);
    await expect(page.getByText("RUNNING", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("COMPLETED", { exact: true }).first()).toBeVisible({
        timeout: 6_000
    });
    await page.getByRole("link", { name: "Open exact Result" }).click();
    await expect(page).toHaveURL(`/research/results/${result}`);
    await expect(page.getByRole("heading", { name: "Scientific Workstation" })).toBeVisible();
});

test("single-instrument Signal Research opens authoritative Market Exact Data and Graph", async ({
    page
}) => {
    await mockScientificWorkstation(page, false);
    await page.goto(`/research/results/${result}`);
    await page.getByRole("tab", { name: "Market" }).click();
    await expect(page.getByTestId("financial-chart")).toBeVisible();
    await expect(page.getByText(/2 market · 1 variable · 4 signal rows loaded/)).toBeVisible();
    await page.getByRole("tab", { name: "Exact Data" }).click();
    await expect(page.getByRole("heading", { name: "Signal · ENTRY_SIGNAL" })).toBeVisible();
    await expect(page.getByText("true", { exact: true })).toBeVisible();
    await expect(page.getByText("NULL", { exact: true })).toBeVisible();
    await page.getByRole("tab", { name: "Graph" }).click();
    await expect(page.getByTestId("graphviz-view")).toBeVisible();
    await expect(page.getByText(graphA)).toBeAttached();
});

test("multi-Candidate sweep keeps comparison and exact Graph on one Candidate", async ({
    page
}) => {
    await mockScientificWorkstation(page, true);
    await page.goto(`/research/results/${result}`);
    await page.getByRole("tab", { name: "Candidates" }).click();
    await expect(page.getByTestId("scientific-chart")).toBeVisible();
    await expect(page.getByText(/exact timestamp 2000000000/i)).toBeVisible();
    const rows = page.getByRole("row");
    await rows.nth(2).getByRole("button", { name: "Select" }).click();
    await page.getByRole("tab", { name: "Graph" }).click();
    await expect(page.getByTestId("graphviz-view")).toBeVisible();
    await expect(page.getByText(graphB)).toBeAttached();
});
