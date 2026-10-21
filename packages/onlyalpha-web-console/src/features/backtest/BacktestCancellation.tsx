import { useState } from "react";
import { useResearchApi } from "../../app/providers";
import { createUuidV4 } from "../../api/integrations/submissionIntent";
import { errorMessage } from "../../api/research/errors";
import type { BacktestRunId } from "../../domain/research/identity";

export function BacktestCancellation({
    id,
    refresh
}: {
    readonly id: BacktestRunId;
    readonly refresh: () => void;
}) {
    const client = useResearchApi();
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    async function cancel() {
        setBusy(true);
        setError(null);
        try {
            const key = `onlyalpha.backtest.cancellation-intent/1/${id}`;
            const commandId = sessionStorage.getItem(key) ?? createUuidV4();
            sessionStorage.setItem(key, commandId);
            await client.cancelBacktestRun(id, commandId);
            sessionStorage.removeItem(key);
            refresh();
        } catch (failure) {
            setError(
                `Cancellation is unconfirmed. Retrying preserves the same command. ${errorMessage(failure)}`
            );
            refresh();
        } finally {
            setBusy(false);
        }
    }
    return (
        <div>
            <button type="button" disabled={busy} onClick={() => void cancel()}>
                {busy ? "Requesting cancellation…" : "Cancel Backtest"}
            </button>
            <p>
                Cancellation stops further replay at a durable boundary. Existing orders and
                economic effects remain in history.
            </p>
            {error ? (
                <p role="alert" className="error">
                    {error}
                </p>
            ) : null}
        </div>
    );
}
