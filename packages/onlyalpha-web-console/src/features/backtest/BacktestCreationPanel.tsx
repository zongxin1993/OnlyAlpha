import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { useResearchApi } from "../../app/providers";
import { ProductWebError, errorMessage } from "../../api/research/errors";
import { createUuidV4 } from "../../api/integrations/submissionIntent";
import { parseBacktestRunId } from "../../domain/research/identity";
import { QueryError } from "../../shared/components/QueryState";
import {
    newBacktestIntent,
    persistBacktestIntent,
    readPendingBacktest,
    type PendingBacktest
} from "./submissionIntent";

export function BacktestCreationPanel() {
    const client = useResearchApi();
    const navigate = useNavigate();
    const context = useQuery({
        queryKey: ["product", "backtest-creation-context"],
        queryFn: ({ signal }) => client.getBacktestCreationContext(signal),
        staleTime: 0
    });
    const [initial] = useState(() => {
        try {
            return { pending: readPendingBacktest(), error: null };
        } catch {
            return {
                pending: null,
                error: "Pending submission storage is unavailable or invalid. Creation is stopped to preserve the original intent."
            };
        }
    });
    const [pending, setPending] = useState<PendingBacktest | null>(initial.pending);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(initial.error);
    const [selection, setSelection] = useState("");
    const options = context.data?.options ?? [];
    const optionKey = (item: (typeof options)[number]) =>
        `${item.strategy_fingerprint}/${item.dataset_binding_fingerprint}/${item.market_product_configuration_fingerprint}`;
    const option = options.find((item) => optionKey(item) === selection);
    async function submit(intent: PendingBacktest) {
        setBusy(true);
        setError(null);
        try {
            persistBacktestIntent(intent);
        } catch {
            setError("Unable to preserve the submission identity. Creation has not been sent.");
            setBusy(false);
            return;
        }
        setPending(intent);
        try {
            const response = await client.createBacktestRun(intent.request, intent.commandId);
            persistBacktestIntent(null);
            setPending(null);
            void navigate(`/backtest/runs/${parseBacktestRunId(response.backtest_run_id)}`);
        } catch (failure) {
            if (
                failure instanceof ProductWebError &&
                !intent.uncertain &&
                (failure.status === 400 ||
                    (failure.status === 409 &&
                        failure.phase === "ADMISSION" &&
                        failure.code === "STRATEGY_NOT_ADMITTED_TO_BACKTEST"))
            ) {
                persistBacktestIntent(null);
                setPending(null);
                setError(errorMessage(failure));
            } else {
                const retained = { ...intent, uncertain: true };
                try {
                    persistBacktestIntent(retained);
                } catch {
                    /* Retain the same identity in memory and keep creation disabled. */
                }
                setPending(retained);
                setError(
                    `Submission outcome is unconfirmed. The original command, Run and Generation are retained. ${errorMessage(failure)}`
                );
            }
        } finally {
            setBusy(false);
        }
    }
    return (
        <section className="catalog-panel" aria-labelledby="create-backtest-heading">
            <h2 id="create-backtest-heading">Create Rust Backtest</h2>
            <p>
                Select an existing frozen strategy and immutable dataset. The server owns execution
                and recovery.
            </p>
            {context.isPending ? <p role="status">Loading admitted Backtest inputs…</p> : null}
            {context.isError ? (
                <QueryError
                    title="Backtest creation is unavailable."
                    error={context.error}
                    retry={() => void context.refetch()}
                />
            ) : null}
            {pending !== null ? (
                <div role="status">
                    <p>
                        Unconfirmed submission:{" "}
                        <Link to={`/backtest/runs/${pending.request.backtest_run_id}`}>
                            Check submitted Run
                        </Link>
                    </p>
                    <p>Retry sends the same command and immutable execution identity.</p>
                    <button type="button" disabled={busy} onClick={() => void submit(pending)}>
                        {busy ? "Confirming…" : "Retry original submission"}
                    </button>
                </div>
            ) : null}
            <form
                onSubmit={(event) => {
                    event.preventDefault();
                    if (!option || !context.data || pending !== null || initial.error !== null)
                        return;
                    try {
                        const fields = new FormData(event.currentTarget);
                        const text = (name: string) => {
                            const value = fields.get(name);
                            if (typeof value !== "string") throw new Error("Invalid form field");
                            return value;
                        };
                        void submit(
                            newBacktestIntent({
                                schema_version: 2,
                                backtest_run_id: createUuidV4(),
                                runtime_generation_fingerprint:
                                    context.data.runtime_generation_fingerprint,
                                strategy_fingerprint: option.strategy_fingerprint,
                                dataset_binding_fingerprint: option.dataset_binding_fingerprint,
                                market_product_configuration_fingerprint:
                                    option.market_product_configuration_fingerprint,
                                portfolio_profile: { profile_id: "fixed-capital", version: "1" },
                                risk_profile: { profile_id: "default-risk", version: "1" },
                                execution_profile: { profile_id: "virtual-next-bar", version: "1" },
                                initial_account: {
                                    base_currency: option.base_currency,
                                    capital: text("capital")
                                },
                                runtime_options: {
                                    ordered_fact_policy: "ORDERED_FACTS_V1",
                                    order_policy: {
                                        schema_version: 1,
                                        kind: "FINITE_LONG_LIMIT",
                                        quantity: text("quantity"),
                                        entry_limit: text("entry"),
                                        exit_limit: text("exit"),
                                        maximum_fill_quantity: text("maximum-fill"),
                                        round_trips: Number(text("round-trips"))
                                    }
                                }
                            })
                        );
                    } catch {
                        setError(
                            "Invalid Backtest configuration. Check the numeric inputs before submitting."
                        );
                    }
                }}
            >
                <fieldset
                    className="backtest-configuration"
                    disabled={
                        busy ||
                        pending !== null ||
                        initial.error !== null ||
                        context.isError ||
                        context.isPending
                    }
                >
                    <legend>Backtest configuration</legend>
                    <label htmlFor="backtest-inputs">Strategy and dataset</label>
                    <select
                        id="backtest-inputs"
                        value={selection}
                        onChange={(event) => {
                            setSelection(event.target.value);
                        }}
                        required
                    >
                        <option value="">Choose strategy and data…</option>
                        {options.map((item) => (
                            <option
                                key={`${item.strategy_fingerprint}-${item.dataset_binding_fingerprint}-${item.market_product_configuration_fingerprint}`}
                                value={optionKey(item)}
                            >
                                {item.instruments.join(", ")} · strategy{" "}
                                {item.strategy_fingerprint.slice(0, 8)} · {item.start} — {item.end}{" "}
                                · {item.row_count} bars
                            </option>
                        ))}
                    </select>
                    {context.isSuccess && options.length === 0 ? (
                        <p>
                            No compatible admitted strategy and sealed dataset are available. Freeze
                            and admit a strategy in the Strategy workspace and prepare its matching
                            dataset first.
                        </p>
                    ) : null}
                    {option ? (
                        <p>
                            {option.instruments.join(", ")} · {option.row_count} immutable bars ·
                            account currency {option.base_currency}
                        </p>
                    ) : null}
                    <label htmlFor="backtest-capital">Initial capital</label>
                    <input
                        id="backtest-capital"
                        name="capital"
                        inputMode="decimal"
                        pattern="[0-9]+(\.[0-9]+)?"
                        defaultValue="10000.00"
                        required
                    />
                    <p>
                        Finite long LIMIT policy: entry and exit signals come from the frozen
                        strategy; these values specify order sizing and prices. Orders match
                        subsequent bars. Current Rust product supports one Generic T0 cash
                        instrument with provider-native RAW bars.
                    </p>
                    <label htmlFor="backtest-quantity">Order quantity</label>
                    <input
                        id="backtest-quantity"
                        name="quantity"
                        inputMode="decimal"
                        defaultValue="1"
                        required
                    />
                    <label htmlFor="backtest-entry">Entry limit price</label>
                    <input id="backtest-entry" name="entry" inputMode="decimal" required />
                    <label htmlFor="backtest-exit">Exit limit price</label>
                    <input id="backtest-exit" name="exit" inputMode="decimal" required />
                    <label htmlFor="backtest-fill">Maximum fill quantity per bar</label>
                    <input
                        id="backtest-fill"
                        name="maximum-fill"
                        inputMode="decimal"
                        defaultValue="1"
                        required
                    />
                    <label htmlFor="backtest-round-trips">Maximum round trips</label>
                    <input
                        id="backtest-round-trips"
                        name="round-trips"
                        type="number"
                        min="1"
                        max="8"
                        defaultValue="1"
                        required
                    />
                    <button type="submit" disabled={!option}>
                        {busy ? "Submitting…" : "Create and run Backtest"}
                    </button>
                </fieldset>
            </form>
            {error ? (
                <p className="error" role="alert">
                    {error}
                </p>
            ) : null}
            {context.data && context.data.denied.length > 0 ? (
                <details>
                    <summary>Unavailable strategy admissions</summary>
                    <ul>
                        {context.data.denied.map((item, index) => (
                            <li key={index}>
                                {item.code}: {item.detail}
                            </li>
                        ))}
                    </ul>
                </details>
            ) : null}
        </section>
    );
}
