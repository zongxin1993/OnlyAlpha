//! Native calculation acknowledgments around installed arithmetic. No admission.
//! Python owns only numerical factory instances; native Predicates stay in Rust.
use super::algorithm::{AlgorithmProcess, describe_research_runtime};
use onlyalpha_calculation::{CalculationState, Definition, ExecutionBinding, normalize_result_outputs, product::Definition as ProductDefinition};
use onlyalpha_calculation_bridge::{Cancellation, ChartInstallation, Worker, WorkerError, native_predicates::PredicateCalculation, native_operators::{OperatorCalculation,OperatorStream}};
use onlyalpha_domain::{base::OnlyDomainModel, time::OnlyTimestamp};
use onlyalpha_strategy::{NodeDescriptor, NodeFailure, NodePort, NodeRequest, Program, record_fingerprint};
use serde_json::{Value,json};
use std::{collections::BTreeMap, sync::Arc, time::Duration};
type Result<T> = std::result::Result<T,NodeFailure>;
const WORK:usize=8*1024*1024;
type ChildObserver = Arc<dyn Fn(Cancellation)->Result<()> + Send+Sync>;
#[cfg(test)]
thread_local! { static FAIL_BEFORE_INITIALIZE: std::cell::Cell<bool> = const { std::cell::Cell::new(false) }; }
#[cfg(test)]
pub(super) fn test_fail_before_initialize() { FAIL_BEFORE_INITIALIZE.with(|value| value.set(true)); }
fn known<T>(_:T)->NodeFailure {NodeFailure::Known}
fn failure(error:WorkerError)->NodeFailure {if matches!(error,WorkerError::Unknown(_)){NodeFailure::Unknown}else{NodeFailure::Known}}
fn exact(value:&Value,keys:&[&str])->Result<()> {
    if value.as_object().is_none_or(|m|m.len()!=keys.len()||keys.iter().any(|k|!m.contains_key(*k))) {Err(NodeFailure::Known)}else{Ok(())}
}
fn typed(values:&Value,ports:&Value)->Result<()> {
    if normalize_result_outputs(values).map_err(known)?!=*values {return Err(NodeFailure::Known);}
    let values=values.as_object().ok_or(NodeFailure::Known)?;
    let ports=ports.as_array().ok_or(NodeFailure::Known)?;
    if values.len()!=ports.len() {return Err(NodeFailure::Known);}
    for port in ports {
        let value=values.get(port["name"].as_str().ok_or(NodeFailure::Known)?).ok_or(NodeFailure::Known)?;
        if value["type"]=="NULL" {
            if port["nullable"]!=true {return Err(NodeFailure::Known);}
        } else if value["type"]!=port["data_type"] {return Err(NodeFailure::Known);}
    }
    Ok(())
}
struct Node {
    definition:ProductDefinition,
    descriptor:NodeDescriptor,
    state:CalculationState,
    predicate:Option<PredicateCalculation>,
    operator:Option<OperatorStream>,
    handle:Option<String>,
    plugin:Value,
}
impl Node {
    fn plugin(&self,value:&Value)->Result<()> {
        exact(value,&["definition","implementation_fingerprint","state_capability","checkpoint_schema_version","state"])?;
        if value["definition"]!=self.definition.to_record()
            || value["implementation_fingerprint"]!=self.descriptor.implementation
            || value["state_capability"]!=self.descriptor.state_capability
            || value["checkpoint_schema_version"]!=json!(self.descriptor.checkpoint_schema)
            || self.descriptor.state_capability=="STATELESS" && !value["state"].is_null()
        {return Err(NodeFailure::Known);}
        Ok(())
    }
    /// The typed stream is only an in-memory execution projection. Its complete
    /// checkpoint must match the original plugin fact before outward capture.
    fn actual_operator_state(&self) -> Result<()> {
        if let Some(stream) = &self.operator {
            if self.descriptor.state_capability == "CHECKPOINTABLE" {
                let checkpoint = stream.checkpoint().map_err(known)?;
                if self.state.cursor().samples() == 0 {
                    if !self.plugin["state"].is_null()
                        || checkpoint["windows"]
                            .as_object()
                            .ok_or(NodeFailure::Known)?
                            .values()
                            .any(|values| values.as_array().is_none_or(|v| !v.is_empty()))
                    {
                        return Err(NodeFailure::Known);
                    }
                } else if checkpoint != self.plugin["state"] {
                    return Err(NodeFailure::Known);
                }
            } else if !self.plugin["state"].is_null() {
                return Err(NodeFailure::Known);
            }
        }
        Ok(())
    }
    fn checkpoint(&self)->Value {
        let state=self.state.capture();
        json!({"schema_version":1,"binding":self.state.cursor().binding().to_record(),"cursor":state["cursor"],"receipt":state["receipt"],"plugin_state":self.plugin,"state_fingerprint":record_fingerprint(&self.plugin),"state_capability":self.descriptor.state_capability,"checkpoint_schema_version":self.descriptor.checkpoint_schema,"definition_fingerprint":self.descriptor.definition.fingerprint()})
    }
}
/// Constructed only from exact already-selected values. The caller retains all
/// Runtime/Dataset/permission authority; the completion hold follows child join.
pub struct InstalledTradingNodes {
    installation:Arc<ChartInstallation>,
    program:Program,
    definitions:BTreeMap<String,ProductDefinition>,
    sources:Vec<Value>,
    completion:Arc<dyn Send+Sync>,
    observer:Option<ChildObserver>,
    deadline:Duration,
    worker:Option<Worker>,
    nodes:BTreeMap<String,Node>,
    failed:bool,
}
impl InstalledTradingNodes {
    pub fn new(installation:Arc<ChartInstallation>,program:Program,definitions:BTreeMap<String,ProductDefinition>,sources:Vec<Value>,completion:Arc<dyn Send+Sync>,deadline:Duration)->Result<Self> {
        Self::construct(installation,program,definitions,sources,completion,deadline,None)
    }
    /// The backend owner retains every observed original handle before this
    /// callback returns, including on an error. It owns draining those children.
    pub fn new_owned(installation:Arc<ChartInstallation>,program:Program,definitions:BTreeMap<String,ProductDefinition>,sources:Vec<Value>,completion:Arc<dyn Send+Sync>,deadline:Duration,observer:ChildObserver)->Result<Self> {
        Self::construct(installation,program,definitions,sources,completion,deadline,Some(observer))
    }
    fn construct(installation:Arc<ChartInstallation>,program:Program,definitions:BTreeMap<String,ProductDefinition>,sources:Vec<Value>,completion:Arc<dyn Send+Sync>,deadline:Duration,observer:Option<ChildObserver>)->Result<Self> {
        installation.verify().map_err(failure)?;
        if program.bindings().len()>128 || sources.len()>128 || serde_json::to_vec(&sources).map_err(known)?.len()>WORK {return Err(NodeFailure::Known);}
        if program.artifact()!=installation.artifact_fingerprint() || definitions.keys().ne(program.revision().descriptors().keys()) {return Err(NodeFailure::Known);}
        let image=describe_research_runtime(env!("CARGO_PKG_VERSION")).map_err(failure)?;
        let image=image["artifact"].as_str().ok_or(NodeFailure::Known)?;
        let mut blueprints=BTreeMap::new();
        for (key,definition) in &definitions {
            let descriptor=&program.revision().descriptors()[key];
            let mut projected=definition.to_record();
            projected["schema_version"]=json!(3);
            if definition.fingerprint()!=descriptor.native_definition || Definition::from_record(&projected).map_err(known)?!=descriptor.definition {return Err(NodeFailure::Known);}
            let record=definition.to_record();
            let predicate=if record["kind"]=="PREDICATE" {
                let predicate=PredicateCalculation::from_record(&record).map_err(known)?;
                if descriptor.state_capability!="STATELESS" || descriptor.checkpoint_schema.is_some()
                    || predicate.implementation_manifest("TRADING",image).map_err(known)?["implementation_fingerprint"]!=descriptor.implementation {return Err(NodeFailure::Known);}
                Some(predicate)
            } else if record["kind"]=="FACTOR" || record["kind"]=="INDICATOR" && record["type_id"].as_str().is_some_and(|t|t.starts_with("onlyalpha.operator.")) {None}
            else {return Err(NodeFailure::Known);};
            let operator=if record["kind"]=="INDICATOR" {
                let operator=OperatorCalculation::from_record(&record).map_err(known)?;
                if descriptor.state_capability!=operator.state_capability() || descriptor.checkpoint_schema!=operator.checkpoint_schema_version()
                    || operator.implementation_manifest("TRADING",image).map_err(known)?["implementation_fingerprint"]!=descriptor.implementation {return Err(NodeFailure::Known);}
                Some(operator)
            }else{None};
            blueprints.insert(key.clone(),(definition.clone(),descriptor.clone(),predicate,operator));
        }
        let mut math=serde_json::Map::new();
        let mut nodes=BTreeMap::new();
        for (scope,binding) in program.bindings() {
            let (definition,descriptor,predicate,operator)=blueprints.get(&binding.digests()[2]).ok_or(NodeFailure::Known)?;
            let handle=if predicate.is_none() && operator.is_none() {
                if math.len()>=128 {return Err(NodeFailure::Known);}
                let handle=format!("node_{}",math.len());math.insert(handle.clone(),definition.to_record());Some(handle)
            } else {None};
            let plugin=json!({"definition":definition.to_record(),"implementation_fingerprint":descriptor.implementation,"state_capability":descriptor.state_capability,"checkpoint_schema_version":descriptor.checkpoint_schema,"state":null});
            nodes.insert(scope.clone(),Node{definition:definition.clone(),descriptor:descriptor.clone(),state:CalculationState::new(binding.clone()),predicate:predicate.clone(),operator:operator.as_ref().map(|operator|operator.stream().map_err(known)).transpose()?,handle,plugin});
        }
        let worker=if math.is_empty(){None}else{
            let mut worker=AlgorithmProcess::trading(&installation,program.generation(),Box::new(completion.clone())).map_err(failure)?;
            let initialized=(||->Result<()> {
                if let Some(observe)=&observer {observe(worker.cancellation().map_err(failure)?)?;}
                worker.handshake_trading_numerics(deadline).map_err(failure)?;
                #[cfg(test)]
                if FAIL_BEFORE_INITIALIZE.with(|value| value.replace(false)) {return Err(NodeFailure::Unknown);}
                let checkpoint=worker.exchange_trading_numerics(json!({"schema_version":1,"op":"INITIALIZE","sources":sources,"nodes":math}),deadline).map_err(failure)?;
                let observed=math_states(&checkpoint,&nodes)?;
                for (scope,value) in observed {nodes.get_mut(&scope).ok_or(NodeFailure::Known)?.plugin=value;}
                Ok(())
            })();
            if let Err(error)=initialized {
                // A known protocol rejection cannot conceal an unknown cleanup.
                if worker.terminate().is_err(){return Err(NodeFailure::Unknown);}
                return Err(error);
            }
            Some(worker)
        };
        Ok(Self{installation,program,definitions,sources,completion,observer,deadline,worker,nodes,failed:false})
    }
    pub fn cancellation(&self)->Result<Option<Cancellation>> {self.worker.as_ref().map(|w|w.cancellation().map_err(failure)).transpose()}
    fn abandon(&mut self)->NodeFailure {
        self.failed=true;
        if let Some(worker)=&self.worker {let _=worker.terminate();}
        NodeFailure::Unknown
    }
    fn actual_states(&mut self)->Result<()> {
        for node in self.nodes.values() { node.actual_operator_state()?; }
        if let Some(worker)=&mut self.worker {
            let checkpoint=worker.exchange_trading_numerics(json!({"schema_version":1,"op":"CHECKPOINT"}),self.deadline).map_err(failure)?;
            let observed=math_states(&checkpoint,&self.nodes)?;
            if observed.iter().any(|(scope,state)|self.nodes[scope].plugin!=*state) {return Err(NodeFailure::Unknown);}
        }
        Ok(())
    }
}
fn math_states(checkpoint:&Value,nodes:&BTreeMap<String,Node>)->Result<BTreeMap<String,Value>> {
    exact(checkpoint,&["schema_version","nodes"])?;
    if checkpoint["schema_version"].as_u64()!=Some(1) {return Err(NodeFailure::Known);}
    let observed=checkpoint["nodes"].as_object().ok_or(NodeFailure::Known)?;
    if observed.len()!=nodes.values().filter(|n|n.handle.is_some()).count() {return Err(NodeFailure::Known);}
    let mut result=BTreeMap::new();
    for (scope,node) in nodes {
        if let Some(handle)=&node.handle {
            let value=observed.get(handle).ok_or(NodeFailure::Known)?;
            node.plugin(value)?;
            result.insert(scope.clone(),value.clone());
        }
    }
    Ok(result)
}
impl NodePort for InstalledTradingNodes {
    fn bindings(&self)->Vec<ExecutionBinding> {self.program.bindings().values().cloned().collect()}
    fn update(&mut self,request:&NodeRequest)->Result<Value> {
        if self.failed {return Err(NodeFailure::Unknown);}
        let node=self.nodes.get(&request.scope).ok_or(NodeFailure::Known)?;
        let record=node.definition.to_record();
        let bar=request.bar.to_record();
        if request.binding!=*node.state.cursor().binding() || request.revision!=node.state.cursor().revision()
            || request.input_digest!=record_fingerprint(&request.input_record())
            || self.program.instance_scope(request.bar.instrument_id(),&node.descriptor.definition.fingerprint())!=request.scope
            || !self.program.revision().universe().contains(request.bar.instrument_id())
            || request.bar.bar_type().semantic()!=self.program.revision().semantic()
            || !request.bar.is_closed() || request.bar.ts_event()!=request.bar.bar_end()
            || bar["revision"].as_u64()!=Some(0) || bar["adjustment_type"]!="RAW" {return Err(NodeFailure::Known);}
        typed(&request.inputs,&record["inputs"])?;
        let time=OnlyTimestamp::from_datetime(*request.bar.bar_end()).unix_nanos().to_string();
        let prepared=node.state.prepare(&[&time],&request.input_digest).map_err(known)?;
        let samples=node.state.cursor().samples().checked_add(1).ok_or(NodeFailure::Known)?;
        let mut cursor=node.state.cursor().capture();
        cursor["revision"]=json!(request.revision.checked_add(1).ok_or(NodeFailure::Known)?);
        cursor["samples"]=json!(samples);cursor["last_event_ns"]=json!(time);
        let handle=node.handle.clone();
        let result=(||->Result<(Value,Value,Option<OperatorStream>)>{
            if let Some(predicate)=&node.predicate {
                let values=request.inputs.as_object().ok_or(NodeFailure::Known)?.iter().map(|(key,value)|(key.clone(),if value["type"]=="NULL"{Value::Null}else{value["value"].clone()})).collect::<serde_json::Map<_,_>>();
                let raw=predicate.evaluate(&Value::Object(values)).map_err(known)?;
                let output=if raw["value"].is_null(){json!({"type":"NULL","value":null})}else{json!({"type":"BOOLEAN","value":raw["value"].as_bool().ok_or(NodeFailure::Known)?})};
                Ok((json!({"value":output}),node.plugin.clone(),None))
            } else if let Some(operator)=&node.operator {
                // Preserve candidate/commit atomicity without decoding and
                // re-evaluating the previous JSON window on every observation.
                let mut stream=operator.clone();
                let values=request.inputs.as_object().ok_or(NodeFailure::Known)?.iter().map(|(key,value)|(key.clone(),if value["type"]=="NULL"{Value::Null}else{value["value"].clone()})).collect::<serde_json::Map<_,_>>();
                let raw=stream.push(&Value::Object(values)).map_err(known)?;
                let outputs=Value::Object(raw.as_object().ok_or(NodeFailure::Known)?.iter().map(|(key,value)|(key.clone(),if value.is_null(){json!({"type":"NULL","value":null})}else{json!({"type":"DECIMAL","value":value})})).collect());
                let mut plugin=node.plugin.clone();
                if node.descriptor.state_capability=="CHECKPOINTABLE" {plugin["state"]=stream.checkpoint().map_err(known)?;}
                Ok((outputs,plugin,Some(stream)))
            } else {
                let response=self.worker.as_mut().ok_or(NodeFailure::Unknown)?.exchange_trading_numerics(json!({"schema_version":1,"op":"UPDATE","node":handle.ok_or(NodeFailure::Known)?,"inputs":request.inputs}),self.deadline).map_err(failure)?;
                exact(&response,&["outputs","state"])?;
                node.plugin(&response["state"])?;
                Ok((response["outputs"].clone(),response["state"].clone(),None))
            }
        })();
        let (outputs,plugin,operator)=match result {Ok(value)=>value,Err(_)=>return Err(self.abandon())};
        // The private SDK scalar codec preserves Decimal output scale. Bind the
        // mathematical value to the existing native scalar representation before
        // constructing a canonical receipt; plugin state remains byte-exact.
        let outputs=match normalize_result_outputs(&outputs) {
            Ok(values)=>values,
            Err(_)=>return Err(self.abandon()),
        };
        if typed(&outputs,&record["outputs"]).is_err() {return Err(self.abandon());}
        // This is the declared warmup contract for these actual incremental
        // Operator/Factor factories, independent of a numeric null/zero result.
        let ready=samples>=record["warmup"]["minimum_observations"].as_u64().ok_or(NodeFailure::Known)?;
        let receipt=json!({"cursor":cursor,"input_digest":request.input_digest,"outputs":outputs,"ready":ready,"quality_flags":[]});
        let node=self.nodes.get_mut(&request.scope).ok_or(NodeFailure::Known)?;
        if node.state.commit(&prepared,&receipt).is_err(){return Err(self.abandon());}
        node.plugin=plugin;
        if let Some(operator)=operator {node.operator=Some(operator);}
        Ok(json!({"receipt":receipt,"state_fingerprint":record_fingerprint(&node.plugin)}))
    }
    fn capture(&mut self)->Result<Value> {
        if self.failed {return Err(NodeFailure::Unknown);}
        if self.actual_states().is_err(){return Err(self.abandon());}
        let record=json!({"schema_version":1,"nodes":self.nodes.iter().map(|(scope,node)|json!([scope,node.checkpoint()])).collect::<Vec<_>>()});
        if record.to_string().len()>WORK {return Err(self.abandon());}
        Ok(record)
    }
    fn restore_candidate(&self,checkpoint:&Value)->Result<Self> {
        if checkpoint.to_string().len()>WORK {return Err(NodeFailure::Known);}
        exact(checkpoint,&["schema_version","nodes"])?;
        if checkpoint["schema_version"].as_u64()!=Some(1){return Err(NodeFailure::Known);}
        let rows=checkpoint["nodes"].as_array().ok_or(NodeFailure::Known)?;
        if rows.len()!=self.nodes.len(){return Err(NodeFailure::Known);}
        let mut checked=BTreeMap::new();
        for row in rows {
            let row=row.as_array().filter(|r|r.len()==2).ok_or(NodeFailure::Known)?;
            let scope=row[0].as_str().ok_or(NodeFailure::Known)?;
            let node=self.nodes.get(scope).ok_or(NodeFailure::Known)?;
            let value=&row[1];
            exact(value,&["schema_version","binding","cursor","receipt","plugin_state","state_fingerprint","state_capability","checkpoint_schema_version","definition_fingerprint"])?;
            if value["schema_version"].as_u64()!=Some(1)||value["binding"]!=node.state.cursor().binding().to_record()
                ||value["state_capability"]!=node.descriptor.state_capability
                ||value["checkpoint_schema_version"]!=json!(node.descriptor.checkpoint_schema)
                ||value["definition_fingerprint"]!=node.descriptor.definition.fingerprint()
                ||value["state_fingerprint"]!=record_fingerprint(&value["plugin_state"]){return Err(NodeFailure::Known);}
            node.plugin(&value["plugin_state"])?;
            if node.predicate.is_some()&&value["plugin_state"]!=node.plugin {return Err(NodeFailure::Known);}
            let mut state=CalculationState::new(node.state.cursor().binding().clone());
            let ready=if value["receipt"].is_null(){None}else{Some(value["receipt"]["ready"].as_bool().ok_or(NodeFailure::Known)?)};
            let record=json!({"schema_version":1,"cursor":value["cursor"],"receipt":value["receipt"],"outcome":match ready {None=>"UNINITIALIZED",Some(false)=>"WARMING",Some(true)=>"READY"},"reason":null});
            state.restore(&record).map_err(known)?;
            if state.cursor().revision()!=state.cursor().samples(){return Err(NodeFailure::Known);}
            if let Some(ready)=ready {
                let definition=node.definition.to_record();
                if ready!=(state.cursor().samples()>=definition["warmup"]["minimum_observations"].as_u64().ok_or(NodeFailure::Known)?) || value["receipt"]["quality_flags"]!=json!([]){return Err(NodeFailure::Known);}
                typed(&value["receipt"]["outputs"],&definition["outputs"])?;
            }
            if checked.insert(scope.to_owned(),(state,value["plugin_state"].clone())).is_some(){return Err(NodeFailure::Known);}
        }
        let mut candidate=Self::construct(self.installation.clone(),self.program.clone(),self.definitions.clone(),self.sources.clone(),self.completion.clone(),self.deadline,self.observer.clone())?;
        let restored=(||->Result<()> {
            if let Some(worker)=&mut candidate.worker {
                let states=candidate.nodes.iter().filter_map(|(scope,node)|node.handle.as_ref().map(|h|(h.clone(),checked[scope].1.clone()))).collect::<serde_json::Map<_,_>>();
                let expected=json!({"schema_version":1,"nodes":states});
                let actual=worker.exchange_trading_numerics(json!({"schema_version":1,"op":"RESTORE","checkpoint":expected}),self.deadline).map_err(failure)?;
                if actual!=expected {return Err(NodeFailure::Known);}
            }
            for (scope,(state,plugin)) in checked {
                let node=candidate.nodes.get_mut(&scope).ok_or(NodeFailure::Known)?;
                if let Some(operator)=&node.operator {
                    if node.descriptor.state_capability=="CHECKPOINTABLE" {
                        let samples=state.cursor().samples();
                        if (samples==0)!=plugin["state"].is_null(){return Err(NodeFailure::Known);}
                        if samples>0 {
                            let restored=operator.restored_candidate(&plugin["state"]).map_err(known)?;
                            node.operator=Some(restored);
                            let definition=node.definition.to_record();
                            let period=definition["parameters"]["period"]["value"].as_u64().ok_or(NodeFailure::Known)?;
                            let limit=period+u64::from(matches!(definition["type_id"].as_str(),Some("onlyalpha.operator.delay"|"onlyalpha.operator.delta")));
                            let expected=samples.min(limit);
                            if plugin["state"]["windows"].as_object().ok_or(NodeFailure::Known)?.values().any(|w|w.as_array().is_none_or(|w|w.len() as u64!=expected)){return Err(NodeFailure::Known);}
                        }
                    }
                }
                node.state=state;node.plugin=plugin;
            }
            if candidate.capture()!=Ok(checkpoint.clone()){return Err(NodeFailure::Known);}
            Ok(())
        })();
        if let Err(error)=restored {
            if candidate.worker.as_ref().is_some_and(|worker|worker.terminate().is_err()){return Err(NodeFailure::Unknown);}
            return Err(error);
        }
        Ok(candidate)
    }
}

