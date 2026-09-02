import { NavLink, Outlet } from "react-router-dom";

const navClass = ({ isActive }: { readonly isActive: boolean }) =>
    isActive ? "research-nav-link active" : "research-nav-link";

export function WorkstationShell() {
    return (
        <div className="workstation-shell">
            <header className="product-rail">
                <NavLink to="/research/new" className="brand" aria-label="OnlyAlpha Research">
                    <span className="brand-mark">OA</span>
                    <span>OnlyAlpha</span>
                </NavLink>
                <span className="product-label">Research</span>
            </header>
            <aside className="research-navigation" aria-label="Research navigation">
                <p className="nav-eyebrow">Research</p>
                <NavLink to="/research/new" className={navClass}>
                    New Research
                </NavLink>
                <NavLink to="/research/runs" className={navClass}>
                    Runs
                </NavLink>
                <NavLink to="/research/results" className={navClass}>
                    Results
                </NavLink>
            </aside>
            <div className="workstation-workspace">
                <Outlet />
            </div>
            <footer className="status-surface">
                <span className="status-dot" aria-hidden="true" />
                Browser is control and presentation only · Server authority required
            </footer>
        </div>
    );
}
