import { useEffect, useRef } from "react";
import * as echarts from "echarts";

interface EquityPoint {
    readonly timeLabel: string;
    readonly equity: number;
    readonly drawdownPercent: number | null;
}

export function BacktestEquityChart({ points }: { readonly points: readonly EquityPoint[] }) {
    const host = useRef<HTMLDivElement>(null);
    useEffect(() => {
        if (host.current === null || points.length === 0) return;
        const chart = echarts.init(host.current);
        chart.setOption({
            animation: false,
            tooltip: { trigger: "axis" },
            legend: { data: ["账户权益", "回撤"] },
            grid: [
                { left: 70, right: 24, top: 40, height: "47%" },
                { left: 70, right: 24, top: "69%", height: "21%" }
            ],
            xAxis: [
                {
                    type: "category",
                    data: points.map((point) => point.timeLabel),
                    axisLabel: { show: false }
                },
                {
                    type: "category",
                    gridIndex: 1,
                    data: points.map((point) => point.timeLabel),
                    axisLabel: { hideOverlap: true }
                }
            ],
            yAxis: [
                { type: "value", scale: true, name: "USDT" },
                { type: "value", gridIndex: 1, name: "%" }
            ],
            series: [
                {
                    name: "账户权益",
                    type: "line",
                    showSymbol: false,
                    data: points.map((point) => point.equity),
                    lineStyle: { width: 2, color: "#20658b" }
                },
                {
                    name: "回撤",
                    type: "line",
                    xAxisIndex: 1,
                    yAxisIndex: 1,
                    showSymbol: false,
                    areaStyle: { opacity: 0.15 },
                    data: points.map((point) => point.drawdownPercent),
                    lineStyle: { width: 1, color: "#a64b51" }
                }
            ]
        });
        const resize = () => {
            chart.resize();
        };
        window.addEventListener("resize", resize);
        const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
        observer?.observe(host.current);
        return () => {
            observer?.disconnect();
            window.removeEventListener("resize", resize);
            chart.dispose();
        };
    }, [points]);
    return (
        <div
            className="backtest-equity-chart"
            ref={host}
            role="img"
            aria-label="账户权益与回撤曲线"
        />
    );
}
