import { render, screen } from "@testing-library/react";
import { WorkspaceLibraryControls } from "./WorkspaceLibraryControls";

it("keeps exact restoration failures visible over command acceptance", () => {
    render(
        <WorkspaceLibraryControls
            workspace={{
                book: null,
                restoration: null,
                activeWorkspace: null,
                pending: null,
                busy: false,
                message: "工作区已载入。",
                reload: vi.fn(() => Promise.resolve()),
                save: vi.fn(() => Promise.resolve(false)),
                load: vi.fn(() => Promise.resolve(false)),
                resolvePending: vi.fn(() => Promise.resolve())
            }}
            configuration={null}
            ready={false}
            dirty={false}
            notice="保存的行情上下文未恢复；请检查精确来源。"
        />
    );
    expect(screen.getByRole("alert")).toHaveTextContent("行情上下文未恢复");
    expect(screen.queryByText("工作区已载入。")).not.toBeInTheDocument();
});
