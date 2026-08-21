import type { ResearchCandidate, ResearchStatisticPoint } from "../../domain/research/model";
import type { UnixNanoseconds } from "../../domain/research/time";
import { formatUtcNanoseconds } from "../../domain/research/time";
import type { CandidateSurface, ScientificSeriesPoint } from "../model/scientific";
import { projectFiniteDecimal } from "./financialProjection";

export function projectStatisticsEvidence(points: readonly ResearchStatisticPoint[]):
    | {
          readonly ok: true;
          readonly points: readonly ScientificSeriesPoint[];
      }
    | { readonly ok: false; readonly detail: string } {
    const result: ScientificSeriesPoint[] = [];
    let previous: bigint | undefined;
    for (const point of points) {
        if (previous !== undefined && point.tsEventNs <= previous)
            return { ok: false, detail: "Statistics timestamps are not strictly ordered" };
        let value: number | null = null;
        if (point.statisticValue !== null) {
            const projected = projectFiniteDecimal(point.statisticValue);
            if (!projected.ok) return { ok: false, detail: projected.detail };
            value = projected.value;
        }
        result.push({
            tsEventNs: point.tsEventNs,
            timeLabel: formatUtcNanoseconds(point.tsEventNs),
            value,
            status: point.status,
            sampleCount: point.sampleCount
        });
        previous = point.tsEventNs;
    }
    return { ok: true, points: result };
}

export function commonExactTimestamps(
    candidates: readonly ResearchCandidate[],
    evidence: ReadonlyMap<string, readonly ResearchStatisticPoint[]>
): readonly UnixNanoseconds[] {
    if (candidates.length === 0) return [];
    let common = new Set(
        (evidence.get(candidates[0]?.candidateFingerprint ?? "") ?? []).map((point) =>
            point.tsEventNs.toString()
        )
    );
    for (const candidate of candidates.slice(1)) {
        const timestamps = new Set(
            (evidence.get(candidate.candidateFingerprint) ?? []).map((point) =>
                point.tsEventNs.toString()
            )
        );
        common = new Set([...common].filter((timestamp) => timestamps.has(timestamp)));
    }
    return [...common]
        .map((timestamp) => BigInt(timestamp) as UnixNanoseconds)
        .sort((left, right) => (left < right ? -1 : left > right ? 1 : 0));
}

export function projectCandidateSurface(
    candidates: readonly ResearchCandidate[],
    evidence: ReadonlyMap<string, readonly ResearchStatisticPoint[]>,
    exactTsEventNs: UnixNanoseconds
):
    | { readonly ok: true; readonly surface: CandidateSurface }
    | { readonly ok: false; readonly detail: string } {
    const dimensions = [
        ...new Set(candidates.flatMap((candidate) => Object.keys(candidate.assignment)))
    ].sort();
    const numeric = dimensions.filter((dimension) =>
        candidates.every((candidate) =>
            ["INTEGER", "DECIMAL"].includes(candidate.assignmentTypes[dimension] ?? "")
        )
    );
    const mode =
        numeric.length !== dimensions.length
            ? "TABLE_ONLY"
            : dimensions.length === 1
              ? "ONE_DIMENSION"
              : dimensions.length === 2
                ? "TWO_DIMENSIONS"
                : dimensions.length >= 3
                  ? "MULTI_DIMENSION"
                  : "TABLE_ONLY";
    const points = [];
    const coordinateLabels = new Map<string, Map<number, string>>();
    for (const candidate of candidates) {
        const point = (evidence.get(candidate.candidateFingerprint) ?? []).find(
            (item) => item.tsEventNs === exactTsEventNs
        );
        if (point === undefined)
            return {
                ok: false,
                detail: "Candidate has no evidence at the selected exact timestamp"
            };
        const projected =
            point.statisticValue === null ? null : projectFiniteDecimal(point.statisticValue);
        if (projected !== null && !projected.ok) return { ok: false, detail: projected.detail };
        const numericCoordinates: Record<string, number> = {};
        for (const dimension of numeric) {
            const exact = String(candidate.assignment[dimension]);
            const coordinate = projectFiniteDecimal(exact);
            if (!coordinate.ok) return { ok: false, detail: coordinate.detail };
            const labels = coordinateLabels.get(dimension) ?? new Map<number, string>();
            const existing = labels.get(coordinate.value);
            if (existing !== undefined && existing !== exact)
                return {
                    ok: false,
                    detail: "Distinct exact assignments collide at one numeric renderer coordinate"
                };
            labels.set(coordinate.value, exact);
            coordinateLabels.set(dimension, labels);
            numericCoordinates[dimension] = coordinate.value;
        }
        points.push({
            candidateFingerprint: candidate.candidateFingerprint,
            assignment: candidate.assignment,
            numericCoordinates,
            value: projected === null ? null : projected.value,
            status: point.status
        });
    }
    points.sort((left, right) => {
        for (const dimension of numeric) {
            const leftCoordinate = left.numericCoordinates[dimension];
            const rightCoordinate = right.numericCoordinates[dimension];
            if (leftCoordinate === undefined || rightCoordinate === undefined)
                throw new Error("Candidate numeric coordinate is incomplete");
            const difference = leftCoordinate - rightCoordinate;
            if (difference !== 0) return difference;
        }
        return left.candidateFingerprint < right.candidateFingerprint
            ? -1
            : left.candidateFingerprint > right.candidateFingerprint
              ? 1
              : 0;
    });
    return { ok: true, surface: { dimensions, mode, exactTsEventNs, points } };
}

export function candidateAxis(
    surface: CandidateSurface,
    dimension: string
): readonly { readonly coordinate: number; readonly label: string }[] {
    const values = new Map<number, string>();
    for (const point of surface.points) {
        const coordinate = point.numericCoordinates[dimension];
        if (coordinate === undefined) continue;
        const label = String(point.assignment[dimension]);
        const current = values.get(coordinate);
        if (current !== undefined && current !== label)
            throw new Error(
                "Distinct exact assignments collide at one numeric renderer coordinate"
            );
        values.set(coordinate, label);
    }
    return [...values]
        .sort(([left], [right]) => left - right)
        .map(([coordinate, label]) => ({
            coordinate,
            label
        }));
}
