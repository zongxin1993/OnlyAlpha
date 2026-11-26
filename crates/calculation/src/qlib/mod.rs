//! Qlib-style declarative expression parser, static causal validator, and dual-mode DAG executor.
//!
//! Top-level expressions are strictly separated at compile time:
//! - [`FactorExpr`]: causal factors usable in Research, Backtest, SIM, and LIVE.
//!   Any look-ahead offset (`Ref($x, -n)`, `Lead($x, n)`) or non-market account/execution/clock
//!   input is rejected statically during compilation.
//! - [`TargetExpr`]: Research-only evaluation labels that may declare explicit bounded forward
//!   look-ahead (`Ref($x, -n)` / `Lead($x, n)`). By type construction, [`TargetExpr`] exposes
//!   vector/panel Research evaluation only and cannot construct an [`EventExecutor`] or be passed
//!   where a [`FactorExpr`] is required.

mod compile;
mod execute;
mod parser;

pub use compile::{
    CompareOp, ExprKind, Instruction, MAX_DAG_NODES, MAX_INPUT_FIELDS, ResourceEstimate,
};
pub use execute::{DagState, EventExecutor, PanelDagState, PanelEventExecutor};
pub use parser::{MAX_CALL_ARGS, MAX_EXPR_BYTES, MAX_EXPR_DEPTH, MAX_IDENT_LEN};

use crate::Result;
use compile::CompiledDag;
use onlyalpha_operators::algebra::Decimal;
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

/// Statically verified causal factor expression compiled to a deduplicated operator DAG.
#[derive(Clone, Debug)]
pub struct FactorExpr {
    dag: Arc<CompiledDag>,
}

impl FactorExpr {
    pub fn compile(source: &str) -> Result<Self> {
        Ok(Self {
            dag: Arc::new(compile::compile(source, ExprKind::Factor, None)?),
        })
    }

    pub fn compile_with_allowed_fields(source: &str, allowed: &BTreeSet<String>) -> Result<Self> {
        Ok(Self {
            dag: Arc::new(compile::compile(source, ExprKind::Factor, Some(allowed))?),
        })
    }

    pub fn source(&self) -> &str {
        &self.dag.source
    }

    pub fn canonical(&self) -> &str {
        &self.dag.canonical
    }

    pub fn fingerprint(&self) -> &str {
        &self.dag.fingerprint
    }

    pub fn inputs(&self) -> &BTreeSet<String> {
        &self.dag.inputs
    }

    pub fn operator_ids(&self) -> &BTreeSet<String> {
        &self.dag.operator_ids
    }

    pub fn minimum_observations(&self) -> usize {
        self.dag.budget.minimum_observations
    }

    pub fn has_cross_section(&self) -> bool {
        self.dag.has_cross_section
    }

    pub fn supports_event_execution(&self) -> bool {
        !self.dag.has_cross_section
    }

    pub fn node_count(&self) -> usize {
        self.dag.budget.node_count
    }

    pub fn resource_budget(&self) -> ResourceEstimate {
        self.dag.budget
    }

    pub fn instructions(&self) -> &[Instruction] {
        &self.dag.instructions
    }

    /// Vectorized batch evaluation for one time series.
    /// Rejects expressions containing cross-section operators to prevent mixing timestamps.
    pub fn evaluate_vector(
        &self,
        inputs: &BTreeMap<String, Vec<Option<Decimal>>>,
    ) -> Result<Vec<Option<Decimal>>> {
        execute::evaluate_vector(&self.dag, inputs)
    }

    /// Vectorized batch evaluation over an aligned multi-instrument cohort panel.
    pub fn evaluate_panel(
        &self,
        instruments: &[BTreeMap<String, Vec<Option<Decimal>>>],
    ) -> Result<Vec<Vec<Option<Decimal>>>> {
        execute::evaluate_panel(&self.dag, instruments)
    }

    /// Incremental event-driven executor for one time series.
    /// Rejects cross-section expressions (`QLIB_RESEARCH_ONLY_OPERATOR`).
    pub fn event_executor(&self) -> Result<EventExecutor> {
        EventExecutor::new(self.dag.clone())
    }

    /// Incremental event-driven executor stepping an aligned multi-instrument cohort one event at a time.
    pub fn panel_event_executor(&self, instrument_count: usize) -> Result<PanelEventExecutor> {
        PanelEventExecutor::new(self.dag.clone(), instrument_count)
    }
}

/// Research-only target/label expression permitting explicit bounded forward look-ahead.
/// Cannot construct event executors or convert into [`FactorExpr`].
#[derive(Clone, Debug)]
pub struct TargetExpr {
    dag: Arc<CompiledDag>,
}

impl TargetExpr {
    pub fn compile(source: &str) -> Result<Self> {
        Ok(Self {
            dag: Arc::new(compile::compile(source, ExprKind::Target, None)?),
        })
    }

    pub fn compile_with_allowed_fields(source: &str, allowed: &BTreeSet<String>) -> Result<Self> {
        Ok(Self {
            dag: Arc::new(compile::compile(source, ExprKind::Target, Some(allowed))?),
        })
    }

    pub fn source(&self) -> &str {
        &self.dag.source
    }

    pub fn canonical(&self) -> &str {
        &self.dag.canonical
    }

    pub fn fingerprint(&self) -> &str {
        &self.dag.fingerprint
    }

    pub fn inputs(&self) -> &BTreeSet<String> {
        &self.dag.inputs
    }

    pub fn operator_ids(&self) -> &BTreeSet<String> {
        &self.dag.operator_ids
    }

    pub fn minimum_observations(&self) -> usize {
        self.dag.budget.minimum_observations
    }

    pub fn max_lookahead(&self) -> usize {
        self.dag.budget.max_lookahead
    }

    pub fn has_cross_section(&self) -> bool {
        self.dag.has_cross_section
    }

    pub fn node_count(&self) -> usize {
        self.dag.budget.node_count
    }

    pub fn resource_budget(&self) -> ResourceEstimate {
        self.dag.budget
    }

    pub fn instructions(&self) -> &[Instruction] {
        &self.dag.instructions
    }

    /// Vectorized batch evaluation for one time series (Research only).
    pub fn evaluate_vector(
        &self,
        inputs: &BTreeMap<String, Vec<Option<Decimal>>>,
    ) -> Result<Vec<Option<Decimal>>> {
        execute::evaluate_vector(&self.dag, inputs)
    }

    /// Vectorized batch evaluation over an aligned multi-instrument cohort panel (Research only).
    pub fn evaluate_panel(
        &self,
        instruments: &[BTreeMap<String, Vec<Option<Decimal>>>],
    ) -> Result<Vec<Vec<Option<Decimal>>>> {
        execute::evaluate_panel(&self.dag, instruments)
    }
}
