import {
    marketDataStreamEventSchema,
    type MarketDataStreamEvent,
    type MarketDataStreamSubscribe
} from "./stream.generated";
import type { LocalReadCredentials } from "./localReadCredentials";

export { marketDataStreamEventSchema, marketDataStreamSubscribeSchema } from "./stream.generated";
export type { MarketDataStreamEvent, MarketDataStreamSubscribe } from "./stream.generated";

export function openMarketDataStream(
    request: MarketDataStreamSubscribe,
    onEvent: (event: MarketDataStreamEvent) => void,
    onDisconnect: (failure?: "MALFORMED_JSON" | "CONTRACT_ERROR" | "AUTHENTICATION_ERROR") => void,
    credentials?: LocalReadCredentials
): () => void {
    const captured = credentials?.capture();
    if (captured?.bearer != null) {
        onDisconnect("AUTHENTICATION_ERROR");
        return () => undefined;
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}/api/v2/market-data/stream`);
    let disposed = false;
    const current = () =>
        !disposed && (captured == null || credentials?.isCurrent(captured.generation) === true);
    const unsubscribe = credentials?.subscribe(() => {
        disposed = true;
        socket.close();
    });
    let terminalFailure: "MALFORMED_JSON" | "CONTRACT_ERROR" | "AUTHENTICATION_ERROR" | undefined;
    socket.addEventListener("open", () => {
        if (!current()) return;
        socket.send(JSON.stringify(request));
    });
    socket.addEventListener("message", (message) => {
        if (!current()) return;
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
    socket.addEventListener("close", (event) => {
        unsubscribe?.();
        if (current()) onDisconnect(event.code === 1008 ? "AUTHENTICATION_ERROR" : terminalFailure);
    });
    socket.addEventListener("error", () => {
        socket.close();
    });
    return () => {
        disposed = true;
        unsubscribe?.();
        socket.close(1000, "context changed");
    };
}
