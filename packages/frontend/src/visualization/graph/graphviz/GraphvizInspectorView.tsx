import { useEffect, useRef, useState } from "react";

export function GraphvizInspectorView({
    dot,
    onSelectNode
}: {
    readonly dot: string;
    readonly onSelectNode: (nodeId: string) => void;
}) {
    const container = useRef<HTMLDivElement>(null);
    const [failure, setFailure] = useState<string | null>(null);
    useEffect(() => {
        const element = container.current;
        if (element === null) return;
        let active = true;
        const listeners: { node: Element; listener: () => void }[] = [];
        void import("@viz-js/viz")
            .then(({ instance }) => instance())
            .then((viz) => {
                if (!active) return;
                const svg = viz.renderSVGElement(dot);
                svg.setAttribute("role", "img");
                svg.setAttribute("aria-label", "Read-only Research graph");
                for (const node of svg.querySelectorAll("g.node")) {
                    const nodeId = node.querySelector("title")?.textContent;
                    if (nodeId == null) continue;
                    const listener = () => {
                        onSelectNode(nodeId);
                    };
                    node.addEventListener("click", listener);
                    node.setAttribute("tabindex", "0");
                    listeners.push({ node, listener });
                }
                element.replaceChildren(svg);
                setFailure(null);
            })
            .catch(() => {
                if (active)
                    setFailure("GRAPH_RENDER_ERROR: Graphviz rejected the admitted projection");
            });
        return () => {
            active = false;
            for (const { node, listener } of listeners) node.removeEventListener("click", listener);
            element.replaceChildren();
        };
    }, [dot, onSelectNode]);
    return (
        <>
            {failure === null ? null : (
                <p className="error" role="alert">
                    {failure}
                </p>
            )}
            <div className="graphviz-view" ref={container} data-testid="graphviz-view" />
        </>
    );
}
