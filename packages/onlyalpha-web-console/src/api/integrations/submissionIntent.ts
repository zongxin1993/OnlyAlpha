export class MutationSubmissionIntent {
    private readonly pending = new Map<string, string>();

    constructor(private readonly createUuid: () => string = () => crypto.randomUUID()) {}

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
