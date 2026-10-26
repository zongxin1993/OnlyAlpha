import { useState } from "react";
import type { IntegrationDraft, IntegrationType } from "../../../api/integrations/model";

type Field = IntegrationType["configuration_contract"]["fields"][number];
const text = (value: unknown): string =>
    typeof value === "string" || typeof value === "number" || typeof value === "boolean"
        ? String(value)
        : "";

interface Props {
    readonly descriptor: IntegrationType;
    readonly values: Readonly<Record<string, unknown>>;
    readonly secretStatuses: IntegrationDraft["secret_statuses"];
    readonly readOnly: boolean;
    readonly onChange: (fieldId: string, value: unknown) => void;
    readonly onReplaceSecret: (fieldId: string, secret: string) => void | Promise<void>;
    readonly onClearSecret: (fieldId: string) => void | Promise<void>;
}

function SecretField({
    field,
    status,
    readOnly,
    onReplace,
    onClear
}: {
    readonly field: Field;
    readonly status: IntegrationDraft["secret_statuses"][number] | undefined;
    readonly readOnly: boolean;
    readonly onReplace: (secret: string) => void | Promise<void>;
    readonly onClear: () => void | Promise<void>;
}) {
    const [secret, setSecret] = useState("");
    return (
        <div className="integration-field">
            <strong>{field.display_name}</strong>
            <p className="muted">
                {status?.configured ? `已配置 · generation ${String(status.generation)}` : "未配置"}
            </p>
            <label>
                更换 {field.display_name}
                <input
                    type="password"
                    autoComplete="new-password"
                    value={secret}
                    disabled={readOnly}
                    onChange={(event) => {
                        setSecret(event.target.value);
                    }}
                />
            </label>
            <div className="workspace-actions">
                <button
                    type="button"
                    disabled={readOnly || secret.length === 0}
                    onClick={() => {
                        void (async () => {
                            try {
                                await onReplace(secret);
                                setSecret("");
                            } catch {
                                // Unknown outcome keeps value and command intent for explicit retry.
                            }
                        })();
                    }}
                >
                    更换凭据
                </button>
                <button
                    type="button"
                    className="button-subtle"
                    disabled={readOnly || !status?.configured}
                    onClick={() => {
                        void onClear();
                    }}
                >
                    清除凭据
                </button>
            </div>
        </div>
    );
}

function MapField({
    field,
    value,
    readOnly,
    onChange
}: {
    readonly field: Field;
    readonly value: unknown;
    readonly readOnly: boolean;
    readonly onChange: (value: Record<string, number>) => void;
}) {
    const entries = Object.entries(
        typeof value === "object" && value !== null ? (value as Record<string, number>) : {}
    );
    const [key, setKey] = useState("");
    const [number, setNumber] = useState(0);
    return (
        <div className="integration-field">
            <strong>{field.display_name}</strong>
            <table aria-label={field.display_name}>
                <thead>
                    <tr>
                        <th>键</th>
                        <th>整数</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                    {entries.map(([name, item]) => (
                        <tr key={name}>
                            <td>{name}</td>
                            <td>{item}</td>
                            <td>
                                <button
                                    type="button"
                                    disabled={readOnly}
                                    onClick={() => {
                                        onChange(
                                            Object.fromEntries(
                                                entries.filter(([entry]) => entry !== name)
                                            )
                                        );
                                    }}
                                >
                                    移除
                                </button>
                            </td>
                        </tr>
                    ))}
                    <tr>
                        <td>
                            <input
                                aria-label={`${field.display_name} 键`}
                                value={key}
                                disabled={readOnly}
                                onChange={(event) => {
                                    setKey(event.target.value);
                                }}
                            />
                        </td>
                        <td>
                            <input
                                aria-label={`${field.display_name} 整数`}
                                type="number"
                                step="1"
                                value={number}
                                disabled={readOnly}
                                onChange={(event) => {
                                    setNumber(Number(event.target.value));
                                }}
                            />
                        </td>
                        <td>
                            <button
                                type="button"
                                disabled={readOnly || key.length === 0}
                                onClick={() => {
                                    onChange({ ...Object.fromEntries(entries), [key]: number });
                                    setKey("");
                                }}
                            >
                                添加
                            </button>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    );
}

