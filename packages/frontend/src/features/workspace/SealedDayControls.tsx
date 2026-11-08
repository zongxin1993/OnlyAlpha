import { useEffect, useRef, useState } from "react";
import { z } from "zod";
import { useLocalReadCredentials, useMarketDataApi } from "../../app/providers";
import {
    marketDataBarSemanticSchema,
    type MarketDataAcquisition,
    type MarketDataSource
} from "../../api/marketData/model";
import type { MarketDataChartState } from "./useMarketDataChart";
import { onlyMarketDataSourceReference } from "./useMarketDataChart";

const savedQuery = z.strictObject({
    original_request_id: z.uuid(),
    instrument_id: z.string().min(1),
    start_ns: z.string().regex(/^[0-9]+$/),
    end_ns: z.string().regex(/^[0-9]+$/),
    bar_semantic: marketDataBarSemanticSchema,
    adjustment_anchor: z.iso.date().optional()
});
const statuses = {
    PENDING: "待执行",
    RUNNING: "采集中",
    COMPLETE: "已封存",
    FAILED: "失败",
    UNKNOWN: "结果未知"
};

export function SealedDayControls({
    chart,
    source
}: {
    chart: MarketDataChartState;
    source: MarketDataSource;
}) {
    const [search, setSearch] = useState("");
    return (
        <section aria-label="封存日线">
            <label>
                证券代码
                <input
                    value={search}
                    onChange={(e) => {
                        setSearch(e.target.value);
                    }}
                />
            </label>
            <button type="button" onClick={() => void chart.searchInstruments(search, true)}>
                查已封存证券
            </button>
            {source.new_work_status === "AVAILABLE" && (
                <button type="button" onClick={() => void chart.searchInstruments(search)}>
                    查源端证券
                </button>
            )}
            {chart.instruments.length > 0 && (
                <ul>
                    {chart.instruments.map((i) => (
                        <li key={i.instrument_id}>
                            <button type="button" onClick={() => void chart.selectInstrument(i)}>
                                {i.instrument_id}
                            </button>
                        </li>
                    ))}
                </ul>
            )}
            {chart.instrument !== null && (
                <DayOperation
                    key={chart.instrument.instrument_id}
                    chart={chart}
                    source={source}
                    instrument={chart.instrument.instrument_id}
                />
            )}
        </section>
    );
}

