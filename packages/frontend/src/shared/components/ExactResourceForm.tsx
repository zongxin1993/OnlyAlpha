import { useState, type SyntheticEvent } from "react";

export function ExactResourceForm({
    id,
    label,
    action,
    initialValue,
    placeholder,
    onOpen
}: {
    readonly id: string;
    readonly label: string;
    readonly action: string;
    readonly initialValue: string;
    readonly placeholder: string;
    readonly onOpen: (value: string) => void;
}) {
    const [value, setValue] = useState(initialValue);
    const [error, setError] = useState<string | null>(null);
    function submit(event: SyntheticEvent<HTMLFormElement>) {
        event.preventDefault();
        try {
            onOpen(value);
            setError(null);
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : "Invalid exact identity");
        }
    }
    return (
        <form className="exact-resource-form" aria-label={action} onSubmit={submit} noValidate>
            <label htmlFor={id}>{label}</label>
            <div className="exact-resource-controls">
                <input
                    id={id}
                    value={value}
                    onChange={(event) => {
                        setValue(event.target.value);
                        setError(null);
                    }}
                    autoComplete="off"
                    spellCheck={false}
                    placeholder={placeholder}
                />
                <button type="submit">{action}</button>
            </div>
            {error === null ? null : (
                <p role="alert" className="field-error">
                    {error}
                </p>
            )}
        </form>
    );
}
