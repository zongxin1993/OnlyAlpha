import { capabilitySummary } from "./status";

const labels: readonly [keyof ReturnType<typeof capabilitySummary>, string][] = [
    ["historical", "历史"],
    ["realtime", "实时"],
    ["reference", "参考"]
];

/** Shared capability projection; unmapped canonical IDs stay visible instead of being dropped. */
export function CapabilityTags({ capabilities }: { readonly capabilities: readonly string[] }) {
    const summary = capabilitySummary(capabilities);
    return (
        <span className="capability-tags">
            {labels
                .filter(([key]) => summary[key] === true)
                .map(([key, label]) => (
                    <span className="capability-tag" key={key}>
                        {label}
                    </span>
                ))}
            {summary.unmapped.map((item) => (
                <span className="capability-tag capability-tag--unmapped" key={item}>
                    {item}
                </span>
            ))}
        </span>
    );
}
