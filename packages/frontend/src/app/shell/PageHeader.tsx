import { useSyncExternalStore } from "react";
import { WorkspaceIcon } from "../../shared/components/WorkspaceIcon";
import { getRailSnapshot, setRail, subscribeRail } from "./rail";

/** 页内标题条（非工作台画面使用；冻结稿布局契约）。 */
export function PageHeader({
    title,
    subtitle
}: {
    readonly title: string;
    readonly subtitle?: string | undefined;
}) {
    const railOpen = useSyncExternalStore(subscribeRail, getRailSnapshot);
    return (
        <header className="view-head">
            <div className="view-head-text">
                <h1>{title}</h1>
                {subtitle === undefined ? null : <p className="view-sub">{subtitle}</p>}
            </div>
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
        </header>
    );
}
