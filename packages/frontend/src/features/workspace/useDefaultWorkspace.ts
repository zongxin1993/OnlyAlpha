import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LocalReadCredentials } from "../../api/marketData/localReadCredentials";
import {
    FetchWorkspaceApiClient,
    WorkspaceWebError,
    type WorkspaceBook,
    type WorkspaceConfiguration
} from "../../api/workspace/client";
import { createUuidV4 } from "../../api/integrations/submissionIntent";
const PENDING = "onlyalpha.workspace.library.pending-command";
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
        async (signal?: AbortSignal, restore = true) => {
            if (writing.current) return;
            const current = ++generation.current;
            try {
                const value = await api.read(signal);
                if (!signal?.aborted && current === generation.current) {
                    setBook(value);
                    if (restore)
                        setRestoration({
                            key: createUuidV4(),
                            configuration:
                                value.workspaces.find(
                                    (item) => item.workspace_id === value.active_workspace_id
                                )?.configuration ?? null
                        });
                    setMessage(null);
                }
            } catch {
                if (!signal?.aborted && current === generation.current)
                    setMessage("工作区列表暂不可用；请重新载入，不会以空配置覆盖。");
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
                    setRestoration({
                        key: createUuidV4(),
                        configuration:
                            value.workspaces.find(
                                (item) => item.workspace_id === value.active_workspace_id
                            )?.configuration ?? null
                    });
                    setMessage(null);
                }
            })
            .catch(() => {
                if (!controller.signal.aborted && current === generation.current)
                    setMessage("工作区列表暂不可用；请重新载入，不会以空配置覆盖。");
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
    const commit = async (
        workspaces: WorkspaceBook["workspaces"],
        active_workspace_id: string,
        restore: boolean
    ) => {
        if (book === null || writing.current || pending !== null) return false;
        writing.current = true;
        setBusy(true);
        generation.current++;
        const intent = {
            schema_version: 3 as const,
            command_id: createUuidV4(),
            expected_version: book.version,
            active_workspace_id,
            workspaces
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
            if (restore)
                setRestoration({
                    key: createUuidV4(),
                    configuration:
                        saved.workspaces.find(
                            (item) => item.workspace_id === saved.active_workspace_id
                        )?.configuration ?? null
                });
            clearPending(intent.command_id);
            setMessage(null);
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
    const activeWorkspace =
        book?.workspaces.find((item) => item.workspace_id === book.active_workspace_id) ?? null;
    const save = (configuration: WorkspaceConfiguration, name: string, targetId: string | null) => {
        if (book === null) return Promise.resolve(false);
        if (targetId !== null && !book.workspaces.some((item) => item.workspace_id === targetId))
            return Promise.resolve(false);
        const entry = { workspace_id: targetId ?? createUuidV4(), name, configuration };
        return commit(
            targetId === null
                ? [...book.workspaces, entry]
                : book.workspaces.map((item) => (item.workspace_id === targetId ? entry : item)),
            entry.workspace_id,
            false
        );
    };
    const load = (id: string) => {
        if (!book?.workspaces.some((item) => item.workspace_id === id))
            return Promise.resolve(false);
        return commit(book.workspaces, id, true);
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
    return {
        book,
        restoration,
        pending,
        busy,
        message,
        reload,
        save,
        load,
        activeWorkspace,
        resolvePending
    };
}
