import { NavLink, Outlet } from "react-router-dom";

const products = [
    { to: "/", label: "工作台" },
    { to: "/research/new", label: "研究" },
    { to: "/data/inputs", label: "数据" },
    { to: "/strategies", label: "策略" },
    { to: "/backtest/runs", label: "回测" },
    { to: "/system/health", label: "系统" }
] as const;

export function WorkstationShell() {
    return (
        <div className="workstation-shell">
            <a className="skip-link" href="#workspace-content">
                跳到工作区
            </a>
            <header className="workspace-topbar">
                <NavLink to="/" className="brand" aria-label="OnlyAlpha 工作台" end>
                    <span className="brand-mark">OA</span>
                    <span>OnlyAlpha</span>
                </NavLink>
                <span className="topbar-divider" aria-hidden="true" />
                <nav className="primary-nav" aria-label="产品导航">
                    {products.map((product) => (
                        <NavLink
                            key={product.to}
                            to={product.to}
                            end={product.to === "/"}
                            className={({ isActive }) =>
                                isActive ? "primary-nav-link active" : "primary-nav-link"
                            }
                        >
                            {product.label}
                        </NavLink>
                    ))}
                </nav>
                <div className="topbar-actions">
                    <NavLink to="/research/new" className="topbar-action">
                        新建研究
                    </NavLink>
                    <span className="topbar-mode">Control + Presentation</span>
                </div>
            </header>
            <div className="workstation-workspace" id="workspace-content" tabIndex={-1}>
                <Outlet />
            </div>
            <footer className="status-surface">
                <span className="status-dot" aria-hidden="true" />
                <span>OnlyAlpha · 浏览器只做控制与呈现</span>
                <span className="status-authority">服务端 Authority 必需</span>
            </footer>
        </div>
    );
}
