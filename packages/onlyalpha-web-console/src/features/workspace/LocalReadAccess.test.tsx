import { render, screen, fireEvent } from "@testing-library/react";
import { AppProviders } from "../../app/providers";
import { LocalReadAccess } from "./LocalReadAccess";

it("clears the password input and keeps credentials out of persistent storage", () => {
    const local = vi.spyOn(Storage.prototype, "setItem");
    const cookie = vi.spyOn(document, "cookie", "set");
    render(
        <AppProviders>
            <LocalReadAccess />
        </AppProviders>
    );
    const input = screen.getByLabelText<HTMLInputElement>("本地行情凭据");
    expect(input.type).toBe("password");
    fireEvent.change(input, { target: { value: "ee".repeat(32) } });
    fireEvent.submit(screen.getByRole("form", { name: "本地行情只读访问" }));
    expect(input.value).toBe("");
    expect(screen.getByRole("status")).toHaveTextContent("已提供只读凭据");
    expect(local).not.toHaveBeenCalled();
    expect(cookie).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "清除凭据" }));
    expect(screen.getByRole("status")).toHaveTextContent("未提供凭据");
    local.mockRestore();
    cookie.mockRestore();
});
