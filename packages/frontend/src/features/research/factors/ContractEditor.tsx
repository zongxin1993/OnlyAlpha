import { useEffect, useId, useRef, useState } from "react";
import {
    changeRow,
    contractFromRows,
    contractTitles,
    contractTypes,
    inspectContract,
    newRow,
    rowsFromContract,
    sameContractValues,
    type ContractKind,
    type ContractRow
} from "./contractForm";
const labels = { DECIMAL: "精确数值", INTEGER: "整数", BOOLEAN: "是或否", STRING: "文本" };
const jsonLabels = {
    input_contract: "输入契约 JSON",
    parameter_contract: "参数契约 JSON",
    output_contract: "输出契约 JSON"
};
export function ContractEditor({
    kind,
    value,
    onChange,
    onValidity
}: {
    readonly kind: ContractKind;
    readonly value: string;
    readonly onChange: (text: string) => void;
    readonly onValidity: (kind: ContractKind, error: string) => void;
}) {
    const title = contractTitles[kind];
    const id = useId();
    const [baseline, setBaseline] = useState(value);
    const formText = useRef(value);
    const [rows, setRows] = useState(() => rowsFromContract(kind, value) ?? []);
    const [advanced, setAdvanced] = useState(() => rowsFromContract(kind, value) === null);
    const [notice, setNotice] = useState("");
    const [confirmed, setConfirmed] = useState<Set<ContractRow["original"]>>(() => new Set());
    const [pending, setPending] = useState<{ before: ContractRow[]; next: ContractRow[] } | null>(
        null
    );
    const result = contractFromRows(kind, rows, baseline);
    const error = advanced
        ? inspectContract(value).error
        : pending !== null
          ? "请确认保持必填设置的关联变更"
          : result.error;
    useEffect(() => {
        onValidity(kind, error);
    }, [kind, error, onValidity]);
    function commit(next: ContractRow[]) {
        setRows(next);
        setNotice("");
        const built = contractFromRows(kind, next, baseline);
        if (built.error) {
            setPending(null);
            return;
        }
        if (built.companionRows.some((row) => !confirmed.has(row.original))) {
            setPending({ before: pending?.before ?? rows, next });
            return;
        }
        setPending(null);
        setConfirmed(
            (previous) =>
                new Set(
                    built.companionRows
                        .map((row) => row.original)
                        .filter((original) => previous.has(original))
                )
        );
        formText.current = built.text;
        onChange(built.text);
    }
    function update<
        K extends "name" | "type" | "nullable" | "required" | "hasDefault" | "defaultText"
    >(index: number, key: K, next: ContractRow[K]) {
        commit(rows.map((row, i) => (i === index ? changeRow(row, key, next) : row)));
    }
    function toggle() {
        setNotice("");
        if (advanced) {
            const next = rowsFromContract(kind, value);
            if (next === null) {
                setNotice("当前结构无法无损转换；仅此项保留高级 JSON，原始字段完整保留。");
                return;
            }
            if (!sameContractValues(value, formText.current)) {
                setRows(next);
                setBaseline(value);
                setConfirmed(new Set());
                formText.current = value;
            }
            setPending(null);
            setAdvanced(false);
        } else if (error) setNotice("请先修正当前表单，未完成的输入仍保留。");
        else setAdvanced(true);
    }
    return (
        <section className="factor-contract" aria-label={title}>
            <header>
                <h4>{title}</h4>
                <button type="button" onClick={toggle}>
                    {advanced ? `切换到${title}表单` : `${title}高级 JSON`}
                </button>
            </header>
            <p>
                {kind === "input_contract"
                    ? "声明计算需要哪些输入；具体数据源在使用时选择。"
                    : kind === "parameter_contract"
                      ? "定义可调整的参数，不是在这里运行计算。"
                      : "声明源码返回的结果字段。"}
            </p>
            {advanced ? (
                <>
                    {rowsFromContract(kind, value) === null && !inspectContract(value).error && (
                        <p>此结构需要高级编辑；其他两项仍可独立使用表单。</p>
                    )}
                    <label>
                        {jsonLabels[kind]}
                        <textarea
                            spellCheck={false}
                            rows={7}
                            value={value}
                            aria-invalid={!!error}
                            aria-describedby={error ? `${id}-error` : undefined}
                            onChange={(e) => {
                                onChange(e.target.value);
                            }}
                        />
                    </label>
                </>
            ) : (
                <>
                    {rows.length === 0 && (
                        <p>
                            {kind === "parameter_contract"
                                ? "没有可调参数"
                                : kind === "input_contract"
                                  ? "没有所需数据"
                                  : "没有计算结果"}
                        </p>
                    )}
                    {rows.map((row, index) => {
                        const prefix = `${title}第 ${String(index + 1)} 项`;
                        return (
                            <fieldset
                                className="factor-contract-row"
                                key={index}
                                aria-label={prefix}
                            >
                                <legend>{index + 1}</legend>
                                <div className="factor-contract-fields">
                                    <label>
                                        {kind === "output_contract" ? "结果字段名" : "代码中的名称"}
                                        <input
                                            aria-label={`${prefix}${kind === "output_contract" ? "结果字段名" : "代码中的名称"}`}
                                            value={row.name}
                                            onChange={(e) => {
                                                update(index, "name", e.target.value);
                                            }}
                                        />
                                    </label>
                                    <label>
                                        {kind === "parameter_contract" ? "参数类型" : "数据类型"}
                                        <select
                                            aria-label={`${prefix}类型`}
                                            value={row.type}
                                            onChange={(e) => {
                                                update(index, "type", e.target.value);
                                            }}
                                        >
                                            {contractTypes.map((type) => (
                                                <option key={type} value={type}>
                                                    {labels[type]}
                                                </option>
                                            ))}
                                        </select>
                                    </label>
                                    {kind === "parameter_contract" ? (
                                        <>
                                            <label className="factor-contract-check">
                                                <input
                                                    type="checkbox"
                                                    aria-label={`${prefix}使用时必须填写`}
                                                    checked={row.required}
                                                    onChange={(e) => {
                                                        update(index, "required", e.target.checked);
                                                    }}
                                                />
                                                使用时必须填写
                                            </label>
                                            <label className="factor-contract-check">
                                                <input
                                                    type="checkbox"
                                                    aria-label={`${prefix}设置默认值`}
                                                    checked={row.hasDefault}
                                                    onChange={(e) => {
                                                        update(
                                                            index,
                                                            "hasDefault",
                                                            e.target.checked
                                                        );
                                                    }}
                                                />
                                                设置默认值
                                            </label>
                                            {row.hasDefault && (
                                                <label>
                                                    默认值
                                                    {row.type === "BOOLEAN" ? (
                                                        <select
                                                            aria-label={`${prefix}默认值`}
                                                            value={row.defaultText}
                                                            onChange={(e) => {
                                                                update(
                                                                    index,
                                                                    "defaultText",
                                                                    e.target.value
                                                                );
                                                            }}
                                                        >
                                                            <option value="">请选择</option>
                                                            <option value="true">是</option>
                                                            <option value="false">否</option>
                                                        </select>
                                                    ) : (
                                                        <input
                                                            aria-label={`${prefix}默认值`}
                                                            value={row.defaultText}
                                                            inputMode={
                                                                row.type === "INTEGER"
                                                                    ? "numeric"
                                                                    : row.type === "DECIMAL"
                                                                      ? "decimal"
                                                                      : "text"
                                                            }
                                                            onChange={(e) => {
                                                                update(
                                                                    index,
                                                                    "defaultText",
                                                                    e.target.value
                                                                );
                                                            }}
                                                        />
                                                    )}
                                                </label>
                                            )}
                                        </>
                                    ) : (
                                        <label className="factor-contract-check">
                                            <input
                                                type="checkbox"
                                                aria-label={`${prefix}允许缺失`}
                                                checked={row.nullable}
                                                onChange={(e) => {
                                                    update(index, "nullable", e.target.checked);
                                                }}
                                            />
                                            允许缺失
                                        </label>
                                    )}
                                    <button
                                        type="button"
                                        aria-label={`删除${prefix}`}
                                        onClick={() => {
                                            commit(rows.filter((_, i) => i !== index));
                                        }}
                                    >
                                        删除
                                    </button>
                                </div>
                                {row.name !== row.originalName && (
                                    <p>
                                        请同步检查源码中的输入、参数或结果名称；源码不会自动修改。
                                    </p>
                                )}
                                {kind === "input_contract" && row.name === "close" && (
                                    <p>close：收盘价；名称需与源码一致。</p>
                                )}
                                {kind === "output_contract" && (
                                    <details>
                                        <summary>更多设置 · 结果含义：因子值</summary>
                                        <p>
                                            使用现有 FACTOR_VALUE 含义；自定义含义通过高级 JSON
                                            编辑。
                                        </p>
                                    </details>
                                )}
                            </fieldset>
                        );
                    })}
                    <button
                        type="button"
                        onClick={() => {
                            commit([...rows, newRow(kind)]);
                        }}
                    >
                        {kind === "parameter_contract"
                            ? "添加参数"
                            : kind === "input_contract"
                              ? "添加数据"
                              : "添加结果"}
                    </button>
                    {kind === "parameter_contract" && (
                        <p>必填与默认值独立；必填时仍需明确提供参数，默认值不会自动生效。</p>
                    )}
                </>
            )}
            {pending !== null && (
                <div className="factor-contract-confirm" role="group" aria-label="确认关联变更">
                    <p>
                        默认值的有无会影响缺省的必填含义。为保持所选必填设置，此次将同时显式记录
                        required；不会修改其他契约。
                    </p>
                    <pre>{contractFromRows(kind, pending.next, baseline).text}</pre>
                    <button
                        type="button"
                        onClick={() => {
                            const built = contractFromRows(kind, pending.next, baseline);
                            setConfirmed(new Set(built.companionRows.map((row) => row.original)));
                            setPending(null);
                            formText.current = built.text;
                            onChange(built.text);
                        }}
                    >
                        确认关联变更
                    </button>
                    <button
                        type="button"
                        onClick={() => {
                            setRows(pending.before);
                            setPending(null);
                        }}
                    >
                        取消关联变更
                    </button>
                </div>
            )}
            {notice && <p role="status">{notice}</p>}
            {error && (
                <p id={`${id}-error`} role="alert">
                    {error}
                </p>
            )}
        </section>
    );
}
