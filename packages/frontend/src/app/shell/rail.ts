/** 抽屉导航开合状态（≤900px 窄屏；body.rail-open 为样式契约）。 */
let open = false;
const listeners = new Set<() => void>();

export function getRailSnapshot(): boolean {
    return open;
}

export function subscribeRail(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

export function setRail(next: boolean): void {
    if (open === next) {
        return;
    }
    open = next;
    for (const listener of listeners) {
        listener();
    }
}
