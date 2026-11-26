//! Deterministic Wasmtime engine configuration, resource budgets, and linear memory tracking.

use crate::contract::{Error, Result};
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use wasmtime::{Config, Engine, ResourceLimiter};

/// Minimum allowed linear memory budget: one 64 KiB WebAssembly memory page.
pub const MIN_MEMORY_BYTES: usize = 64 * 1024;
/// Hard ceiling on linear memory budget per WASM store (256 MiB).
pub const HARD_MAX_MEMORY_BYTES: usize = 256 * 1024 * 1024;
/// Hard ceiling on `.wasm` artifact size (32 MiB).
pub const HARD_MAX_ARTIFACT_BYTES: usize = 32 * 1024 * 1024;
/// Minimum allowed host-side Component Model lifting memory budget per call (64 KiB).
pub const MIN_HOST_LIFT_BYTES: usize = 64 * 1024;
/// Hard ceiling on host-side Component Model lifting memory budget per call (32 MiB).
pub const HARD_MAX_HOST_LIFT_BYTES: usize = 32 * 1024 * 1024;
/// Hard ceiling on serialized event-kernel snapshot size (512 KiB).
pub const HARD_MAX_SNAPSHOT_BYTES: usize = 512 * 1024;
/// Hard ceiling on output items (rows or order intents) per call.
pub const HARD_MAX_OUTPUT_ITEMS: usize = 100_000;
/// Hard ceiling on table elements per WASM store.
pub const HARD_MAX_TABLE_ELEMENTS: usize = 65_536;
/// Hard ceiling on core module instances per WASM store.
pub const HARD_MAX_INSTANCES: usize = 64;
/// Hard ceiling on tables per WASM store.
pub const HARD_MAX_TABLES: usize = 64;
/// Hard ceiling on linear memories per WASM store.
pub const HARD_MAX_MEMORIES: usize = 16;
/// Hard ceiling on per-call fuel budget.
pub const HARD_MAX_FUEL_PER_CALL: u64 = 100_000_000;
/// Hard ceiling on cumulative fuel across one extended-operator certification run.
pub const HARD_MAX_CERTIFICATION_FUEL: u64 = 500_000_000;

/// Explicit sandbox resource limits enforced on every L3 WASM plugin call.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ResourceBudget {
    /// Maximum linear memory bytes a single WASM store may allocate.
    pub max_memory_bytes: usize,
    /// Maximum table elements per WASM store.
    pub max_table_elements: usize,
    /// Maximum core module instances per WASM store.
    pub max_instances: usize,
    /// Maximum tables per WASM store.
    pub max_tables: usize,
    /// Maximum linear memories per WASM store.
    pub max_memories: usize,
    /// Deterministic instruction fuel budget granted per host-to-guest call.
    pub max_fuel_per_call: u64,
    /// Cumulative instruction fuel budget across all calls in one admission certification.
    pub max_certification_fuel: u64,
    /// Maximum accepted `.wasm` component artifact size in bytes.
    pub max_artifact_bytes: usize,
    /// Maximum host-side bytes Wasmtime may lift from guest linear memory in one call.
    pub max_host_lift_bytes: usize,
    /// Maximum serialized event-kernel snapshot size in bytes.
    pub max_snapshot_bytes: usize,
    /// Maximum number of output elements (column rows or order intents) per call.
    pub max_output_items: usize,
}

impl Default for ResourceBudget {
    fn default() -> Self {
        Self {
            max_memory_bytes: 16 * 1024 * 1024,
            max_table_elements: 10_000,
            max_instances: 16,
            max_tables: 16,
            max_memories: 4,
            max_fuel_per_call: 10_000_000,
            max_certification_fuel: 50_000_000,
            max_artifact_bytes: 16 * 1024 * 1024,
            max_host_lift_bytes: 16 * 1024 * 1024,
            max_snapshot_bytes: 256 * 1024,
            max_output_items: 100_000,
        }
    }
}

