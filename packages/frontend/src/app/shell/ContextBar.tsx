import { useSyncExternalStore } from "react";
import { WorkspaceIcon } from "../../shared/components/WorkspaceIcon";
import { getRailSnapshot, setRail, subscribeRail } from "./rail";

/** 顶部工作条：只属于工作台，承载 WorkspacePage 工具条的 portal 挂载点。 */
export function ContextBar({
    hostRef
}: {
    readonly hostRef: (element: HTMLDivElement | null) => void;
}) {
    const railOpen = useSyncExternalStore(subscribeRail, getRailSnapshot);
    return (
        <header className="workspace-topbar context-bar">
            <button
                type="button"
                className="menu-toggle"
                aria-label="开启导航"
                aria-expanded={railOpen}
                onClick={() => {
                    setRail(!railOpen);
                }}
            >
                <WorkspaceIcon name="menu" />
            </button>
            <div id="workspace-toolbar-host" ref={hostRef} />
        </header>
    );
}
