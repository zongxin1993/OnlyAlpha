//! Registered node Infrastructure; all semantic state belongs to Strategy.
use crate::{Worker, WorkerConnector, WorkerError, client::keys, process::MAX_FRAME};
use onlyalpha_calculation::{Definition, ExecutionBinding, product::TypeDeclaration};
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBarType};
use onlyalpha_gateway_protocol::{CalculationNode, calculation_request::Operation};
use onlyalpha_strategy::{NodeDescriptor, NodeFailure, NodePort, NodeRequest, Program};
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc, time::Duration};
const PRODUCT_WORK: usize = 8 * MAX_FRAME;
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
    connector: Arc<dyn WorkerConnector>,
    requests: BTreeMap<String, Value>,
    deadline: Duration,
}
impl StrategyNodes {
    pub fn resolve(
        worker: &mut Worker,
        request: Value,
        deadline: Duration,
    ) -> Result<NodeDescriptor, NodeFailure> {
        let reference = request["reference"].clone();
        if !keys(&reference, &["kind", "type_id", "semantic_version"])
            || reference
                .as_object()
                .is_none_or(|r| r.values().any(|v| !v.is_string()))
        {
            return Err(NodeFailure::Known);
        }
        let v = exchange(worker, request, deadline)?;
        let checked = (|| {
            if !keys(
                &v,
                &[
                    "schema_version",
                    "descriptor",
                    "product_definition",
                    "type_declaration",
                ],
            ) || v["schema_version"].as_u64() != Some(2)
            {
                return Err(NodeFailure::Known);
            }
            let declaration = TypeDeclaration::from_record(&v["type_declaration"], PRODUCT_WORK)
                .map_err(|_| NodeFailure::Known)?;
            let native = declaration
                .validate_candidate(&v["product_definition"], PRODUCT_WORK)
                .map_err(|_| NodeFailure::Known)?;
            let mut projection = native.to_record();
            for key in ["kind", "type_id", "semantic_version"] {
                if projection[key] != reference[key] {
                    return Err(NodeFailure::Known);
                }
            }
            let descriptor =
                NodeDescriptor::from_record(&v["descriptor"]).map_err(|_| NodeFailure::Known)?;
            if descriptor.native_definition != native.fingerprint() {
                return Err(NodeFailure::Known);
            }
            // Product2 keeps its own identity. Verify the existing typed
            // component projection independently; never trust only its digest.
            projection["schema_version"] = json!(3);
            if Definition::from_record(&projection).map_err(|_| NodeFailure::Known)?
                != descriptor.definition
            {
                return Err(NodeFailure::Known);
            }
            Ok(descriptor)
        })();
        checked.or_else(|_| worker.poison("PRODUCT_RESOLUTION").map_err(failure))
    }
    pub fn new(
        connector: Arc<dyn WorkerConnector>,
        program: Program,
        requests: BTreeMap<String, Value>,
        deadline: Duration,
    ) -> Result<Self, NodeFailure> {
        if program.bindings().len() > 16
            || requests.keys().ne(program.revision().descriptors().keys())
        {
            return Err(NodeFailure::Known);
        }
        let worker = crate::process::connect_exact(
            connector.as_ref(),
            program.generation(),
            program.artifact(),
            program.revision().is_product_materialization(),
            deadline,
        )
        .map_err(failure)?;
        let mut p = Self {
            worker,
            program,
            connector,
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
            self.connector.clone(),
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
