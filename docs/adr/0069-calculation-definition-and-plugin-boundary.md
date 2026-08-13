# ADR 0069: Calculation Definition Authority and Plugin Boundary

Status: Accepted

Date: 2026-08-13

## Context

Trading 原先用 `OnlyIndicatorSpec`、legacy type token 和 Core-owned factory 描述并创建 Indicator。semantic defaults、
warmup、missing/timestamp/numeric/output contract 隐含在 concrete class 中，Factor definition 也与 mutable Trading
lifecycle 混合。这不能为未来 Research backend、Calculation Store 或跨进程复用提供唯一 identity。

## Decision

Core owns immutable Runtime-independent Calculation semantics：stable dotted `type_id`、`semantic_version`、typed parameter
schema/default normalization、input contract/binding、output schema、warmup、missing value、timestamp 和 numeric semantics。
canonical payload 使用共享 `onlyalpha.canonical` authority 并以 SHA-256 fingerprint；alias、class path、filesystem、时间、
UUID 和 Runtime identity 均排除。

`OnlyCalculationGraphDefinition` 是 canonical DAG，显式校验 dependency、cycle、output 和 data-type/nullability compatibility。
semantic node fingerprint 是 node identity；alias 只属于 presentation。

Registry 以 `kind + type_id + semantic_version + backend` exact resolve。unknown type/version/backend、duplicate 和 invalid
registration fail closed，不选择 latest、不 backend fallback。P7.0 只注册真实 TRADING backend。

Core owns contracts, plugins own concrete algorithms. `onlyalpha-plugin-indicators` 拥有原有九个 Indicator backend；
`onlyalpha-plugin-factors` 建立官方扩展点但不虚构 Factor。entry point group 是 `onlyalpha.calculations`，稳定排序沿用现有
discovery。Core composition root 只提供 Registry，不 import plugin。旧 Core concrete implementation 一次性删除，无 shim。

Trading config remains an input DTO. Composition resolves defaults into a Definition, validates a Graph and resolves the exact
TRADING backend before constructing mutable Runtime instances. Existing Decimal math, ready/warmup, duplicate/out-of-order,
timestamp, snapshot and checkpoint payload semantics remain unchanged.

## Consequences

Future Research may implement a different batch interface for the same semantic version. It must not redefine semantics or claim
availability until a real backend exists. Concrete snapshot DTOs are plugin API because output shape belongs to algorithm semantic
versions; Core retains generic output contracts and base snapshot protocols.

Architecture gates forbid Core imports of calculation plugins and forbid calculation semantic modules from Runtime, Cluster,
Account, Broker, Order, Position and Transaction authorities.
