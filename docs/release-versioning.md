# Release units and compatibility

[ADR 0142](adr/0142-library-product-boundaries-and-independent-releases.md) records the original owner-selected release model,
updated by [ADR 0150](adr/0150-product-layout-and-programmable-quant-assets.md);
[repository architecture](repository-product-architecture.md) defines ownership. AGENTS.md governs execution/validation.
This document explains release policy, not implementation status or a second version/acceptance ledger.

## Independent metadata authorities

Keep one repository and root Cargo workspace; independent versions do not require independent repositories or a lock per worker.

| Release unit | Single version metadata authority after cutover | Tag |
|---|---|---|
| Reusable Rust libraries | Root `Cargo.toml` workspace package version, inherited by the selected library set | `libs-vX.Y.Z` |
| Frontend | `packages/frontend/package.json`; lock root must match | `frontend-vX.Y.Z` |
| Concrete plugin distribution | Its own package metadata; multi-language projections of one distribution derive from one selected authority | unambiguous `plugin-<name>-v<distribution-version>` |

当前发行单元为 Rust 基础库、前端和独立插件。原 Backend 发行线已退役，既有发行身份和工件保持不可变。

SemVer release lines use actual declared support/compatibility boundaries and ADR 0130 breaking-change classification. During
`0.y.z`, classify all changes explicitly and do not pretend initial development means permanent patch compatibility. Major-zero
breaking public changes advance minor rather than being hidden as patch; stable supported breaking changes require major,
compatible public additions minor, compatible fixes patch. First versions for the new lines require checking actual published
history; example version numbers in discussions do not assign them. Private asset/provider versions retain ADR 0115, including
positive-integer semantic/provider identities and existing private distribution rules rather than forced SemVer conversion.

Only selected changed release units advance. A source PR may change multiple units in one atomic commit; unrelated units and
pure documentation changes do not force a release. An actual release requires explicit selection and authorized publication,
not every mainline merge. Do not create a version registry duplicating package metadata or an automatic post-merge version commit.
Tags, versions and artifact identities are immutable. Exact reruns may finish/reuse the same matching publication; conflicting
content, tag targets, unknown boundaries or ambiguous existing publication fail closed without overwrite or tag movement.

## Source and dependency locking

开发依赖使用实际 workspace 路径及各工程提交的锁文件。同版本的路径依赖也须核对源码字节。正式构建须满足以下要求。

1. Select exact released library/plugin source artifacts and their immutable content identity; verify all relevant source,
   manifests, generated inputs, resources and build configuration in their dependency closures, excluding credentials.
2. Verify the actual source used in the frozen build equals that selected content. Same version plus changed source is a failure.
   A new library change requires a new selected library release before backend can formally claim it.
3. Bind dependency locks/registry checksums, compiler/toolchain, target, profile, features and relevant non-secret configuration.
   Preserve isolated package/dependency proofs and reject undesired feature/registry changes; no automatic latest resolution.
4. Build/install from those exact inputs and record actual artifact bytes and provenance through existing artifact manifests.
   Source-only tags are not proof of a correctly built binary/Python environment.

Start with immutable source bundles and content verification, without a private Cargo registry. Source/build provenance extends
existing Distribution Artifact records where needed; it is not another work-binding or activation Authority. A path/registry URL
is an operational locator, never semantic identity. Artifact retention/availability is independently required by bound history.

新插件发布只建立该发行单元的工件，采用它的宿主还须精确选择并验证实际装配内容。旧 Backend Python 基座、SDK wheel 与应用镜像已退役。独立插件的运行环境与依赖仍须按各自的发行工件锁定。
Private Factor/Strategy Draft/Revision remains DB-native under ADR 0129. Exact algorithm plugins and materialized Revisions enter
isolated environments through existing artifact/Catalog/Generation admission. Keep base runtime and author code identities
separate; changing a Factor does not require a backend release. Retain the original exact environment for already-bound work.

## Compatibility and activation

