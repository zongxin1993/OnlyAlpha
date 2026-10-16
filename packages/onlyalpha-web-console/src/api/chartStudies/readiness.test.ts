import { isChartStudyReadiness } from "./client";

it.each([
    ["PARTIAL", "WARMUP_INCOMPLETE", null],
    ["PARTIAL", "WARMUP_INCOMPLETE", "1.0"],
    ["READY", "NONE", "1.0"],
    ["READY", "VALUE_UNDEFINED", null],
    ["UNAVAILABLE", "INPUT_UNAVAILABLE", null],
    ["UNAVAILABLE", "DEPENDENCY_UNAVAILABLE", null]
] as const)("admits canonical nullable output %s/%s/%s", (readiness, reason, value) => {
    expect(isChartStudyReadiness({ readiness, reason, value }, true)).toBe(true);
});
it.each([
    ["PARTIAL", "NONE", "1.0"],
    ["PARTIAL", "VALUE_UNDEFINED", null],
    ["READY", "NONE", null],
    ["READY", "VALUE_UNDEFINED", "1.0"],
    ["UNAVAILABLE", "INPUT_UNAVAILABLE", "1.0"],
    ["UNAVAILABLE", "NONE", null],
    ["UNKNOWN", "NONE", null]
] as const)("rejects contradictory output %s/%s/%s", (readiness, reason, value) => {
    expect(isChartStudyReadiness({ readiness, reason, value }, true)).toBe(false);
});
it("keeps nonnullable warmup and ready outputs nonnull without inferring readiness from values", () => {
    expect(
        isChartStudyReadiness(
            { readiness: "PARTIAL", reason: "WARMUP_INCOMPLETE", value: null },
            false
        )
    ).toBe(false);
    expect(
        isChartStudyReadiness({ readiness: "READY", reason: "VALUE_UNDEFINED", value: null }, false)
    ).toBe(false);
    expect(
        isChartStudyReadiness(
            { readiness: "PARTIAL", reason: "WARMUP_INCOMPLETE", value: "1" },
            false
        )
    ).toBe(true);
});

it("admits nullable warmup and undefined values produced by the installed indicator backends", async () => {
    const { default: fixture } =
        await import("../../../../../test-data/web/chart-studies/numeric-cases.json");
    expect(fixture.source_kind).toBe("INSTALLED_CALCULATION_BACKEND");
    expect(fixture.cases.some((row) => row.readiness === "PARTIAL" && row.value === null)).toBe(
        true
    );
    expect(fixture.cases.some((row) => row.readiness === "READY" && row.value === null)).toBe(true);
    for (const row of fixture.cases)
        expect(
            isChartStudyReadiness(row, row.nullable),
            `${row.type_id}@${row.semantic_version}/${row.output_name}`
        ).toBe(true);
});
