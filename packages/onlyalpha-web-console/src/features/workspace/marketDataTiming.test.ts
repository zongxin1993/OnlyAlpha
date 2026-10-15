import { formatMarketDataDelay, nextMarketDataTiming } from "./marketDataTiming";
import { marketDataBarSemantic } from "../../api/marketData/model";

it.each([
    [null, "—"],
    ["0", "0 ms"],
    ["1", "0.000001 ms"],
    ["-1", "-0.000001 ms（时钟偏差）"],
    ["123456789", "123.456789 ms"],
    ["-1000000", "-1 ms（时钟偏差）"]
])("formats signed exact ns %s only after subtraction", (value, label) => {
    expect(formatMarketDataDelay(value)).toBe(label);
});

it.each(["DERIVED", "PROVIDER_NATIVE"] as const)(
    "keeps absent timing unavailable for %s",
    (mode) => {
        const subscription = {
            schema_version: 2 as const,
            event: "SUBSCRIBED" as const,
            source_id: "source",
            instrument_id: "BTCUSDT.TEST",
            stream_id: "s",
            resolution_mode: mode,
            resolution_plan_fingerprint: "f".repeat(64),
            cursor_bar_stride_minutes: 1
        };
        const bar = {
            bar_start_ns: "0",
            bar_end_ns: "60000000000",
            open: "1",
            high: "1",
            low: "1",
            close: "1",
            volume: "1",
            closed: true
        };
        const event = {
            schema_version: 2 as const,
            event: "BAR_CLOSED" as const,
            sequence: "1",
            source_id: "source",
            instrument_id: "BTCUSDT.TEST",
            bar_semantic: marketDataBarSemantic(1),
            bar,
            timing: null
        };
        expect(nextMarketDataTiming(null, event, subscription)).toBeNull();
        expect(
            nextMarketDataTiming(
                null,
                {
                    ...event,
                    timing: {
                        stream_id: "s",
                        provider_event_ns: null,
                        ingress_received_ns: "60000000001"
                    }
                },
                { ...subscription, resolution_mode: "PROVIDER_NATIVE" }
            )
        ).toEqual({
            streamId: "s",
            currentConnection: true,
            receiveDelayNs: null,
            closedArrivalDelayNs: "1"
        });
        expect(
            nextMarketDataTiming(
                null,
                {
                    ...event,
                    timing: { stream_id: "s", provider_event_ns: "2", ingress_received_ns: "1" }
                },
                { ...subscription, resolution_mode: "DERIVED" }
            )
        ).toBeNull();
        expect(
            nextMarketDataTiming(
                null,
                {
                    ...event,
                    timing: { stream_id: "s", provider_event_ns: "2", ingress_received_ns: null }
                },
                { ...subscription, resolution_mode: "PROVIDER_NATIVE" }
            )
        ).toEqual({
            streamId: "s",
            currentConnection: false,
            receiveDelayNs: null,
            closedArrivalDelayNs: null
        });
    }
);
