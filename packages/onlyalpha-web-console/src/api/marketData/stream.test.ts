import {
    marketDataStreamEventSchema,
    marketDataStreamSubscribeSchema,
    openMarketDataStream
} from "./stream";
import { marketDataBarSemantic } from "./model";
import { LocalReadCredentials } from "./localReadCredentials";

it.each([1012, 1008])(
    "distinguishes Source generation replacement from authentication refusal: %s",
    (code) => {
        class Socket extends EventTarget {
            static current: Socket;
            constructor() {
                super();
                Socket.current = this;
            }
            send() {
                return undefined;
            }
            close() {
                return undefined;
            }
        }
        vi.stubGlobal("WebSocket", Socket);
        try {
            const disconnect = vi.fn();
            openMarketDataStream(
                {
                    schema_version: 2,
                    operation: "SUBSCRIBE_BAR",
                    source_reference: {
                        integration_id: "i",
                        integration_revision_fingerprint: "a".repeat(64),
                        expected_type_id: "test.source"
                    },
                    instrument_id: "BTCUSDT.TEST",
                    bar_semantic: marketDataBarSemantic(15),
                    resume_after_sequence: "0"
                },
                vi.fn(),
                disconnect,
                new LocalReadCredentials(true)
            );
            Socket.current.dispatchEvent(new CloseEvent("close", { code }));
            expect(disconnect).toHaveBeenCalledExactlyOnceWith(
                code === 1008 ? "AUTHENTICATION_ERROR" : undefined
            );
        } finally {
            vi.unstubAllGlobals();
        }
    }
);

it("sends AUTH before Subscribe and fences all old socket messages on token A→B→A", () => {
    class Socket extends EventTarget {
        static current: Socket;
        frames: string[] = [];
        constructor(
            readonly url: string,
            readonly protocols?: string[]
        ) {
            super();
            Socket.current = this;
        }
        send(value: string) {
            this.frames.push(value);
        }
        close() {
            this.dispatchEvent(new CloseEvent("close", { code: 1000 }));
        }
        emit(value: unknown) {
            this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(value) }));
        }
    }
    vi.stubGlobal("WebSocket", Socket);
    const credentials = new LocalReadCredentials();
    const token = "ee".repeat(32);
    credentials.replace(token);
    const event = vi.fn();
    const disconnect = vi.fn();
    const request = marketDataStreamSubscribeSchema.parse({
        schema_version: 2,
        operation: "SUBSCRIBE_BAR",
        source_reference: {
            integration_id: "i",
            integration_revision_fingerprint: "a".repeat(64),
            expected_type_id: "test.source"
        },
        instrument_id: "BTCUSDT.TEST",
        bar_semantic: marketDataBarSemantic(15),
        resume_after_sequence: "0"
    });
    const dispose = openMarketDataStream(request, event, disconnect, credentials);
    const socket = Socket.current;
    socket.dispatchEvent(new Event("open"));
    expect(socket.url).not.toContain(token);
    expect(socket.protocols).toBeUndefined();
    const operations = () =>
        socket.frames.map((frame) => (JSON.parse(frame) as { operation: string }).operation);
    expect(operations()).toEqual(["AUTH"]);
    socket.emit({ schema_version: 1, event: "AUTHENTICATED" });
    expect(operations()).toEqual(["AUTH", "SUBSCRIBE_BAR"]);
    socket.emit({ schema_version: 2, event: "STATE", state: "READY" });
    expect(event).toHaveBeenCalledTimes(1);
    credentials.replace("ff".repeat(32));
    credentials.replace(token);
    socket.emit({ schema_version: 2, event: "STATE", state: "READY" });
    expect(event).toHaveBeenCalledTimes(1);
    expect(disconnect).not.toHaveBeenCalled();
    dispose();
    vi.unstubAllGlobals();
});

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
