import { errorMessage } from "../../api/research/errors";

export function QueryError({
    error,
    retry,
    title = "Unable to load exact Research data."
}: {
    readonly error: unknown;
    readonly retry: () => void;
    readonly title?: string;
}) {
    return (
        <div className="error" role="alert">
            <strong>{title}</strong>
            <p>{errorMessage(error)}</p>
            <button type="button" onClick={retry}>
                Retry
            </button>
        </div>
    );
}
