import { useState, type SyntheticEvent } from "react";
import { useNavigate } from "react-router-dom";
import { parseResearchResultFingerprint } from "../../../domain/research/identity";

export function ResearchOpenPage() {
    const [value, setValue] = useState("");
    const [error, setError] = useState<string | null>(null);
    const navigate = useNavigate();

    function submit(event: SyntheticEvent<HTMLFormElement>) {
        event.preventDefault();
        try {
            const fingerprint = parseResearchResultFingerprint(value);
            setError(null);
            void navigate(`/research/${fingerprint}`);
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : "Invalid fingerprint");
        }
    }

    return (
        <main className="page narrow">
            <p className="eyebrow">Portable Artifact Consumer</p>
            <h1>Open an exact Research result</h1>
            <p className="lede">
                Enter the full lower-case SHA256. There is intentionally no latest, search, or
                catalog authority.
            </p>
            <form onSubmit={submit} noValidate>
                <label htmlFor="research-fingerprint">Research Result fingerprint</label>
                <input
                    id="research-fingerprint"
                    value={value}
                    onChange={(event) => {
                        setValue(event.target.value);
                    }}
                    autoComplete="off"
                    spellCheck={false}
                    placeholder="64 lower-case hexadecimal characters"
                />
                {error === null ? null : (
                    <p className="field-error" role="alert">
                        {error}
                    </p>
                )}
                <button type="submit">Open exact result</button>
            </form>
        </main>
    );
}
