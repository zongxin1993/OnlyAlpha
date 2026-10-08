import { researchCalculationCatalogSchema } from "../api/research/schemas";
import { marketDataBarSemantic } from "../api/marketData/model";
import { projectMarketDataBar } from "../charts/lightweight/marketDataChartProjection";
import type { StudySeriesEvidence } from "../charts/lightweight/studySeriesProjection";
import type { ChartStudyInstance } from "../features/workspace/chartStudy";
import { chartCatalogFixture } from "./chartCatalog";

/** Controlled evidence only. Never imported by the shipping Workspace. */
export function studySeriesFixture() {
    const registration = researchCalculationCatalogSchema.parse(chartCatalogFixture().discovery)
        .calculations[0];
    if (registration === undefined) throw new Error("Missing registration");
    const context = {
        key: "controlled-chart",
        source: {
            integration_id: "a".repeat(32),
            integration_revision_fingerprint: "b".repeat(64),
            expected_type_id: "example.data"
        },
        instrumentId: "FIXTURE",
        barSemantic: marketDataBarSemantic(15)
    };
    const instance: ChartStudyInstance = {
        instanceId: "controlled-instance",
        context,
        selection: { source: "REGISTERED_DISCOVERY", registration },
        configuration: {
            parameters: {
                period: { type: "INTEGER", value: 20 },
                price_field: { type: "STRING", value: "CLOSE" }
            },
            outputName: "value"
        },
        presentation: {
            placement: "PRICE_OVERLAY",
            color: "#1f5f8b",
            opacity: 1,
            lineWidth: 2,
            visible: true
        },
        connectionState: "CONFIGURED_NOT_EXECUTED"
    };
    const bars = Array.from({ length: 80 }, (_, index) =>
        projectMarketDataBar({
            bar_start_ns: (1767225600000000000n + BigInt(index) * 900000000000n).toString(),
            bar_end_ns: (1767225600000000000n + BigInt(index + 1) * 900000000000n).toString(),
            open: "100",
            high: "103",
            low: "98",
            close: "101",
            volume: "2.1234567890123456789",
            closed: true
        })
    );
    const evidence: StudySeriesEvidence = {
        source: { kind: "CONTROLLED_TEST_EVIDENCE", fixtureId: "display-line-points" },
        instanceId: instance.instanceId,
        chartContextKey: context.key,
        incarnationKey: "controlled-incarnation",
        configurationKey: JSON.stringify(instance.configuration),
        outputName: "value",
        points: bars.map((bar, index) => ({
            timeNs: bar.barStartNs,
            value: index === 40 ? null : "102.000000000000000001",
            readiness: index === 40 ? "PRE_READY" : "READY",
            reason: index === 40 ? "controlled missing value" : null
        }))
    };
    return { instance, bars, evidence };
}