#[cfg(test)]
mod native_stream_tests {
    use super::*;

    fn node(stateful: bool) -> Node {
        let type_id = if stateful {
            "onlyalpha.operator.rolling_mean"
        } else {
            "onlyalpha.operator.scale"
        };
        let parameters = if stateful {
            json!({"period": {"type": "INTEGER", "value": 2}})
        } else {
            json!({})
        };
        let bindings = json!({
            "value": {"node_fingerprint": null, "output_name": "value", "source": "close"}
        });
        let calculation = OperatorCalculation::resolve(type_id, "2", &parameters, &bindings)
            .unwrap();
        let definition = calculation.definition().clone();
        let mut component = definition.to_record();
        component["schema_version"] = json!(3);
        let manifest = calculation
            .implementation_manifest("TRADING", &"a".repeat(64))
            .unwrap();
        let implementation = manifest["implementation_fingerprint"]
            .as_str()
            .unwrap()
            .to_owned();
        let descriptor = NodeDescriptor {
            definition: Definition::from_record(&component).unwrap(),
            native_definition: definition.fingerprint(),
            implementation: implementation.clone(),
            state_capability: calculation.state_capability().into(),
            checkpoint_schema: calculation.checkpoint_schema_version(),
        };
        let plugin = json!({
            "definition": definition.to_record(),
            "implementation_fingerprint": implementation,
            "state_capability": descriptor.state_capability,
            "checkpoint_schema_version": descriptor.checkpoint_schema,
            "state": null
        });
        let binding = ExecutionBinding::new(
            std::array::from_fn(|_| "a".repeat(64)),
            "native-stream",
        )
        .unwrap();
        Node {
            definition,
            descriptor,
            state: CalculationState::new(binding),
            predicate: None,
            operator: Some(calculation.stream().unwrap()),
            handle: None,
            plugin,
        }
    }

