import type { ResearchCalculationCatalogItemTransport } from "../../../api/research/schemas";
import type { CalculationDraft } from "./researchDraft";

export function CalculationEditor({
    draft,
    catalog,
    sources,
    target,
    onChange,
    onRemove
}: {
    readonly draft: CalculationDraft;
    readonly catalog: ResearchCalculationCatalogItemTransport;
    readonly sources: readonly string[];
    readonly target: boolean;
    readonly onChange: (value: CalculationDraft) => void;
    readonly onRemove: () => void;
}) {
    return (
        <article className="calculation-editor">
            <div className="section-heading">
                <div>
                    <strong>{catalog.type_reference.type_id}</strong>
                    <span className="kind-label">{catalog.type_reference.kind}</span>
                </div>
                <button type="button" className="button-subtle" onClick={onRemove}>
                    Remove
                </button>
            </div>
            <label>
                Instance key
                <input
                    aria-label={`${catalog.type_reference.type_id} instance key`}
                    value={draft.instanceKey}
                    onChange={(event) => {
                        onChange({ ...draft, instanceKey: event.target.value });
                    }}
                />
            </label>
            {catalog.parameters.map((parameter) => {
                const value = draft.parameters[parameter.name];
                if (value === undefined) return null;
                return (
                    <div className="parameter-row" key={parameter.name}>
                        <label>
                            {parameter.name}
                            {parameter.enum_values.length > 0 && value.mode === "FIXED" ? (
                                <select
                                    value={value.valuesText}
                                    onChange={(event) => {
                                        onChange({
                                            ...draft,
                                            parameters: {
                                                ...draft.parameters,
                                                [parameter.name]: {
                                                    ...value,
                                                    valuesText: event.target.value
                                                }
                                            }
                                        });
                                    }}
                                >
                                    {parameter.enum_values.map((item) => (
                                        <option key={String(item.value)} value={String(item.value)}>
                                            {String(item.value)}
                                        </option>
                                    ))}
                                </select>
                            ) : (
                                <input
                                    aria-label={`${draft.instanceKey || catalog.type_reference.type_id} ${parameter.name}`}
                                    value={value.valuesText}
                                    placeholder={value.mode === "SWEEP" ? "1, 2, 3" : undefined}
                                    onChange={(event) => {
                                        onChange({
                                            ...draft,
                                            parameters: {
                                                ...draft.parameters,
                                                [parameter.name]: {
                                                    ...value,
                                                    valuesText: event.target.value
                                                }
                                            }
                                        });
                                    }}
                                />
                            )}
                        </label>
                        {!target && catalog.parameter_sweep_allowed ? (
                            <label className="compact-control">
                                Mode
                                <select
                                    value={value.mode}
                                    onChange={(event) => {
                                        onChange({
                                            ...draft,
                                            parameters: {
                                                ...draft.parameters,
                                                [parameter.name]: {
                                                    ...value,
                                                    mode:
                                                        event.target.value === "SWEEP"
                                                            ? "SWEEP"
                                                            : "FIXED"
                                                }
                                            }
                                        });
                                    }}
                                >
                                    <option value="FIXED">Fixed</option>
                                    <option value="SWEEP">Sweep</option>
                                </select>
                            </label>
                        ) : null}
                    </div>
                );
            })}
            {catalog.inputs.map((input) => (
                <label key={input.name}>
                    Input · {input.name}
                    <select
                        value={draft.inputBindings[input.name] ?? ""}
                        onChange={(event) => {
                            onChange({
                                ...draft,
                                inputBindings: {
                                    ...draft.inputBindings,
                                    [input.name]: event.target.value
                                }
                            });
                        }}
                    >
                        <option value="">Select source…</option>
                        {sources.map((source) => (
                            <option key={source} value={source}>
                                {source}
                            </option>
                        ))}
                    </select>
                </label>
            ))}
            <fieldset className="inline-options">
                <legend>Published outputs</legend>
                {catalog.outputs.map((output) => (
                    <label key={output.name}>
                        <input
                            type="checkbox"
                            checked={draft.publishedOutputs.includes(output.name)}
                            onChange={(event) => {
                                onChange({
                                    ...draft,
                                    publishedOutputs: event.target.checked
                                        ? [...draft.publishedOutputs, output.name]
                                        : draft.publishedOutputs.filter(
                                              (name) => name !== output.name
                                          )
                                });
                            }}
                        />
                        {output.name} · {output.semantic_type}
                    </label>
                ))}
            </fieldset>
        </article>
    );
}
