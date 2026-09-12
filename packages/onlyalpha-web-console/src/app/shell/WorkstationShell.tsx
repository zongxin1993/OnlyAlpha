import { useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { WorkspaceIcon, type WorkspaceIconName } from "../../shared/components/WorkspaceIcon";

const navClass = ({ isActive }: { readonly isActive: boolean }) =>
    isActive ? "research-nav-link active" : "research-nav-link";

export function WorkstationShell() {
    const [navigationOpen, setNavigationOpen] = useState(false);
    const navigationToggle = useRef<HTMLButtonElement>(null);
    const workspace = useRef<HTMLDivElement>(null);
    function closeNavigation() {
        setNavigationOpen(false);
        workspace.current?.focus();
    }
    const { pathname } = useLocation();
    const products = [
        { to: "/data/inputs", label: "Research Inputs", product: "Data", icon: "data" },
        { to: "/strategies", label: "Strategies", product: "Strategies", icon: "shield" },
        { to: "/backtest/runs", label: "Backtests", product: "Backtest", icon: "results" },
        { to: "/system/health", label: "System Health", product: "System", icon: "shield" }
    ] as const;
    const currentProduct = products.find((item) => pathname.startsWith(item.to));
    const product = currentProduct?.product ?? "Research";
    const destinations: readonly {
        readonly to: string;
        readonly label: string;
        readonly icon: WorkspaceIconName;
        readonly secondary?: boolean;
    }[] = [
        { to: "/research/new", label: "New Research", icon: "research" },
        { to: "/research/library", label: "Research Library", icon: "library", secondary: true },
        { to: "/research/runs", label: "Runs", icon: "runs" },
        { to: "/research/results", label: "Results", icon: "results" },
        { to: "/research/analysis", label: "AI Analysis", icon: "analysis", secondary: true }
    ];
    const currentPage =
        destinations.find((item) => pathname.startsWith(item.to))?.label ??
        currentProduct?.label ??
        "Research";
    return (
        <div className="workstation-shell">
            <a className="skip-link" href="#workspace-content">
                Skip to workspace
            </a>
            <header className="product-rail">
                <NavLink to="/research/new" className="brand" aria-label="OnlyAlpha Research">
                    <span className="brand-mark">OA</span>
                    <span>OnlyAlpha</span>
                </NavLink>
            </header>
            <div className="workspace-topbar">
                <button
                    type="button"
                    className="navigation-toggle"
                    ref={navigationToggle}
                    aria-label="Toggle navigation"
                    aria-controls="workstation-navigation"
                    aria-expanded={navigationOpen}
                    onClick={() => {
                        setNavigationOpen(!navigationOpen);
                    }}
                >
                    <WorkspaceIcon name="menu" />
                </button>
                <div className="workspace-breadcrumb">
                    <span>{product}</span>
                    <span aria-hidden="true">/</span>
                    <strong>{currentPage}</strong>
                </div>
                <span className="workspace-mode">
                    <WorkspaceIcon name="shield" /> Evidence workspace
                </span>
            </div>
            <aside
                id="workstation-navigation"
                className={`research-navigation${navigationOpen ? " navigation-open" : ""}`}
                aria-label="Workspace navigation"
                onKeyDown={(event) => {
                    if (event.key === "Escape" && navigationOpen) {
                        setNavigationOpen(false);
                        navigationToggle.current?.focus();
                    }
                }}
            >
                <nav aria-label="Workspace">
                    <p className="nav-eyebrow">Research workspace</p>
                    {destinations.map((item) => (
                        <NavLink
                            key={item.to}
                            to={item.to}
                            className={(state) =>
                                `${navClass(state)}${item.secondary ? " research-nav-secondary" : ""}`
                            }
                            onClick={closeNavigation}
                        >
                            <WorkspaceIcon name={item.icon} />
                            <span>{item.label}</span>
                        </NavLink>
                    ))}
                    <p className="nav-eyebrow nav-section">Product workspaces</p>
                    {products.map((item) => (
                        <NavLink
                            key={item.to}
                            to={item.to}
                            className={navClass}
                            onClick={closeNavigation}
                        >
                            <WorkspaceIcon name={item.icon} />
                            <span>{item.label}</span>
                        </NavLink>
                    ))}
                </nav>
                <div className="navigation-note">
                    <WorkspaceIcon name="shield" />
                    <span>
                        One identity.
                        <br />
                        Traceable evidence.
                    </span>
                </div>
            </aside>
            <div
                className="workstation-workspace"
                id="workspace-content"
                tabIndex={-1}
                ref={workspace}
            >
                <Outlet />
            </div>
            <footer className="status-surface">
                <span className="status-dot" aria-hidden="true" />
                <span>OnlyAlpha · Browser is control and presentation only</span>
                <span className="status-authority">Server authority required</span>
            </footer>
        </div>
    );
}
