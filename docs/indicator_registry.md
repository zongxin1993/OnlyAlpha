# Indicator Factory Registry

`OnlyIndicatorFactoryRegistry` 以可扩展 `OnlyIndicatorTypeId` 为键。内置 ID 使用大写规范；包含点的第三方 ID 规范化为小写。重复注册和未知类型均 Fail Fast。

创建请求包含 type、local indicator ID、BarType 和参数。空参数使用具体 Config 默认值，非空参数覆盖默认值。Factor-scoped `OnlyIndicatorRegistry` 用以下完整键保存实例：

```text
runtime_id / cluster_id / factor_id / indicator_id
```

相同 local ID 可在不同 Cluster 或 Factor 使用，但可变实例绝不共享。Factor 拥有创建能力；Strategy 只有 Factor View；Runtime/Assembly 不识别具体算法。

## Rust scoped calculation state and readiness boundary

The Rust `calculation` library owns the cursor and immutable last-result projection through `CalculationState`.
Its explicit outcomes are UNINITIALIZED, WARMING, READY, FAILED, UNAVAILABLE and UNKNOWN; `ready` remains a producer fact.
Failed/uncertain state cannot accept new work without explicit reset or fresh exact restore. Snapshots retain previous
committed outputs for diagnosis, never as proof that a failed/current input succeeded. Records strictly validate the complete
binding, cursor/result relationship, tagged scalar outputs, quality flags, outcome and reason before atomic replacement.

`ReadinessPlan` is a pure instance dependency barrier, not a Factor/Strategy executor. Each evaluation must supply an expected
revision, sample position, event nanoseconds and exact batch input digest for every registered instance. Different timeframes
have separate explicit expectations. Missing, stale, warming, unavailable, failed, UNKNOWN or dependency-blocked required nodes
prevent readiness. An optional dependency still blocks its required consumer; unrelated optional non-readiness is visible as
degradation. Foreign/mixed-generation bindings, duplicate/missing dependencies, cycles and incomplete expectation context fail.
A READY barrier is not Source/Generation admission, complete historical input proof, Research Evidence or execution permission.

The worker Rust adapter consumes this state and owns a schema2 checkpoint bundle pairing native worker schema1 bytes and the
Rust state record under one caller-expected SHA-256. Native algorithm output, cursor and local snapshot relations are validated;
restore installs local state only after exact worker acknowledgment. A cancellation or poisoned process withdraws current
snapshots as UNKNOWN, including before the next request. No old-envelope fallback, official checkpoint participant, durable store
or Runtime activation is introduced. See the [state design](superpowers/specs/2026-10-18-rust-calculation-state-design.md).
