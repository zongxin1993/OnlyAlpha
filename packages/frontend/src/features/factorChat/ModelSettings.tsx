import { useState } from "react";
import { type Access, type Model, modelSchema, request } from "./api";
export function ModelSettings({
    access,
    model,
    onSaved,
    onPending,
    blocked,
    onSettled
}: {
    readonly blocked: boolean;
    readonly onSettled: () => void;
    readonly access: Access;
    readonly model: Model | null;
    readonly onSaved: () => Promise<void>;
    readonly onPending: (id: string, command: string) => void;
}) {
    const [name, setName] = useState(model?.name ?? "聊天模型");
    const [url, setUrl] = useState(model?.base_url ?? "");
    const [modelId, setModelId] = useState(model?.model_id ?? "");
    const [version, setVersion] = useState(model?.model_version ?? "");
    const [secret, setSecret] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    return (
        <form
            className="factor-chat-model-editor"
            aria-label="模型配置"
            onSubmit={(e) => {
                e.preventDefault();
                setBusy(true);
                setError("");
                const id = model?.id ?? crypto.randomUUID();
                const command = crypto.randomUUID();
                onPending(id, command);
                void request(
                    `/api/v1/agent/models/${id}`,
                    modelSchema,
                    {
                        expected: model?.revision ?? null,
                        name,
                        base_url: url,
                        model_id: modelId,
                        model_version: version,
                        secret
                    },
                    command,
                    access,
                    "PUT"
                )
                    .then(async () => {
                        setSecret("");
                        await onSaved();
                    })
                    .catch((e: unknown) => {
                        setSecret("");
                        setError(
                            "保存结果尚未确认，请使用上方“核对并重新载入”。" +
                                (e instanceof Error ? e.message : String(e))
                        );
                    })
                    .finally(() => {
                        setBusy(false);
                        onSettled();
                    });
            }}
        >
            <label>
                配置名称
                <input
                    value={name}
                    maxLength={200}
                    required
                    onChange={(e) => {
                        setName(e.target.value);
                    }}
                />
            </label>
            <label>
                服务地址
                <input
                    value={url}
                    type="url"
                    required
                    placeholder="https://…/v1"
                    onChange={(e) => {
                        setUrl(e.target.value);
                    }}
                />
            </label>
            <label>
                模型名称
                <input
                    value={modelId}
                    required
                    maxLength={200}
                    onChange={(e) => {
                        setModelId(e.target.value);
                    }}
                />
            </label>
            <label>
                模型版本说明
                <input
                    value={version}
                    required
                    maxLength={200}
                    onChange={(e) => {
                        setVersion(e.target.value);
                    }}
                />
            </label>
            <label>
                API 密钥
                <input
                    value={secret}
                    type="password"
                    autoComplete="new-password"
                    required
                    maxLength={8192}
                    onChange={(e) => {
                        setSecret(e.target.value);
                    }}
                />
            </label>
            <p>密钥仅提交给 Agent，不会回显；修改配置产生新版本，已有对话保留原绑定。</p>
            <button disabled={busy || blocked}>{busy ? "保存中…" : "保存模型设置"}</button>
            {error !== "" && <p role="alert">{error}</p>}
        </form>
    );
}
