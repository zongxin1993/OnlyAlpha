import { parseDecimalText } from "../../domain/research/decimal";
import { parseSha256Fingerprint, parseStatisticsFingerprint } from "../../domain/research/identity";
import type { ResearchCandidate, ResearchStatisticPoint } from "../../domain/research/model";
import { parseUnixNanoseconds } from "../../domain/research/time";
import {
    candidateAxis,
    commonExactTimestamps,
    projectCandidateSurface
} from "./scientificProjection";

const candidate = (fingerprint: string, window: number): ResearchCandidate => ({
    candidateFingerprint: parseSha256Fingerprint(fingerprint.repeat(64)),
    candidateCalculationId: "factor",
    assignment: { window },
    assignmentTypes: { window: "INTEGER" },
    calculationFingerprint: parseSha256Fingerprint("c".repeat(64)),
    graphFingerprint: parseSha256Fingerprint("d".repeat(64)),
    statisticsFingerprints: [parseStatisticsFingerprint(fingerprint.repeat(64))],
    signalRoles: []
});
const point = (timestamp: string, value: string): ResearchStatisticPoint => ({
    tsEventNs: parseUnixNanoseconds(timestamp),
    statisticValue: parseDecimalText(value),
    sampleCount: 300,
    status: "VALID"
});

it("uses one explicit common timestamp rather than inventing a Candidate aggregate", () => {
    const candidates = [candidate("1", 10), candidate("2", 20)] as const;
    const evidence = new Map([
        [
            candidates[0].candidateFingerprint,
            [point("1000000000", "0.1"), point("2000000000", "0.2")]
        ],
        [candidates[1].candidateFingerprint, [point("2000000000", "0.3")]]
    ]);
    const timestamps = commonExactTimestamps(candidates, evidence);
    expect(timestamps.map(String)).toEqual(["2000000000"]);
    const timestamp = timestamps[0];
    expect(timestamp).toBeDefined();
    if (timestamp === undefined) return;
    const projected = projectCandidateSurface(candidates, evidence, timestamp);
    expect(projected.ok && projected.surface.mode).toBe("ONE_DIMENSION");
    expect(projected.ok && projected.surface.points.map((item) => item.value)).toEqual([0.2, 0.3]);
});

it.each([
    [
        [20, 2, 10],
        [2, 10, 20],
        ["2", "10", "20"]
    ],
    [
        ["10.25", "0.5", "2"],
        [0.5, 2, 10.25],
        ["0.5", "2", "10.25"]
    ]
] as const)(
    "orders numeric Candidate coordinates without rewriting exact assignments",
    (values, numeric, exact) => {
        const candidates = values.map((value, index) => ({
            ...candidate(String(index + 1), typeof value === "number" ? value : 0),
            assignment: { window: value },
            assignmentTypes: { window: typeof value === "number" ? "INTEGER" : "DECIMAL" } as const
        }));
        const timestamp = parseUnixNanoseconds("1000000000");
        const evidence = new Map(
            candidates.map((item) => [item.candidateFingerprint, [point(String(timestamp), "0.1")]])
        );
        const projected = projectCandidateSurface(candidates, evidence, timestamp);
        expect(projected.ok).toBe(true);
        if (!projected.ok) return;
        expect(projected.surface.points.map((item) => item.numericCoordinates.window)).toEqual(
            numeric
        );
        expect(projected.surface.points.map((item) => String(item.assignment.window))).toEqual(
            exact
        );
        expect(candidateAxis(projected.surface, "window").map((item) => item.label)).toEqual(exact);
    }
);

it.each([
    ["ONE_DIMENSION", { window: "9007199254740992" }, { window: "9007199254740993" }],
    [
        "MULTI_DIMENSION",
        { a: "9007199254740992", b: "1", c: "2" },
        { a: "9007199254740993", b: "3", c: "4" }
    ]
] as const)("fails closed on lossy exact-coordinate collisions for %s", (_mode, left, right) => {
    const candidates = [left, right].map((assignment, index) => ({
        ...candidate(String(index + 1), 0),
        assignment,
        assignmentTypes: Object.fromEntries(
            Object.keys(assignment).map((name): [string, "DECIMAL"] => [name, "DECIMAL"])
        )
    }));
    const timestamp = parseUnixNanoseconds("1000000000");
    const evidence = new Map(
        candidates.map((item) => [item.candidateFingerprint, [point(String(timestamp), "0.1")]])
    );
    expect(projectCandidateSurface(candidates, evidence, timestamp)).toEqual({
        ok: false,
        detail: "Distinct exact assignments collide at one numeric renderer coordinate"
    });
});
