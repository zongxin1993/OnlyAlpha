import { marketDataStreamEventSchema, marketDataStreamSubscribeSchema } from "./stream";

it("admits the exact-source cursor contract and rejects browser OHLCV truth", () => {
    const request = {
        schema_version: 1,
        operation: "SUBSCRIBE_BAR",
        source_reference: {
            integration_id: "integration",
            integration_revision_fingerprint: "a".repeat(64),
            expected_type_id: "binance.spot.market_data"
        },
        instrument_id: "BTCUSDT.BINANCE",
        bar_specification: "1m",
        resume_after_sequence: "42"
    };
    expect(marketDataStreamSubscribeSchema.parse(request)).toEqual(request);
    expect(marketDataStreamSubscribeSchema.safeParse({ ...request, close: "100" }).success).toBe(
        false
    );
});

it("keeps preview and closed event semantics distinct", () => {
    const bar = {
        bar_start_ns: "60000000000",
        bar_end_ns: "120000000000",
        open: "1",
        high: "2",
        low: "0.5",
        close: "1.5",
        volume: "10",
        closed: false
    };
    expect(
        marketDataStreamEventSchema.parse({
            schema_version: 1,
            event: "BAR_PREVIEW",
            source_id: "source",
            instrument_id: "BTCUSDT.BINANCE",
            bar_specification: "1m",
            bar
        }).event
    ).toBe("BAR_PREVIEW");
    expect(
        marketDataStreamEventSchema.parse({
            schema_version: 1,
            event: "BAR_CLOSED",
            source_id: "source",
            instrument_id: "BTCUSDT.BINANCE",
            bar_specification: "1m",
            sequence: "1",
            bar: { ...bar, closed: true }
        }).event
    ).toBe("BAR_CLOSED");
});
