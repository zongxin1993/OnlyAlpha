import "./toolbars.css";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { WorkspaceIcon } from "../../shared/components/WorkspaceIcon";
import { NAV_GROUPS } from "../nav";
import { ContextBar } from "./ContextBar";
import { getRailSnapshot, setRail, subscribeRail } from "./rail";
import { SideRail } from "./SideRail";

export interface WorkspaceShellSlots {
    toolbarHost: HTMLElement | null;
    railHost: HTMLElement | null;
}

const NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

function matchNavItem(pathname: string) {
    return NAV_ITEMS.find((item) =>
        item.to === "/"
            ? pathname === "/"
            : pathname === item.to || pathname.startsWith(`${item.to}/`)
    );
}

export function WorkstationShell() {
    const [toolbarHost, setToolbarHost] = useState<HTMLDivElement | null>(null);
    const [railHost, setRailHost] = useState<HTMLDivElement | null>(null);
    const location = useLocation();
    const railOpen = useSyncExternalStore(subscribeRail, getRailSnapshot);
    const isContextBar = matchNavItem(location.pathname)?.ctxbar === true;
    useEffect(() => {
        document.body.classList.toggle("no-ctx", !isContextBar);
    }, [isContextBar]);
    useEffect(() => {
        document.body.classList.toggle("rail-open", railOpen);
    }, [railOpen]);
    useEffect(() => {
        setRail(false);
    }, [location.pathname]);
    useEffect(() => {
        if (!railOpen) {
            return;
        }
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                setRail(false);
            }
        };
        window.addEventListener("keydown", onKeyDown);
        return () => {
            window.removeEventListener("keydown", onKeyDown);
        };
    }, [railOpen]);
    return (
        <div className="workstation-shell app-shell">
            <a className="skip-link" href="#workspace-content">
                跳到工作区
            </a>
            <SideRail />
            <button
                type="button"
                className="menu-toggle shell-menu-toggle"
                aria-label="开启导航"
                aria-expanded={railOpen}
                onClick={() => {
                    setRail(!railOpen);
                }}
            >
                <WorkspaceIcon name="menu" />
            </button>
            <div
                id="rail-mask"
                className="rail-mask"
                aria-hidden="true"
                onClick={() => {
                    setRail(false);
                }}
            />
            {isContextBar ? <ContextBar hostRef={setToolbarHost} /> : null}
            <div className="workstation-workspace" id="workspace-content" tabIndex={-1}>
                <Outlet context={{ toolbarHost, railHost } satisfies WorkspaceShellSlots} />
            </div>
            <aside className="global-workspace-rail" aria-label="工作区面板">
                <div ref={setRailHost} className="workspace-panel-host" />
            </aside>
            <footer className="status-surface">
                <span className="status-dot" aria-hidden="true" />
                <span>OnlyAlpha · 个人量化工作台</span>
                <nav className="footer-quick" aria-label="页脚导航">
                    <Link to="/overview">总览</Link>
                    <Link to="/">工作台</Link>
                    <Link to="/data/inputs">数据</Link>
                    <Link to="/system/health">系统</Link>
                </nav>
            </footer>
        </div>
    );
}
