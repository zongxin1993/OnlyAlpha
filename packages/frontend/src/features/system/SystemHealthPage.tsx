import { useEffect, useState, type ReactElement } from "react";
import { Button, Card, Space, Typography } from "antd";
import { getLiveHealth, getReadyHealth, type HealthStatus } from "../../api/health/health";
import { PageHeader } from "../../app/shell/PageHeader";
import { getThemeSnapshot, subscribeTheme, type Theme } from "../../app/theme/theme";

type ProbeRead =
    | { readonly state: "pending" }
    | { readonly state: "ok"; readonly status: HealthStatus }
    | { readonly state: "failed" };

const pending: ProbeRead = { state: "pending" };

function probeRow(label: string, path: string, read: ProbeRead, okWord: string): ReactElement {
    return (
        <div key={path} className="system-probe-row">
            <Typography.Text strong>{label}</Typography.Text>
            <Typography.Text type="secondary" className="system-probe-path">
                {path}
            </Typography.Text>
            {read.state === "pending" ? (
                <Typography.Text role="status">正在读取运行时状态…</Typography.Text>
            ) : read.state === "ok" ? (
                <Typography.Text>
                    <Typography.Text strong>{read.status}</Typography.Text>
                    <Typography.Text type="secondary"> 已{okWord}</Typography.Text>
                </Typography.Text>
            ) : (
                <Typography.Text>
                    未确认：服务未响应或返回异常，本次查看未生效。可点右侧「重新查看」。
                </Typography.Text>
            )}
        </div>
    );
}

/** 系统画面：只展示正式可得事实。健康来自 /health/live 与 /health/ready；
 * 版本与迁移号无端点，诚实缺省（QUERY_GAP），宁缺毋假。 */
export function SystemHealthPage() {
    const [refresh, setRefresh] = useState(0);
    const [live, setLive] = useState<ProbeRead>(pending);
    const [ready, setReady] = useState<ProbeRead>(pending);
    const [theme, setTheme] = useState<Theme>(getThemeSnapshot());

    useEffect(() => {
        const unsubscribe = subscribeTheme(() => {
            setTheme(getThemeSnapshot());
        });
        return unsubscribe;
    }, []);

    // 探针读取是外部系统同步；未确认态在「重新查看」点击时同步重置，effect 内不再同步 setState。
    useEffect(() => {
        let mounted = true;
        void getLiveHealth().then(
            (status) => {
                if (mounted) setLive({ state: "ok", status });
            },
            () => {
                if (mounted) setLive({ state: "failed" });
            }
        );
        void getReadyHealth().then(
            (status) => {
                if (mounted) setReady({ state: "ok", status });
            },
            () => {
                if (mounted) setReady({ state: "failed" });
            }
        );
        return () => {
            mounted = false;
        };
    }, [refresh]);

    const quiet = document.body.classList.contains("quiet");
    return (
        <div className="page-with-head">
            <PageHeader title="系统" subtitle="运行时状态" />
            <main className="page system-page" aria-label="系统运行时状态">
                <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                    <Card
                        title="运行时健康"
                        extra={
                            <Button
                                onClick={() => {
                                    setLive(pending);
                                    setReady(pending);
                                    setRefresh((value) => value + 1);
                                }}
                            >
                                重新查看
                            </Button>
                        }
                    >
                        {probeRow("存活探针", "/health/live", live, "存活")}
                        {probeRow("就绪探针", "/health/ready", ready, "就绪")}
                    </Card>
                    <Card title="本地偏好">
                        <Typography.Paragraph>
                            主题：{theme === "dark" ? "暗色" : "浅色"}
                            （本机浏览器偏好，可在左侧栏底部切换）
                        </Typography.Paragraph>
                        <Typography.Paragraph>
                            密度：{quiet ? "紧凑" : "舒适"}（本次查看时的状态，可在左侧栏底部调整）
                        </Typography.Paragraph>
                    </Card>
                    <Card title="信息缺省">
                        <Typography.Paragraph>
                            后端版本与迁移号暂无正式查询端点（QUERY_GAP），此处宁缺毋假。
                        </Typography.Paragraph>
                    </Card>
                </Space>
            </main>
        </div>
    );
}
