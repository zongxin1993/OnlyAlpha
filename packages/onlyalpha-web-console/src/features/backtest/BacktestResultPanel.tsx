import { useQuery } from "@tanstack/react-query";
import { useResearchApi } from "../../app/providers";
import type { BacktestRunId } from "../../domain/research/identity";
import type { BacktestRunTransport } from "../../api/research/schemas";
import { QueryError } from "../../shared/components/QueryState";

function object(value: unknown): Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {};
}
function display(value: unknown): string {
    if (value === null || value === undefined) return "Not reported";
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    if (typeof value !== "object") return "Not reported";
    const row = object(value);
    return typeof row.value === "string" ? row.value : JSON.stringify(value);
}

export function BacktestResultPanel({
    id,
    run
}: {
    readonly id: BacktestRunId;
    readonly run: BacktestRunTransport;
}) {
    const client = useResearchApi();
    const query = useQuery({
        queryKey: ["product", "backtest-result", id, run.evidence_fingerprint],
        queryFn: ({ signal }) => client.getBacktestResult(id, signal),
        staleTime: Infinity
    });
    if (query.isPending) return <p role="status">Loading verified Backtest result…</p>;
    if (query.isError)
        return (
            <QueryError
                title="Unable to load owning Backtest result."
                error={query.error}
                retry={() => void query.refetch()}
            />
        );
    const value = query.data;
    const result = value.result;
    if (
        result.result_fingerprint !== run.result_fingerprint ||
        result.determinism_fingerprint !== run.determinism_fingerprint
    )
        return (
            <p className="error" role="alert">
                CONTRACT_ERROR: Result identity differs from the completed Run.
            </p>
        );
    if (value.implementation === "PYTHON")
        return (
            <section className="catalog-panel">
                <h2>Historical Python result</h2>
                <details>
                    <summary>Verified owning result</summary>
                    <pre>{JSON.stringify(result, null, 2)}</pre>
                </details>
            </section>
        );
    const summary = object(object(result.runtime_performance).summary);
    const execution = object(result.execution);
    return (
        <section
            className="catalog-panel backtest-result"
            aria-labelledby="backtest-result-heading"
        >
            <h2 id="backtest-result-heading">Backtest result</h2>
            <p>
                Execution implementation: <strong>Rust</strong> ·{" "}
                {display(object(result.run).status)}
            </p>
            <p>Account currency: {display(object(object(result.scope).currency).code)}</p>
            <dl className="facts">
                {Object.entries(summary).map(([key, value]) => (
                    <div key={key}>
                        <dt>{key.replaceAll("_", " ")}</dt>
                        <dd>{display(value)}</dd>
                    </div>
                ))}
            </dl>
            <p>
                Orders: {display(execution.order_count)} · Trades: {display(execution.trade_count)}
            </p>
            <h3>Orders</h3>
            <div className="table-scroll">
                <table>
                    <thead>
                        <tr>
                            {["Side", "State", "Quantity", "Limit price", "Order"].map((label) => (
                                <th scope="col" key={label}>
                                    {label}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {Array.isArray(result.orders)
                            ? result.orders.map((value, index) => {
                                  const row = object(object(value).snapshot);
                                  return (
                                      <tr key={index}>
                                          <td>{display(row.side)}</td>
                                          <td>{display(row.status)}</td>
                                          <td>{display(row.quantity)}</td>
                                          <td>{display(row.price)}</td>
                                          <td>
                                              <details>
                                                  <summary>Order identity</summary>
                                                  {display(row.order_id)}
                                              </details>
                                          </td>
                                      </tr>
                                  );
                              })
                            : null}
                    </tbody>
                </table>
            </div>
            <h3>Trades</h3>
            <div className="table-scroll">
                <table>
                    <thead>
                        <tr>
                            <th scope="col">Quantity</th>
                            <th scope="col">Fill price</th>
                            <th scope="col">Cumulative order charge</th>
                            <th scope="col">Recorded fill</th>
                        </tr>
                    </thead>
                    <tbody>
                        {Array.isArray(result.trades)
                            ? result.trades.map((value, index) => {
                                  const row = object(value);
                                  const fill = object(object(row.input).payload);
                                  return (
                                      <tr key={index}>
                                          <td>{display(fill.quantity)}</td>
                                          <td>{display(fill.price)}</td>
                                          <td>{display(object(fill.fees).charge_target)}</td>
                                          <td>
                                              <details>
                                                  <summary>Execution fact</summary>
                                                  <pre>{JSON.stringify(row, null, 2)}</pre>
                                              </details>
                                          </td>
                                      </tr>
                                  );
                              })
                            : null}
                    </tbody>
                </table>
            </div>
            <details>
                <summary>Account, positions and reconciliation</summary>
                <pre>
                    {JSON.stringify(
                        {
                            account: result.final_account,
                            positions: result.final_positions,
                            reconciliation: result.reconciliation,
                            diagnostics: result.diagnostics
                        },
                        null,
                        2
                    )}
                </pre>
            </details>
            <details>
                <summary>Exact execution provenance</summary>
                <pre>{JSON.stringify(value.runtime, null, 2)}</pre>
            </details>
        </section>
    );
}
