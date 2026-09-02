export type UnixNanoseconds = bigint & { readonly __unixNanoseconds: unique symbol };
const INTEGER = /^(?:0|-?[1-9][0-9]*)$/;

export function parseUnixNanoseconds(value: string): UnixNanoseconds {
    if (!INTEGER.test(value))
        throw new Error("Nanoseconds must be a canonical decimal integer string");
    return BigInt(value) as UnixNanoseconds;
}

export const nanosecondsToRequestText = (value: UnixNanoseconds): string => value.toString(10);

export function formatUtcNanoseconds(value: UnixNanoseconds): string {
    const milliseconds = value / 1_000_000n;
    const remainder = value % 1_000_000_000n;
    const date = new Date(Number(milliseconds));
    if (Number.isNaN(date.getTime())) return "UTC date outside browser range";
    const base = date.toISOString().replace(/\.\d{3}Z$/, "");
    const nanos = (remainder < 0n ? -remainder : remainder).toString().padStart(9, "0");
    return `${base}.${nanos}Z`;
}
