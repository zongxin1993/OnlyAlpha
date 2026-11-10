/* eslint-disable react-refresh/only-export-components */
import {
    createContext,
    useContext,
    useRef,
    useSyncExternalStore,
    useState,
    type ReactNode
} from "react";
import { getThemeSnapshot, subscribeTheme } from "../../app/theme/theme";
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
    const uiTheme = useSyncExternalStore(subscribeTheme, getThemeSnapshot);
    const antdAlgorithm = uiTheme === "dark" ? theme.darkAlgorithm : theme.defaultAlgorithm;
    const antdColorBgBase = uiTheme === "dark" ? "#14161a" : "#f8f8f5";
    const antdColorTextBase = uiTheme === "dark" ? "#e8eaf0" : "#20242b";
    const trigger = useRef<HTMLElement | null>(null);
    const [section, setSection] = useState<Section>("sources");
    const [open, setOpen] = useState(false);
    const [chartSettingsHost, setChartSettingsHost] = useState<HTMLDivElement | null>(null);
    const [chartAvailable, setChartAvailable] = useState(false);
    return (
        <ConfigProvider
            locale={zhCN}
            theme={{
                algorithm: antdAlgorithm,
                token: {
                    colorPrimary: "#1f5f8b",
                    colorBgBase: antdColorBgBase,
                    colorTextBase: antdColorTextBase,
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
                        trigger.current =
                            document.activeElement instanceof HTMLElement
                                ? document.activeElement
                                : null;
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
                    afterOpenChange={(visible) => {
                        if (!visible) {
                            trigger.current?.focus();
                            trigger.current = null;
                        }
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
