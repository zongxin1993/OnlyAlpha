import type {
    ResearchStatisticPoint,
    ResearchStatisticSeriesPage
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
