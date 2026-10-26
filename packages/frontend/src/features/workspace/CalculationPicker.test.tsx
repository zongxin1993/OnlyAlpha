import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { ChartCalculationDraft } from "../../api/research/chartCatalog";
import { chartCatalogFixture } from "../../test/chartCatalog";
import {
    CalculationPicker as ControlledPicker,
    CalculationSelectionSummary
} from "./CalculationPicker";

function CalculationPicker() {
    const [draft, setDraft] = useState<ChartCalculationDraft | null>(null);
    return (
        <>
            <ControlledPicker draft={draft} onDraftChange={setDraft} />
            {draft === null ? null : <CalculationSelectionSummary draft={draft} />}
        </>
    );
}

const dialogDescriptors = {
    showModal: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal"),
    close: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close")
};
beforeEach(() => {
    // jsdom has no native modal implementation. Only open/close markers are shimmed;
    // Chromium E2E owns the focus-trap, Escape and background-inertness proof.
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
    // Unmount while the shim still exists; RTL's automatic cleanup may run later.
    cleanup();
    for (const name of ["showModal", "close"] as const) {
        const descriptor = dialogDescriptors[name];
        if (descriptor === undefined) Reflect.deleteProperty(HTMLDialogElement.prototype, name);
        else Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
    }
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
});

function transport(fixture = chartCatalogFixture()) {
    const state = {
        active: fixture.runtime as string | null,
        activeSequence: [] as (string | null)[],
        reads: [] as string[]
    };
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string, init: RequestInit) => {
            expect(init.method).toBeUndefined();
            state.reads.push(url);
            if (url.endsWith("/active") && state.activeSequence.length > 0)
                state.active = state.activeSequence.shift() ?? null;
            if (url.endsWith("/active") && state.active === null)
                return Promise.resolve(
                    new Response(JSON.stringify({ detail: "RUNTIME_GENERATION_NOT_ACTIVE" }), {
                        status: 503
                    })
                );
            const body = url.endsWith("/active")
                ? { ...fixture.active, runtime_generation_fingerprint: state.active }
                : url.includes("/runtime-generations/")
                  ? fixture.binding
                  : url.endsWith("/readiness")
                    ? fixture.readiness
                    : url.endsWith("/catalog/calculations")
                      ? fixture.discovery
                      : fixture.context;
            return Promise.resolve(new Response(JSON.stringify(body)));
        })
    );
    return state;
}

it("opens, searches descriptor metadata and preserves exact browser-only handoff", async () => {
    const fixture = chartCatalogFixture();
    const traffic = transport(fixture);
    const user = userEvent.setup();
    render(<CalculationPicker />);
    expect(traffic.reads).toEqual([]);
    const trigger = screen.getByRole("button", { name: "指标" });
    await user.click(trigger);
    const modal = screen.getByRole("dialog");
    expect(screen.getByRole("searchbox")).toHaveFocus();
    expect(await within(modal).findByText("默认 20")).toBeInTheDocument();
    expect(within(modal).getByText("默认 CLOSE")).toBeInTheDocument();
    await user.type(screen.getByRole("searchbox"), "nothing");
    expect(within(modal).getByText("没有匹配的注册项。")).toBeInTheDocument();
    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), fixture.capability.type_id);
    await user.click(within(modal).getByRole("button", { name: "选择 SMA · RESEARCH" }));
    const handoff = await screen.findByTestId("calculation-handoff");
    expect(handoff).toHaveAttribute("data-runtime-generation", fixture.runtime);
    expect(handoff).toHaveAttribute("data-catalog-generation", fixture.catalog);
    expect(handoff).toHaveAttribute("data-type-id", fixture.capability.type_id);
    expect(handoff).toHaveAttribute("data-semantic-version", "1");
    expect(handoff).toHaveAttribute("data-kind", "INDICATOR");
    expect(handoff).toHaveAttribute("data-backend", "RESEARCH");
    expect(handoff).toHaveAttribute(
        "data-implementation",
        fixture.capability.implementation_fingerprint
    );
    expect(handoff).toHaveAttribute(
        "data-readiness-capability",
        fixture.witness.capability_fingerprint
    );
    expect(handoff).toHaveTextContent("仅配置草稿，尚未计算");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(traffic.reads.every((path) => path.startsWith("/api/v2/research/"))).toBe(true);
});

