import { PrivateFactorAuthoring } from "./PrivateFactorAuthoring";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useLocalReadCredentials } from "../../../app/providers";
import { readChartStudyCapabilities, sameChartBinding } from "../../../api/chartStudies/client";
import {
    FetchPrivateAssetsApiClient,
    type PrivateAssetLocator
} from "../../../api/privateAssets/client";
import { QueryError } from "../../../shared/components/QueryState";
import "./factors.css";

export function FactorExplorerPage() {
    const credentials = useLocalReadCredentials();
    const client = useMemo(() => new FetchPrivateAssetsApiClient(credentials), [credentials]);
    const capabilities = useQuery({
        queryKey: ["calculation-library", "chart-support"],
        queryFn: ({ signal }) => readChartStudyCapabilities(credentials, signal)
    });
    // These two reads share the installed algorithm child. Observe both
    // independently, sequentially; a capability error does not hide inventory.
    const catalog = useQuery({
        queryKey: ["calculation-library", "registered"],
        queryFn: ({ signal }) => client.catalog(signal),
        enabled: !capabilities.isPending
    });
    const assets = useQuery({
        queryKey: ["calculation-library", "private-assets"],
        queryFn: ({ signal }) => client.current(signal)
    });
    const [search, setSearch] = useState("");
    const [selected, setSelected] = useState<PrivateAssetLocator | null>(null);
    const exact = useQuery({
        queryKey: ["calculation-library", "private-factor", selected],
        queryFn: ({ signal }) => {
            if (selected === null) throw new Error("PRIVATE_FACTOR_SELECTION_REQUIRED");
            return client.factor(selected, signal);
        },
        enabled: selected !== null
    });
    const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
    const presentations = new Map(
        assets.data?.factor_presentations.map((item) => [item.locator.private_asset_id, item]) ?? []
    );
    const currentPresentation =
        selected === null || assets.isError
            ? undefined
            : presentations.get(selected.private_asset_id);
    const needle = search.trim().toLocaleLowerCase();
    const calculations =
        catalog.data?.calculations.filter((item) =>
            `${item.type_reference.type_id} ${item.kind} ${item.type_reference.semantic_version}`
                .toLocaleLowerCase()
                .includes(needle)
        ) ?? [];
    const factors =
        assets.data?.entries.filter(
            (item) =>
                item.locator.private_asset_kind === "FACTOR" &&
                `${presentations.get(item.locator.private_asset_id)?.display.display_name ?? ""} ${presentations.get(item.locator.private_asset_id)?.display.usage_summary ?? ""} ${item.locator.private_asset_id} ${item.description} ${item.category ?? ""} ${item.tags.join(" ")}`
                    .toLocaleLowerCase()
                    .includes(needle)
        ) ?? [];
    return (
        <section className="factor-explorer" aria-label="Factor / Indicator Library">
            <header className="factor-page-header">
                <div>
                    <h1>Factor / Indicator Library</h1>
                    <p>Installed calculations and exact published private Factor metadata.</p>
                </div>
                <button
                    type="button"
                    disabled
                    title="Research execution is not implemented in this version"
                >
                    Configure Research · unavailable
                </button>
            </header>
            <PrivateFactorAuthoring
                onChanged={() => {
                    void assets.refetch();
                }}
            />
            <label htmlFor="factor-search">Search calculations and private Factors</label>
            <input
                id="factor-search"
                type="search"
                value={search}
                onChange={(event) => {
                    setSearch(event.target.value);
                }}
                placeholder="Type, name, purpose, description or tag…"
            />
            <section aria-labelledby="registered-calculations">
                <h2 id="registered-calculations">Registered calculations</h2>
                <p>
                    Registration describes installed code. Chart support is a separate capability.
                </p>
                {catalog.isError ? (
                    <QueryError
                        title="Registered calculations are unavailable."
                        error={catalog.error}
                        retry={() => {
                            void catalog.refetch();
                        }}
                    />
                ) : catalog.isPending ? (
                    <p role="status">Loading registered calculations…</p>
                ) : calculations.length === 0 ? (
                    <p>No registered calculations match this search.</p>
                ) : (
                    <ul className="factor-catalog-items">
                        {calculations.map((item) => {
                            const supported = capabilities.data?.find(
                                (capability) =>
                                    capability.type_id === item.type_reference.type_id &&
                                    capability.semantic_version ===
                                        item.type_reference.semantic_version &&
                                    capability.kind === item.kind &&
                                    sameChartBinding(item.inputs, capability.descriptor.inputs) &&
                                    sameChartBinding(item.outputs, capability.descriptor.outputs) &&
                                    sameChartBinding(
                                        item.parameters.map((p) => ({
                                            name: p.name,
                                            parameter_type: p.type,
                                            required: p.required,
                                            default: p.default.value,
                                            minimum: p.minimum?.value ?? null,
                                            maximum: p.maximum?.value ?? null,
                                            enum_values: p.enum_values.map((value) => value.value),
                                            uppercase: p.uppercase
                                        })),
                                        capability.descriptor.parameters
                                    )
                            );
                            return (
                                <li
                                    key={`${item.type_reference.kind}:${item.type_reference.type_id}@${item.type_reference.semantic_version}`}
                                >
                                    <strong>
                                        {item.type_reference.type_id} @
                                        {item.type_reference.semantic_version}
                                    </strong>
                                    <span> · {item.kind}</span>
                                    <p>
                                        {capabilities.isPending
                                            ? "Checking chart support…"
                                            : supported === undefined
                                              ? "Chart support unavailable"
                                              : "Chart display supported · DISPLAY_ONLY"}
                                    </p>
                                    <details>
                                        <summary>Parameters and outputs</summary>
                                        <p>
                                            {item.parameters
                                                .map((field) => `${field.name} (${field.type})`)
                                                .join(", ") || "No parameters"}
                                        </p>
                                        <p>
                                            Outputs:{" "}
                                            {item.outputs.map((output) => output.name).join(", ")}
                                        </p>
                                    </details>
                                </li>
                            );
                        })}
                    </ul>
                )}
                {capabilities.isError ? (
                    <QueryError
                        title="Chart support could not be verified."
                        error={capabilities.error}
                        retry={() => void capabilities.refetch()}
                    />
                ) : null}
            </section>
            <section aria-labelledby="private-factor-library">
                <h2 id="private-factor-library">Published private Factors</h2>
                <p>
                    Authoring revisions are distinct from registered calculations. Drafts and source
                    editing are unavailable here.
                </p>
                {assets.isError ? (
                    <QueryError
                        title="Private Factor inventory is unavailable."
                        error={assets.error}
                        retry={() => {
                            void assets.refetch();
                        }}
                    />
                ) : assets.isPending ? (
                    <p role="status">Loading private Factor metadata…</p>
                ) : factors.length === 0 ? (
                    <p>No published private Factor metadata matches this search.</p>
                ) : (
                    <div className="factor-catalog-items">
                        {factors.map((item) => {
                            const label = presentations.get(item.locator.private_asset_id);
                            if (label === undefined)
                                return (
                                    <p role="alert" key={item.locator.private_asset_id}>
                                        因子展示信息不可用，请重新载入目录。
                                    </p>
                                );
                            return (
                                <button
                                    type="button"
                                    key={`${item.locator.private_asset_id}:${item.locator.revision_fingerprint}`}
                                    aria-pressed={
                                        selected?.revision_fingerprint ===
                                            item.locator.revision_fingerprint &&
                                        selected.private_asset_id === item.locator.private_asset_id
                                    }
                                    onClick={() => {
                                        setSelected(item.locator);
                                        setSelectedVersion(label.display_version);
                                    }}
                                >
                                    <strong>
                                        {label.display.display_name} · 第 {label.display_version} 版
                                    </strong>
                                    <span>{label.display.usage_summary}</span>
                                    <span>作者内容 · 尚未验证或执行</span>
                                </button>
                            );
                        })}
                    </div>
                )}
                {selected === null ? (
                    <p>Select a private Factor to inspect its exact revision.</p>
                ) : exact.isError ? (
                    <QueryError
                        title="The selected exact Factor revision is unavailable."
                        error={exact.error}
                        retry={() => void exact.refetch()}
                    />
                ) : exact.isPending ? (
                    <p role="status">Loading exact Factor revision…</p>
                ) : (
                    <article aria-label="Exact Factor metadata">
                        <h3>
                            {currentPresentation?.display.display_name ?? "所选私有因子"} · 第{" "}
                            {selectedVersion} 版
                        </h3>
                        {currentPresentation === undefined ? (
                            <p role="alert">
                                当前名称和用途不可用，请重试目录读取；所选精确内容未被替换。
                            </p>
                        ) : (
                            <p>{currentPresentation.display.usage_summary}</p>
                        )}
                        {assets.isFetching && <p role="status">正在刷新当前名称和用途…</p>}
                        {currentPresentation !== undefined &&
                            currentPresentation.locator.revision_fingerprint !==
                                selected.revision_fingerprint && (
                                <p>
                                    当前已发布第 {currentPresentation.display_version}{" "}
                                    版；此处仍查看已选定的第 {selectedVersion} 版。
                                </p>
                            )}
                        <details>
                            <summary>版本技术信息与精确身份</summary>
                            <p>
                                内部标识：{exact.data.factor_id} · 算法语义版本{" "}
                                {exact.data.semantic_version}
                            </p>
                            <p>版本内容说明：{exact.data.description}</p>
                            <p>{exact.data.economic_rationale}</p>
                            <dl>
                                <dt>Revision</dt>
                                <dd>{exact.data.revision_fingerprint}</dd>
                                <dt>Source content</dt>
                                <dd>{exact.data.source_sha256}</dd>
                                <dt>Factor API</dt>
                                <dd>
                                    {exact.data.factor_api_version} ·{" "}
                                    {exact.data.factor_api_contract_fingerprint}
                                </dd>
                                <dt>Inputs</dt>
                                <dd>
                                    <pre>{JSON.stringify(exact.data.input_contract, null, 2)}</pre>
                                </dd>
                                <dt>Parameters</dt>
                                <dd>
                                    <pre>
                                        {JSON.stringify(exact.data.parameter_contract, null, 2)}
                                    </pre>
                                </dd>
                                <dt>Outputs</dt>
                                <dd>
                                    <pre>{JSON.stringify(exact.data.output_contract, null, 2)}</pre>
                                </dd>
                            </dl>
                        </details>
                    </article>
                )}
            </section>
            <section aria-label="Research availability">
                <h2>Research · unavailable</h2>
                <p role="status">
                    Research runs, published results, IC / Rank IC and source execution are not
                    implemented in this version. Metadata and transient chart display are not
                    Research evidence.
                </p>
                <button type="button" disabled>
                    Run Research
                </button>
                <button type="button" disabled>
                    Open published results
                </button>
            </section>
        </section>
    );
}
