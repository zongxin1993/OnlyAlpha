import { Link } from "react-router-dom";
import { PageHeader } from "./shell/PageHeader";

/** 总览画面占位：P3 随多市场实时监控交付，此处不发明数据。 */
export function OverviewPlaceholder() {
    return (
        <div className="page-with-head">
            <PageHeader title="总览" subtitle="多市场实时行情监控与全局状态" />
            <main className="product-empty">
                <p role="status">总览画面将于 P3 阶段随实时行情聚合一并交付。</p>
                <Link to="/" className="button-secondary">
                    前往工作台
                </Link>
            </main>
        </div>
    );
}
