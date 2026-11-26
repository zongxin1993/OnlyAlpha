//! Deterministic WebAssembly (L3) plugin host, versioned WIT contract verifier, automatic
//! dual-kernel extended operator certifier, and runtime hot-load/hot-unload manager.
//!
//! Architecture authority: ADR 0152 (§2.5, §2.6, Phase 2).
//!
//! - Zero WASI ambient capabilities (no clock, random, filesystem, network, process, or env).
//! - Explicit per-call fuel and linear-memory budgets with Fail-Closed trap isolation.
//! - Automatic `Vector == Event`, multi-prefix causality, warmup/null, and snapshot capture/restore
//!   admission certification before any extended operator enters READY state.
//! - Exact `.wasm` SHA-256, WIT contract version, and parameter binding verification for replay.

pub mod certification;
pub mod config;
pub mod contract;
pub mod manager;
pub mod market_rule_plugin;
pub mod operator_plugin;
pub mod sandbox;
pub mod strategy_plugin;

pub use certification::{CertificationRequest, GoldenCase};
pub use config::{
    HARD_MAX_ARTIFACT_BYTES, HARD_MAX_CERTIFICATION_FUEL, HARD_MAX_FUEL_PER_CALL,
    HARD_MAX_HOST_LIFT_BYTES, HARD_MAX_INSTANCES, HARD_MAX_MEMORIES, HARD_MAX_MEMORY_BYTES,
    HARD_MAX_OUTPUT_ITEMS, HARD_MAX_SNAPSHOT_BYTES, HARD_MAX_TABLE_ELEMENTS, HARD_MAX_TABLES,
    HostMetricsSnapshot, MIN_HOST_LIFT_BYTES, MIN_MEMORY_BYTES, ResourceBudget, WasmHostEngine,
};
pub use contract::{
    ArtifactBinding, CallOutcome, EXTENDED_OPERATOR_INTERFACE, Error, HOST_RUNTIME_VERSION,
    MARKET_RULE_INTERFACE, MAX_CANONICAL_PARAMETERS, MAX_DECIMAL_PRECISION, MAX_DECIMAL_SCALE,
    MAX_PARAMETER_KEY_BYTES, MAX_PARAMETER_VALUE_BYTES, MarketRuleDecision, MarketRuleInput,
    MarketRuleMetadata, NUMERIC_POLICY, NamedFactor, OperatorMetadata, OrderIntent, OrderSide,
    OrderType, PluginKind, ReadonlyAccountState, ReadonlyPosition, ReadyCertificate, Result,
    STRATEGY_INTERFACE, StrategyMetadata, TimeInForce, WIT_CONTRACT_VERSION, is_valid_sha256_hex,
    sha256_hex,
};
pub use manager::{LoadedPluginSummary, UnloadReceipt, WasmPluginManager};
pub use market_rule_plugin::WasmMarketRulePlugin;
pub use operator_plugin::{
    MAX_OPERATOR_ARITY, MAX_OPERATOR_WARMUP, MAX_VECTOR_CELLS, WasmExtendedOperator,
    WasmOperatorStream,
};
pub use strategy_plugin::WasmStrategyPlugin;

#[cfg(test)]
mod tests {
    mod sandbox_and_manager_tests;
    mod wit_contract_tests;
}