it("keeps Factor category empty instead of inventing an example or importing a plugin", async () => {
    transport();
    const user = userEvent.setup();
    render(<CalculationPicker />);
    await user.click(screen.getByRole("button", { name: "因子" }));
    expect(await screen.findByText("当前目录没有此类注册项。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /选择 SMA/ })).not.toBeInTheDocument();
});

it.each(["missing", "unsupported", "duplicate"])(
    "does not select %s capability",
    async (condition) => {
        const fixture = chartCatalogFixture();
        if (condition === "missing")
            fixture.readiness.ordered_calculation_readiness_capabilities = [];
        if (condition === "unsupported") fixture.witness.readiness_contract_versions = [2];
        if (condition === "duplicate")
            fixture.context.ordered_calculation_capabilities.push(fixture.capability);
        transport(fixture);
        const user = userEvent.setup();
        render(<CalculationPicker />);
        await user.click(screen.getByRole("button", { name: "指标" }));
        if (condition === "duplicate")
            expect(await screen.findByRole("alert")).toHaveTextContent("验证失败");
        else expect(await screen.findByRole("button", { name: /选择 SMA/ })).toBeDisabled();
        expect(screen.queryByTestId("calculation-handoff")).not.toBeInTheDocument();
    }
);

it("detects an active generation switch at selection and invalidates old entries", async () => {
    const traffic = transport();
    const user = userEvent.setup();
    render(<CalculationPicker />);
    await user.click(screen.getByRole("button", { name: "指标" }));
    const choose = await screen.findByRole("button", { name: /选择 SMA/ });
    traffic.active = "b".repeat(64);
    await user.click(choose);
    expect(await screen.findByRole("alert")).toHaveTextContent("已切换");
    expect(screen.queryByRole("button", { name: /选择 SMA/ })).not.toBeInTheDocument();
    expect(screen.queryByTestId("calculation-handoff")).not.toBeInTheDocument();
});

it("does not fall back to discovery when Runtime disappears at the exact Catalog fence", async () => {
    const traffic = transport();
    traffic.activeSequence = [chartCatalogFixture().runtime, null];
    const user = userEvent.setup();
    render(<CalculationPicker />);
    await user.click(screen.getByRole("button", { name: "指标" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("已切换");
    expect(traffic.reads).not.toContain("/api/v2/research/catalog/calculations");
    expect(screen.queryByRole("button", { name: /选择 SMA/ })).not.toBeInTheDocument();
    expect(screen.queryByTestId("calculation-handoff")).not.toBeInTheDocument();
});

it("invalidates selected handoff on focus-based authoritative refresh", async () => {
    const traffic = transport();
    const user = userEvent.setup();
    render(<CalculationPicker />);
    await user.click(screen.getByRole("button", { name: "指标" }));
    await user.click(await screen.findByRole("button", { name: /选择 SMA/ }));
    await screen.findByTestId("calculation-handoff");
    traffic.active = "b".repeat(64);
    fireEvent(window, new Event("focus"));
    await waitFor(() => {
        expect(screen.queryByTestId("calculation-handoff")).not.toBeInTheDocument();
    });
});

it("fences a late closed-dialog response before a new open", async () => {
    let release: ((response: Response) => void) | undefined;
    vi.stubGlobal(
        "fetch",
        vi.fn(
            () =>
                new Promise<Response>((resolve) => {
                    release = resolve;
                })
        )
    );
    const user = userEvent.setup();
    render(<CalculationPicker />);
    await user.click(screen.getByRole("button", { name: "指标" }));
    expect(screen.getByRole("status")).toHaveTextContent("正在读取");
    const old = release;
    fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }));
    transport();
    await user.click(screen.getByRole("button", { name: "因子" }));
    expect(await screen.findByText("当前目录没有此类注册项。")).toBeInTheDocument();
    act(() => {
        old?.(
            new Response(
                JSON.stringify({
                    schema_version: 1,
                    runtime_generation_fingerprint: "b".repeat(64)
                })
            )
        );
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("当前目录没有此类注册项。")).toBeInTheDocument();
});

it("lists and selects registered metadata without inventing Runtime or readiness proof", async () => {
    const traffic = transport();
    traffic.active = null;
    const user = userEvent.setup();
    render(<CalculationPicker />);
    await user.click(screen.getByRole("button", { name: "指标" }));
    expect(await screen.findByText("默认 20")).toBeInTheDocument();
    expect(screen.getByText("默认 CLOSE")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Runtime 未激活");
    await user.type(screen.getByRole("searchbox"), "nothing");
    expect(screen.getByText("没有匹配的注册项。")).toBeInTheDocument();
    await user.clear(screen.getByRole("searchbox"));
    await user.click(screen.getByRole("button", { name: "选择 SMA · 配置草稿" }));
    const handoff = await screen.findByTestId("calculation-handoff");
    expect(handoff).toHaveAttribute("data-registration-source", "REGISTERED_DISCOVERY");
    expect(handoff).toHaveAttribute("data-type-id", "onlyalpha.indicator.sma");
    expect(handoff).toHaveAttribute("data-kind", "INDICATOR");
    expect(handoff).toHaveAttribute("data-semantic-version", "1");
    for (const name of [
        "runtime-generation",
        "catalog-generation",
        "backend",
        "implementation",
        "readiness-capability"
    ])
        expect(handoff).not.toHaveAttribute(`data-${name}`);
    expect(handoff).toHaveTextContent("已登记，执行未接入");
    expect(handoff).toHaveTextContent("仅配置草稿，尚未计算");
    expect(traffic.reads).toEqual([
        "/api/v2/research/runtime-generations/active",
        "/api/v2/research/catalog/calculations",
        "/api/v2/research/catalog/calculations"
    ]);
});

it("keeps an empty registered Factor list distinct from private-asset absence", async () => {
    transport().active = null;
    const user = userEvent.setup();
    render(<CalculationPicker />);
    await user.click(screen.getByRole("button", { name: "因子" }));
    expect(await screen.findByText(/当前发现目录没有此类已登记项/)).toHaveTextContent(
        "因子资产不在此列表"
    );
    expect(screen.queryByRole("button", { name: /选择 SMA/ })).not.toBeInTheDocument();
});

it("selects a formally registered Factor draft without requiring a hosted generation", async () => {
    const fixture = chartCatalogFixture();
    const item = fixture.discovery.calculations[0];
    if (item === undefined) throw new Error("Missing discovery fixture");
    item.kind = "FACTOR";
    item.type_reference.kind = "FACTOR";
    item.type_reference.type_id = "registered.factor.momentum";
    item.type_reference.semantic_version = "3";
    transport(fixture).active = null;
    const user = userEvent.setup();
    render(<CalculationPicker />);
    await user.click(screen.getByRole("button", { name: "因子" }));
    await user.click(await screen.findByRole("button", { name: "选择 MOMENTUM · 配置草稿" }));
    const handoff = await screen.findByTestId("calculation-handoff");
    expect(handoff).toHaveAttribute("data-kind", "FACTOR");
    expect(handoff).toHaveAttribute("data-type-id", "registered.factor.momentum");
    expect(handoff).toHaveAttribute("data-semantic-version", "3");
    expect(handoff).not.toHaveAttribute("data-runtime-generation");
});

it.each(["removed", "defaults", "version", "duplicate"])(
    "rejects %s discovery changes at selection",
    async (change) => {
        const fixture = chartCatalogFixture();
        transport(fixture).active = null;
        const user = userEvent.setup();
        render(<CalculationPicker />);
        await user.click(screen.getByRole("button", { name: "指标" }));
        const choose = await screen.findByRole("button", { name: /选择 SMA/ });
        const item = fixture.discovery.calculations[0];
        if (item?.parameters[0] === undefined) throw new Error("Missing discovery fixture");
        if (change === "removed") fixture.discovery.calculations = [];
        if (change === "defaults") item.parameters[0].default.value = 30;
        if (change === "version") item.type_reference.semantic_version = "2";
        if (change === "duplicate") fixture.discovery.calculations.push(item);
        await user.click(choose);
        expect(await screen.findByRole("alert")).toHaveTextContent(
            change === "duplicate" ? "验证失败" : "已切换"
        );
        expect(screen.queryByTestId("calculation-handoff")).not.toBeInTheDocument();
    }
);

it("invalidates a discovery draft when focus observes an activated exact generation", async () => {
    const traffic = transport();
    traffic.active = null;
    const user = userEvent.setup();
    render(<CalculationPicker />);
    await user.click(screen.getByRole("button", { name: "指标" }));
    await user.click(await screen.findByRole("button", { name: /配置草稿/ }));
    await screen.findByTestId("calculation-handoff");
    traffic.active = chartCatalogFixture().runtime;
    fireEvent(window, new Event("focus"));
    await waitFor(() => {
        expect(screen.queryByTestId("calculation-handoff")).not.toBeInTheDocument();
    });
});

it("does not disguise discovery transport failure as empty registration", async () => {
    transport().active = null;
    const user = userEvent.setup();
    render(<CalculationPicker />);
    await user.click(screen.getByRole("button", { name: "指标" }));
    await screen.findByText("默认 20");
    vi.stubGlobal(
        "fetch",
        vi.fn(() => Promise.reject(new TypeError("offline")))
    );
    await user.click(screen.getByRole("button", { name: "刷新目录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("请求失败");
    expect(screen.queryByTestId("calculation-handoff")).not.toBeInTheDocument();
});

it("does not publish an in-flight discovery selection after the dialog is cancelled", async () => {
    const fixture = chartCatalogFixture();
    transport(fixture).active = null;
    const user = userEvent.setup();
    render(<CalculationPicker />);
    await user.click(screen.getByRole("button", { name: "指标" }));
    const choose = await screen.findByRole("button", { name: /配置草稿/ });
    let release: ((response: Response) => void) | undefined;
    const pending = new Promise<Response>((resolve) => {
        release = resolve;
    });
    vi.stubGlobal(
        "fetch",
        vi.fn(() => pending)
    );
    await user.click(choose);
    fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }));
    await act(async () => {
        release?.(new Response(JSON.stringify(fixture.discovery)));
        await pending;
    });
    expect(screen.queryByTestId("calculation-handoff")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("focus refresh supersedes an in-flight discovery selection", async () => {
    const fixture = chartCatalogFixture();
    transport(fixture).active = null;
    const user = userEvent.setup();
    render(<CalculationPicker />);
    await user.click(screen.getByRole("button", { name: "指标" }));
    const choose = await screen.findByRole("button", { name: /配置草稿/ });
    let release: ((response: Response) => void) | undefined;
    const pending = new Promise<Response>((resolve) => {
        release = resolve;
    });
    vi.stubGlobal(
        "fetch",
        vi.fn(() => pending)
    );
    await user.click(choose);
    transport(fixture).active = null;
    fireEvent(window, new Event("focus"));
    await screen.findByText("默认 20");
    await act(async () => {
        release?.(new Response(JSON.stringify(fixture.discovery)));
        await pending;
    });
    expect(screen.queryByTestId("calculation-handoff")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
});
