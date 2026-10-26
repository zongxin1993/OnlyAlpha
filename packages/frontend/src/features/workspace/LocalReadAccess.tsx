import { useState, useSyncExternalStore } from "react";
import { useLocalReadCredentials } from "../../app/providers";

export function LocalReadAccess() {
    const credentials = useLocalReadCredentials();
    useSyncExternalStore(credentials.subscribe, credentials.getGeneration);
    const [invalid, setInvalid] = useState(false);
    const configured = credentials.capture().bearer !== null;
    return (
        <form
            aria-label="本地行情只读访问"
            onSubmit={(event) => {
                event.preventDefault();
                const form = event.currentTarget;
                const input = form.elements.namedItem("local-read-credential") as HTMLInputElement;
                const bearer = input.value;
                input.value = "";
                if (!/^[0-9a-f]{64}$/.test(bearer)) {
                    setInvalid(true);
                    return;
                }
                credentials.replace(bearer);
                setInvalid(false);
            }}
        >
            <label>
                本地行情凭据
                <input
                    type="password"
                    name="local-read-credential"
                    autoComplete="off"
                    maxLength={64}
                />
            </label>
            <button type="submit">连接只读行情</button>
            <button
                type="button"
                disabled={!configured}
                onClick={() => {
                    credentials.replace(null);
                }}
            >
                清除凭据
            </button>
            <span role="status">
                {invalid
                    ? "凭据格式错误"
                    : configured
                      ? "已提供只读凭据（权限由服务器验证）"
                      : "未提供凭据"}
            </span>
        </form>
    );
}
