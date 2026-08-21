import { parseDecimalText } from "../../domain/research/decimal";
import { parseSha256Fingerprint, parseStatisticsFingerprint } from "../../domain/research/identity";
import type { ResearchCandidate, ResearchStatisticPoint } from "../../domain/research/model";
import { parseUnixNanoseconds } from "../../domain/research/time";
import { commonExactTimestamps, projectCandidateSurface } from "./scientificProjection";

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
