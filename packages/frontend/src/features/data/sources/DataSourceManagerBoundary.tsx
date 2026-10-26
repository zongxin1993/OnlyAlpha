import { Component, type ReactNode } from "react";

interface State {
    readonly failed: boolean;
}

/**
 * A render failure inside the manager must not blank the operator's workspace. The
 * boundary keeps the failure local and leaves a recovery path (close and reopen).
 */
export class DataSourceManagerBoundary extends Component<{ readonly children: ReactNode }, State> {
    override state: State = { failed: false };

    static getDerivedStateFromError(): State {
        return { failed: true };
    }

    override render() {
        if (this.state.failed) {
            return (
                <p className="error" role="alert">
                    数据源管理界面发生未预期错误。工作区不受影响，请关闭后重新打开；若持续出现请记录本次操作。
                </p>
            );
        }
        return this.props.children;
    }
}
