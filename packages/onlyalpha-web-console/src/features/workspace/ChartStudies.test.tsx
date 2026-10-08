import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { RegisteredCalculation } from "../../api/research/chartCatalog";
import { researchCalculationCatalogSchema } from "../../api/research/schemas";
import { chartCatalogFixture } from "../../test/chartCatalog";
import { marketDataBarSemantic } from "../../api/marketData/model";
import { ChartStudies } from "./ChartStudies";
import type { ChartStudyContext } from "./chartStudy";
import { onlyMarketDataChartContextKey } from "./marketDataHistoryLoader";

const modalMethods = {
    showModal: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal"),
    close: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close")
};
beforeEach(() => {
    document.documentElement.style.setProperty("--accent-solid", "#1f5f8b");
    Object.defineProperties(HTMLDialogElement.prototype, {
        showModal: {
            configurable: true,
            value: function (this: HTMLDialogElement) {
                this.setAttribute("open", "");
            }
        },
        close: {
            configurable: true,
            value: function (this: HTMLDialogElement) {
                this.removeAttribute("open");
            }
        }
    });
});
afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.documentElement.style.removeProperty("--accent-solid");
    for (const name of ["showModal", "close"] as const) {
        const method = modalMethods[name];
        if (method === undefined) Reflect.deleteProperty(HTMLDialogElement.prototype, name);
        else Object.defineProperty(HTMLDialogElement.prototype, name, method);
    }
});
const chartInputs = {
    source: {
        integration_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        integration_revision_fingerprint: "a".repeat(64),
        expected_type_id: "binance.spot.market_data"
    },
    instrumentId: "BTCUSDT.BINANCE",
    barSemantic: marketDataBarSemantic(15)
};
const context: ChartStudyContext = {
    ...chartInputs,
    key: onlyMarketDataChartContextKey(
        chartInputs.source,
        chartInputs.instrumentId,
        chartInputs.barSemantic
    )
};
function transport(exact = false) {
    const fixture = chartCatalogFixture();
    const item = researchCalculationCatalogSchema.parse(fixture.discovery).calculations[0];
    if (item === undefined) throw new Error("Missing fixture");
    const state = {
        registration: structuredClone(item) as RegisteredCalculation,
        fixture,
        active: exact,
        reads: [] as string[],
        hold: null as Promise<Response> | null,
        missing: false
    };
    vi.stubGlobal(
        "fetch",
        vi.fn((input: string, init: RequestInit) => {
            expect(init.method).toBeUndefined();
            state.reads.push(input);
            if (state.hold !== null) return state.hold;
            if (input.endsWith("/active") && !state.active)
                return Promise.resolve(
                    new Response(JSON.stringify({ detail: "RUNTIME_GENERATION_NOT_ACTIVE" }), {
                        status: 503
                    })
                );
            const body = input.endsWith("/active")
                ? fixture.active
                : input.endsWith("/catalog/calculations")
                  ? {
                        ...fixture.discovery,
                        calculations: state.missing ? [] : [state.registration]
                    }
                  : input.includes("/runtime-generations/")
                    ? fixture.binding
                    : input.endsWith("/readiness")
                      ? fixture.readiness
                      : fixture.context;
            return Promise.resolve(new Response(JSON.stringify(body)));
        })
    );
    return state;
}
async function select(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("button", { name: "指标" }));
    await user.click(await screen.findByRole("button", { name: /选择 SMA/ }));
    return screen.findByRole("dialog", { name: "指标 / 因子参数配置" });
}
it("confirms independent instances; cancel/edit has a single state source and style does not modify configuration", async () => {
    const traffic = transport();
    const user = userEvent.setup();
    render(<ChartStudies context={context} />);
    await select(user);
    expect(screen.getByRole("textbox", { name: "period" })).toHaveValue("20");
    expect(screen.getByRole("combobox", { name: "price_field" })).toHaveValue("CLOSE");
    await user.click(screen.getByRole("button", { name: "取消配置" }));
    expect(screen.queryByTestId("chart-study-instance")).not.toBeInTheDocument();
    await select(user);
    await user.click(screen.getByRole("button", { name: "添加" }));
    const first = await screen.findByTestId("chart-study-instance");
    const id = first.getAttribute("data-instance-id"),
        original = first.getAttribute("data-configuration");
    await user.click(within(first).getByRole("button", { name: "编辑 SMA" }));
    await user.clear(screen.getByRole("textbox", { name: "period" }));
    await user.type(screen.getByRole("textbox", { name: "period" }), "30");
    await user.click(screen.getByRole("button", { name: "取消配置" }));
    expect(first).toHaveAttribute("data-configuration", original);
    await user.click(within(first).getByRole("button", { name: "编辑 SMA" }));
    await user.clear(screen.getByRole("textbox", { name: "颜色" }));
    await user.type(screen.getByRole("textbox", { name: "颜色" }), "#c8332a");
    await user.selectOptions(screen.getByRole("combobox", { name: "位置" }), "SEPARATE_PANE");
    await user.click(screen.getByRole("checkbox", { name: "显示" }));
    await user.click(screen.getByRole("button", { name: "应用" }));
    await waitFor(() => {
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(first).toHaveAttribute("data-instance-id", id);
    expect(first).toHaveAttribute("data-configuration", original);
    expect(JSON.parse(first.getAttribute("data-presentation") ?? "null")).toMatchObject({
        color: "#c8332a",
        placement: "SEPARATE_PANE",
        visible: false
    });
    await select(user);
    await user.click(screen.getByRole("button", { name: "添加" }));
    await waitFor(() => {
        expect(screen.getAllByTestId("chart-study-instance")).toHaveLength(2);
    });
    const second = screen.getAllByTestId("chart-study-instance")[1];
    expect(second).not.toHaveAttribute("data-instance-id", id);
    expect(second).toHaveAttribute("data-configuration", original);
    expect(second).toHaveAttribute("data-registration-source", "REGISTERED_DISCOVERY");
    expect(first).toHaveTextContent("已配置，尚未接入后端计算");
    expect(traffic.reads.every((path) => path.startsWith("/api/v2/research/"))).toBe(true);
});
it.each(["removed", "changed", "runtime-disappeared", "paired-schema"])(
    "refuses confirmation after %s metadata",
    async (condition) => {
        const traffic = transport(
            condition === "runtime-disappeared" || condition === "paired-schema"
        );
        const user = userEvent.setup();
        render(<ChartStudies context={context} />);
        await select(user);
        if (condition === "removed") traffic.missing = true;
        if (condition === "changed") {
            const p = traffic.registration.parameters[0];
            if (p === undefined) throw new Error("Missing parameter");
            p.default = { type: "INTEGER", value: 30 };
        }
        if (condition === "runtime-disappeared") traffic.active = false;
        if (condition === "paired-schema") {
            traffic.fixture.context.projection_schema_fingerprint = "e".repeat(64);
            traffic.fixture.readiness.exact_catalog_context_projection_schema_fingerprint =
                traffic.fixture.context.projection_schema_fingerprint;
        }
        await user.click(screen.getByRole("button", { name: "添加" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("STALE");
        expect(screen.getByRole("button", { name: "添加" })).toBeDisabled();
        expect(screen.queryByTestId("chart-study-instance")).not.toBeInTheDocument();
        if (condition === "runtime-disappeared")
            expect(traffic.reads).not.toContain("/api/v2/research/catalog/calculations");
    }
);
it("supports descriptor-driven decimal precision, required boolean and multiple output selection", async () => {
    const traffic = transport();
    traffic.registration.type_reference.type_id = "example.precise";
    traffic.registration.parameters = [
        {
            name: "threshold",
            type: "DECIMAL",
            required: false,
            default: { type: "DECIMAL", value: "9007199254740993.123456789012345678901" },
            minimum: null,
            maximum: null,
            enum_values: [],
            uppercase: false
        },
        {
            name: "enabled",
            type: "BOOLEAN",
            required: true,
            default: { type: "NULL", value: null },
            minimum: null,
            maximum: null,
            enum_values: [],
            uppercase: false
        }
    ];
    const output = traffic.registration.outputs[0];
    if (output === undefined) throw new Error("Missing output");
    traffic.registration.outputs.push({ ...output, name: "other" });
    const user = userEvent.setup();
    render(<ChartStudies context={context} />);
    await user.click(screen.getByRole("button", { name: "指标" }));
    await user.click(await screen.findByRole("button", { name: /选择 PRECISE/ }));
    expect(screen.getByRole("button", { name: "添加" })).toBeDisabled();
    const value = "9007199254740993.123456789012345678902";
    await user.clear(screen.getByRole("textbox", { name: "threshold" }));
    await user.type(screen.getByRole("textbox", { name: "threshold" }), value);
    const booleanField = screen.getByRole("combobox", { name: "enabled" });
    booleanField.focus();
    await user.selectOptions(booleanField, "false");
    expect(booleanField).toHaveFocus();
    expect(screen.getByRole("combobox", { name: "enabled" })).toBe(booleanField);
    await user.selectOptions(screen.getByRole("combobox", { name: "输出" }), "other");
    await user.click(screen.getByRole("button", { name: "添加" }));
    const instance = await screen.findByTestId("chart-study-instance");
    expect(JSON.parse(instance.getAttribute("data-configuration") ?? "null")).toEqual({
        parameters: {
            threshold: { type: "DECIMAL", value },
            enabled: { type: "BOOLEAN", value: false }
        },
        outputName: "other"
    });
});
it.each(["cancel", "focus", "source", "instrument", "bar"])(
    "fences held confirmation on %s",
    async (condition) => {
        const traffic = transport();
        const user = userEvent.setup();
        function Workspace() {
            const [active, setActive] = useState(context);
            return (
                <>
                    <button
                        onClick={() => {
                            const next = {
                                ...context,
                                source:
                                    condition === "source"
                                        ? {
                                              ...context.source,
                                              integration_revision_fingerprint: "b".repeat(64)
                                          }
                                        : context.source,
                                instrumentId:
                                    condition === "instrument"
                                        ? "ETHUSDT.BINANCE"
                                        : context.instrumentId,
                                barSemantic:
                                    condition === "bar"
                                        ? marketDataBarSemantic(5)
                                        : context.barSemantic
                            };
                            const key = onlyMarketDataChartContextKey(
                                next.source,
                                next.instrumentId,
                                next.barSemantic
                            );
                            expect(key).not.toBe(context.key);
                            setActive({ ...next, key });
                        }}
                    >
                        switch context
                    </button>
                    <ChartStudies key={active.key} context={active} />
                </>
            );
        }
        render(<Workspace />);
        await select(user);
        let release: ((response: Response) => void) | undefined;
        const pending = new Promise<Response>((resolve) => {
            release = resolve;
        });
        traffic.hold = pending;
        await user.click(screen.getByRole("button", { name: "添加" }));
        expect(screen.getByText("正在重新验证元数据…")).toBeInTheDocument();
        if (condition === "cancel")
            await user.click(screen.getByRole("button", { name: "取消配置" }));
        else if (condition === "focus") fireEvent(window, new Event("focus"));
        else await user.click(screen.getByRole("button", { name: "switch context" }));
        await act(async () => {
            release?.(
                new Response(
                    JSON.stringify({ schema_version: 2, calculations: [traffic.registration] })
                )
            );
            await pending;
        });
        expect(screen.queryByTestId("chart-study-instance")).not.toBeInTheDocument();
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    }
);

it("invalid edit keeps the prior instance inputs and marks it stale; focus is not validity proof", async () => {
    const traffic = transport();
    const user = userEvent.setup();
    render(<ChartStudies context={context} />);
    await select(user);
    await user.click(screen.getByRole("button", { name: "添加" }));
    const instance = await screen.findByTestId("chart-study-instance");
    const original = instance.getAttribute("data-configuration");
    fireEvent(window, new Event("focus"));
    await waitFor(() => {
        expect(instance).toHaveAttribute("data-connection-state", "STALE_CONFIG");
    });
    await user.click(within(instance).getByRole("button", { name: "编辑 SMA" }));
    traffic.missing = true;
    await user.clear(screen.getByRole("textbox", { name: "period" }));
    await user.type(screen.getByRole("textbox", { name: "period" }), "50");
    await user.click(screen.getByRole("button", { name: "应用" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("STALE");
    expect(instance).toHaveAttribute("data-configuration", original);
    expect(instance).toHaveAttribute("data-connection-state", "STALE_CONFIG");
    await user.click(screen.getByRole("button", { name: "取消配置" }));
    expect(screen.getAllByTestId("chart-study-instance")).toHaveLength(1);
});
it("blocks unsafe input, missing chart context and invalid style without any confirmation read", async () => {
    const traffic = transport();
    const user = userEvent.setup();
    render(<ChartStudies context={null} />);
    await select(user);
    const reads = traffic.reads.length;
    expect(screen.getByRole("button", { name: "添加" })).toBeDisabled();
    await user.clear(screen.getByRole("textbox", { name: "period" }));
    await user.type(screen.getByRole("textbox", { name: "period" }), "9007199254740992");
    await user.clear(screen.getByRole("textbox", { name: "颜色" }));
    await user.type(screen.getByRole("textbox", { name: "颜色" }), "not-a-color");
    expect(
        screen
            .getAllByRole("alert")
            .map((node) => node.textContent)
            .join(" ")
    ).toContain("精度不安全");
    expect(screen.getByRole("button", { name: "添加" })).toBeDisabled();
    expect(traffic.reads).toHaveLength(reads);
});

it("fences an old confirmation across A to B to restored A without polluting a new instance", async () => {
    const traffic = transport();
    const user = userEvent.setup();
    const otherInputs = { ...chartInputs, instrumentId: "ETHUSDT.BINANCE" };
    const other: ChartStudyContext = {
        ...otherInputs,
        key: onlyMarketDataChartContextKey(
            otherInputs.source,
            otherInputs.instrumentId,
            otherInputs.barSemantic
        )
    };
    expect(other.key).not.toBe(context.key);
    function Workspace() {
        const [active, setActive] = useState(context);
        return (
            <>
                <button
                    onClick={() => {
                        setActive((previous) => (previous.key === context.key ? other : context));
                    }}
                >
                    switch context
                </button>
                <ChartStudies key={active.key} context={active} />
            </>
        );
    }
    render(<Workspace />);
    await select(user);
    await user.clear(screen.getByRole("textbox", { name: "period" }));
    await user.type(screen.getByRole("textbox", { name: "period" }), "45");
    let release: ((response: Response) => void) | undefined;
    const pending = new Promise<Response>((resolve) => {
        release = resolve;
    });
    traffic.hold = pending;
    await user.click(screen.getByRole("button", { name: "添加" }));
    await user.click(screen.getByRole("button", { name: "switch context" }));
    await user.click(screen.getByRole("button", { name: "switch context" }));
    traffic.hold = null;
    await select(user);
    await user.click(screen.getByRole("button", { name: "添加" }));
    const current = await screen.findByTestId("chart-study-instance");
    const id = current.getAttribute("data-instance-id");
    await act(async () => {
        release?.(
            new Response(
                JSON.stringify({ schema_version: 2, calculations: [traffic.registration] })
            )
        );
        await pending;
    });
    expect(screen.getAllByTestId("chart-study-instance")).toHaveLength(1);
    expect(current).toHaveAttribute("data-instance-id", id);
    expect(current).toHaveAttribute("data-chart-context-key", context.key);
    expect(current).toHaveTextContent("period=20");
    expect(current).not.toHaveTextContent("period=45");
});
