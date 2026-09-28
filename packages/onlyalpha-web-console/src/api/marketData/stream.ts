import {
    marketDataStreamEventSchema,
    type MarketDataStreamEvent,
    type MarketDataStreamSubscribe
} from "./stream.generated";

export { marketDataStreamEventSchema, marketDataStreamSubscribeSchema } from "./stream.generated";
export type { MarketDataStreamEvent, MarketDataStreamSubscribe } from "./stream.generated";

export function openMarketDataStream(
    request: MarketDataStreamSubscribe,
    onEvent: (event: MarketDataStreamEvent) => void,
    onDisconnect: (failure?: "MALFORMED_JSON" | "CONTRACT_ERROR") => void
): () => void {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}/api/v2/market-data/stream`);
    let terminalFailure: "MALFORMED_JSON" | "CONTRACT_ERROR" | undefined;
    socket.addEventListener("open", () => {
        socket.send(JSON.stringify(request));
    });
    socket.addEventListener("message", (message) => {
        let payload: unknown;
        try {
            payload = JSON.parse(String(message.data));
        } catch {
            terminalFailure = "MALFORMED_JSON";
            socket.close(1002, "invalid JSON");
            return;
        }
        const admitted = marketDataStreamEventSchema.safeParse(payload);
        if (admitted.success) onEvent(admitted.data);
        else {
            terminalFailure = "CONTRACT_ERROR";
            socket.close(1002, "contract error");
        }
    });
    socket.addEventListener("close", () => {
        onDisconnect(terminalFailure);
    });
    socket.addEventListener("error", () => {
        socket.close();
    });
    return () => {
        socket.close(1000, "context changed");
    };
}
