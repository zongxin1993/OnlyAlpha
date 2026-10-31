import { useRef, useState } from "react";
import { Alert, Button, Form, Input, Space } from "antd";
import { z } from "zod";
import {
    acceptModelSave,
    beginModelSave,
    finishModelSave,
    pendingModelResource
} from "./modelSave";
import { type Access, type Model, modelSchema, request } from "./api";
interface Values {
    name: string;
    base_url: string;
    model_id: string;
    model_version: string;
    secret: string;
}
export function ModelSettings({
    access,
    model,
    onSaved,
    blocked
}: {
    readonly blocked: boolean;
    readonly access: Access;
    readonly model: Model | null;
    readonly onSaved: (model: Model) => void;
}) {
    const [form] = Form.useForm<Values>();
    const [busy, setBusy] = useState(false);
    const working = useRef(false);
    const target = useRef({
        id: model?.id ?? pendingModelResource(access) ?? crypto.randomUUID(),
        revision: model?.revision ?? null
    });
    const [error, setError] = useState("");
    const [testing, setTesting] = useState(false);
    const [reply, setReply] = useState("");
    const [tested, setTested] = useState(false);
    async function testConnection() {
        if (working.current) return;
        working.current = true;
        let values: Values;
        try {
            values = await form.validateFields();
        } catch {
            working.current = false;
            return;
        }
        setTesting(true);
        setTested(false);
        setReply("");
        setError("");
        try {
            const result = await request(
                "/api/v1/agent/models/test",
                z.strictObject({ reply: z.string().min(1).max(2000) }),
                { base_url: values.base_url, model_id: values.model_id, secret: values.secret },
                undefined,
                access
            );
            setReply(result.reply);
            setTested(true);
        } catch (error: unknown) {
            const messages: Record<string, string> = {
                AGENT_MODEL_ENDPOINT_INVALID:
                    "请填写有效的模型服务地址。本机和局域网 IP 支持 HTTP，公网地址请使用 HTTPS。",
                MODEL_AUTH_FAILED: "模型服务拒绝了密钥，请检查 API 密钥和访问权限。",
                MODEL_ENDPOINT_NOT_FOUND:
                    "没有找到模型接口，请检查服务地址是否包含正确的 /v1 路径。",
                MODEL_BUSY: "模型服务繁忙或额度不足，请稍后再测试。",
                MODEL_REJECTED: "模型服务拒绝了测试请求，请检查模型名称及服务配置。",
                MODEL_RESPONSE_INVALID: "模型没有返回有效的文字回复，请确认服务支持聊天接口。"
            };
            const message = error instanceof Error ? messages[error.message] : undefined;
            setError(
                message ??
                    "未能取得模型回复，请检查服务地址、网络连接和模型是否已启动。配置尚未保存。"
            );
        } finally {
            working.current = false;
            setTesting(false);
        }
    }
    async function save(values: Values) {
        if (working.current || !tested || blocked) return;
        working.current = true;
        setBusy(true);
        setError("");
        try {
            const previous = await finishModelSave(access);
            if (previous?.id === target.current.id) target.current.revision = previous.revision;
            const id = target.current.id;
            const command = crypto.randomUUID();
            beginModelSave(access, id, command);
            let saved: Model;
            try {
                saved = await request(
                    `/api/v1/agent/models/${id}`,
                    modelSchema,
                    { expected: target.current.revision, ...values },
                    command,
                    access,
                    "PUT"
                );
                acceptModelSave(saved, access, id, command);
            } catch {
                const original = await finishModelSave(access);
                if (original === null) throw new Error("not saved");
                if (
                    original.id !== id ||
                    original.credential_generation !== command ||
                    original.owner !== access.subject
                )
                    throw new Error("receipt mismatch");
                saved = original;
            }
            target.current.revision = saved.revision;
            form.setFieldValue("secret", "");
            onSaved(saved);
        } catch {
            setError("模型设置暂时无法完成，请检查连接后重试。");
        } finally {
            form.setFieldValue("secret", "");
            setTested(false);
            setReply("");
            working.current = false;
            setBusy(false);
        }
    }
    const required = [{ required: true, whitespace: true, message: "请填写此项" }];
    return (
        <Form<Values>
            form={form}
            aria-label="模型配置"
            className="factor-chat-model-editor"
            layout="vertical"
            disabled={busy || testing}
            onValuesChange={() => {
                setTested(false);
                setReply("");
                setError("");
            }}
            initialValues={{
                name: model?.name ?? "聊天模型",
                base_url: model?.base_url ?? "",
                model_id: model?.model_id ?? "",
                model_version: model?.model_version ?? "",
                secret: ""
            }}
            onFinish={(values) => {
                void save(values);
            }}
        >
            <Form.Item label="配置名称" name="name" rules={required}>
                <Input maxLength={200} />
            </Form.Item>
            <Form.Item
                label="服务地址"
                name="base_url"
                rules={[...required, { type: "url", message: "请输入完整的服务地址" }]}
            >
                <Input type="url" placeholder="https://…/v1" />
            </Form.Item>
            <Form.Item label="模型名称" name="model_id" rules={required}>
                <Input maxLength={200} />
            </Form.Item>
            <Form.Item label="模型版本说明" name="model_version" rules={required}>
                <Input maxLength={200} />
            </Form.Item>
            <Form.Item label="API 密钥" name="secret" rules={required}>
                <Input.Password
                    autoComplete="new-password"
                    maxLength={8192}
                    visibilityToggle={false}
                />
            </Form.Item>
            <p>密钥不会回显。</p>
            <p>先测试连接，收到模型回复后再保存。修改配置后需重新测试。</p>
            <Space wrap>
                <Button
                    onClick={() => void testConnection()}
                    loading={testing}
                    disabled={busy || testing}
                >
                    测试连接
                </Button>
                <Button
                    type="primary"
                    htmlType="submit"
                    loading={busy}
                    disabled={busy || testing || blocked || !tested}
                >
                    保存模型设置
                </Button>
            </Space>
            {reply !== "" && (
                <Alert
                    type="success"
                    title={<span style={{ whiteSpace: "pre-wrap" }}>{reply}</span>}
                />
            )}
            {error !== "" && <Alert type="warning" title={error} />}
        </Form>
    );
}
