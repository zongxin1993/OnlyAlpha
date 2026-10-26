import { openTemporaryMarketDataStream } from "./temporaryStream";
import { LocalReadCredentials } from "./localReadCredentials";
import { marketDataBarSemantic } from "./model";
import type { TemporaryMarketDataStreamSubscribe } from "./stream.generated";
const request: TemporaryMarketDataStreamSubscribe = {
    schema_version: 2,
    operation: "SUBSCRIBE_TEMPORARY_BARS",
    page_id: "00000000-0000-4000-8000-000000000001",
    source_reference: {
        integration_id: "source",
        integration_revision_fingerprint: "a".repeat(64),
        expected_type_id: "test.source"
    },
    instrument_id: "BTCUSDT.TEST",
    bar_semantic: marketDataBarSemantic(7),
    before_ns: "6000000000000",
    target_bar_count: 2000,
    expected_window_fingerprint: "b".repeat(64)
};
class Socket extends EventTarget {
    static current: Socket;
    readonly send = vi.fn();
    readonly close = vi.fn();
    constructor(readonly url: string) {
        super();
        Socket.current = this;
    }
}
afterEach(() => vi.unstubAllGlobals());
it("opens only the temporary route and submits the exact pinned window", () => {
    vi.stubGlobal("WebSocket", Socket);
    const received = vi.fn();
    const disconnect = vi.fn();
    const close = openTemporaryMarketDataStream(
        request,
        received,
        disconnect,
        new LocalReadCredentials(true)
    );
    expect(Socket.current.url).toMatch(/\/api\/v2\/chart\/market-data\/stream$/);
    Socket.current.dispatchEvent(new Event("open"));
    expect(Socket.current.send).toHaveBeenCalledExactlyOnceWith(JSON.stringify(request));
    Socket.current.dispatchEvent(
        new MessageEvent("message", {
            data: JSON.stringify({ schema_version: 2, event: "STATE", state: "RECOVERING" })
        })
    );
    expect(received).toHaveBeenCalledExactlyOnceWith({
        schema_version: 2,
        event: "STATE",
        state: "RECOVERING"
    });
    close();
    Socket.current.dispatchEvent(new CloseEvent("close"));
    expect(disconnect).not.toHaveBeenCalled();
});
it("rejects malformed wire events and preserves the terminal reason", () => {
    vi.stubGlobal("WebSocket", Socket);
    const received = vi.fn();
    const disconnect = vi.fn();
    openTemporaryMarketDataStream(request, received, disconnect, new LocalReadCredentials(true));
    Socket.current.dispatchEvent(
        new MessageEvent("message", {
            data: JSON.stringify({
                schema_version: 2,
                event: "STATE",
                state: "READY",
                seal_id: "fake"
            })
        })
    );
    expect(Socket.current.close).toHaveBeenCalledWith(1002, "contract error");
    Socket.current.dispatchEvent(new CloseEvent("close"));
    expect(disconnect).toHaveBeenCalledExactlyOnceWith("CONTRACT_ERROR");
    expect(received).not.toHaveBeenCalled();
});
it("withdraws the original credential occurrence and drops late events", () => {
    vi.stubGlobal("WebSocket", Socket);
    const credentials = new LocalReadCredentials(true);
    const received = vi.fn();
    openTemporaryMarketDataStream(request, received, vi.fn(), credentials);
    credentials.replace("c".repeat(64));
    expect(Socket.current.close).toHaveBeenCalled();
    Socket.current.dispatchEvent(
        new MessageEvent("message", {
            data: JSON.stringify({ schema_version: 2, event: "STATE", state: "READY" })
        })
    );
    expect(received).not.toHaveBeenCalled();
});
it("refuses a bearer before creating a socket", () => {
    const socket = vi.fn();
    vi.stubGlobal("WebSocket", socket);
    const disconnect = vi.fn();
    const credentials = new LocalReadCredentials(true);
    credentials.replace("d".repeat(64));
    openTemporaryMarketDataStream(request, vi.fn(), disconnect, credentials);
    expect(socket).not.toHaveBeenCalled();
    expect(disconnect).toHaveBeenCalledExactlyOnceWith("AUTHENTICATION_ERROR");
});
