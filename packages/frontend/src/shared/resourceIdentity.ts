export function admitResourceIdentity<T>(
    raw: string | undefined,
    parse: (value: string) => T
): { readonly value: T | null; readonly error: string | null } {
    if (raw === undefined) return { value: null, error: null };
    try {
        return { value: parse(raw), error: null };
    } catch (caught) {
        return {
            value: null,
            error: caught instanceof Error ? caught.message : "Invalid exact identity"
        };
    }
}
