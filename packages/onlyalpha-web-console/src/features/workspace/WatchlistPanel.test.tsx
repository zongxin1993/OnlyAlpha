import type { MarketDataApiClient } from "../../api/marketData/client";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProviders } from "../../app/providers";
import {
    marketDataClient,
    marketDataSource,
    marketDataBars,
    marketDataBarsForQuery,
    marketDataAcquisition
} from "../../test/marketDataClient";
import { WatchlistPanel } from "./WatchlistPanel";

it("saves named lists through the formal command and exposes conflicts without pretending to save", async () => {
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true");
    const source = marketDataSource();
    let book = { schema_version: 1, version: 0, lists: [] as unknown[] };
    let conflict = false;
    vi.stubGlobal(
        "fetch",
        vi.fn(async (_url: string, init?: RequestInit) => {
            await Promise.resolve();
            if (init?.method === "PUT") {
                if (conflict)
                    return new Response(
                        JSON.stringify({ error: { code: "WATCHLIST_VERSION_CONFLICT" } }),
                        { status: 409 }
                    );
                if (typeof init.body !== "string") throw new Error("JSON body required");
                const body = JSON.parse(init.body) as {
                    lists: unknown[];
                    expected_version: number;
                    command_id: string;
                };
                expect(body.command_id).toMatch(/^[0-9a-f-]{36}$/);
                expect(body.expected_version).toBe(book.version);
                book = { ...book, version: book.version + 1, lists: body.lists };
            }
            return new Response(JSON.stringify(book));
        })
    );
    const user = userEvent.setup();
    render(
        <AppProviders marketDataClient={marketDataClient()}>
            <WatchlistPanel
                sources={[source]}
                enabled={false}
                onSelect={vi.fn()}
                onPrepare={vi.fn()}
            />
        </AppProviders>
    );
    await user.type(await screen.findByLabelText("新列表名称"), "日常");
    await user.selectOptions(screen.getByLabelText("列表行情来源"), source.integration_id);
    await user.click(screen.getByRole("button", { name: "创建列表" }));
    await waitFor(() => {
        expect(screen.getByLabelText("自选列表")).toHaveValue(
            (book.lists[0] as { list_id: string }).list_id
        );
    });
    expect(book.lists).toHaveLength(1);
    conflict = true;
    await user.type(screen.getByLabelText("新列表名称"), "趋势");
    await user.click(screen.getByRole("button", { name: "创建列表" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("其他窗口");
    expect(book.lists).toHaveLength(1);
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
});

it("retains an uncertain command across remount and failed resolution without a second submit", async () => {
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true");
    sessionStorage.clear();
    const source = marketDataSource();
    let book = { schema_version: 1, version: 0, lists: [] as unknown[] };
    let resolveFails = true;
    let putCount = 0;
    let submitted = "";
    const queried: string[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string, init?: RequestInit) => {
            await Promise.resolve();
            if (init?.method === "PUT") {
                putCount++;
                if (typeof init.body !== "string") throw new Error("JSON required");
                const body = JSON.parse(init.body) as { command_id: string; lists: unknown[] };
                submitted = body.command_id;
                book = { ...book, version: 1, lists: body.lists };
                throw new TypeError("response lost after commit");
            }
            if (url.includes("/commands/")) {
                queried.push(url);
                if (resolveFails)
                    return new Response(
                        JSON.stringify({ error: { code: "WATCHLIST_UNAVAILABLE" } }),
                        { status: 503 }
                    );
            }
            return new Response(JSON.stringify(book));
        })
    );
    const user = userEvent.setup();
    const view = () => (
        <AppProviders marketDataClient={marketDataClient()}>
            <WatchlistPanel
                sources={[source]}
                enabled={false}
                onSelect={vi.fn()}
                onPrepare={vi.fn()}
            />
        </AppProviders>
    );
    const first = render(view());
    await user.type(await screen.findByLabelText("新列表名称"), "待核对");
    await user.selectOptions(screen.getByLabelText("列表行情来源"), source.integration_id);
    await user.click(screen.getByRole("button", { name: "创建列表" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("提交结果未知");
    first.unmount();
    render(view());
    expect(await screen.findByRole("button", { name: "核对提交结果" })).toBeEnabled();
    expect(await screen.findByLabelText("新列表名称")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "核对提交结果" }));
    await waitFor(() => {
        expect(screen.getByRole("button", { name: "核对提交结果" })).toBeEnabled();
    });
    expect(screen.getByLabelText("新列表名称")).toBeDisabled();
    resolveFails = false;
    await user.click(screen.getByRole("button", { name: "核对提交结果" }));
    await waitFor(() => {
        expect(screen.getByLabelText("新列表名称")).toBeEnabled();
    });
    expect(screen.getByRole("alert")).toHaveTextContent("提交结果已确认");
    expect(putCount).toBe(1);
    expect(queried).toEqual([
        `/api/v2/watchlists/commands/${submitted}`,
        `/api/v2/watchlists/commands/${submitted}`
    ]);
    expect(sessionStorage.getItem("onlyalpha.watchlist.pending-command")).toBeNull();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
});

it("observes only visible rows and stops scheduling when the document or panel hides", async () => {
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true");
    sessionStorage.clear();
    const source = marketDataSource();
    const book = {
        schema_version: 1,
        version: 1,
        lists: [
            {
                list_id: "0926c6a2-0cb8-47a5-8d94-cdb89b336182",
                name: "观察",
                source: {
                    integration_id: source.integration_id,
                    integration_revision_fingerprint: source.integration_revision_fingerprint,
                    expected_type_id: source.type_id
                },
                instrument_ids: ["BTCUSDT.TEST"]
            }
        ]
    };
    vi.stubGlobal(
        "fetch",
        vi.fn(() => Promise.resolve(new Response(JSON.stringify(book))))
    );
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
                /* Visibility comes from the controlled observer. */
            }
            disconnect = disconnect;
        }
    );
    const queryLatestBar = vi.fn<MarketDataApiClient["queryLatestBar"]>(() =>
        Promise.resolve(null)
    );
    const client = marketDataClient({ queryLatestBar });
    const renderPanel = (enabled: boolean) => (
        <AppProviders marketDataClient={client}>
            <WatchlistPanel
                sources={[source]}
                enabled={enabled}
                onSelect={vi.fn()}
                onPrepare={vi.fn()}
            />
        </AppProviders>
    );
    const view = render(renderPanel(true));
    await screen.findByRole("button", { name: "BTCUSDT.TEST" });
    expect(queryLatestBar).not.toHaveBeenCalled();
    vi.useFakeTimers();
    await act(async () => {
        observe?.(true);
        await Promise.resolve();
    });
    expect(queryLatestBar).toHaveBeenCalledTimes(1);
    await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(queryLatestBar).toHaveBeenCalledTimes(2);
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    await act(async () => {
        document.dispatchEvent(new Event("visibilitychange"));
        await Promise.resolve();
    });
    await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(queryLatestBar).toHaveBeenCalledTimes(2);
    expect(queryLatestBar.mock.calls[1]?.[3]?.aborted).toBe(true);
    expect(screen.getByText("未更新 / 上次价格可能已过期")).toBeVisible();
    visibility.mockReturnValue("visible");
    await act(async () => {
        document.dispatchEvent(new Event("visibilitychange"));
        await Promise.resolve();
    });
    expect(queryLatestBar).toHaveBeenCalledTimes(3);
    view.rerender(renderPanel(false));
    await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(queryLatestBar).toHaveBeenCalledTimes(3);
    view.unmount();
    expect(disconnect).toHaveBeenCalledOnce();
    visibility.mockRestore();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
});