impl ResourceBudget {
    pub fn validate(&self) -> Result<()> {
        if self.max_memory_bytes < MIN_MEMORY_BYTES || self.max_memory_bytes > HARD_MAX_MEMORY_BYTES
        {
            return Err(Error::InvalidBudget(format!(
                "max_memory_bytes must be within [{MIN_MEMORY_BYTES}, {HARD_MAX_MEMORY_BYTES}]"
            )));
        }
        if self.max_table_elements == 0 || self.max_table_elements > HARD_MAX_TABLE_ELEMENTS {
            return Err(Error::InvalidBudget(format!(
                "max_table_elements must be within [1, {HARD_MAX_TABLE_ELEMENTS}]"
            )));
        }
        if self.max_instances == 0 || self.max_instances > HARD_MAX_INSTANCES {
            return Err(Error::InvalidBudget(format!(
                "max_instances must be within [1, {HARD_MAX_INSTANCES}]"
            )));
        }
        if self.max_tables == 0 || self.max_tables > HARD_MAX_TABLES {
            return Err(Error::InvalidBudget(format!(
                "max_tables must be within [1, {HARD_MAX_TABLES}]"
            )));
        }
        if self.max_memories == 0 || self.max_memories > HARD_MAX_MEMORIES {
            return Err(Error::InvalidBudget(format!(
                "max_memories must be within [1, {HARD_MAX_MEMORIES}]"
            )));
        }
        if self.max_fuel_per_call == 0 || self.max_fuel_per_call > HARD_MAX_FUEL_PER_CALL {
            return Err(Error::InvalidBudget(format!(
                "max_fuel_per_call must be within [1, {HARD_MAX_FUEL_PER_CALL}]"
            )));
        }
        if self.max_certification_fuel == 0
            || self.max_certification_fuel > HARD_MAX_CERTIFICATION_FUEL
        {
            return Err(Error::InvalidBudget(format!(
                "max_certification_fuel must be within [1, {HARD_MAX_CERTIFICATION_FUEL}]"
            )));
        }
        if self.max_artifact_bytes == 0 || self.max_artifact_bytes > HARD_MAX_ARTIFACT_BYTES {
            return Err(Error::InvalidBudget(format!(
                "max_artifact_bytes must be within [1, {HARD_MAX_ARTIFACT_BYTES}]"
            )));
        }
        if self.max_host_lift_bytes < MIN_HOST_LIFT_BYTES
            || self.max_host_lift_bytes > HARD_MAX_HOST_LIFT_BYTES
        {
            return Err(Error::InvalidBudget(format!(
                "max_host_lift_bytes must be within [{MIN_HOST_LIFT_BYTES}, {HARD_MAX_HOST_LIFT_BYTES}]"
            )));
        }
        if self.max_snapshot_bytes == 0 || self.max_snapshot_bytes > HARD_MAX_SNAPSHOT_BYTES {
            return Err(Error::InvalidBudget(format!(
                "max_snapshot_bytes must be within [1, {HARD_MAX_SNAPSHOT_BYTES}]"
            )));
        }
        if self.max_output_items == 0 || self.max_output_items > HARD_MAX_OUTPUT_ITEMS {
            return Err(Error::InvalidBudget(format!(
                "max_output_items must be within [1, {HARD_MAX_OUTPUT_ITEMS}]"
            )));
        }
        Ok(())
    }
}

/// Snapshot of deterministic host lifecycle and memory-reclamation counters.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct HostMetricsSnapshot {
    pub total_loads: u64,
    pub total_unloads: u64,
    pub active_plugins: usize,
    pub active_stores: usize,
    pub live_linear_memory_bytes: usize,
    pub peak_linear_memory_bytes: usize,
    pub total_fuel_consumed: u64,
    pub total_traps_isolated: u64,
}

/// Shared atomic counters proving deterministic store creation, bounding, and memory reclamation.
#[derive(Debug, Default)]
pub struct HostMetrics {
    total_loads: AtomicU64,
    total_unloads: AtomicU64,
    active_plugins: AtomicUsize,
    active_stores: AtomicUsize,
    live_linear_memory_bytes: AtomicUsize,
    peak_linear_memory_bytes: AtomicUsize,
    total_fuel_consumed: AtomicU64,
    total_traps_isolated: AtomicU64,
}

impl HostMetrics {
    pub fn snapshot(&self) -> HostMetricsSnapshot {
        HostMetricsSnapshot {
            total_loads: self.total_loads.load(Ordering::Acquire),
            total_unloads: self.total_unloads.load(Ordering::Acquire),
            active_plugins: self.active_plugins.load(Ordering::Acquire),
            active_stores: self.active_stores.load(Ordering::Acquire),
            live_linear_memory_bytes: self.live_linear_memory_bytes.load(Ordering::Acquire),
            peak_linear_memory_bytes: self.peak_linear_memory_bytes.load(Ordering::Acquire),
            total_fuel_consumed: self.total_fuel_consumed.load(Ordering::Acquire),
            total_traps_isolated: self.total_traps_isolated.load(Ordering::Acquire),
        }
    }

    pub(crate) fn record_plugin_loaded(&self) {
        self.total_loads.fetch_add(1, Ordering::AcqRel);
        self.active_plugins.fetch_add(1, Ordering::AcqRel);
    }

    pub(crate) fn record_plugin_unloaded(&self) {
        self.total_unloads.fetch_add(1, Ordering::AcqRel);
        self.active_plugins.fetch_sub(1, Ordering::AcqRel);
    }

    pub(crate) fn record_store_created(&self) {
        self.active_stores.fetch_add(1, Ordering::AcqRel);
    }

    pub(crate) fn record_store_dropped(&self, tracked_memory_bytes: usize) {
        if tracked_memory_bytes > 0 {
            self.live_linear_memory_bytes
                .fetch_sub(tracked_memory_bytes, Ordering::AcqRel);
        }
        self.active_stores.fetch_sub(1, Ordering::AcqRel);
    }

    pub(crate) fn record_memory_allocated(&self, delta: usize) {
        if delta == 0 {
            return;
        }
        let now = self
            .live_linear_memory_bytes
            .fetch_add(delta, Ordering::AcqRel)
            + delta;
        self.peak_linear_memory_bytes
            .fetch_max(now, Ordering::AcqRel);
    }

