export function createUuidV4(): string {
    if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
    bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
    const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export class MutationSubmissionIntent {
    private readonly pending = new Map<string, string>();

    constructor(private readonly createUuid: () => string = createUuidV4) {}

    commandFor(key: string): string {
        const pending = this.pending.get(key);
        if (pending !== undefined) return pending;
        const commandId = this.createUuid();
        this.pending.set(key, commandId);
        return commandId;
    }

    definitive(key: string): void {
        this.pending.delete(key);
    }
}
