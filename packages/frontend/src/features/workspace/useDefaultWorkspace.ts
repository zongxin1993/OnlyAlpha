import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LocalReadCredentials } from "../../api/marketData/localReadCredentials";
import {
    FetchWorkspaceApiClient,
    WorkspaceWebError,
    type WorkspaceBook,
    type WorkspaceConfiguration
} from "../../api/workspace/client";
import { createUuidV4 } from "../../api/integrations/submissionIntent";
const PENDING = "onlyalpha.workspace.pending-command";
function retainedCommand(): string | null {
    try {
        return sessionStorage.getItem(PENDING);
    } catch {
        return null;
    }
}
export function useDefaultWorkspace(credentials: LocalReadCredentials) {
    const api = useMemo(() => new FetchWorkspaceApiClient(credentials), [credentials]);
    const [book, setBook] = useState<WorkspaceBook | null>(null);
    const [restoration, setRestoration] = useState<{
        key: string;
        configuration: WorkspaceConfiguration | null;
    } | null>(null);
    const [pending, setPending] = useState<string | null>(retainedCommand);
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState<string | null>(null);
    const writing = useRef(false);
    const generation = useRef(0);
    const reload = useCallback(
        async (signal?: AbortSignal) => {
            if (writing.current) return;
            const current = ++generation.current;
            try {
                const value = await api.read(signal);
                if (!signal?.aborted && current === generation.current) {
                    setBook(value);
                    setRestoration({ key: createUuidV4(), configuration: value.configuration });
                    setMessage(null);
                }
            } catch {
                if (!signal?.aborted && current === generation.current)
                    setMessage("默认工作区暂不可用；请重新载入，不会以空配置覆盖。");
            }
        },
        [api]
    );
    const invalidate = useCallback(() => {
        generation.current++;
    }, []);
    useEffect(() => {
        const controller = new AbortController();
        const current = ++generation.current;
        void api
            .read(controller.signal)
            .then((value) => {
                if (!controller.signal.aborted && current === generation.current) {
                    setBook(value);
                    setRestoration({ key: createUuidV4(), configuration: value.configuration });
                    setMessage(null);
                }
            })
            .catch(() => {
                if (!controller.signal.aborted && current === generation.current)
                    setMessage("默认工作区暂不可用；请重新载入，不会以空配置覆盖。");
            });
        return () => {
            controller.abort();
            invalidate();
        };
    }, [api, invalidate]);
    function clearPending(id: string) {
        if (sessionStorage.getItem(PENDING) === id) sessionStorage.removeItem(PENDING);
        setPending((current) => (current === id ? null : current));
    }
    const save = async (configuration: WorkspaceConfiguration) => {
        if (book === null || writing.current || pending !== null) return false;
        writing.current = true;
        setBusy(true);
        generation.current++;
        const intent = {
            schema_version: 2 as const,
            command_id: createUuidV4(),
            expected_version: book.version,
            configuration
        };
        try {
            sessionStorage.setItem(PENDING, intent.command_id);
        } catch {
            setMessage("无法保留提交标识，本次未提交；请检查站点会话存储权限。");
            writing.current = false;
            setBusy(false);
            return false;
        }
        setPending(intent.command_id);
        setMessage(null);
        try {
            const saved = await api.save(intent);
            setBook(saved);
            clearPending(intent.command_id);
            setMessage("默认工作区已保存；仅保存配置。");
            return true;
        } catch (error) {
            setMessage(
                error instanceof WorkspaceWebError && error.definitive
                    ? error.code === "WORKSPACE_VERSION_CONFLICT"
                        ? "其他窗口已保存工作区；当前编辑保留，请显式重新载入后再决定。"
                        : "工作区未保存，请检查配置或权限。"
                    : "提交结果尚未确认；请核对原提交，不会重复保存。"
            );
            if (error instanceof WorkspaceWebError && error.definitive) {
                try {
                    clearPending(intent.command_id);
                } catch {
                    /* Keep the original queryable identity. */
                }
            }
            return false;
        } finally {
            writing.current = false;
            setBusy(false);
        }
    };
    const resolvePending = async () => {
        if (pending === null || writing.current) return;
        writing.current = true;
        setBusy(true);
        generation.current++;
        try {
            const accepted = await api.command(pending);
            setBook(accepted);
            clearPending(pending);
            setMessage("原提交已确认；当前编辑保留，可显式重新载入保存配置。");
        } catch {
            setMessage("提交结果仍未确认，请稍后再次核对原提交。");
        } finally {
            writing.current = false;
            setBusy(false);
        }
    };
    return { book, restoration, pending, busy, message, reload, save, resolvePending };
}