function ConfigurationField({
    field,
    value,
    status,
    readOnly,
    onChange,
    onReplaceSecret,
    onClearSecret
}: {
    readonly field: Field;
    readonly value: unknown;
    readonly status: IntegrationDraft["secret_statuses"][number] | undefined;
    readonly readOnly: boolean;
    readonly onChange: (value: unknown) => void;
    readonly onReplaceSecret: (secret: string) => void | Promise<void>;
    readonly onClearSecret: () => void | Promise<void>;
}) {
    if (field.secret)
        return (
            <SecretField
                field={field}
                status={status}
                readOnly={readOnly}
                onReplace={onReplaceSecret}
                onClear={onClearSecret}
            />
        );
    if (field.value_kind === "STRING_INTEGER_MAP")
        return <MapField field={field} value={value} readOnly={readOnly} onChange={onChange} />;
    if (field.value_kind === "BOOLEAN")
        return (
            <label className="integration-checkbox">
                <input
                    type="checkbox"
                    checked={Boolean(value ?? field.default)}
                    disabled={readOnly}
                    onChange={(event) => {
                        onChange(event.target.checked);
                    }}
                />
                {field.display_name}
            </label>
        );
    if (field.value_kind === "ENUM")
        return (
            <label>
                {field.display_name}
                <select
                    value={text(value ?? field.default)}
                    disabled={readOnly}
                    onChange={(event) => {
                        onChange(event.target.value);
                    }}
                >
                    <option value="">Select…</option>
                    {field.enum_values.map((item) => (
                        <option key={item} value={item}>
                            {item}
                        </option>
                    ))}
                </select>
            </label>
        );
    const numeric = ["INTEGER", "NUMBER", "DURATION"].includes(field.value_kind);
    const inputId = `integration-field-${field.field_id}`;
    const hintId = `${field.field_id}-hint`;
    return (
        <div>
            <label htmlFor={inputId}>{field.display_name}</label>
            <input
                id={inputId}
                type={numeric ? "number" : "text"}
                step={field.value_kind === "INTEGER" ? "1" : numeric ? "any" : undefined}
                min={field.minimum ?? undefined}
                max={field.maximum ?? undefined}
                required={field.required}
                value={text(value ?? field.default)}
                disabled={readOnly}
                aria-describedby={field.value_kind === "DURATION" ? hintId : undefined}
                onChange={(event) => {
                    onChange(
                        numeric && event.target.value !== ""
                            ? Number(event.target.value)
                            : event.target.value
                    );
                }}
            />
            {field.value_kind === "DURATION" ? <small id={hintId}>秒</small> : null}
            {field.description ? <small className="muted">{field.description}</small> : null}
        </div>
    );
}

export function IntegrationConfigurationForm(props: Props) {
    const regular = props.descriptor.configuration_contract.fields.filter(
        (field) => !field.advanced
    );
    const advanced = props.descriptor.configuration_contract.fields.filter(
        (field) => field.advanced
    );
    const render = (field: Field) => (
        <ConfigurationField
            key={field.field_id}
            field={field}
            value={props.values[field.field_id]}
            status={props.secretStatuses.find((item) => item.field_id === field.field_id)}
            readOnly={props.readOnly}
            onChange={(value) => {
                props.onChange(field.field_id, value);
            }}
            onReplaceSecret={(secret) => {
                return props.onReplaceSecret(field.field_id, secret);
            }}
            onClearSecret={() => {
                return props.onClearSecret(field.field_id);
            }}
        />
    );
    return (
        <div className="integration-fields">
            {regular.map(render)}
            {advanced.length > 0 ? (
                <fieldset>
                    <legend>高级设置</legend>
                    {advanced.map(render)}
                </fieldset>
            ) : null}
        </div>
    );
}
