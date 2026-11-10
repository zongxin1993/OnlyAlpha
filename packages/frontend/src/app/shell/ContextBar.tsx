/** 顶部工作条：只属于工作台，承载 WorkspacePage 工具条的 portal 挂载点。 */
export function ContextBar({
    hostRef
}: {
    readonly hostRef: (element: HTMLDivElement | null) => void;
}) {
    return (
        <header className="workspace-topbar context-bar">
            <div id="workspace-toolbar-host" ref={hostRef} />
        </header>
    );
}
