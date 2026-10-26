import { bandPolygons } from "./studyBandFill";
import { projectStudySeries } from "./studySeriesProjection";
import { studySeriesFixture } from "../../test/studySeries";
it("fills only paired admitted points and never bridges a missing lower value", () => {
    const { instance, bars, evidence } = studySeriesFixture();
    const upper = projectStudySeries(
        instance,
        evidence.incarnationKey,
        bars.map((bar) => bar.time),
        evidence
    );
    const lower = projectStudySeries(
        instance,
        evidence.incarnationKey,
        bars.map((bar) => bar.time),
        {
            ...evidence,
            points: evidence.points.map((point, index) => ({
                ...point,
                value: index === 20 ? null : "100.25"
            }))
        }
    );
    if (upper.status !== "PROJECTED" || lower.status !== "PROJECTED")
        throw new Error("Missing projection");
    const polygons = bandPolygons(upper.projection, lower.projection);
    expect(polygons).toHaveLength(3);
    expect(polygons.flat().every((point) => point.lower === 100.25)).toBe(true);
    expect(polygons.flat().some((point) => point.time === bars[20]?.time)).toBe(false);
});
