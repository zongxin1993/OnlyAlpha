/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Alert, Button, ConfigProvider, Drawer, Empty, Space, Tabs, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { DataSourceManager } from "../data/sources/DataSourceManager";
import { ModelSettings } from "../factorChat/ModelSettings";
import {
    connect,
    modelsSchema,
    request,
    savedAccess,
    type Access,
    type Model
} from "../factorChat/api";
import { finishModelSave } from "../factorChat/modelSave";
import "./settings.css";
export const settingsChangedEvent = "onlyalpha-settings-changed";
type Section = "models" | "sources";
const SettingsContext = createContext<{
    openSettings: (section: Section) => void;
}>({ openSettings: () => undefined });
export function useSettings() {
    return useContext(SettingsContext);
}
function changed() {
    window.dispatchEvent(new Event(settingsChangedEvent));
}
export function SettingsProvider({ children }: { readonly children: ReactNode }) {
    const [section, setSection] = useState<Section>("models");
    const [open, setOpen] = useState(false);
    return (
        <ConfigProvider
            locale={zhCN}
            theme={{
                algorithm: theme.defaultAlgorithm,
                token: {
                    colorPrimary: "#1f5f8b",
                    colorBgBase: "#f8f8f5",
                    colorTextBase: "#20242b",
                    borderRadius: 6,
                    fontFamily: "inherit"
                }
            }}
        >
            <SettingsContext.Provider
                value={{
                    openSettings: (next) => {
                        setSection(next);
                        setOpen(true);
                    }
                }}
            >
                {children}
                <Drawer
                    className="global-settings"
                    title="设置"
                    open={open}
                    size={760}
                    destroyOnHidden
                    onClose={() => {
                        setOpen(false);
                        changed();
                    }}
                    closable={{ "aria-label": "关闭设置" }}
                >
                    <Tabs
                        activeKey={section}
                        onChange={(key) => {
                            if (key === "models" || key === "sources") setSection(key);
                        }}
                        destroyOnHidden
                        items={[
                            {
                                key: "sources",
                                label: "数据源",
                                children: <DataSourceManager variant="page" />
                            },
                            { key: "models", label: "模型", children: <ModelManager /> }
                        ]}
                    />
                </Drawer>
            </SettingsContext.Provider>
        </ConfigProvider>
    );
}
function ModelManager() {
    const [access, setAccess] = useState<Access | null>(savedAccess);
    const [models, setModels] = useState<Model[]>([]);
    const [editor, setEditor] = useState<Model | "new" | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [success, setSuccess] = useState("");
    const working = useRef(false);
    async function auth() {
        const current = savedAccess();
        if (current !== null && current.expires_at > Date.now() / 1000) {
            setAccess(current);
            return current;
        }
        const next = await connect();
        setAccess(next);
        return next;
    }
    async function load() {
        const current = await auth();
        const saved = await finishModelSave(current);
        if (saved !== null) setSuccess("模型设置已保存");
        const result = await request(
            "/api/v1/agent/models",
            modelsSchema,
            undefined,
            undefined,
            current
        );
        setModels(result.items);
    }
    async function act(action: () => Promise<void>) {
        if (working.current) return;
        working.current = true;
        setBusy(true);
        setError("");
        try {
            await action();
        } catch {
            setError("模型设置暂时无法完成，请检查连接后重试。");
        } finally {
            working.current = false;
            setBusy(false);
        }
    }
    useEffect(() => {
        void Promise.resolve().then(() => act(load));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return (
        <section aria-label="模型设置" className="model-settings-content">
            <p>管理用于因子讨论的模型。修改配置后，新对话使用新版本，已有对话保留原模型。</p>
            <Space>
                <Button
                    disabled={busy}
                    onClick={() => {
                        setSuccess("");
                        setError("");
                        setEditor("new");
                    }}
                >
                    添加模型
                </Button>
                <Button
                    loading={busy}
                    onClick={() => {
                        void act(load);
                    }}
                >
                    重新载入模型
                </Button>
            </Space>
            {error !== "" && <Alert type="error" title={error} />}
            {success !== "" && <Alert type="success" title={success} />}
            {models.length === 0 && !busy ? (
                <Empty description="尚未配置模型" />
            ) : (
                <ul className="model-settings-list">
                    {models.map((model) => (
                        <li key={model.id}>
                            <div>
                                <strong>{model.name}</strong>
                                <p>
                                    {model.model_id} · {model.model_version}
                                </p>
                                <small>{model.base_url}</small>
                            </div>
                            <Button
                                disabled={busy}
                                onClick={() => {
                                    setSuccess("");
                                    setError("");
                                    setEditor(model);
                                }}
                            >
                                编辑 {model.name}
                            </Button>
                        </li>
                    ))}
                </ul>
            )}
            {editor !== null && access !== null && (
                <ModelSettings
                    key={editor === "new" ? "new" : editor.revision}
                    access={access}
                    model={editor === "new" ? null : editor}
                    blocked={busy}
                    onSaved={(saved) => {
                        setModels((items) => [
                            ...items.filter((item) => item.id !== saved.id),
                            saved
                        ]);
                        setEditor(null);
                        setSuccess("模型设置已保存");
                        setError("");
                        changed();
                    }}
                />
            )}
        </section>
    );
}
