import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FetchMarketDataApiClient } from "../../api/marketData/client";
import { LocalReadCredentials } from "../../api/marketData/localReadCredentials";
import {
    FIXTURE_SELECTION,
    marketDataInstrument,
    marketDataSource
} from "../../test/marketDataClient";
import { SymbolSearch } from "./SymbolSearch";
import { useWatchlists } from "./useWatchlists";

const credentials = new LocalReadCredentials(true);
const market = new FetchMarketDataApiClient(credentials);
beforeEach(() => {
    Object.defineProperties(HTMLDialogElement.prototype, {
        showModal: {
            configurable: true,
            value: function (this: HTMLDialogElement) {
                this.open = true;
            }
        },
        close: {
            configurable: true,
            value: function (this: HTMLDialogElement) {
                this.open = false;
            }
        }
    });
});
afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
});
it("searches all sources, stars without changing the chart and opens an exact chosen result", async () => {
    let book = { schema_version: 2, version: 0, lists: [] as unknown[] };
    const requests: string[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string, init?: RequestInit) => {
            await Promise.resolve();
            requests.push(url);
            if (url.includes("/instruments/search?"))
                return new Response(
                    JSON.stringify({
                        schema_version: 1,
                        results: [
                            {
                                source_selection: FIXTURE_SELECTION,
                                instrument: marketDataInstrument()
                            }
                        ],
                        sources: [
                            {
                                source_selection: FIXTURE_SELECTION,
                                status: "COMPLETE",
                                asset_classes: ["CRYPTOCURRENCY"],
                                truncated: false
                            }
                        ],
                        truncated: false
                    })
                );
            if (init?.method === "PUT") {
                const body = JSON.parse(typeof init.body === "string" ? init.body : "") as {
                    lists: unknown[];
                };
                book = { ...book, version: book.version + 1, lists: body.lists };
            }
            return new Response(JSON.stringify(book));
        })
    );
    const onSelect = vi.fn(),
        onClose = vi.fn();
    function Harness() {
        const controller = useWatchlists(credentials);
        return (
            <SymbolSearch
                market={market}
                controller={controller}
                sources={[marketDataSource()]}
                onSelect={onSelect}
                onClose={onClose}
                returnFocus={null}
            />
        );
    }
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByRole("searchbox", { name: "商品代码或名称" }), "BTC");
    await user.click(await screen.findByRole("button", { name: "加入自选 BTCUSDT" }));
    expect(await screen.findByRole("button", { name: "移出自选 BTCUSDT" })).toHaveAttribute(
        "aria-pressed",
        "true"
    );
    expect(onSelect).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /查看 BTCUSDT/ }));
    expect(onSelect).toHaveBeenCalledWith(
        {
            integration_id: FIXTURE_SELECTION.integration_id,
            integration_revision_fingerprint: FIXTURE_SELECTION.integration_revision_fingerprint,
            expected_type_id: FIXTURE_SELECTION.type_id
        },
        "BTCUSDT.TEST"
    );
    expect(onClose).toHaveBeenCalledOnce();
    expect(
        requests.some(
            (url) => url.includes("/instruments/search?") && !url.includes("integration_id")
        )
    ).toBe(true);
});
it.each([
    ["TIMEOUT", "全部来源查询未完成"],
    ["UNSUPPORTED", "当前行情来源不支持商品搜索"]
])(
    "distinguishes total source failure from an empty successful search (%s)",
    async (sourceStatus, expected) => {
        vi.stubGlobal(
            "fetch",
            vi.fn((url: string) =>
                Promise.resolve(
                    new Response(
                        JSON.stringify(
                            url.includes("/search?")
                                ? {
                                      schema_version: 1,
                                      results: [],
                                      sources: [
                                          {
                                              source_selection: FIXTURE_SELECTION,
                                              status: sourceStatus,
                                              asset_classes: ["CRYPTOCURRENCY"],
                                              truncated: false
                                          }
                                      ],
                                      truncated: false
                                  }
                                : { schema_version: 2, version: 0, lists: [] }
                        )
                    )
                )
            )
        );
        function Harness() {
            const controller = useWatchlists(credentials);
            return (
                <SymbolSearch
                    market={market}
                    controller={controller}
                    sources={[]}
                    onSelect={vi.fn()}
                    onClose={vi.fn()}
                    returnFocus={null}
                />
            );
        }
        const user = userEvent.setup();
        render(<Harness />);
        await user.type(screen.getByRole("searchbox"), "BTC");
        await waitFor(() => {
            expect(screen.getByRole("status")).toHaveTextContent(expected);
        });
        expect(screen.queryByText("未找到匹配商品")).not.toBeInTheDocument();
    }
);
