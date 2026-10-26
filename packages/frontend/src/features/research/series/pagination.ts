import type {
    ResearchStatisticPoint,
    ResearchStatisticSeriesPage,
    ResearchScientificSeriesPage
} from "../../../domain/research/model";

export function mergeSeriesPages(
    pages: readonly ResearchStatisticSeriesPage[]
): readonly ResearchStatisticPoint[] {
    const result: ResearchStatisticPoint[] = [];
    let previous: bigint | undefined;
    for (const page of pages) {
        for (const point of page.points) {
            if (previous !== undefined && point.tsEventNs <= previous) {
                throw new Error(
                    "Series pages are duplicate, missing-order, or cursor inconsistent"
                );
            }
            result.push(point);
            previous = point.tsEventNs;
        }
        const expected =
            page.hasMore && page.points.length > 0 ? page.points.at(-1)?.tsEventNs : null;
        if (page.nextAfterTsEventNs !== expected)
            throw new Error("Series page cursor does not match page content");
    }
    return result;
}

export function mergeScientificSeriesPages(
    pages: readonly ResearchScientificSeriesPage[]
): ResearchScientificSeriesPage["points"] {
    const result: ResearchScientificSeriesPage["points"][number][] = [];
    let previous: bigint | undefined;
    let kind: ResearchScientificSeriesPage["points"][number]["kind"] | undefined;
    for (const page of pages) {
        for (const point of page.points) {
            if (kind !== undefined && point.kind !== kind)
                throw new Error("Scientific pages contain mixed evidence kinds");
            if (previous !== undefined && point.tsEventNs <= previous)
                throw new Error("Scientific pages are duplicate or cursor inconsistent");
            result.push(point);
            previous = point.tsEventNs;
            kind = point.kind;
        }
        const expected =
            page.hasMore && page.points.length > 0 ? page.points.at(-1)?.tsEventNs : null;
        if (page.nextAfterTsEventNs !== expected)
            throw new Error("Scientific page cursor does not match page content");
    }
    return result;
}
