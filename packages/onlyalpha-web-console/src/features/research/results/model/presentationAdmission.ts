export type PresentationAdmission<T> =
    { readonly ok: true; readonly value: T } | { readonly ok: false };

export function admitPresentation<T>(operation: () => T): PresentationAdmission<T> {
    try {
        return { ok: true, value: operation() };
    } catch {
        return { ok: false };
    }
}
