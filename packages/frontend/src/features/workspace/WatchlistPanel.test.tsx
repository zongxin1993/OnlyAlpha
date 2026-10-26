import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { MarketDataSourceReference } from "../../api/marketData/model";
import { FetchMarketDataApiClient } from "../../api/marketData/client";
import { LocalReadCredentials } from "../../api/marketData/localReadCredentials";
import {
    FIXTURE_REFERENCE,
    FIXTURE_SELECTION,
    marketDataSource
} from "../../test/marketDataClient";
import { WatchlistPanel } from "./WatchlistPanel";
import { useWatchlists } from "./useWatchlists";

const credentials = new LocalReadCredentials(true);
const market = new FetchMarketDataApiClient(credentials);
const sources = [marketDataSource()];
const member = {
    source: { ...FIXTURE_REFERENCE, expected_type_id: "test.market_data" },
    instrument_id: "BTCUSDT.TEST"
};
afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    sessionStorage.clear();
});
function Harness({
    onSelect = vi.fn(),
    enabled = true
}: {
    onSelect?: (source: MarketDataSourceReference, id: string) => void;
    enabled?: boolean;
}) {
    const controller = useWatchlists(credentials);
    return (
        <>
            <button onClick={() => void controller.toggle(member)}>收藏 BTC</button>
            <WatchlistPanel
                controller={controller}
                market={market}
                sources={sources}
                enabled={enabled}
                onSelect={onSelect}
                onSearch={vi.fn()}
            />
        </>
    );
}
it.each([
    ["123.456000", "123.456"],
    ["105.00", "105.00"],
    ["-37.630000", "-37.63"],
    ["0.00001000", "0.00001"],
    ["1e-8", "1e-8"]
])(
    "presents a compact exact quote %s without changing its original value",
    async (price, display) => {
        let book = { schema_version: 2, version: 0, lists: [] as unknown[] };
        const onSelect = vi.fn();
        const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
            await Promise.resolve();
            if (url.includes("/quotes?"))
                return new Response(
                    JSON.stringify({
                        schema_version: 1,
                        source_selection: FIXTURE_SELECTION,
                        status: "COMPLETE",
                        quotes: [
                            {
                                instrument_id: member.instrument_id,
                                status: "AVAILABLE",
                                last_price: price,
                                change_pct: "-2.50",
                                change_basis: "ROLLING_24H",
                                ts_event_ns: "1767225720000000000"
                            }
                        ]
                    })
                );
            if (init?.method === "PUT") {
                const body = JSON.parse(typeof init.body === "string" ? init.body : "") as {
                    lists: unknown[];
                };
                book = { ...book, version: book.version + 1, lists: body.lists };
            }
            return new Response(JSON.stringify(book));
        });
        vi.stubGlobal("fetch", fetcher);
        const user = userEvent.setup();
        render(<Harness onSelect={onSelect} />);
        await screen.findByText("还没有自选，在搜索结果中点 ☆ 添加。");
        expect(screen.queryByLabelText("新列表名称")).not.toBeVisible();
        expect(screen.queryByLabelText("列表行情来源")).not.toBeInTheDocument();
        await user.click(screen.getByRole("button", { name: "收藏 BTC" }));
        expect(await screen.findByText(display)).toBeVisible();
        expect(screen.getByTestId("watchlist-row")).toHaveAttribute(
            "title",
            expect.stringContaining(price)
        );
        expect(screen.getByText("-2.50%")).toBeVisible();
        expect(screen.getAllByRole("columnheader").map((node) => node.textContent)).toEqual([
            "商品",
            "最新价",
            "涨跌幅"
        ]);
        await user.click(screen.getByRole("button", { name: "BTCUSDT" }));
        expect(onSelect).toHaveBeenCalledWith(member.source, member.instrument_id);
        expect(fetcher.mock.calls.some(([url]) => /acquisitions|latest-bar|bars\?/.test(url))).toBe(
            false
        );
    }
);

