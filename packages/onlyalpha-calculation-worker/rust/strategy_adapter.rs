//! Registered node Infrastructure; all semantic state belongs to Strategy.
use crate::{Worker, WorkerError};
use onlyalpha_calculation::ExecutionBinding;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBarType};
use onlyalpha_gateway_protocol::{CalculationNode, calculation_request::Operation};
use onlyalpha_strategy::{NodeDescriptor, NodeFailure, NodePort, NodeRequest, Program};
use serde_json::{Value, json};
use std::{collections::BTreeMap, path::PathBuf, time::Duration};
fn failure(e: WorkerError) -> NodeFailure {
    if matches!(e, WorkerError::Unknown(_)) {
        NodeFailure::Unknown
    } else {
        NodeFailure::Known
    }
}
fn exchange(worker: &mut Worker, request: Value, deadline: Duration) -> Result<Value, NodeFailure> {
    worker
        .exchange(
            Operation::Node(CalculationNode {
                request_json: request.to_string().into_bytes(),
            }),
            deadline,
        )
        .map_err(failure)
}
pub struct StrategyNodes {
    worker: Worker,
    program: Program,
    interpreter: PathBuf,
    requests: BTreeMap<String, Value>,
    deadline: Duration,
}
impl StrategyNodes {
    pub fn resolve(
        worker: &mut Worker,
        request: Value,
        deadline: Duration,
    ) -> Result<NodeDescriptor, NodeFailure> {
        let v = exchange(worker, request, deadline)?;
        NodeDescriptor::from_record(&v).map_err(|_| NodeFailure::Known)
    }
    pub fn new(
        interpreter: PathBuf,
        program: Program,
        requests: BTreeMap<String, Value>,
        deadline: Duration,
    ) -> Result<Self, NodeFailure> {
        if program.bindings().len() > 16
            || requests.keys().ne(program.revision().descriptors().keys())
        {
            return Err(NodeFailure::Known);
        }
        let spawn = if program.revision().is_product_materialization() {
            Worker::spawn_hosted
        } else {
            Worker::spawn
        };
        let worker = spawn(
            &interpreter,
            program.generation().into(),
            program.artifact().into(),
            deadline,
        )
        .map_err(failure)?;
        let mut p = Self {
            worker,
            program,
            interpreter,
            requests,
            deadline,
        };
        for instrument in p.program.revision().universe() {
            let bar_type=OnlyBarType::from_record(&json!({"schema_version":2,"instrument_id":instrument.to_record(),"semantic":p.program.revision().semantic().to_record()})).map_err(|_|NodeFailure::Known)?;
            for (node, descriptor) in p.program.revision().descriptors() {
                let scope = p.program.instance_scope(instrument, node);
                let request = p.requests[node].clone();
                let resolved = Self::resolve(&mut p.worker, request.clone(), deadline)?;
                if &resolved != descriptor {
                    return Err(NodeFailure::Known);
                }
                exchange(
                    &mut p.worker,
                    json!({"schema_version":1,"op":"CREATE","binding":p.program.bindings()[&scope].to_record(),"resolution":request,"bar_type":bar_type.to_record(),"source":p.program.source(),"strategy_fingerprint":p.program.revision().fingerprint()}),
                    deadline,
                )?;
            }
        }
        Ok(p)
    }
    pub fn cancellation(&self) -> crate::Result<crate::Cancellation> {
        self.worker.cancellation()
    }
}
impl NodePort for StrategyNodes {
    fn bindings(&self) -> Vec<ExecutionBinding> {
        self.program.bindings().values().cloned().collect()
    }
    fn update(&mut self, r: &NodeRequest) -> Result<Value, NodeFailure> {
        exchange(
            &mut self.worker,
            json!({"schema_version":1,"op":"UPDATE","scope":r.scope,"revision":r.revision,"bar":r.bar.to_record(),"inputs":r.inputs,"input_digest":r.input_digest}),
            self.deadline,
        )
    }
    fn capture(&mut self) -> Result<Value, NodeFailure> {
        let mut nodes = vec![];
        for scope in self.program.bindings().keys() {
            let v = exchange(
                &mut self.worker,
                json!({"schema_version":1,"op":"CHECKPOINT","scope":scope}),
                self.deadline,
            )?;
            nodes.push(json!([scope, v]));
        }
        Ok(json!({"schema_version":1,"nodes":nodes}))
    }
    fn restore_candidate(&self, v: &Value) -> Result<Self, NodeFailure> {
        if v.as_object().is_none_or(|m| m.len() != 2) || v["schema_version"].as_u64() != Some(1) {
            return Err(NodeFailure::Known);
        }
        let rows = v["nodes"].as_array().ok_or(NodeFailure::Known)?;
        if rows.len() != self.program.bindings().len() {
            return Err(NodeFailure::Known);
        }
        let mut checked = BTreeMap::new();
        for row in rows {
            let a = row
                .as_array()
                .filter(|a| a.len() == 2)
                .ok_or(NodeFailure::Known)?;
            let scope = a[0].as_str().ok_or(NodeFailure::Known)?;
            if !self.program.bindings().contains_key(scope)
                || checked.insert(scope, a[1].clone()).is_some()
            {
                return Err(NodeFailure::Known);
            }
        }
        let mut candidate = Self::new(
            self.interpreter.clone(),
            self.program.clone(),
            self.requests.clone(),
            self.deadline,
        )?;
        for (scope, checkpoint) in checked {
            let restored = exchange(
                &mut candidate.worker,
                json!({"schema_version":1,"op":"RESTORE","scope":scope,"checkpoint":checkpoint}),
                self.deadline,
            )?;
            if restored != checkpoint {
                return Err(NodeFailure::Known);
            }
        }
        Ok(candidate)
    }
}
