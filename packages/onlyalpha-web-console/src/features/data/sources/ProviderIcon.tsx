/**
 * Fallback Provider icon: official brand assets are not supplied and remote logo
 * fetching is out of scope, so every provider gets the same neutral monogram box.
 */
export function ProviderIcon({
    providerId,
    size = "md"
}: {
    readonly providerId: string;
    readonly size?: "sm" | "md" | "lg";
}) {
    const letter = (/[a-z0-9]/i.exec(providerId)?.[0] ?? "?").toUpperCase();
    return (
        <span
            className={`provider-icon provider-icon--${size}`}
            data-provider={providerId}
            aria-hidden="true"
        >
            {letter}
        </span>
    );
}