    pub(crate) fn record_memory_released(&self, delta: usize) {
        if delta == 0 {
            return;
        }
        self.live_linear_memory_bytes
            .fetch_sub(delta, Ordering::AcqRel);
    }

    pub(crate) fn record_fuel(&self, fuel: u64) {
        self.total_fuel_consumed.fetch_add(fuel, Ordering::AcqRel);
    }

    pub(crate) fn record_trap_isolated(&self) {
        self.total_traps_isolated.fetch_add(1, Ordering::AcqRel);
    }
}

/// Deterministic Wasmtime engine configured according to ADR 0152.
///
/// - Enables WebAssembly Component Model and deterministic fuel metering.
/// - Enables Cranelift NaN canonicalization for cross-platform bit-exact determinism.
/// - Disables threads, relaxed SIMD, memory64, epoch interruption, and debug info.
/// - Links zero WASI capabilities.
#[derive(Debug)]
pub struct WasmHostEngine {
    engine: Engine,
    metrics: Arc<HostMetrics>,
}

impl WasmHostEngine {
    pub fn new() -> Result<Self> {
        let mut config = Config::new();
        config.wasm_component_model(true);
        config.consume_fuel(true);
        config.cranelift_nan_canonicalization(true);
        // `threads` feature is excluded at compile time in Cargo.toml.
        config.wasm_relaxed_simd(false);
        config.wasm_memory64(false);
        config.epoch_interruption(false);
        config.debug_info(false);
        let engine =
            Engine::new(&config).map_err(|err| Error::HostInitialization(err.to_string()))?;
        Ok(Self {
            engine,
            metrics: Arc::new(HostMetrics::default()),
        })
    }

    pub fn metrics(&self) -> HostMetricsSnapshot {
        self.metrics.snapshot()
    }

    pub(crate) fn engine(&self) -> &Engine {
        &self.engine
    }

    pub(crate) fn metrics_handle(&self) -> Arc<HostMetrics> {
        Arc::clone(&self.metrics)
    }
}

/// Per-store resource limiter and linear memory lifecycle tracker.
pub(crate) struct SandboxState {
    budget: ResourceBudget,
    metrics: Arc<HostMetrics>,
    tracked_memory_bytes: usize,
    pending_memory_delta: usize,
    memory_limit_exceeded: bool,
}

impl SandboxState {
    pub(crate) fn new(budget: ResourceBudget, metrics: Arc<HostMetrics>) -> Self {
        metrics.record_store_created();
        Self {
            budget,
            metrics,
            tracked_memory_bytes: 0,
            pending_memory_delta: 0,
            memory_limit_exceeded: false,
        }
    }

    pub(crate) fn reset_call_flags(&mut self) {
        self.memory_limit_exceeded = false;
        self.pending_memory_delta = 0;
    }

    pub(crate) fn memory_limit_exceeded(&self) -> bool {
        self.memory_limit_exceeded
    }

    pub(crate) fn tracked_memory_bytes(&self) -> usize {
        self.tracked_memory_bytes
    }

    pub(crate) fn budget(&self) -> ResourceBudget {
        self.budget
    }
}

impl Drop for SandboxState {
    fn drop(&mut self) {
        self.metrics.record_store_dropped(self.tracked_memory_bytes);
        self.tracked_memory_bytes = 0;
        self.pending_memory_delta = 0;
    }
}

impl ResourceLimiter for SandboxState {
    fn memory_growing(
        &mut self,
        current: usize,
        desired: usize,
        maximum: Option<usize>,
    ) -> wasmtime::Result<bool> {
        // Guest module's own declared maximum does not breach the host's ResourceBudget.
        if let Some(max) = maximum
            && desired > max
        {
            self.pending_memory_delta = 0;
            return Ok(false);
        }
        let delta = desired.saturating_sub(current);
        let next_total = self.tracked_memory_bytes.saturating_add(delta);
        if desired > self.budget.max_memory_bytes || next_total > self.budget.max_memory_bytes {
            self.pending_memory_delta = 0;
            self.memory_limit_exceeded = true;
            return Ok(false);
        }
        self.pending_memory_delta = delta;
        self.tracked_memory_bytes = next_total;
        self.metrics.record_memory_allocated(delta);
        Ok(true)
    }

    fn memory_grow_failed(&mut self, _error: wasmtime::Error) -> wasmtime::Result<()> {
        let delta = std::mem::take(&mut self.pending_memory_delta);
        if delta > 0 {
            self.tracked_memory_bytes = self.tracked_memory_bytes.saturating_sub(delta);
            self.metrics.record_memory_released(delta);
        }
        Ok(())
    }

    fn table_growing(
        &mut self,
        _current: usize,
        desired: usize,
        maximum: Option<usize>,
    ) -> wasmtime::Result<bool> {
        if let Some(max) = maximum
            && desired > max
        {
            return Ok(false);
        }
        Ok(desired <= self.budget.max_table_elements)
    }

    fn instances(&self) -> usize {
        self.budget.max_instances
    }

    fn tables(&self) -> usize {
        self.budget.max_tables
    }

    fn memories(&self) -> usize {
        self.budget.max_memories
    }
}
