import type { MarketDataStreamEvent } from "../../api/marketData/stream";

type BarEvent = Extract<MarketDataStreamEvent, { event: "BAR_PREVIEW" | "BAR_CLOSED" }>;
type Subscription = Extract<MarketDataStreamEvent, { event: "SUBSCRIBED" }>;

export interface MarketDataTiming {
    readonly streamId: string;
    readonly currentConnection: boolean;
    readonly receiveDelayNs: string | null;
    readonly closedArrivalDelayNs: string | null;
}

/** Called only after the current frame has been admitted by the owning Bar ledger. */
export function nextMarketDataTiming(
    current: MarketDataTiming | null,
    event: BarEvent,
    subscription: Subscription | null,
    connectionReady = true
): MarketDataTiming | null {
    if (subscription?.resolution_mode !== "PROVIDER_NATIVE") return null;
    const timing = event.timing;
    if (timing !== null && timing.stream_id !== subscription.stream_id) return current;
    if (timing === null && current === null) return null;
    const received = timing?.ingress_received_ns ?? null;
    const provider = timing?.provider_event_ns ?? null;
    return {
        streamId: subscription.stream_id,
        currentConnection: connectionReady && received !== null,
        receiveDelayNs:
            received === null || provider === null
                ? null
                : (BigInt(received) - BigInt(provider)).toString(),
        closedArrivalDelayNs:
            event.event === "BAR_CLOSED"
                ? received === null
                    ? null
                    : (BigInt(received) - BigInt(event.bar.bar_end_ns)).toString()
                : (current?.closedArrivalDelayNs ?? null)
    };
}

/** UTC ns subtraction precedes presentation; even a sub-ms negative retains its sign. */
export function formatMarketDataDelay(nanoseconds: string | null): string {
    if (nanoseconds === null) return "—";
    const value = BigInt(nanoseconds);
    const magnitude = value < 0n ? -value : value;
    const fraction = (magnitude % 1_000_000n).toString().padStart(6, "0").replace(/0+$/, "");
    return `${value < 0n ? "-" : ""}${(magnitude / 1_000_000n).toString()}${fraction === "" ? "" : `.${fraction}`} ms${value < 0n ? "（时钟偏差）" : ""}`;
}
