import { errorMessage } from "../../api/research/errors";

export function QueryError({
    error,
    retry
}: {
    readonly error: unknown;
    readonly retry: () => void;
}) {
    return (
        <div className="error" role="alert">
            <strong>Unable to load exact Research data.</strong>
            <p>{errorMessage(error)}</p>
            <button type="button" onClick={retry}>
                Retry
            </button>
        </div>
    );
}