it("observes visible rows only and stops polling when the panel or document hides", async () => {
    const book = {
        schema_version: 2,
        version: 1,
        lists: [
            { list_id: "0926c6a2-0cb8-47a5-8d94-cdb89b336182", name: "自选", members: [member] }
        ]
    };
    let observe: ((visible: boolean) => void) | undefined;
    const disconnect = vi.fn();
    vi.stubGlobal(
        "IntersectionObserver",
        class {
            constructor(callback: IntersectionObserverCallback) {
                observe = (visible) => {
                    callback(
                        [{ isIntersecting: visible } as IntersectionObserverEntry],
                        this as unknown as IntersectionObserver
                    );
                };
            }
            observe() {
                /* Controlled visibility, never a timer-based layout guess. */
            }
            disconnect = disconnect;
        }
    );
    const quoteSignals: (AbortSignal | null | undefined)[] = [];
    const quotes = vi.fn((signal: AbortSignal | null | undefined) => {
        quoteSignals.push(signal);
        return new Response(
            JSON.stringify({
                schema_version: 1,
                source_selection: FIXTURE_SELECTION,
                status: "COMPLETE",
                quotes: [
                    {
                        instrument_id: member.instrument_id,
                        status: "UNAVAILABLE",
                        last_price: null,
                        change_pct: null,
                        change_basis: null,
                        ts_event_ns: null
                    }
                ]
            })
        );
    });
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string, init?: RequestInit) =>
            Promise.resolve(
                url.includes("/quotes?") ? quotes(init?.signal) : new Response(JSON.stringify(book))
            )
        )
    );
    const view = render(<Harness />);
    await screen.findByRole("button", { name: "BTCUSDT" });
    expect(quotes).not.toHaveBeenCalled();
    vi.useFakeTimers();
    await act(async () => {
        observe?.(true);
        await Promise.resolve();
    });
    expect(quotes).toHaveBeenCalledTimes(1);
    await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(quotes).toHaveBeenCalledTimes(2);
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    await act(async () => {
        document.dispatchEvent(new Event("visibilitychange"));
        await Promise.resolve();
    });
    await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(quotes).toHaveBeenCalledTimes(2);
    expect(quoteSignals[1]?.aborted).toBe(true);
    expect(screen.getByText("未更新，报价可能已过期")).toBeVisible();
    visibility.mockReturnValue("visible");
    await act(async () => {
        document.dispatchEvent(new Event("visibilitychange"));
        await Promise.resolve();
    });
    expect(quotes).toHaveBeenCalledTimes(3);
    view.rerender(<Harness enabled={false} />);
    await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(quotes).toHaveBeenCalledTimes(3);
    view.unmount();
    expect(disconnect).toHaveBeenCalledOnce();
});

it.each([
    ["UNSUPPORTED", "此来源不支持报价"],
    ["UNAVAILABLE", "行情来源暂不可用"],
    ["TIMEOUT", "报价超时"],
    ["COMPLETE", "暂无报价"]
])("distinguishes quote source status %s", async (status, message) => {
    const book = {
        schema_version: 2,
        version: 1,
        lists: [
            { list_id: "0926c6a2-0cb8-47a5-8d94-cdb89b336182", name: "自选", members: [member] }
        ]
    };
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string) =>
            Promise.resolve(
                new Response(
                    JSON.stringify(
                        url.includes("/quotes?")
                            ? {
                                  schema_version: 1,
                                  source_selection: FIXTURE_SELECTION,
                                  status,
                                  quotes: [
                                      {
                                          instrument_id: member.instrument_id,
                                          status: "UNAVAILABLE",
                                          last_price: null,
                                          change_pct: null,
                                          change_basis: null,
                                          ts_event_ns: null
                                      }
                                  ]
                              }
                            : book
                    )
                )
            )
        )
    );
    render(<Harness />);
    expect(await screen.findByText(message)).toBeVisible();
});