| Domain | Governing rule |
|---|---|
| Frontend/backend | Default tested combination; different versions allowed only for explicitly verified Product API combinations. Clear unsupported UI/startup feedback, no guessing or fallback. No arbitrary mixed-version or rolling-upgrade promise. |
| Libraries/backend/plugins | Exact build selection plus public API/SPI/capability checks. Equal versions alone do not prove compatibility; independent versions alone do not prove incompatibility. |
| Provider/Calculation/private assets | Existing semantic version, Provider content, implementation fingerprint, Catalog and StrategyRevision authorities; software releases do not rewrite them. |
| Persistence/checkpoints | Owning schema, integrity and recovery contracts; apply supported history/upgrade gates. Disposable local dev data follows AGENTS.md, not a fabricated migration PASS. |
| Runtime/deployment | Actual artifact/image content, source provenance and immutable Generation/work binding. Fixed `:dev` tags are convenience, not execution identity. |

Release publication, deployment, Generation activation and LIVE authorization are separate. New-work activation/rollback uses
the sole existing Generation ledger; running work is never rebound to the current pointer. Preserve exact history/readers,
UNKNOWN and risk-reduction paths. A smaller version string does not prove a persistence downgrade safe. Do not introduce shims
for retired development versions or new legacy loaders; actual supported contract obligations still apply.

## 发行选择与证据

按实际清单选择发行单元并核对版本变更。当前没有 Backend 发行清单、安装程序或可验证的前后端发行组合。
PR selection uses explicit labels such as `release:frontend:patch` or `release:plugin-binance:minor`. No label means no release;
selected units must equal changed version units. Multiple units can select their own level. Minor/major retains explicit human
Owner label-action proof; generic approval or a later post-merge label does not authorize an earlier transition. Validate exact
current base/head and strictly ordered historical events before the exact merge. Actual transitions are reported even when
historical authorization proof is unavailable. Unknown/conflicting labels and stale/skipped/downgraded versions fail closed.

发行负责人从 GitHub REST API 读取仓库元数据、目标 PR 和该 PR 对应的全部分页 issue events。
将原始对象分别放入 `release-context.json` 的 `repository`、`pull_request` 和 `events` 字段；
`events` 保留按 ID 严格递增的 `labeled`、`unlabeled`、`merged` 原始事件，不手工补造、改写或省略历史。
将文件放在源码树外或固定验证环境的 `test-results/` 下，不提交文件或凭据。
合并前核对当前源码等于 PR 的 `head.sha`，且包含远端当前 `master` 的精确 SHA；以该 SHA 作为 `EXACT_BASE`。
合并后依据实际合并提交与对应事件核对历史授权。
任一来源不全、身份不符或无法确认时停止发行；当前标签或人工重写的输入不能补足历史证据。

### 不可变源码和构建输入

候选源码工件必须绑定所选单元、精确提交、实际内容摘要和权限位。若引用标签，应核对标签已存在且指向该提交与版本。构建前后复核全部非秘密输入、工具链、目标、profile 和 feature 的冻结选择。
The ZIP uses sorted entries, fixed metadata/timestamps and no compression. Its canonical manifest records the unit/version,
commit/tag, file hashes and exact execution bits. Same inputs yield identical bytes. Consumption verifies the selected SHA-256,
canonical archive, complete payload and actual frozen unit source; it never extracts archive paths into the working tree.
Links, duplicate/escaping paths, missing/extra payload and same-version source drift fail closed.

依照实际依赖闭包清点编译资源、协议、许可、锁文件及工具配置。源归档的身份必须与最终工件、实际使用的源码、构建回执相互印证。历史 Backend 与算法安装环境按原始发行证据解释，不能将当前仓库重建物冒充原工件。

产品服务重建后，正式组合还须绑定前后端各自选定的版本、实际二进制和 Web 内容摘要，核对 HTTP 与 WebSocket 契约以及真实运行的兼容性。发行、安装、Generation 激活和实盘权限各自需要对应证据。

## 已退役市场插件

Generic T0 Cash 的 Python 发行单元 `plugin-generic-t0-cash` 已停止参与当前 workspace、CI 与新发行。
发行清单仅接受该单元的精确退役；其他单元的新增、删除或连带移除仍须独立批准。
既有版本、标签、源码归档、wheel、manifest 和历史身份不因此改写或覆盖。
历史发行元数据与源码应按原提交或原快照校验；当前源码清单不能替代历史基线。
运行恢复继续读取原 Generation 绑定的确切工件，缺失或不匹配时拒绝恢复，不从当前源码重建退役插件。
