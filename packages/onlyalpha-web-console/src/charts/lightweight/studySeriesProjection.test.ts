import { studySeriesFixture } from "../../test/studySeries";
import { projectStudySeries, studyHover } from "./studySeriesProjection";
import type { StudySeriesEvidence } from "./studySeriesProjection";
import { rebaseChartRange } from "./chartViewport";
import type { LogicalRange } from "lightweight-charts";

it("retains exact hover values and upstream readiness/reason with distinct lines around NULL and missing timestamps", () => {
    const { instance, bars, evidence } = studySeriesFixture();
    const points = evidence.points.filter((_, index) => index !== 30);
    const view = projectStudySeries(
        instance,
        evidence.incarnationKey,
        bars.map((bar) => bar.time),
        { ...evidence, points }
    );
    expect(view.status).toBe("PROJECTED");
    if (view.status !== "PROJECTED") throw new Error("Not projected");
    expect(view.projection.segments).toHaveLength(3);
    expect(view.projection.segments.every((segment) => segment.length === 80)).toBe(true);
    expect(
        view.projection.segments.every(
            (segment) => segment[30] !== undefined && !("value" in segment[30])
        )
    ).toBe(true);
    expect(studyHover(view, bars[0]?.time ?? null)).toContain("102.000000000000000001 · READY");
    expect(studyHover(view, bars[40]?.time ?? null)).toContain(
        "无数值 · PRE_READY · controlled missing value"
    );
    expect(studyHover(view, bars[30]?.time ?? null)).toBe("此时间无对应结果");
});
it.each([
    "owner",
    "context",
    "incarnation",
    "output",
    "configuration",
    "source",
    "readiness",
    "unsafe-value",
    "underflow",
    "nan",
    "duplicate",
    "reversed",
    "fractional-time",
    "unsafe-time"
])("rejects structural mutation %s", (condition) => {
    const { instance, bars, evidence } = studySeriesFixture();
    const candidate = structuredClone(evidence);
    const first = candidate.points[0];
    if (first === undefined) throw new Error("Missing point");
    const altered = candidate as unknown as Record<string, unknown>;
    if (condition === "owner") altered.instanceId = "different-instance";
    if (condition === "context") altered.chartContextKey = "different-chart";
    if (condition === "incarnation") altered.incarnationKey = "old-incarnation";
    if (condition === "output") altered.outputName = "other";
    if (condition === "configuration") altered.configurationKey = "changed-parameters";
    if (condition === "source") altered.source = { kind: "RESULT_READY" };
    if (condition === "readiness") altered.points = [{ ...first, readiness: undefined }];
    if (condition === "unsafe-value") altered.points = [{ ...first, value: "9007199254740992" }];
    if (condition === "underflow") altered.points = [{ ...first, value: `0.${"0".repeat(400)}1` }];
    if (condition === "nan") altered.points = [{ ...first, value: "NaN" }];
    if (condition === "duplicate") altered.points = [first, first];
    if (condition === "reversed") altered.points = [...candidate.points].reverse();
    if (condition === "fractional-time")
        altered.points = [{ ...first, timeNs: (BigInt(first.timeNs) + 1n).toString() }];
    if (condition === "unsafe-time")
        altered.points = [{ ...first, timeNs: "9007199254740992000000000" }];
    expect(
        projectStudySeries(
            instance,
            evidence.incarnationKey,
            bars.map((bar) => bar.time),
            candidate
        ).status
    ).toBe("INVALID");
});
it("missing, stale, empty and all-NULL remain distinct and never produce a zero or a line", () => {
    const { instance, bars, evidence } = studySeriesFixture();
    const timeline = bars.map((bar) => bar.time);
    expect(projectStudySeries(instance, evidence.incarnationKey, timeline, undefined).status).toBe(
        "NOT_CONNECTED"
    );
    expect(
        projectStudySeries(
            { ...instance, connectionState: "STALE_CONFIG" },
            evidence.incarnationKey,
            timeline,
            evidence
        ).status
    ).toBe("STALE");
    for (const points of [[], evidence.points.map((point) => ({ ...point, value: null }))]) {
        const view = projectStudySeries(instance, evidence.incarnationKey, timeline, {
            ...evidence,
            points
        });
        if (view.status !== "PROJECTED") throw new Error("Not projected");
        expect(view.projection.segments).toEqual([]);
    }
});
it("retains fractional viewport anchors across union time changes and history prepend", () => {
    const range = { from: 1.25, to: 3.75 } as LogicalRange;
    expect(rebaseChartRange(range, [10, 20, 30, 40, 50], [0, 10, 15, 20, 30, 40, 50])).toEqual({
        from: 3.25,
        to: 5.75
    });
    expect(rebaseChartRange(range, [10, 20, 30, 40, 50], [10, 20, 30, 40, 50])).toEqual(range);
});
it.each([null, [], 42, { points: [] }])("contains malformed root %j as INVALID", (root) => {
    const { instance, evidence } = studySeriesFixture();
    expect(
        projectStudySeries(
            instance,
            evidence.incarnationKey,
            [],
            root as unknown as StudySeriesEvidence
        ).status
    ).toBe("INVALID");
});
it.each([102, [102], true])("rejects coerced numeric or array value %j", (value) => {
    const { instance, evidence } = studySeriesFixture();
    const candidate = {
        ...evidence,
        points: [{ ...evidence.points[0], value }]
    } as unknown as StudySeriesEvidence;
    expect(projectStudySeries(instance, evidence.incarnationKey, [], candidate).status).toBe(
        "INVALID"
    );
});
it.each([Number(1767225600000000001n), ["1767225600000000000"]])(
    "rejects precision-lost or array timestamp %j",
    (timeNs) => {
        const { instance, evidence } = studySeriesFixture();
        const candidate = {
            ...evidence,
            points: [{ ...evidence.points[0], timeNs }]
        } as unknown as StudySeriesEvidence;
        expect(projectStudySeries(instance, evidence.incarnationKey, [], candidate).status).toBe(
            "INVALID"
        );
    }
);
