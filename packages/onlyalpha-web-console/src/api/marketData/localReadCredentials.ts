/** Disposable credential memory, never Product identity or a persistence surface. */
export class LocalReadCredentials {
    readonly #localSession: boolean;

    constructor(localSession = false) {
        this.#localSession = localSession;
    }

    get localSession(): boolean {
        return this.#localSession;
    }

    #bearer: string | null = null;
    #generation = 0;
    #listeners = new Set<() => void>();

    readonly getGeneration = () => this.#generation;
    readonly subscribe = (listener: () => void) => {
        this.#listeners.add(listener);
        return () => this.#listeners.delete(listener);
    };

    replace(bearer: string | null): void {
        if (bearer !== null && !/^[0-9a-f]{64}$/.test(bearer))
            throw new Error("LOCAL_READ_CREDENTIAL_INVALID");
        this.#bearer = bearer;
        this.#generation += 1;
        for (const listener of this.#listeners) listener();
    }

    capture(): Readonly<{ bearer: string | null; generation: number }> {
        return { bearer: this.#bearer, generation: this.#generation };
    }

    isCurrent(generation: number): boolean {
        return generation === this.#generation;
    }
}