it.each(["missing", "covered", "complete-plan", "unprovable", "outside", "reversed"])(
    "admits only proven native preparation ranges without changing the chart (%s)",
    async (scenario) => {
        const covered = scenario === "covered" || scenario === "complete-plan";
        const rejected = !["missing", "covered"].includes(scenario);
        vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true");
        sessionStorage.clear();
        vi.stubGlobal(
            "IntersectionObserver",
            class {
                observe() {
                    /* No visible observation in this preparation test. */
                }
                disconnect() {
                    /* No observation to retain. */
                }
            }
        );
        const source = marketDataSource();
        const book = {
            schema_version: 1,
            version: 1,
            lists: [
                {
                    list_id: "0926c6a2-0cb8-47a5-8d94-cdb89b336182",
                    name: "原生价格",
                    source: {
                        integration_id: source.integration_id,
                        integration_revision_fingerprint: source.integration_revision_fingerprint,
                        expected_type_id: source.type_id
                    },
                    instrument_ids: ["BTCUSDT.TEST"]
                }
            ]
        };
        vi.stubGlobal(
            "fetch",
            vi.fn(() => Promise.resolve(new Response(JSON.stringify(book))))
        );
        const template = marketDataBars();
        const start = template.bars[1]?.bar_start_ns ?? "";
        const end = template.resolved_end_ns;
        const coverage = {
            ...template.coverage,
            expected_bar_count: 1,
            actual_bar_count: covered ? 1 : 0,
            status: covered
                ? ("COMPLETE" as const)
                : scenario === "unprovable"
                  ? ("UNPROVABLE" as const)
                  : ("INCOMPLETE" as const),
            planned_acquisition_ranges:
                scenario === "covered"
                    ? []
                    : [
                          {
                              start_ns:
                                  scenario === "outside"
                                      ? "0"
                                      : scenario === "reversed"
                                        ? end
                                        : start,
                              end_ns: scenario === "reversed" ? start : end
                          }
                      ]
        };
        const queryBars = vi.fn<MarketDataApiClient["queryBars"]>((_reference, query) =>
            Promise.resolve(
                marketDataBarsForQuery(query, {
                    resolved_start_ns: start,
                    bars: covered ? template.bars.slice(-1) : [],
                    coverage,
                    revision_evidence: covered ? template.revision_evidence : [],
                    resume_after_sequence: covered ? template.resume_after_sequence : null,
                    resume_plan_fingerprint: covered ? template.resume_plan_fingerprint : null,
                    history_projection_fingerprint: covered
                        ? template.history_projection_fingerprint
                        : null
                })
            )
        );
        const createAcquisition = vi.fn<MarketDataApiClient["createAcquisition"]>(
            (_reference, query) => Promise.resolve(marketDataAcquisition({ ...query }))
        );
        const onSelect = vi.fn(),
            onPrepare = vi.fn();
        const user = userEvent.setup();
        render(
            <AppProviders marketDataClient={marketDataClient({ queryBars, createAcquisition })}>
                <WatchlistPanel
                    sources={[source]}
                    enabled={false}
                    onSelect={onSelect}
                    onPrepare={onPrepare}
                />
            </AppProviders>
        );
        const button = await screen.findByRole("button", { name: "准备 BTCUSDT.TEST 原生行情" });
        expect(createAcquisition).not.toHaveBeenCalled();
        await user.click(button);
        await waitFor(() => {
            expect(button).toBeEnabled();
        });
        expect(queryBars).toHaveBeenCalledWith(book.lists[0]?.source, {
            instrument_id: "BTCUSDT.TEST",
            anchor_kind: "LATEST_CLOSED",
            target_bar_count: 1,
            bar_semantic: source.time_bar_capability.provider_base_semantic
        });
        expect(createAcquisition).toHaveBeenCalledTimes(covered || rejected ? 0 : 1);
        if (rejected) expect(screen.getByText(/原生行情准备未确认/)).toBeVisible();
        if (!covered && !rejected)
            expect(createAcquisition).toHaveBeenCalledWith(book.lists[0]?.source, {
                instrument_id: "BTCUSDT.TEST",
                start_ns: start,
                end_ns: end,
                bar_semantic: source.time_bar_capability.provider_base_semantic
            });
        expect(onSelect).not.toHaveBeenCalled();
        expect(onPrepare).not.toHaveBeenCalled();
        await user.click(screen.getByRole("button", { name: "准备 BTCUSDT.TEST 图表行情" }));
        expect(onPrepare).toHaveBeenCalledOnce();
        vi.unstubAllGlobals();
        vi.unstubAllEnvs();
    }
);
