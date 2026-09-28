import {
    marketDataStreamEventSchema,
    marketDataStreamSubscribeSchema,
    openMarketDataStream
} from "./stream";
import { marketDataBarSemantic } from "./model";

it("admits the exact-source cursor contract and rejects browser OHLCV truth", () => {
    const request = {
        schema_version: 2,
        operation: "SUBSCRIBE_BAR",
        source_reference: {
            integration_id: "integration",
            integration_revision_fingerprint: "a".repeat(64),
            expected_type_id: "binance.spot.market_data"
        },
        instrument_id: "BTCUSDT.BINANCE",
        bar_semantic: marketDataBarSemantic(1),
        resume_after_sequence: "42",
        resume_plan_fingerprint: "a".repeat(64)
    };
    expect(marketDataStreamSubscribeSchema.parse(request)).toEqual(request);
    expect(marketDataStreamSubscribeSchema.safeParse({ ...request, close: "100" }).success).toBe(
        false
    );
    expect(
        marketDataStreamSubscribeSchema.safeParse({ ...request, resume_plan_fingerprint: "wrong" })
            .success
    ).toBe(false);
    expect(
        marketDataStreamSubscribeSchema.safeParse({
            ...request,
            resume_plan_fingerprint: undefined
        }).success
    ).toBe(false);
    expect(
        marketDataStreamSubscribeSchema.safeParse({
            ...request,
            resume_after_sequence: "0",
            resume_plan_fingerprint: null
        }).success
    ).toBe(true);
    expect(
        marketDataStreamEventSchema.safeParse({
            schema_version: 2,
            event: "SUBSCRIBED",
            stream_id: "s",
            source_id: "source",
            instrument_id: "BTCUSDT.TEST",
            resolution_mode: "PROVIDER_NATIVE",
            resolution_plan_fingerprint: "a".repeat(64),
            cursor_bar_stride_minutes: 15
        }).success
    ).toBe(true);
});

it.each([
    ["{", "MALFORMED_JSON"],
    ['{"schema_version":2,"event":"SUBSCRIBED"}', "CONTRACT_ERROR"]
])("terminates invalid stream frame %s without requesting reconnect", (frame, reason) => {
    class Socket {
        static current: Socket;
        handlers = new Map<string, (event: { data: string }) => void>();
        constructor() {
            Socket.current = this;
        }
        addEventListener(name: string, handler: (event: { data: string }) => void) {
            this.handlers.set(name, handler);
        }
        send() {
            return undefined;
        }
        close() {
            this.handlers.get("close")?.({ data: "" });
        }
        emit(frame: string) {
            this.handlers.get("message")?.({ data: frame });
        }
    }
    vi.stubGlobal("WebSocket", Socket);
    const onEvent = vi.fn();
    const onDisconnect = vi.fn();
    openMarketDataStream(
        {
            schema_version: 2,
            operation: "SUBSCRIBE_BAR",
            source_reference: {
                integration_id: "i",
                integration_revision_fingerprint: "a".repeat(64),
                expected_type_id: "source"
            },
            instrument_id: "BTCUSDT.TEST",
            bar_semantic: marketDataBarSemantic(1),
            resume_after_sequence: "0",
            resume_plan_fingerprint: null
        },
        onEvent,
        onDisconnect
    );
    Socket.current.emit(frame);
    expect(onEvent).not.toHaveBeenCalled();
    expect(onDisconnect).toHaveBeenCalledWith(reason);
    vi.unstubAllGlobals();
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
            schema_version: 2,
            event: "BAR_PREVIEW",
            source_id: "source",
            instrument_id: "BTCUSDT.BINANCE",
            bar_semantic: marketDataBarSemantic(1),
            bar
        }).event
    ).toBe("BAR_PREVIEW");
    expect(
        marketDataStreamEventSchema.parse({
            schema_version: 2,
            event: "BAR_CLOSED",
            source_id: "source",
            instrument_id: "BTCUSDT.BINANCE",
            bar_semantic: marketDataBarSemantic(1),
            sequence: "1",
            bar: { ...bar, closed: true }
        }).event
    ).toBe("BAR_CLOSED");
});