function DayOperation({
    chart,
    source,
    instrument
}: {
    chart: MarketDataChartState;
    source: MarketDataSource;
    instrument: string;
}) {
    const client = useMarketDataApi();
    const credentials = useLocalReadCredentials();
    const ref = onlyMarketDataSourceReference(source);
    const storageKey = JSON.stringify([
        "onlyalpha.history.day.v1",
        ref.integration_id,
        ref.integration_revision_fingerprint,
        instrument
    ]);
    const [saved, setSaved] = useState(() => {
        try {
            const s = localStorage.getItem(storageKey);
            const value = s === null ? null : savedQuery.parse(JSON.parse(s));
            if (
                value &&
                (value.instrument_id !== instrument ||
                    JSON.stringify(value.bar_semantic) !== JSON.stringify(chart.barSemantic))
            )
                throw new Error();
            return { query: value, readable: true };
        } catch {
            return { query: null, readable: false };
        }
    });
    const [result, setResult] = useState<MarketDataAcquisition | null>(null);
    const [message, setMessage] = useState("");
    const [busy, setBusy] = useState(false);
    const working = useRef(false);
    const alive = useRef(true);
    useEffect(() => {
        alive.current = true;
        return () => {
            alive.current = false;
        };
    }, []);
    const [start, setStart] = useState("");
    const [end, setEnd] = useState("");
    const [anchor, setAnchor] = useState("");
    const [count, setCount] = useState(1);
    const [lookup, setLookup] = useState("");
    const last = chart.bars.at(-1);
    const canMutate = credentials.localSession && credentials.capture().bearer === null;
    const terminal = result?.status === "COMPLETE" || result?.status === "FAILED";
    const run = async (action: "observe" | "resume" | "create") => {
        if (working.current) return;
        working.current = true;
        setBusy(true);
        setMessage("");
        try {
            let q = saved.query;
            if (action === "create") {
                const ns = (date: string) =>
                    (BigInt(Date.parse(date + "T00:00:00Z")) * 1000000n).toString();
                if (start === "" || end <= start)
                    throw new Error("请选择有效的 UTC 起止日期，结束日期不包含在采集范围内。");
                q = savedQuery.parse({
                    original_request_id: crypto.randomUUID(),
                    instrument_id: instrument,
                    start_ns: ns(start),
                    end_ns: ns(end),
                    bar_semantic: chart.barSemantic,
                    ...(chart.barSemantic.adjustment_policy === "FORWARD"
                        ? { adjustment_anchor: anchor }
                        : {})
                });
                localStorage.setItem(storageKey, JSON.stringify(q));
                setSaved({ query: q, readable: true });
                setResult(null);
            }
            if (action === "observe" && q === null) {
                const id = z.uuid().parse(lookup.trim());
                const found = await client.getAcquisition(ref, id);
                if (!alive.current) return;
                if (
                    found.original_request_id !== id ||
                    found.instrument_id !== instrument ||
                    found.source_id !== source.source_id ||
                    JSON.stringify(found.bar_semantic) !== JSON.stringify(chart.barSemantic)
                )
                    throw new Error("该原操作与所选证券不匹配。");
                setResult(found);
                if (found.status === "COMPLETE" && found.revision_id !== null) {
                    const size = Math.min(2000, found.coverage.actual_bar_count);
                    setCount(size);
                    await chart.readSealedDay(found.revision_id, size);
                }
                return;
            }
            if (q === null) throw new Error("未找到可查询的原操作");
            const r =
                action === "observe"
                    ? await client.getAcquisition(ref, q.original_request_id)
                    : await client.createAcquisition(ref, {
                          instrument_id: q.instrument_id,
                          original_request_id: q.original_request_id,
                          start_ns: q.start_ns,
                          end_ns: q.end_ns,
                          bar_semantic: q.bar_semantic,
                          ...(q.adjustment_anchor === undefined
                              ? {}
                              : { adjustment_anchor: q.adjustment_anchor })
                      });
            if (!alive.current) return;
            if (
                r.original_request_id === undefined ||
                r.instrument_id !== instrument ||
                r.source_id !== source.source_id ||
                r.start_ns !== q.start_ns ||
                r.end_ns !== q.end_ns ||
                JSON.stringify(r.bar_semantic) !== JSON.stringify(q.bar_semantic) ||
                (action !== "create" && r.original_request_id !== q.original_request_id)
            )
                throw new Error("原操作响应与所选来源或请求不匹配。");
            if (r.original_request_id !== q.original_request_id) {
                q = { ...q, original_request_id: r.original_request_id };
                localStorage.setItem(storageKey, JSON.stringify(q));
                setSaved({ query: q, readable: true });
            }
            setResult(r);
            if (r.status === "COMPLETE" && r.revision_id !== null) {
                const size = Math.min(2000, r.coverage.actual_bar_count);
                setCount(size);
                await chart.readSealedDay(r.revision_id, size);
            }
        } catch (error) {
            if (alive.current)
                setMessage(error instanceof Error ? error.message : "请求未完成，请查询原操作。");
        } finally {
            working.current = false;
            if (alive.current) setBusy(false);
        }
    };
    return (
        <div>
            <p>
                {chart.barSemantic.adjustment_policy === "FORWARD"
                    ? "前复权"
                    : chart.barSemantic.adjustment_policy === "BACKWARD"
                      ? "后复权"
                      : "不复权"}
            </p>
            {last && (
                <p aria-label="最新封存日线">
                    收盘 {last.close} · 成交量 {last.volume}
                </p>
            )}
            {saved.query === null && (
                <details>
                    <summary>按原操作编号查询</summary>
                    <label>
                        原操作编号
                        <input
                            value={lookup}
                            onChange={(e) => {
                                setLookup(e.target.value);
                            }}
                        />
                    </label>
                    <button
                        type="button"
                        disabled={busy || !lookup.trim()}
                        onClick={() => void run("observe")}
                    >
                        查询原操作
                    </button>
                </details>
            )}
            <label>
                读取根数
                <input
                    type="number"
                    min={1}
                    max={2000}
                    value={count}
                    onChange={(e) => {
                        setCount(Number(e.target.value));
                    }}
                />
            </label>
            <button
                type="button"
                disabled={busy || !Number.isInteger(count) || count < 1 || count > 2000}
                onClick={() => void chart.readSealedDay(result?.revision_id ?? undefined, count)}
            >
                读取封存日线
            </button>
            {canMutate && source.new_work_status === "AVAILABLE" && (
                <details>
                    <summary>采集日线</summary>
                    <form
                        onSubmit={(e) => {
                            e.preventDefault();
                            void run("create");
                        }}
                    >
                        <label>
                            开始日期（UTC）
                            <input
                                type="date"
                                required
                                value={start}
                                onChange={(e) => {
                                    setStart(e.target.value);
                                }}
                            />
                        </label>
                        <label>
                            结束日期（UTC，不含）
                            <input
                                type="date"
                                required
                                value={end}
                                onChange={(e) => {
                                    setEnd(e.target.value);
                                }}
                            />
                        </label>
                        {chart.barSemantic.adjustment_policy === "FORWARD" && (
                            <label>
                                前复权基准交易日
                                <input
                                    type="date"
                                    required
                                    value={anchor}
                                    onChange={(e) => {
                                        setAnchor(e.target.value);
                                    }}
                                />
                            </label>
                        )}
                        <button
                            type="submit"
                            disabled={
                                !saved.readable || busy || (saved.query !== null && !terminal)
                            }
                        >
                            开始采集
                        </button>
                    </form>
                </details>
            )}
            {!saved.readable && <p role="alert">无法读取本机保存的原操作，采集已停用。</p>}
            {saved.query !== null && (
                <>
                    <p>
                        原操作 <code>{saved.query.original_request_id}</code>
                    </p>
                    <button type="button" disabled={busy} onClick={() => void run("observe")}>
                        查询原操作
                    </button>
                    {canMutate && !terminal && (
                        <button type="button" disabled={busy} onClick={() => void run("resume")}>
                            恢复原操作
                        </button>
                    )}
                </>
            )}
            <p role="status">
                {busy
                    ? "正在处理…"
                    : message ||
                      (result === null
                          ? ""
                          : statuses[result.status] +
                            (result.failure_detail ? " · " + result.failure_detail : ""))}
            </p>
        </div>
    );
}