    #[test]
    fn typed_operator_candidate_does_not_mutate_committed_state_and_capture_detects_divergence() {
        let mut node = node(true);
        assert!(node.actual_operator_state().is_ok());
        let original = node.checkpoint();
        let mut candidate = node.operator.as_ref().unwrap().clone();
        let raw = candidate.push(&json!({"value": "1"})).unwrap();

        // Advancing a candidate cannot change the old outward plugin/cursor.
        assert_eq!(node.checkpoint(), original);
        assert!(node.actual_operator_state().is_ok());
        let prepared = node.state.prepare(&["1"], &"b".repeat(64)).unwrap();
        let mut cursor = node.state.cursor().capture();
        cursor["revision"] = json!(1);
        cursor["samples"] = json!(1);
        cursor["last_event_ns"] = json!("1");
        let receipt = json!({
            "cursor": cursor,
            "input_digest": "b".repeat(64),
            "outputs": {"value": {"type": "NULL", "value": raw["value"]}},
            "ready": false,
            "quality_flags": []
        });

        // A rejected formal commit still leaves the original typed stream intact.
        let mut invalid = receipt.clone();
        invalid["input_digest"] = json!("c".repeat(64));
        assert!(node.state.commit(&prepared, &invalid).is_err());
        assert_eq!(node.checkpoint(), original);

        node.state.commit(&prepared, &receipt).unwrap();
        node.plugin["state"] = candidate.checkpoint().unwrap();
        node.operator = Some(candidate);
        assert!(node.actual_operator_state().is_ok());
        let checkpoint = node.checkpoint();
        node.operator
            .as_mut()
            .unwrap()
            .push(&json!({"value": "2"}))
            .unwrap();
        assert!(node.actual_operator_state().is_err());
        assert_eq!(
            node.checkpoint(),
            checkpoint,
            "typed projection cannot silently replace the committed plugin"
        );
    }

    #[test]
    fn typed_stateless_operator_keeps_null_plugin_state_without_checkpoint_contract() {
        let mut node = node(false);
        assert!(node.actual_operator_state().is_ok());
        node.operator
            .as_mut()
            .unwrap()
            .push(&json!({"value": "2"}))
            .unwrap();
        assert!(node.operator.as_ref().unwrap().checkpoint().is_err());
        assert!(node.actual_operator_state().is_ok());
        assert!(node.plugin["state"].is_null());
        assert!(node.checkpoint()["plugin_state"]["state"].is_null());
    }
}
