import { parseDecimalText } from "../domain/research/decimal";
import type { ResearchStatisticPoint } from "../domain/research/model";
import { parseUnixNanoseconds } from "../domain/research/time";
import type { ChartProjection } from "./model";
import { projectResearchSeries } from "./researchSeriesProjection";

const make = (time: string, value: string | null): ResearchStatisticPoint => ({
    tsEventNs: parseUnixNanoseconds(time),
    statisticValue: value === null ? null : parseDecimalText(value),
    sampleCount: 1,
    status: "OK"
});

function expectFailure(value: ChartProjection, detail: string): void {
    expect(value.ok).toBe(false);
    if (value.ok) throw new Error("Expected projection failure");
    expect(value.detail).toContain(detail);
}

describe("lossy chart projection", () => {
    it("projects values and preserves null as whitespace", () => {
        expect(
            projectResearchSeries([make("1000000000", "1.25"), make("2000000000", null)])
        ).toEqual({
            ok: true,
            points: [{ time: 1, value: 1.25 }, { time: 2 }]
        });
    });

    it("fails closed on second collisions, ordering, unsafe time, and non-finite coordinates", () => {
        expectFailure(
            projectResearchSeries([make("1000000001", "1"), make("1000000002", "2")]),
            "collide"
        );
        expectFailure(
            projectResearchSeries([make("2000000000", "1"), make("1000000000", "2")]),
            "ordered"
        );
        expectFailure(
            projectResearchSeries([make("999999999999999999999999999999", "1")]),
            "safe chart"
        );
        expectFailure(
            projectResearchSeries([
                make(
                    "1000000000",
                    "999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999"
                )
            ]),
            "finite"
        );
    });
});
