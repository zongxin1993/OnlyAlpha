import "./toolbars.css";
import { useState } from "react";
import { Button, Dropdown, Tooltip } from "antd";
import { useSettings } from "../../features/settings/SettingsProvider";
import { NavLink, Outlet, useNavigate, useLocation } from "react-router-dom";

import { WorkspaceIcon } from "../../shared/components/WorkspaceIcon";
export interface WorkspaceShellSlots {
    toolbarHost: HTMLElement | null;
    railHost: HTMLElement | null;
}
const products = [
    { to: "/research/new", label: "研究 · 未实现", icon: "research" },
    { to: "/data/inputs", label: "数据 · 未实现", icon: "data" },
    { to: "/strategies", label: "策略", icon: "library" },
    { to: "/backtest", label: "回测", icon: "runs" },
    { to: "/system/health", label: "系统 · 未实现", icon: "shield" }
] as const;

export function WorkstationShell() {
    const { openSettings } = useSettings();
    const navigate = useNavigate();
    const location = useLocation();
    const [toolbarHost, setToolbarHost] = useState<HTMLDivElement | null>(null);
    const [railHost, setRailHost] = useState<HTMLDivElement | null>(null);
    return (
        <div className="workstation-shell">
            <a className="skip-link" href="#workspace-content">
                跳到工作区
            </a>
            <header className="workspace-topbar">
                <NavLink to="/" className="brand" aria-label="OnlyAlpha 工作台" end>
                    <span className="brand-mark">OA</span>
                </NavLink>
                <div id="workspace-toolbar-host" ref={setToolbarHost} />
            </header>
            <div className="workstation-workspace" id="workspace-content" tabIndex={-1}>
                <Outlet context={{ toolbarHost, railHost } satisfies WorkspaceShellSlots} />
            </div>
            <aside className="global-workspace-rail" aria-label="功能导航">
                <nav className="product-rail" aria-label="产品导航">
                    <Tooltip title="工作台" placement="left">
                        <NavLink
                            aria-label="工作台"
                            to="/"
                            end
                            className={({ isActive }) =>
                                isActive ? "primary-nav-link active" : "primary-nav-link"
                            }
                        >
                            <WorkspaceIcon name="candles" />
                        </NavLink>
                    </Tooltip>
                    <Dropdown
                        trigger={["click"]}
                        placement="bottomLeft"
                        menu={{
                            items: products.map((product) => ({
                                key: product.to,
                                label: product.label,
                                icon: <WorkspaceIcon name={product.icon} />
                            })),
                            onClick: ({ key }) => {
                                void navigate(key);
                            }
                        }}
                    >
                        <Button type="text" className="rail-button" aria-label="更多功能">
                            <WorkspaceIcon name="more" />
                        </Button>
                    </Dropdown>
                </nav>
                <div ref={setRailHost} className="workspace-panel-host" />
                <div className="workspace-settings-anchor">
                    <Tooltip title="设置" placement="left">
                        <Button
                            type="text"
                            className="rail-button"
                            aria-label="全局设置"
                            onClick={() => {
                                openSettings(location.pathname === "/" ? "chart" : "sources");
                            }}
                        >
                            <WorkspaceIcon name="settings" />
                        </Button>
                    </Tooltip>
                </div>
            </aside>
            <footer className="status-surface">
                <span className="status-dot" aria-hidden="true" />
                <span>OnlyAlpha · 个人量化工作台</span>
            </footer>
        </div>
    );
}
