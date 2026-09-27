import { z } from "zod";
import { marketDataBarSchema, marketDataSourceReferenceSchema } from "./model";

export const marketDataStreamSubscribeSchema = z.strictObject({
    schema_version: z.literal(1),
    operation: z.literal("SUBSCRIBE_BAR"),
    source_reference: marketDataSourceReferenceSchema.extend({
        expected_type_id: z.string().min(1)
    }),
    instrument_id: z.string().min(1),
    bar_specification: z.literal("1m"),
    resume_after_sequence: z.string().regex(/^(?:0|[1-9][0-9]*)$/)
});

const base = { schema_version: z.literal(1) };
export const marketDataStreamEventSchema = z.discriminatedUnion("event", [
    z.strictObject({
        ...base,
        event: z.literal("SUBSCRIBED"),
        stream_id: z.string(),
        source_id: z.string(),
        instrument_id: z.string()
    }),
    z.strictObject({
        ...base,
        event: z.literal("STATE"),
        state: z.enum(["CONNECTING", "RECOVERING", "READY", "DEGRADED", "FAILED", "CLOSED"])
    }),
    z.strictObject({
        ...base,
        event: z.literal("BAR_PREVIEW"),
        source_id: z.string(),
        instrument_id: z.string(),
        bar_specification: z.literal("1m"),
        bar: marketDataBarSchema
    }),
    z.strictObject({
        ...base,
        event: z.literal("BAR_CLOSED"),
        source_id: z.string(),
        instrument_id: z.string(),
        bar_specification: z.literal("1m"),
        sequence: z.string().regex(/^(?:0|[1-9][0-9]*)$/),
        bar: marketDataBarSchema
    }),
    z.strictObject({
        ...base,
        event: z.literal("ERROR"),
        code: z.string(),
        detail: z.string().optional()
    })
]);

export type MarketDataStreamSubscribe = z.infer<typeof marketDataStreamSubscribeSchema>;
export type MarketDataStreamEvent = z.infer<typeof marketDataStreamEventSchema>;

export function openMarketDataStream(
    request: MarketDataStreamSubscribe,
    onEvent: (event: MarketDataStreamEvent) => void,
    onDisconnect: () => void
): () => void {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}/api/v2/market-data/stream`);
    socket.addEventListener("open", () => {
        socket.send(JSON.stringify(request));
    });
    socket.addEventListener("message", (message) => {
        const admitted = marketDataStreamEventSchema.safeParse(JSON.parse(String(message.data)));
        if (admitted.success) onEvent(admitted.data);
        else socket.close(1002, "contract error");
    });
    socket.addEventListener("close", () => {
        onDisconnect();
    });
    socket.addEventListener("error", () => {
        socket.close();
    });
    return () => {
        socket.close(1000, "context changed");
    };
}
