import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { chartCatalogFixture } from "../../test/chartCatalog";
import { CalculationPicker } from "./CalculationPicker";

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
    for (const name of ["showModal", "close"] as const) {
        const descriptor = dialogDescriptors[name];
        if (descriptor === undefined) Reflect.deleteProperty(HTMLDialogElement.prototype, name);
        else Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
    }
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
});

function transport(fixture = chartCatalogFixture()) {
    const state = { active: fixture.runtime, reads: [] as string[] };
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string, init: RequestInit) => {
            expect(init.method).toBeUndefined();
            state.reads.push(url);
            const body = url.endsWith("/active")
                ? { ...fixture.active, runtime_generation_fingerprint: state.active }
                : url.includes("/runtime-generations/")
                  ? fixture.binding
                  : url.endsWith("/readiness")
                    ? fixture.readiness
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

it("shows absent runtime and transport failure distinctly with no successful selection", async () => {
    vi.stubGlobal(
        "fetch",
        vi.fn(() =>
            Promise.resolve(
                new Response(JSON.stringify({ detail: "RUNTIME_GENERATION_NOT_ACTIVE" }), {
                    status: 503
                })
            )
        )
    );
    const user = userEvent.setup();
    render(<CalculationPicker />);
    await user.click(screen.getByRole("button", { name: "指标" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("没有可用于新工作的 Runtime");
    vi.stubGlobal(
        "fetch",
        vi.fn(() => Promise.reject(new TypeError("offline")))
    );
    await user.click(screen.getByRole("button", { name: "刷新目录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("请求失败");
    expect(screen.queryByTestId("calculation-handoff")).not.toBeInTheDocument();
});
