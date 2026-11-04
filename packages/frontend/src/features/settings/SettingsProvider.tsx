/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, type ReactNode } from "react";
import { ConfigProvider, Drawer, Tabs, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { DataSourceManager } from "../data/sources/DataSourceManager";
import "./settings.css";
export const settingsChangedEvent = "onlyalpha-settings-changed";
type Section = "sources" | "chart";
const SettingsContext = createContext<{
    openSettings: (section: Section) => void;
    chartSettingsHost: HTMLDivElement | null;
    setChartAvailable: (available: boolean) => void;
}>({ openSettings: () => undefined, chartSettingsHost: null, setChartAvailable: () => undefined });
export function useSettings() {
    return useContext(SettingsContext);
}
function changed() {
    window.dispatchEvent(new Event(settingsChangedEvent));
}
export function SettingsProvider({ children }: { readonly children: ReactNode }) {
    const [section, setSection] = useState<Section>("sources");
    const [open, setOpen] = useState(false);
    const [chartSettingsHost, setChartSettingsHost] = useState<HTMLDivElement | null>(null);
    const [chartAvailable, setChartAvailable] = useState(false);
    return (
        <ConfigProvider
            locale={zhCN}
            theme={{
                algorithm: theme.defaultAlgorithm,
                token: {
                    colorPrimary: "#1f5f8b",
                    colorBgBase: "#f8f8f5",
                    colorTextBase: "#20242b",
                    borderRadius: 6,
                    fontFamily: "inherit"
                }
            }}
        >
            <SettingsContext.Provider
                value={{
                    chartSettingsHost,
                    setChartAvailable,
                    openSettings: (next) => {
                        setSection(next);
                        setOpen(true);
                    }
                }}
            >
                {children}
                <Drawer
                    className="global-settings"
                    title="设置"
                    open={open}
                    size={760}
                    forceRender
                    onClose={() => {
                        setOpen(false);
                        changed();
                    }}
                    closable={{ "aria-label": "关闭设置" }}
                >
                    <Tabs
                        activeKey={section}
                        onChange={(key) => {
                            if (key === "sources" || key === "chart") setSection(key);
                        }}
                        destroyOnHidden
                        items={[
                            {
                                key: "chart",
                                label: "图表",
                                disabled: !chartAvailable,
                                forceRender: true,
                                destroyOnHidden: false,
                                children: (
                                    <div
                                        className="chart-settings-content"
                                        ref={setChartSettingsHost}
                                    />
                                )
                            },
                            {
                                key: "sources",
                                label: "数据源",
                                children:
                                    open && section === "sources" ? (
                                        <DataSourceManager variant="page" />
                                    ) : null
                            }
                        ]}
                    />
                </Drawer>
            </SettingsContext.Provider>
        </ConfigProvider>
    );
}
