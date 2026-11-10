import { useState, useSyncExternalStore } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { WorkspaceIcon } from "../../shared/components/WorkspaceIcon";
import { useSettings } from "../../features/settings/SettingsProvider";
import { NAV_GROUPS } from "../nav";
import { setRail } from "./rail";
import { getThemeSnapshot, subscribeTheme, toggleTheme } from "../theme/theme";
import "./sideRail.css";

/** 左侧栏：品牌、分组导航（图标+中文并排，任何宽度不隐藏文字）、主题/密度/设置。 */
export function SideRail() {
    const { openSettings } = useSettings();
    const location = useLocation();
    const theme = useSyncExternalStore(subscribeTheme, getThemeSnapshot);
    const [quiet, setQuiet] = useState(false);
    return (
        <aside className="side-rail" aria-label="主导航">
            <NavLink to="/" className="rail-brand" aria-label="OnlyAlpha 工作台" end>
                <span className="brand-mark">OA</span>
                <span className="rail-brand-name">OnlyAlpha</span>
            </NavLink>
            <nav className="side-rail-nav" aria-label="产品导航">
                {NAV_GROUPS.map((group) => (
                    <div className="rail-group" key={group.group}>
                        <p className="rail-group-label">{group.group}</p>
                        {group.items.map((item) => (
                            <NavLink
                                key={item.to}
                                to={item.to}
                                end={item.to === "/"}
                                onClick={() => {
                                    setRail(false);
                                }}
                                className={({ isActive }) =>
                                    `rail-item${isActive ? " active" : ""}`
                                }
                            >
                                <WorkspaceIcon name={item.icon} />
                                <span>{item.label}</span>
                            </NavLink>
                        ))}
                    </div>
                ))}
            </nav>
            <div className="rail-foot">
                <button
                    type="button"
                    className="rail-button"
                    aria-label="切换主题"
                    onClick={() => {
                        toggleTheme();
                    }}
                >
                    <WorkspaceIcon name={theme === "dark" ? "sun" : "moon"} />
                </button>
                <button
                    type="button"
                    className="rail-button rail-quiet"
                    aria-label="紧凑模式"
                    aria-pressed={quiet}
                    onClick={() => {
                        const next = !quiet;
                        setQuiet(next);
                        document.body.classList.toggle("quiet", next);
                    }}
                >
                    <WorkspaceIcon name="level" />
                </button>
                <div className="workspace-settings-anchor">
                    <button
                        type="button"
                        className="rail-button"
                        aria-label="全局设置"
                        onClick={() => {
                            openSettings(location.pathname === "/" ? "chart" : "sources");
                        }}
                    >
                        <WorkspaceIcon name="settings" />
                    </button>
                </div>
            </div>
        </aside>
    );
}
