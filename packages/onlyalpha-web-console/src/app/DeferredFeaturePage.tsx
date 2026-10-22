import { Link } from "react-router-dom";

export function DeferredFeaturePage({ feature }: { readonly feature?: string }) {
    return (
        <main className="product-empty">
            <h1>{feature === undefined ? "页面未找到" : `${feature} · 未实现`}</h1>
            <p role="status">
                {feature === undefined
                    ? "此地址没有对应页面，请返回工作台。"
                    : "当前版本先提供工作台中的行情、指标与因子看板。此功能尚未实现。"}
            </p>
            <Link to="/" className="button-secondary">
                返回工作台
            </Link>
        </main>
    );
}
