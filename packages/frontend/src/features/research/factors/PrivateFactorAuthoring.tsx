import { ContractEditor } from "./ContractEditor";
import { inspectContract, type ContractKind } from "./contractForm";
import { z } from "zod";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocalReadCredentials } from "../../../app/providers";
import {
    FactorAuthoringClient,
    FactorAuthoringError,
    type FactorDraft,
    type FactorAuthoringState,
    type FactorAuthoringReceipt,
    type FactorDisplayFields,
    type FactorAuthoringInventory
} from "../../../api/privateAssets/authoring";
const contracts = ["input_contract", "parameter_contract", "output_contract"] as const;
type Contracts = Record<(typeof contracts)[number], string>;
interface Pending {
    id: string;
    factor: string;
    kind: "SAVE" | "PUBLISH" | "DISPLAY";
}
const pendingKey = "onlyalpha.private-factor.pending-command";
const pendingSchema = z.strictObject({
    id: z.uuid().refine((value) => value[14] === "4"),
    factor: z.string().regex(/^private\.factor\.[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$/),
    kind: z.enum(["SAVE", "PUBLISH", "DISPLAY"])
});
function retainedCommand(): { command: Pending | null; error: string | null } {
    try {
        const raw = sessionStorage.getItem(pendingKey);
        return { command: raw === null ? null : pendingSchema.parse(JSON.parse(raw)), error: null };
    } catch {
        return {
            command: null,
            error: "无法读取待确认命令，已停止新的保存和发布；请恢复站点会话存储后重新打开。"
        };
    }
}
function edit(value: FactorDraft): Contracts {
    return {
        input_contract: JSON.stringify(value.input_contract, null, 2),
        parameter_contract: JSON.stringify(value.parameter_contract, null, 2),
        output_contract: JSON.stringify(value.output_contract, null, 2)
    };
}
function initialDraft(id: string, fingerprint: string): FactorDraft {
    return {
        schema_version: 1,
        factor_id: id,
        base_revision_fingerprint: null,
        semantic_version: "1",
        source_text:
            "def calculate(api, inputs, parameters):\n    return {'value': inputs['close']}\n",
        factor_api_version: 1,
        factor_api_contract_fingerprint: fingerprint,
        input_contract: { close: { type: "DECIMAL" } },
        parameter_contract: {},
        output_contract: { value: { type: "DECIMAL" } },
        description: "",
        economic_rationale: "",
        category: "price",
        tags: []
    };
}
function fromState(state: FactorAuthoringState, fingerprint?: string): FactorDraft {
    if (
        state.draft !== null &&
        state.draft.base_revision_fingerprint === state.current_revision_fingerprint
    )
        return state.draft;
    const current = state.revisions.at(-1)?.revision;
    if (current === undefined) {
        if (state.draft !== null) return state.draft;
        if (fingerprint !== undefined) return initialDraft(state.factor_id, fingerprint);
        throw new Error("请重新载入因子 API 信息后编辑");
    }
    return {
        schema_version: current.schema_version,
        factor_id: current.factor_id,
        semantic_version: current.semantic_version,
        source_text: current.source_text,
        factor_api_version: current.factor_api_version,
        factor_api_contract_fingerprint: current.factor_api_contract_fingerprint,
        input_contract: current.input_contract,
        parameter_contract: current.parameter_contract,
        output_contract: current.output_contract,
        description: current.description,
        economic_rationale: current.economic_rationale,
        category: current.category,
        tags: current.tags,
        base_revision_fingerprint: current.revision_fingerprint
    };
}
function serialized(draft: FactorDraft, raw: Contracts): string {
    for (const key of contracts) {
        const checked = inspectContract(raw[key]);
        if (checked.error) throw new Error(checked.error);
    }
    return `{${Object.entries(draft)
        .map(
            ([key, value]) =>
                `${JSON.stringify(key)}:${contracts.includes(key as (typeof contracts)[number]) ? raw[key as (typeof contracts)[number]] : JSON.stringify(value)}`
        )
        .join(",")}}`;
}
export function PrivateFactorAuthoring({ onChanged }: { readonly onChanged: () => void }) {
    const credentials = useLocalReadCredentials();
    const api = useMemo(() => new FactorAuthoringClient(credentials), [credentials]);
    const dialog = useRef<HTMLDialogElement>(null);
    const [open, setOpen] = useState(false);
    const [inventory, setInventory] = useState<FactorAuthoringInventory | null>(null);
    const [state, setState] = useState<FactorAuthoringState | null>(null);
    const [draft, setDraft] = useState<FactorDraft | null>(null);
    const [raw, setRaw] = useState<Contracts>({
        input_contract: "{}",
        parameter_contract: "{}",
        output_contract: "{}"
    });
    const [tagsText, setTagsText] = useState("");
    const [contractEpoch, setContractEpoch] = useState(0);
    const [contractErrors, setContractErrors] = useState<Partial<Record<ContractKind, string>>>({});
    const contractValidity = useCallback((kind: ContractKind, error: string) => {
        setContractErrors((previous) =>
            previous[kind] === error ? previous : { ...previous, [kind]: error }
        );
    }, []);
    function resetContracts() {
        setContractEpoch((epoch) => epoch + 1);
        setContractErrors({});
    }

    const [names, setNames] = useState<FactorDisplayFields>({
        display_name: "",
        usage_summary: ""
    });
    const [draftExpected, setDraftExpected] = useState<string | null>(null);
    const [needsReload, setNeedsReload] = useState(false);
    const [busy, setBusy] = useState(false);
    const [retained] = useState(retainedCommand);
    const [pending, setPending] = useState<Pending | null>(retained.command);
    const [storageProblem] = useState(retained.error);
    const [message, setMessage] = useState("");
    const [error, setError] = useState("");
    const [historical, setHistorical] = useState<FactorAuthoringState["revisions"][number] | null>(
        null
    );
    useEffect(() => {
        if (open) dialog.current?.showModal();
        else if (dialog.current?.open) dialog.current.close();
    }, [open]);
    async function load() {
        setOpen(true);
        setBusy(true);
        setError(storageProblem ?? "");
        if (pending !== null) setMessage("存在结果不明的原命令，请先查询；不会重新提交。");
        try {
            setInventory(await api.list());
        } catch (e) {
            setError(e instanceof Error ? e.message : "读取失败");
        } finally {
            setBusy(false);
        }
    }
    async function choose(id: string) {
        setBusy(true);
        setError("");
        setMessage("");
        try {
            const value = await api.read(id);
            const draft = fromState(value, inventory?.factor_api_contract_fingerprint);
            setState(value);
            setNames({
                display_name: value.display.display_name,
                usage_summary: value.display.usage_summary
            });
            setDraftExpected(value.draft_fingerprint);
            setDraft(draft);
            setRaw(edit(draft));
            resetContracts();
            setTagsText(draft.tags.join(", "));
            setNeedsReload(false);
            setHistorical(null);
        } catch (e) {
            setError(e instanceof Error ? e.message : "读取失败");
        } finally {
            setBusy(false);
        }
    }
    function create() {
        if (inventory === null) return;
        const draft = initialDraft(
            `private.factor.f${crypto.randomUUID().replaceAll("-", "")}`,
            inventory.factor_api_contract_fingerprint
        );
        setState(null);
        setNames(inventory.new_factor_defaults);
        setDraftExpected(null);
        setDraft(draft);
        setRaw(edit(draft));
        resetContracts();
        setTagsText(draft.tags.join(", "));
        setNeedsReload(false);
        setMessage("");
        setError("");
        setHistorical(null);
    }
    function clearPending(): boolean {
        try {
            sessionStorage.removeItem(pendingKey);
            setPending(null);
            return true;
        } catch {
            setError("结果已确认，但无法清理提交标识；请恢复会话存储后再次查询原命令。");
            return false;
        }
    }
    async function accepted(value: FactorAuthoringReceipt, kind: Pending["kind"]) {
        if (!clearPending()) return;
        setError("");
        setMessage(
            kind === "SAVE"
                ? "草稿已保存"
                : kind === "DISPLAY"
                  ? "名称和用途已保存；内容版本未变"
                  : "内容版本已发布；未验证或执行"
        );
        onChanged();
        try {
            // A historical accepted effect is not a query of the current head.
            const current = await api.read(value.factor_id);
            setState(current);
            setNames({
                display_name: current.display.display_name,
                usage_summary: current.display.usage_summary
            });
            if (kind !== "DISPLAY" || draft?.factor_id !== value.factor_id) {
                const editable = fromState(current, inventory?.factor_api_contract_fingerprint);
                setDraft(editable);
                setDraftExpected(current.draft_fingerprint);
                setRaw(edit(editable));
                resetContracts();
                setTagsText(editable.tags.join(", "));
            }
            setNeedsReload(false);
            setHistorical(null);
        } catch {
            setNeedsReload(true);
            setError("命令结果已确认，但当前状态载入失败；请重新载入已保存内容后继续。");
        }
        void api
            .list()
            .then(setInventory)
            .catch(() => {
                setError("结果已确认，但列表刷新失败；可关闭后重新打开");
            });
    }
    async function submit(kind: Pending["kind"]) {
        if (draft === null || pending !== null) return;
        setError("");
        setMessage("");
        if (kind !== "DISPLAY" && Object.values(contractErrors).some(Boolean)) {
            setError("请修正契约填写错误后保存或发布；名称和用途可独立保存。");
            return;
        }
        let body: string;
        try {
            body =
                kind === "DISPLAY"
                    ? ""
                    : serialized(
                          {
                              ...draft,
                              tags: tagsText
                                  .split(/[,，]/)
                                  .map((value) => value.trim())
                                  .filter(Boolean)
                                  .sort()
                          },
                          raw
                      );
        } catch (e) {
            setError(e instanceof Error ? e.message : "契约 JSON 无效");
            return;
        }
        const command: Pending = { id: crypto.randomUUID(), factor: draft.factor_id, kind };
        try {
            sessionStorage.setItem(pendingKey, JSON.stringify(command));
        } catch {
            setError("无法保留提交标识，本次未提交；请检查站点会话存储权限。");
            return;
        }
        setPending(command);
        setBusy(true);
        try {
            const result =
                kind === "DISPLAY"
                    ? await api.updateDisplay(
                          draft.factor_id,
                          command.id,
                          state?.display_fingerprint ?? "",
                          names
                      )
                    : kind === "SAVE"
                      ? await api.save(
                            draft.factor_id,
                            command.id,
                            draftExpected,
                            body,
                            state === null ? names : null
                        )
                      : await api.publish(
                            draft.factor_id,
                            command.id,
                            state?.draft_fingerprint ?? ""
                        );
            await accepted(result, kind);
        } catch (e) {
            if (e instanceof FactorAuthoringError && e.definitive) {
                if (!clearPending()) return;
                setError(
                    e.code === "PRIVATE_FACTOR_DRAFT_CONFLICT" ||
                        e.code === "PRIVATE_FACTOR_DISPLAY_CONFLICT"
                        ? "内容或展示信息已被其他操作修改，请重新载入后编辑。当前输入仍保留。"
                        : e.code === "PRIVATE_ASSET_INVALID"
                          ? "内容无效：请检查版本、契约和值的格式，移除 NUL 控制字符；当前输入仍保留。"
                          : e.code
                );
            } else {
                setMessage("结果不明，请查询原命令结果；不会自动重试。");
            }
        } finally {
            setBusy(false);
        }
    }
    async function recover() {
        if (pending === null) return;
        setBusy(true);
        setError("");
        try {
            const result = await api.command(pending.factor, pending.id, pending.kind);
            if (result === null) {
                if (!clearPending()) return;
                setMessage("原命令未被接纳，未自动重试；可继续手动编辑或保存。");
            } else {
                await accepted(result, pending.kind);
            }
        } catch (e) {
            setError(e instanceof Error ? e.message : "查询失败，仍为结果不明");
        } finally {
            setBusy(false);
        }
    }
    const blocked = busy || pending !== null || storageProblem !== null;
    const savedDraft = state?.draft;
    const dirty =
        draft !== null &&
        (savedDraft == null ||
            JSON.stringify(draft) !== JSON.stringify(savedDraft) ||
            tagsText !== savedDraft.tags.join(", ") ||
            contracts.some((key) => raw[key] !== JSON.stringify(savedDraft[key], null, 2)));
    return (
        <>
            <button
                type="button"
                onClick={() => {
                    void load();
                }}
            >
                创建 / 编辑私有因子
            </button>
            <dialog
                ref={dialog}
                className="private-factor-editor"
                aria-label="私有 Factor 草稿与历史"
                onKeyDown={(event) => {
                    event.stopPropagation();
                }}
                onCancel={(event) => {
                    event.stopPropagation();
                    if (busy || pending !== null) event.preventDefault();
                    else setOpen(false);
                }}
            >
                <header>
                    <h2>私有 Factor 草稿与历史</h2>
                    <button
                        type="button"
                        disabled={busy || pending !== null}
                        onClick={() => {
                            setOpen(false);
                        }}
                    >
                        关闭
                    </button>
                </header>
                <p>保存草稿和发布内容版本 只管理作者内容，不运行代码或授予研究资格。</p>
                {busy && <p role="status">正在处理…</p>}
                {error !== "" && <p role="alert">{error}</p>}
                {message !== "" && <p role="status">{message}</p>}
                {pending !== null && (
                    <button
                        type="button"
                        disabled={busy}
                        onClick={() => {
                            void recover();
                        }}
                    >
                        查询原命令结果
                    </button>
                )}
                <div className="private-factor-layout">
                    <aside>
                        <button
                            type="button"
                            disabled={blocked || inventory === null}
                            onClick={create}
                        >
                            新建因子
                        </button>
                        {inventory?.entries.length === 0 && <p>还没有私有因子，先新建一个草稿。</p>}
                        <ul>
                            {inventory?.entries.map((item) => (
                                <li key={item.factor_id}>
                                    <button
                                        type="button"
                                        disabled={blocked}
                                        onClick={() => {
                                            void choose(item.factor_id);
                                        }}
                                    >
                                        {item.display.display_name} ·{" "}
                                        {item.current_display_version === null
                                            ? "草稿"
                                            : `第 ${String(item.current_display_version)} 版`}
                                    </button>
                                </li>
                            ))}
                        </ul>
                    </aside>
                    {draft !== null && (
                        <section aria-label="Factor 编辑器">
                            <form
                                aria-label="名称和用途"
                                onSubmit={(event) => {
                                    event.preventDefault();
                                    void submit("DISPLAY");
                                }}
                            >
                                <fieldset disabled={blocked || needsReload}>
                                    <label>
                                        因子名称
                                        <input
                                            required
                                            maxLength={100}
                                            value={names.display_name}
                                            onChange={(event) => {
                                                setNames({
                                                    ...names,
                                                    display_name: event.target.value
                                                });
                                            }}
                                        />
                                    </label>
                                    <label>
                                        用途说明
                                        <textarea
                                            required
                                            maxLength={1000}
                                            value={names.usage_summary}
                                            onChange={(event) => {
                                                setNames({
                                                    ...names,
                                                    usage_summary: event.target.value
                                                });
                                            }}
                                        />
                                    </label>
                                    <p>名称和用途不改变计算内容或已发布版本。</p>
                                    {state === null ? (
                                        <p>首次保存草稿时一并保存名称和用途。</p>
                                    ) : (
                                        <button type="submit">保存名称和用途</button>
                                    )}
                                </fieldset>
                            </form>
                            <p>
                                {state?.revisions.at(-1)
                                    ? `当前第 ${String(state.revisions.at(-1)?.display_version)} 版；编辑内容需另行保存和发布。`
                                    : "尚未发布内容版本"}
                            </p>
                            <form
                                onSubmit={(event) => {
                                    event.preventDefault();
                                    void submit("SAVE");
                                }}
                            >
                                <fieldset disabled={blocked || needsReload}>
                                    <details>
                                        <summary>版本技术信息</summary>
                                        <label>
                                            版本内容说明
                                            <textarea
                                                value={draft.description}
                                                onChange={(event) => {
                                                    setDraft({
                                                        ...draft,
                                                        description: event.target.value
                                                    });
                                                }}
                                            />
                                        </label>
                                        <p>此说明随内容版本冻结，与当前名称、用途独立。</p>
                                        <label>
                                            语义版本
                                            <input
                                                required
                                                pattern="[1-9][0-9]*"
                                                value={draft.semantic_version}
                                                onChange={(event) => {
                                                    setDraft({
                                                        ...draft,
                                                        semantic_version: event.target.value
                                                    });
                                                }}
                                            />
                                        </label>
                                        <label>
                                            类别
                                            <input
                                                required
                                                value={draft.category}
                                                onChange={(event) => {
                                                    setDraft({
                                                        ...draft,
                                                        category: event.target.value
                                                    });
                                                }}
                                            />
                                        </label>
                                        <label>
                                            经济依据
                                            <textarea
                                                value={draft.economic_rationale}
                                                onChange={(event) => {
                                                    setDraft({
                                                        ...draft,
                                                        economic_rationale: event.target.value
                                                    });
                                                }}
                                            />
                                        </label>
                                    </details>
                                    <label>
                                        Python 源码
                                        <textarea
                                            required
                                            spellCheck={false}
                                            rows={7}
                                            value={draft.source_text}
                                            onChange={(event) => {
                                                setDraft({
                                                    ...draft,
                                                    source_text: event.target.value
                                                });
                                            }}
                                        />
                                    </label>
                                    {contracts.map((key) => (
                                        <ContractEditor
                                            key={`${draft.factor_id}:${String(contractEpoch)}:${key}`}
                                            kind={key}
                                            value={raw[key]}
                                            onChange={(text) => {
                                                setRaw((previous) => ({
                                                    ...previous,
                                                    [key]: text
                                                }));
                                            }}
                                            onValidity={contractValidity}
                                        />
                                    ))}
                                    <p>
                                        此处检查填写格式；保存或发布不代表源码已执行或计算结果已验证。
                                    </p>
                                    <label>
                                        标签（逗号分隔）
                                        <input
                                            value={tagsText}
                                            onChange={(event) => {
                                                setTagsText(event.target.value);
                                            }}
                                        />
                                    </label>
                                    <button type="submit">保存草稿</button>
                                    <button
                                        type="button"
                                        disabled={
                                            dirty ||
                                            Object.values(contractErrors).some(Boolean) ||
                                            state?.draft_fingerprint == null
                                        }
                                        onClick={() => {
                                            void submit("PUBLISH");
                                        }}
                                    >
                                        发布内容版本
                                    </button>
                                    {dirty && <p>有未保存的修改，请先保存草稿再发布。</p>}
                                </fieldset>
                            </form>
                            {needsReload && (
                                <button
                                    type="button"
                                    disabled={blocked}
                                    onClick={() => {
                                        void choose(draft.factor_id);
                                    }}
                                >
                                    重新载入已保存内容
                                </button>
                            )}
                            {state !== null && !needsReload && (
                                <>
                                    <button
                                        type="button"
                                        disabled={blocked}
                                        onClick={() => {
                                            void choose(state.factor_id);
                                        }}
                                    >
                                        重新载入已保存内容
                                    </button>
                                    <h3>内容版本历史</h3>
                                    {state.revisions.length === 0 ? (
                                        <p>尚未发布内容版本。</p>
                                    ) : (
                                        <ol>
                                            {state.revisions.map((item) => (
                                                <li key={item.revision.revision_fingerprint}>
                                                    <button
                                                        type="button"
                                                        onClick={() => {
                                                            setHistorical(item);
                                                        }}
                                                    >
                                                        查看第 {item.display_version} 版
                                                    </button>
                                                </li>
                                            ))}
                                        </ol>
                                    )}
                                </>
                            )}
                            {historical !== null && (
                                <section aria-label="历史内容版本">
                                    <h4>第 {historical.display_version} 版</h4>
                                    <pre>{historical.revision.source_text}</pre>
                                    <details>
                                        <summary>精确身份</summary>
                                        <p>算法语义版本 {historical.revision.semantic_version}</p>
                                        <p>版本内容说明：{historical.revision.description}</p>
                                        <code>{historical.revision.revision_fingerprint}</code>
                                    </details>
                                </section>
                            )}
                        </section>
                    )}
                </div>
            </dialog>
        </>
    );
}
