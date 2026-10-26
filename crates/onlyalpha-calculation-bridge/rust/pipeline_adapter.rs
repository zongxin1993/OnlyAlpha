//! Exact managed Python calculations for the canonical Pipeline port.
use crate::{Checkpoint, Client, WorkerConnector, WorkerError};
use onlyalpha_calculation::CalculationSnapshot;
use onlyalpha_domain::{
    identifiers::OnlyClusterId,
    market::{OnlyBar, OnlyBarType},
};
use onlyalpha_market_data_pipeline::state::OnlyMarketDataStateScope;
use onlyalpha_market_data_pipeline::{
    CalculationFailure, CalculationPort, CalculationSlot, calculation_scope,
};
use serde_json::{Value, json};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
#[derive(Clone)]
pub struct SmaRequest {
    pub local: String,
    pub cluster: OnlyClusterId,
    pub source: String,
    pub bar_type: OnlyBarType,
    pub parameters: Value,
    pub required: bool,
    pub dependencies: Vec<String>,
}
pub struct PipelineCalculations {
    client: Client,
    connector: Arc<dyn WorkerConnector>,
    generation: String,
    artifact: String,
    owner: OnlyMarketDataStateScope,
    requests: Vec<SmaRequest>,
    slots: Vec<CalculationSlot>,
    deadline: Duration,
    exchange: Duration,
    backend: Duration,
}
fn failure(e: WorkerError) -> CalculationFailure {
    if matches!(e, WorkerError::Unknown(_)) {
        CalculationFailure::Unknown
    } else {
        CalculationFailure::Known
    }
}
impl PipelineCalculations {
    pub fn new(
        connector: Arc<dyn WorkerConnector>,
        generation: String,
        artifact: String,
        owner: OnlyMarketDataStateScope,
        mut requests: Vec<SmaRequest>,
        deadline: Duration,
    ) -> Result<Self, CalculationFailure> {
        if requests.is_empty() || requests.len() > 16 {
            return Err(CalculationFailure::Known);
        }
        requests
            .sort_by_key(|r| calculation_scope(&owner, &r.cluster, &r.local).unwrap_or_default());
        let mut client = Client::new(
            crate::process::connect_exact(
                connector.as_ref(),
                &generation,
                &artifact,
                false,
                deadline,
            )
            .map_err(failure)?,
        );
        let mut slots = vec![];
        for r in &requests {
            let scope = calculation_scope(&owner, &r.cluster, &r.local)
                .map_err(|_| CalculationFailure::Known)?;
            let resolution = client
                .resolve(r.parameters.clone(), deadline)
                .map_err(failure)?;
            client
                .create(&scope, resolution, r.bar_type.clone(), &r.source, deadline)
                .map_err(failure)?;
            let binding = client.snapshot(&scope).map_err(failure)?.binding().clone();
            let mut dependencies = r.dependencies.clone();
            dependencies.sort();
            slots.push(CalculationSlot {
                local: r.local.clone(),
                cluster: r.cluster.clone(),
                binding,
                source: r.source.clone(),
                bar_type: r.bar_type.clone(),
                required: r.required,
                dependencies,
            });
        }
        Ok(Self {
            client,
            connector,
            generation,
            artifact,
            owner,
            requests,
            slots,
            deadline,
            exchange: Duration::ZERO,
            backend: Duration::ZERO,
        })
    }
    pub fn timing(&self) -> (Duration, Duration) {
        (self.exchange, self.backend)
    }
    pub fn cancellation(&self) -> Result<crate::Cancellation, WorkerError> {
        self.client.cancellation()
    }
}
impl CalculationPort for PipelineCalculations {
    fn registrations(&self) -> Vec<CalculationSlot> {
        self.slots.clone()
    }
    fn snapshot(&mut self, scope: &str) -> Result<CalculationSnapshot, CalculationFailure> {
        self.client.snapshot(scope).map_err(failure)
    }
    fn update(&mut self, scope: &str, bars: &[Arc<OnlyBar>]) -> Result<(), CalculationFailure> {
        let input: Vec<_> = bars.iter().map(|b| b.as_ref().clone()).collect();
        let start = Instant::now();
        let result = self.client.update(scope, &input, self.deadline);
        self.exchange += start.elapsed();
        if result.is_ok() {
            self.backend += self.client.last_compute_time();
        }
        result.map(|_| ()).map_err(failure)
    }
    fn capture(&mut self) -> Result<Value, CalculationFailure> {
        let mut records = vec![];
        for slot in &self.slots {
            let scope = slot.binding.scope();
            let checkpoint = self.client.capture(scope, self.deadline).map_err(failure)?;
            let value: Value = serde_json::from_slice(&checkpoint.to_bytes())
                .map_err(|_| CalculationFailure::Known)?;
            records.push(json!([scope, value, checkpoint.fingerprint()]));
        }
        Ok(json!({"schema_version":1,"instances":records}))
    }
    fn restore_candidate(&self, value: &Value) -> Result<Self, CalculationFailure> {
        if value.as_object().is_none_or(|v| {
            v.len() != 2 || !v.contains_key("instances") || !v.contains_key("schema_version")
        }) || value["schema_version"].as_u64() != Some(1)
        {
            return Err(CalculationFailure::Known);
        }
        let records = value["instances"]
            .as_array()
            .ok_or(CalculationFailure::Known)?;
        if records.len() != self.slots.len() {
            return Err(CalculationFailure::Known);
        }
        let mut checked = std::collections::BTreeMap::new();
        for row in records {
            let row = row
                .as_array()
                .filter(|v| v.len() == 3)
                .ok_or(CalculationFailure::Known)?;
            let scope = row[0].as_str().ok_or(CalculationFailure::Known)?;
            if !self.slots.iter().any(|s| s.binding.scope() == scope) {
                return Err(CalculationFailure::Known);
            }
            let checkpoint = Checkpoint::from_bytes(
                row[1].to_string().as_bytes(),
                row[2].as_str().ok_or(CalculationFailure::Known)?,
            )
            .map_err(failure)?;
            if checked.insert(scope, checkpoint).is_some() {
                return Err(CalculationFailure::Known);
            }
        }
        let mut candidate = Self::new(
            self.connector.clone(),
            self.generation.clone(),
            self.artifact.clone(),
            self.owner.clone(),
            self.requests.clone(),
            self.deadline,
        )?;
        if candidate.slots != self.slots {
            return Err(CalculationFailure::Known);
        }
        for (scope, checkpoint) in checked {
            candidate
                .client
                .restore(scope, &checkpoint, self.deadline)
                .map_err(failure)?;
        }
        Ok(candidate)
    }
}
