import type { LocalReadCredentials } from "./localReadCredentials";
import {
    temporaryMarketDataStreamEventSchema,
    temporaryMarketDataStreamSubscribeSchema,
    type TemporaryMarketDataStreamEvent,
    type TemporaryMarketDataStreamSubscribe
} from "./stream.generated";
type Failure = "MALFORMED_JSON" | "CONTRACT_ERROR" | "AUTHENTICATION_ERROR";
/** Explicit volatile subscription. A failure never opens the durable stream. */
export function openTemporaryMarketDataStream(
    request: TemporaryMarketDataStreamSubscribe,
    onEvent: (event: TemporaryMarketDataStreamEvent) => void,
    onDisconnect: (failure?: Failure) => void,
    credentials: LocalReadCredentials
): () => void {
    const captured = credentials.capture();
    if (!credentials.localSession || captured.bearer !== null) {
        onDisconnect("AUTHENTICATION_ERROR");
        return () => undefined;
    }
    if (!temporaryMarketDataStreamSubscribeSchema.safeParse(request).success) {
        onDisconnect("CONTRACT_ERROR");
        return () => undefined;
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(
        `${protocol}//${window.location.host}/api/v2/chart/market-data/stream`
    );
    let disposed = false;
    let terminal: Failure | undefined;
    const current = () => !disposed && credentials.isCurrent(captured.generation);
    const unsubscribe = credentials.subscribe(() => {
        disposed = true;
        socket.close(1000, "session changed");
    });
    socket.addEventListener("open", () => {
        if (current()) socket.send(JSON.stringify(request));
    });
    socket.addEventListener("message", (message) => {
        if (!current() || terminal !== undefined) return;
        let payload: unknown;
        try {
            payload = JSON.parse(String(message.data));
        } catch {
            terminal = "MALFORMED_JSON";
            socket.close(1002, "invalid JSON");
            return;
        }
        const event = temporaryMarketDataStreamEventSchema.safeParse(payload);
        if (event.success) onEvent(event.data);
        else {
            terminal = "CONTRACT_ERROR";
            socket.close(1002, "contract error");
        }
    });
    socket.addEventListener("close", (event) => {
        unsubscribe();
        if (current()) onDisconnect(event.code === 1008 ? "AUTHENTICATION_ERROR" : terminal);
    });
    socket.addEventListener("error", () => {
        socket.close();
    });
    return () => {
        disposed = true;
        unsubscribe();
        socket.close(1000, "context changed");
    };
}
