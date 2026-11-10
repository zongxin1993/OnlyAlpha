import "./toolbars.css";
import { useState } from "react";
import { Outlet } from "react-router-dom";
import { SideRail } from "./SideRail";

export interface WorkspaceShellSlots {
    toolbarHost: HTMLElement | null;
    railHost: HTMLElement | null;
}

export function WorkstationShell() {
    const [toolbarHost, setToolbarHost] = useState<HTMLDivElement | null>(null);
    const [railHost, setRailHost] = useState<HTMLDivElement | null>(null);
    return (
        <div className="workstation-shell app-shell">
            <a className="skip-link" href="#workspace-content">
                跳到工作区
            </a>
            <SideRail />
            <header className="workspace-topbar">
                <div id="workspace-toolbar-host" ref={setToolbarHost} />
            </header>
            <div className="workstation-workspace" id="workspace-content" tabIndex={-1}>
                <Outlet context={{ toolbarHost, railHost } satisfies WorkspaceShellSlots} />
            </div>
            <aside className="global-workspace-rail" aria-label="工作区面板">
                <div ref={setRailHost} className="workspace-panel-host" />
            </aside>
            <footer className="status-surface">
                <span className="status-dot" aria-hidden="true" />
                <span>OnlyAlpha · 个人量化工作台</span>
            </footer>
        </div>
    );
}
