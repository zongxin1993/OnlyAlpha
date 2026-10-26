import type * as ChartStudyApi from "../../api/chartStudies/client";
import { requiredValue } from "../../test/requiredValue";
import type { ReactNode } from "react";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { AppProviders } from "../../app/providers";
import {
    marketDataClient,
    marketDataSource,
    marketDataInstrument
} from "../../test/marketDataClient";
import { integrationClient } from "../../test/integrationClient";
import { temporaryWindowForQuery } from "../../test/temporaryMarketDataClient";
import { marketDataBarSemantic } from "../../api/marketData/model";
import { LocalReadCredentials } from "../../api/marketData/localReadCredentials";
import { readTemporaryMarketData } from "../../api/marketData/temporary";
import { readChartStudyCapabilities } from "../../api/chartStudies/client";
import { ChartStudyCapabilitiesSchema } from "../../api/chartStudies/http.generated";
import sample from "../../../../../test-data/web/chart-studies/query.json";
import { useMarketDataChart, onlyMarketDataSourceReference } from "./useMarketDataChart";
import { ChartStudies } from "./ChartStudies";
import { onlyMarketDataChartContextKey } from "./marketDataChartContext";
vi.mock("../../api/marketData/temporary", () => ({ readTemporaryMarketData: vi.fn() }));
vi.mock("../../api/marketData/temporaryStream", () => ({
    openTemporaryMarketDataStream: vi.fn(() => vi.fn())
}));
vi.mock("../../api/chartStudies/client", async (importOriginal) => ({
    ...(await importOriginal<typeof ChartStudyApi>()),
    readChartStudyCapabilities: vi.fn()
}));
afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllEnvs();
});
it("waits for the workspace read, then restores exact Source, instrument and 7m atomically", async () => {
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true");
    vi.mocked(readTemporaryMarketData).mockImplementation((_c, r, q) =>
        Promise.resolve(temporaryWindowForQuery(r, q))
    );
    const source = marketDataSource({ type_id: "binance.spot.market_data", environment: "GLOBAL" });
    const listSources = vi.fn(() => Promise.resolve([source]));
    const api = marketDataClient({
        listSources,
        listInstruments: vi.fn(() => Promise.resolve([marketDataInstrument()]))
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
        <AppProviders integrationClient={integrationClient()} marketDataClient={api}>
            {children}
        </AppProviders>
    );
    const { result, rerender } = renderHook(({ startup }) => useMarketDataChart({ startup }), {
        wrapper,
        initialProps: { startup: "pending" as "pending" | "restore" }
    });
    expect(listSources).not.toHaveBeenCalled();
    rerender({ startup: "restore" });
    await waitFor(() => {
        expect(result.current.catalogStatus).toBe("ready");
    });
    expect(readTemporaryMarketData).not.toHaveBeenCalled();
    await act(() =>
        result.current.restoreSelection(
            onlyMarketDataSourceReference(source),
            marketDataInstrument().instrument_id,
            marketDataBarSemantic(7)
        )
    );
    expect(result.current.barSemantic).toEqual(marketDataBarSemantic(7));
    expect(readTemporaryMarketData).toHaveBeenCalledTimes(1);
    expect(vi.mocked(readTemporaryMarketData).mock.calls[0]?.[2].bar_semantic).toEqual(
        marketDataBarSemantic(7)
    );
});
it("never substitutes a current Revision for an unavailable saved Source", async () => {
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true");
    const source = marketDataSource();
    const api = marketDataClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
        <AppProviders integrationClient={integrationClient()} marketDataClient={api}>
            {children}
        </AppProviders>
    );
    const { result } = renderHook(() => useMarketDataChart({ startup: "restore" }), { wrapper });
    await waitFor(() => {
        expect(result.current.catalogStatus).toBe("ready");
    });
    await act(() =>
        result.current.restoreSelection(
            {
                ...onlyMarketDataSourceReference(source),
                integration_revision_fingerprint: "f".repeat(64)
            },
            marketDataInstrument().instrument_id,
            marketDataBarSemantic(7)
        )
    );
    expect(result.current.reference).toBeNull();
    expect(result.current.message).toContain("不会自动换源");
    expect(readTemporaryMarketData).not.toHaveBeenCalled();
});
const capability = requiredValue(
    ChartStudyCapabilitiesSchema.parse({
        schema_version: 2,
        capabilities: [sample.capability]
    }).capabilities[0]
);
const source = onlyMarketDataSourceReference(marketDataSource());
const barSemantic = marketDataBarSemantic(7);
const context = {
    key: onlyMarketDataChartContextKey(source, "BTCUSDT.TEST", barSemantic),
    source,
    instrumentId: "BTCUSDT.TEST",
    barSemantic
};
const saved = {
    kind: capability.kind,
    type_id: capability.type_id,
    semantic_version: capability.semantic_version,
    parameters: Object.fromEntries(
        capability.descriptor.parameters.map((parameter) => [
            parameter.name,
            { type: parameter.parameter_type, value: parameter.default }
        ])
    ),
    output_names: ["value"],
    presentation: {
        placement: "PRICE_OVERLAY",
        color: "#abcdef",
        line_width: 2,
        opacity: 0.6,
        visible: false,
        series_styles: {}
    }
};
it("restores configuration order and presentation through a fresh exact capability read", async () => {
    vi.mocked(readChartStudyCapabilities).mockResolvedValue([capability]);
    render(
        <ChartStudies
            context={context}
            credentials={new LocalReadCredentials(true)}
            restoration={{
                key: "saved-1",
                contextKey: context.key,
                studies: [
                    saved,
                    { ...saved, presentation: { ...saved.presentation, color: "#123456" } }
                ]
            }}
        />
    );
    await waitFor(() => {
        expect(screen.getAllByTestId("chart-study-instance")).toHaveLength(2);
    });
    const rows = screen.getAllByTestId("chart-study-instance");
    expect(rows[0]).toHaveAttribute(
        "data-presentation",
        expect.stringContaining('"color":"#abcdef"')
    );
    expect(rows[1]).toHaveAttribute(
        "data-presentation",
        expect.stringContaining('"color":"#123456"')
    );
});
it("retains unavailable exact study intent visibly without silently upgrading its version", async () => {
    vi.mocked(readChartStudyCapabilities).mockResolvedValue([capability]);
    render(
        <ChartStudies
            context={context}
            credentials={new LocalReadCredentials(true)}
            restoration={{
                key: "saved-2",
                contextKey: context.key,
                studies: [{ ...saved, semantic_version: "unavailable-version" }]
            }}
        />
    );
    await waitFor(() => {
        expect(screen.getByText(/保存的指标配置暂不可用/)).toBeInTheDocument();
    });
    expect(screen.queryAllByTestId("chart-study-instance")).toHaveLength(0);
    expect(screen.getByText(/unavailable-version/)).toBeInTheDocument();
});
