import { vi } from "vitest";
import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ContractEditor } from "./ContractEditor";
import type { ContractKind } from "./contractForm";
function Harness({ kind, initial }: { kind: ContractKind; initial: string }) {
    const [value, setValue] = useState(initial);
    return (
        <>
            <ContractEditor kind={kind} value={value} onChange={setValue} onValidity={vi.fn()} />
            <output data-testid="raw">{value}</output>
        </>
    );
}
it("restores original omissions when an edit is reverted across advanced-mode round trips", () => {
    const original = ' {"close":{"type":"DECIMAL"}} ';
    render(<Harness kind="input_contract" initial={original} />);
    fireEvent.click(screen.getByLabelText("所需数据第 1 项允许缺失"));
    fireEvent.click(screen.getByRole("button", { name: "所需数据高级 JSON" }));
    fireEvent.click(screen.getByRole("button", { name: "切换到所需数据表单" }));
    fireEvent.click(screen.getByLabelText("所需数据第 1 项允许缺失"));
    expect(screen.getByTestId("raw").textContent).toBe(original);
});
it("confirms the explicit required companion patch and can undo it without coercing defaults", () => {
    const original = '{"period":{"type":"INTEGER"}}';
    render(<Harness kind="parameter_contract" initial={original} />);
    fireEvent.click(screen.getByLabelText("可调参数第 1 项设置默认值"));
    fireEvent.change(screen.getByLabelText("可调参数第 1 项默认值"), { target: { value: "20" } });
    expect(screen.getByTestId("raw").textContent).toBe(original);
    expect(screen.getByLabelText("可调参数第 1 项使用时必须填写")).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "确认关联变更" }));
    expect(JSON.parse(screen.getByTestId("raw").textContent)).toEqual({
        period: { type: "INTEGER", required: true, default: 20 }
    });
    fireEvent.click(screen.getByLabelText("可调参数第 1 项设置默认值"));
    expect(screen.getByTestId("raw").textContent).toBe(original);
});

it("requires new confirmation for a companion patch on a different parameter row", () => {
    const original = '{"a":{"type":"INTEGER"},"b":{"type":"INTEGER"}}';
    render(<Harness kind="parameter_contract" initial={original} />);
    fireEvent.click(screen.getByLabelText("可调参数第 1 项设置默认值"));
    fireEvent.change(screen.getByLabelText("可调参数第 1 项默认值"), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "确认关联变更" }));
    const first = screen.getByTestId("raw").textContent;
    fireEvent.click(screen.getByLabelText("可调参数第 2 项设置默认值"));
    fireEvent.change(screen.getByLabelText("可调参数第 2 项默认值"), { target: { value: "30" } });
    expect(screen.getByRole("group", { name: "确认关联变更" })).toBeVisible();
    expect(screen.getByTestId("raw").textContent).toBe(first);
    fireEvent.click(screen.getByRole("button", { name: "确认关联变更" }));
    expect(JSON.parse(screen.getByTestId("raw").textContent)).toEqual({
        a: { type: "INTEGER", required: true, default: 20 },
        b: { type: "INTEGER", required: true, default: 30 }
    });
});
