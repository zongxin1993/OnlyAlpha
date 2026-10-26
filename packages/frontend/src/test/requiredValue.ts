/** Fail an invalid controlled fixture explicitly, rather than asserting it away. */
export function requiredValue<T>(value: T | null | undefined): T {
    if (value === null || value === undefined) throw new Error("Expected controlled test value");
    return value;
}
