import {
    parseResearchResultFingerprint,
    parseStatisticsFingerprint
} from "../../../domain/research/identity";
import type { ResearchStatisticSeriesPage } from "../../../domain/research/model";
import { parseUnixNanoseconds } from "../../../domain/research/time";
import { mergeSeriesPages } from "./pagination";

const result = parseResearchResultFingerprint("a".repeat(64));
const statistics = parseStatisticsFingerprint("b".repeat(64));
const page = (times: string[], more: boolean): ResearchStatisticSeriesPage => ({
    researchResultFingerprint: result,
    statisticsFingerprint: statistics,
    points: times.map((time) => ({
        tsEventNs: parseUnixNanoseconds(time),
        statisticValue: null,
        sampleCount: 0,
        status: "EMPTY"
    })),
    hasMore: more,
    nextAfterTsEventNs: more ? parseUnixNanoseconds(times.at(-1) ?? "0") : null
});

it("merges exact pages in stable order", () => {
    expect(
        mergeSeriesPages([page(["1", "2"], true), page(["3"], false)]).map(
            (point) => point.tsEventNs
        )
    ).toEqual([1n, 2n, 3n]);
});

it("rejects duplicate/order and cursor inconsistencies", () => {
    expect(() => mergeSeriesPages([page(["1", "2"], true), page(["2"], false)])).toThrow(
        /inconsistent/
    );
    expect(() =>
        mergeSeriesPages([{ ...page(["1"], true), nextAfterTsEventNs: parseUnixNanoseconds("9") }])
    ).toThrow(/cursor/);
});
