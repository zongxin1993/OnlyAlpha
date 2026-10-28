import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { WorkspaceConfiguration } from "../../api/workspace/client";
import type { useDefaultWorkspace } from "./useDefaultWorkspace";
import { keepDialogFocus } from "./dialogFocus";

export function WorkspaceLibraryControls({
    workspace,
    configuration,
    ready,
    dirty,
    notice
}: {
    readonly workspace: ReturnType<typeof useDefaultWorkspace>;
    readonly configuration: WorkspaceConfiguration | null;
    readonly ready: boolean;
    readonly dirty: boolean;
    readonly notice: string | null;
}) {
    const [mode, setMode] = useState<"save" | "load" | null>(null);
    const [name, setName] = useState("");
    const [target, setTarget] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const dialog = useRef<HTMLDialogElement>(null);
    const returnFocus = useRef<HTMLElement | null>(null);
    const blocked = workspace.busy || workspace.pending !== null;
    useEffect(() => {
        if (mode === null) return;
        dialog.current?.showModal();
        return () => {
            returnFocus.current?.focus();
        };
    }, [mode]);
    const open = (next: "save" | "load") => {
        returnFocus.current =
            document.activeElement instanceof HTMLElement ? document.activeElement : null;
        setName(workspace.activeWorkspace?.name ?? "我的工作区");
        setTarget(null);
        setError(null);
        setMode(next);
        if (next === "load") void workspace.reload(undefined, false);
    };
    const save = async (overwriteId: string | null) => {
        if (
            configuration !== null &&
            (await workspace.save(configuration, name.trim(), overwriteId))
        )
            setMode(null);
    };
    const submit = () => {
        const label = name.trim();
        if (!label || Array.from(label).length > 120 || /\p{Cc}/u.test(label)) {
            setError("请输入 1 至 120 个字符的工作区名称，不含控制字符。");
            return;
        }
        const matches = workspace.book?.workspaces.filter((item) => item.name === label) ?? [];
        const current = matches.find(
            (item) => item.workspace_id === workspace.activeWorkspace?.workspace_id
        );
        if (matches.length > 1 && current === undefined) {
            setError("有多个同名工作区，请先载入要更新的工作区，或使用新名称另存。");
            return;
        }
        const existing = current ?? matches[0];
        if (existing !== undefined) {
            setTarget(existing.workspace_id);
            return;
        }
        if ((workspace.book?.workspaces.length ?? 0) >= 32) {
            setError("最多保存 32 个工作区；请载入已有工作区后更新。");
            return;
        }
        void save(null);
    };
    return (
        <div className="workspace-library-controls">
            <button
                type="button"
                disabled={blocked || workspace.book === null || configuration === null || !ready}
                title={dirty ? "保存当前未保存配置" : "保存工作区"}
                onClick={() => {
                    open("save");
                }}
            >
                保存工作区
            </button>
            <button
                type="button"
                disabled={blocked}
                onClick={() => {
                    open("load");
                }}
            >
                载入工作区
            </button>
            {workspace.pending !== null && (
                <button
                    type="button"
                    disabled={workspace.busy}
                    onClick={() => void workspace.resolvePending()}
                >
                    核对原保存提交
                </button>
            )}
            {(notice ?? workspace.message) !== null && (
                <span role={notice === null ? "status" : "alert"}>
                    {notice ?? workspace.message}
                </span>
            )}
            {mode !== null &&
                createPortal(
                    <dialog
                        ref={dialog}
                        className="workspace-library-dialog"
                        aria-label={mode === "save" ? "保存工作区" : "载入工作区"}
                        onKeyDown={keepDialogFocus}
                        onCancel={(event) => {
                            event.preventDefault();
                            if (!workspace.busy) setMode(null);
                        }}
                    >
                        <header>
                            <h2>{mode === "save" ? "保存工作区" : "载入工作区"}</h2>
                            <button
                                type="button"
                                aria-label="关闭工作区窗口"
                                disabled={workspace.busy}
                                onClick={() => {
                                    setMode(null);
                                }}
                            >
                                ×
                            </button>
                        </header>
                        {mode === "save" ? (
                            <form
                                onSubmit={(event) => {
                                    event.preventDefault();
                                    submit();
                                }}
                            >
                                <label>
                                    工作区名称
                                    <input
                                        autoFocus
                                        required
                                        maxLength={240}
                                        value={name}
                                        disabled={blocked || target !== null}
                                        onChange={(event) => {
                                            setName(event.target.value);
                                            setError(null);
                                        }}
                                    />
                                </label>
                                {target === null ? (
                                    <button type="submit" disabled={blocked}>
                                        保存
                                    </button>
                                ) : (
                                    <div role="alert">
                                        <p>已存在“{name.trim()}”，确认覆盖该工作区的配置？</p>
                                        <button
                                            type="button"
                                            disabled={blocked}
                                            onClick={() => void save(target)}
                                        >
                                            确认覆盖
                                        </button>
                                        <button
                                            type="button"
                                            disabled={blocked}
                                            onClick={() => {
                                                setTarget(null);
                                            }}
                                        >
                                            返回修改名称
                                        </button>
                                    </div>
                                )}
                            </form>
                        ) : (
                            <div>
                                <p>选择要载入的工作区。未保存的当前配置将被替换。</p>
                                {workspace.book === null ? (
                                    <p>工作区列表暂不可用</p>
                                ) : workspace.book.workspaces.length === 0 ? (
                                    <p>还没有保存的工作区</p>
                                ) : (
                                    <ul>
                                        {workspace.book.workspaces.map((item) => (
                                            <li key={item.workspace_id}>
                                                <button
                                                    type="button"
                                                    disabled={blocked}
                                                    onClick={() => {
                                                        void workspace
                                                            .load(item.workspace_id)
                                                            .then((ok) => {
                                                                if (ok) setMode(null);
                                                            });
                                                    }}
                                                >
                                                    {item.name}
                                                    {item.workspace_id ===
                                                    workspace.book?.active_workspace_id
                                                        ? " · 当前"
                                                        : ""}
                                                </button>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                                <button
                                    type="button"
                                    disabled={blocked}
                                    onClick={() => void workspace.reload(undefined, false)}
                                >
                                    刷新工作区列表
                                </button>
                            </div>
                        )}
                        {error !== null && <p role="alert">{error}</p>}
                        {workspace.message !== null && <p role="status">{workspace.message}</p>}
                    </dialog>,
                    document.body
                )}
        </div>
    );
}
