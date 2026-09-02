import type { ExpressionDraft, OperandDraft, ScalarType } from "./researchDraft";
import { emptyComparison } from "./researchDraft";

function OperandEditor({
    value,
    sources,
    onChange
}: {
    readonly value: OperandDraft;
    readonly sources: readonly string[];
    readonly onChange: (value: OperandDraft) => void;
}) {
    return (
        <div className="operand-editor">
            <select
                aria-label="Operand kind"
                value={value.kind}
                onChange={(event) => {
                    onChange({
                        ...value,
                        kind: event.target.value === "LITERAL" ? "LITERAL" : "REFERENCE"
                    });
                }}
            >
                <option value="REFERENCE">Reference</option>
                <option value="LITERAL">Literal</option>
            </select>
            {value.kind === "REFERENCE" ? (
                <select
                    aria-label="Operand reference"
                    value={value.reference}
                    onChange={(event) => {
                        onChange({ ...value, reference: event.target.value });
                    }}
                >
                    {sources.map((source) => (
                        <option key={source} value={source}>
                            {source}
                        </option>
                    ))}
                </select>
            ) : (
                <>
                    <select
                        aria-label="Literal type"
                        value={value.dataType}
                        onChange={(event) => {
                            onChange({ ...value, dataType: event.target.value as ScalarType });
                        }}
                    >
                        {(["DECIMAL", "INTEGER", "BOOLEAN", "STRING"] as const).map((type) => (
                            <option key={type}>{type}</option>
                        ))}
                    </select>
                    <input
                        aria-label="Literal value"
                        value={value.valueText}
                        onChange={(event) => {
                            onChange({ ...value, valueText: event.target.value });
                        }}
                    />
                </>
            )}
        </div>
    );
}

export function ExpressionEditor({
    value,
    sources,
    onChange
}: {
    readonly value: ExpressionDraft;
    readonly sources: readonly string[];
    readonly onChange: (value: ExpressionDraft) => void;
}) {
    const defaultReference = sources[0] ?? "bar.close";
    return (
        <div className="expression-node">
            <select
                aria-label="Expression kind"
                value={value.kind}
                onChange={(event) => {
                    const kind = event.target.value;
                    if (kind === "COMPARISON") onChange(emptyComparison(defaultReference));
                    else if (kind === "NOT")
                        onChange({ kind: "NOT", operand: emptyComparison(defaultReference) });
                    else
                        onChange({
                            kind: kind === "OR" ? "OR" : "AND",
                            operands: [
                                emptyComparison(defaultReference),
                                emptyComparison(defaultReference)
                            ]
                        });
                }}
            >
                <option value="COMPARISON">Comparison</option>
                <option value="AND">AND / ALL</option>
                <option value="OR">OR / ANY</option>
                <option value="NOT">NOT</option>
            </select>
            {value.kind === "COMPARISON" ? (
                <div className="comparison-grid">
                    <OperandEditor
                        value={value.left}
                        sources={sources}
                        onChange={(left) => {
                            onChange({ ...value, left });
                        }}
                    />
                    <select
                        aria-label="Comparison operator"
                        value={value.operator}
                        onChange={(event) => {
                            onChange({
                                ...value,
                                operator: event.target.value as typeof value.operator
                            });
                        }}
                    >
                        {(["==", "!=", "<", "<=", ">", ">="] as const).map((operator) => (
                            <option key={operator}>{operator}</option>
                        ))}
                    </select>
                    <OperandEditor
                        value={value.right}
                        sources={sources}
                        onChange={(right) => {
                            onChange({ ...value, right });
                        }}
                    />
                </div>
            ) : value.kind === "NOT" ? (
                <ExpressionEditor
                    value={value.operand}
                    sources={sources}
                    onChange={(operand) => {
                        onChange({ ...value, operand });
                    }}
                />
            ) : (
                <div className="expression-children">
                    {value.operands.map((operand, index) => (
                        <div className="expression-child" key={index}>
                            <ExpressionEditor
                                value={operand}
                                sources={sources}
                                onChange={(next) => {
                                    onChange({
                                        ...value,
                                        operands: value.operands.map((item, itemIndex) =>
                                            itemIndex === index ? next : item
                                        )
                                    });
                                }}
                            />
                            {value.operands.length > 2 ? (
                                <button
                                    type="button"
                                    className="button-subtle"
                                    onClick={() => {
                                        onChange({
                                            ...value,
                                            operands: value.operands.filter(
                                                (_, itemIndex) => itemIndex !== index
                                            )
                                        });
                                    }}
                                >
                                    Remove condition
                                </button>
                            ) : null}
                        </div>
                    ))}
                    <button
                        type="button"
                        className="button-subtle"
                        onClick={() => {
                            onChange({
                                ...value,
                                operands: [...value.operands, emptyComparison(defaultReference)]
                            });
                        }}
                    >
                        Add condition
                    </button>
                </div>
            )}
        </div>
    );
}
