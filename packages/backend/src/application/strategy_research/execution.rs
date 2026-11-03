//! Actual finite mathematical observations. This value grants no Run or Freeze.
//! Installed numerical factories and the original native Strategy Executor are
//! compared independently; no precomputed Research signal enters that Executor.
use super::{RunSpecification, WORK, decision::evaluate_graph_columns};
use crate::{application::{factor_content::hash, research_admission::{PreparationError, PreparedInputs}, research_dataset::MaterializedDataset, research_run_execution::Control}, persistence::research_dataset::Store, workers::{algorithm::{AlgorithmProcess, describe_research_runtime}, trading_nodes::InstalledTradingNodes}};
use bigdecimal::{BigDecimal, num_bigint::BigInt};
use onlyalpha_calculation::{normalize_result_outputs, product::{Definition, Graph, normalize_scalar}};
use onlyalpha_calculation_bridge::{ChartInstallation, ProcessState, native_predicates::PredicateCalculation};
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp};
use onlyalpha_strategy::{Executor, NodeFailure, Program, Scope, SourceRevision};
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc, time::Duration};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "STRATEGY_RESEARCH_EVALUATION_INPUT_MISMATCH";
const UNAVAILABLE: &str = "STRATEGY_RESEARCH_EVALUATION_UNAVAILABLE";
const MISMATCH: &str = "STRATEGY_RESEARCH_CALCULATION_NOT_EQUIVALENT";
const DEADLINE: Duration = Duration::from_secs(10);
const GRAPH_CONTRACT: &str = "ONLYALPHA_CALCULATION_PLANES_OBSERVATION_V1";
const PROFILE_CONTRACT: &str = "ONLYALPHA_CALCULATION_NODE_PROFILE_OBSERVATION_V1";
const CASES: [&str; 6] = ["FLAT_SEQUENCE", "NEGATIVE_SLOPE_SEQUENCE", "POSITIVE_SLOPE_SEQUENCE", "QUANTIZATION_BOUNDARY", "WARMUP_AND_STEADY_STATE", "ZERO_BOUNDARY"];
// Temporary source-only diagnostics for the actual optimized technical probe.
// Static phases and source lines only: never payloads, values, hashes or grants.
fn phase(stage:&str) { eprintln!("[strategy-evaluation] phase={stage}"); }
#[track_caller]
fn invalid() -> &'static str {
    eprintln!("[strategy-evaluation] invalid line={}",std::panic::Location::caller().line());
    INVALID
}
fn mapped<T>(_: T) -> &'static str { invalid() }
fn rows(v: &Value) -> Result<&Vec<Value>> { v.as_array().ok_or_else(||invalid()) }
fn text(v: &Value) -> Result<&str> { v.as_str().ok_or_else(||invalid()) }
fn exact(v: &Value, keys: &[&str]) -> Result<()> { crate::application::private_strategy::exact(v, keys).map_err(mapped) }
fn scalar(v: Value) -> Result<Value> { normalize_scalar(&v, WORK).map_err(mapped) }
fn decimal(v: BigDecimal) -> Result<Value> { scalar(json!({"type":"DECIMAL","value":v.to_string()})) }
fn event(bar: &OnlyBar) -> Result<u64> { OnlyTimestamp::from_datetime(*bar.bar_end()).unix_nanos().to_string().parse().map_err(mapped) }
/// The original hold survives through this opaque observation's owning handoff.
/// There is no public constructor, deserializer or authorization conversion.
pub struct StrategyEvaluation { inputs: PreparedInputs, record: Value }
impl StrategyEvaluation {
    pub fn record(&self) -> &Value { &self.record }
    pub fn verify_runtime(&self) -> Result<()> { self.inputs.verify_runtime() }
    pub(crate) fn into_parts(self) -> (PreparedInputs, Value) { (self.inputs, self.record) }
    pub fn observe(inputs: PreparedInputs, specification: RunSpecification, datasets: &Store, installation: Arc<ChartInstallation>, native_version: &str, control: &Control) -> std::result::Result<Self, PreparationError> {
        control.check()?;
        inputs.verify_runtime()?;
        installation.verify().map_err(|_| UNAVAILABLE)?;
        phase("observe-pins");
        let prepared=inputs.record(); let spec=specification.record();
        if prepared["contract"]!="ONLYALPHA_STRATEGY_RESEARCH_PREPARED_INPUTS_V1"
            || prepared["run_specification_fingerprint"]!=specification.fingerprint()?
            || prepared["runtime_generation_fingerprint"]!=spec["runtime_generation_fingerprint"]
            || prepared["execution_binding"]!=spec["execution_binding"]
            || prepared["input_window"]!=spec["input_window"]
            || prepared["dataset_snapshot_fingerprint"]!=spec["scientific_specification"]["dataset_snapshot_fingerprint"]
            || prepared["algorithm_resolution"]["algorithm_artifact"]!=installation.artifact_fingerprint()
            || spec["algorithm_artifact_fingerprint"]!=installation.artifact_fingerprint()
            || inputs.runtime_manifest()["catalog_generation_fingerprint"]!=spec["catalog_generation_fingerprint"] {
                for (label,ok) in [
                    ("contract",prepared["contract"]=="ONLYALPHA_STRATEGY_RESEARCH_PREPARED_INPUTS_V1"),
                    ("run-specification",prepared["run_specification_fingerprint"]==specification.fingerprint()?),
                    ("generation",prepared["runtime_generation_fingerprint"]==spec["runtime_generation_fingerprint"]),
                    ("execution-binding",prepared["execution_binding"]==spec["execution_binding"]),
                    ("input-window",prepared["input_window"]==spec["input_window"]),
                    ("dataset",prepared["dataset_snapshot_fingerprint"]==spec["scientific_specification"]["dataset_snapshot_fingerprint"]),
                    ("resolved-algorithm",prepared["algorithm_resolution"]["algorithm_artifact"]==installation.artifact_fingerprint()),
                    ("spec-algorithm",spec["algorithm_artifact_fingerprint"]==installation.artifact_fingerprint()),
                    ("catalog",inputs.runtime_manifest()["catalog_generation_fingerprint"]==spec["catalog_generation_fingerprint"]),
                ] {if !ok {eprintln!("[strategy-evaluation] input-pin={label}");}}
                return Err(invalid().into());
            }
        phase("native-image");
        let image=describe_research_runtime(native_version).map_err(|_| UNAVAILABLE)?;
        if image["artifact"]!=spec["execution_binding"]["executor_artifact_sha256"] || image["version"]!=spec["execution_binding"]["executor_version"] || image["protocol"]!=spec["execution_binding"]["protocol"] { return Err("RESEARCH_EXECUTOR_IMAGE_MISMATCH".into()); }
        phase("dataset-reopen");
        let id=text(&prepared["dataset_materialization"]["materialization_id"])?;
        let retained=MaterializedDataset::load(datasets,id)?;
        let verified=datasets.load(text(&prepared["dataset_snapshot_fingerprint"])?)?;
        if retained.lineage()!=&prepared["dataset_materialization"] || retained.verified().manifest()!=verified.manifest() || verified.dataset().construction_fingerprint()!=text(&prepared["dataset_construction_fingerprint"])? { return Err(invalid().into()); }
        phase("dataset-axis");
        let bars=verified.dataset().bars()?;
        let window=&spec["input_window"];
        let ns=|key:&str|->Result<u64>{text(&window[key])?.parse().map_err(mapped)};
        let start=ns("dataset_event_start_ns")?;let end=ns("dataset_event_end_ns")?;let stride=ns("bar_ns")?;
        if bars.is_empty() || bars.len()>8192 || verified.dataset().definition()["instruments"].as_array().map(Vec::len)!=Some(1) || bars.len() as u64!=window["dataset_observation_capacity"].as_u64().ok_or_else(||invalid())? { return Err(invalid().into()); }
        for (index,bar) in bars.iter().enumerate() { if event(bar)?!=start.checked_add((index as u64).checked_mul(stride).ok_or_else(||invalid())?).ok_or_else(||invalid())? || event(bar)? >=end { return Err(invalid().into()); } }
        phase("graph-values");
        let graph=Graph::from_record(&spec["decision"]["decision_graph"],WORK).map_err(mapped)?;
        let targets=Graph::from_record(&spec["target_graph"],WORK).map_err(mapped)?;
        let mut actual=observe_graph(inputs.runtime_hold(),prepared,spec,&graph,Some(&targets),&bars,verified.dataset().definition(),&verified.manifest()["provenance"][0]["source_metadata"]["construction_recipe"],installation.clone(),control)?;
        phase("statistics");
        let statistics=statistics(&specification,&actual)?;
        let observation_start=ns("observation_start_ns")?;let observation_end=ns("observation_end_ns")?;
        let observation_count=bars.iter().map(event).collect::<Result<Vec<_>>>()?.into_iter().filter(|t|*t>=observation_start&&*t<observation_end).count();
        actual["schema_version"]=json!(1);actual["contract"]=json!("ONLYALPHA_STRATEGY_EVALUATION_OBSERVATION_V1");
        actual["run_specification_fingerprint"]=json!(specification.fingerprint()?);actual["dataset_snapshot_fingerprint"]=prepared["dataset_snapshot_fingerprint"].clone();actual["input_window"]=window.clone();actual["observation_count"]=json!(observation_count);
        actual["producer"]=json!({"native_image":image,"algorithm_artifact_fingerprint":installation.artifact_fingerprint()});actual["statistics"]=json!(statistics);
        if actual.to_string().len()>WORK {return Err(UNAVAILABLE.into());}
        inputs.verify_runtime()?;installation.verify().map_err(|_|UNAVAILABLE)?;control.check()?;
        Ok(Self{inputs,record:actual})
    }
}
/// Purely finite mathematical observation shared by Research and manual Backtest.
/// It does not construct a Research Context, Target, Run, report or admission.
pub(crate) fn observe_graph(runtime:Arc<crate::persistence::research_runtime::RuntimeInputHold>,prepared:&Value,spec:&Value,graph:&Graph,targets:Option<&Graph>,bars:&[OnlyBar],definition:&Value,recipe:&Value,installation:Arc<ChartInstallation>,control:&Control)->std::result::Result<Value,PreparationError> {
    control.check()?;runtime.verify()?;installation.verify().map_err(|_|UNAVAILABLE)?;
    if bars.is_empty()||bars.len()>8192{return Err(INVALID.into());}
    let columns=rows(&spec["input_window"]["dataset_columns"])?;
    let window=&spec["input_window"];
    let binding=rows(&spec["implementation_bindings"] )?.iter().map(|b|Ok((text(&b["node_fingerprint"])?.to_owned(),b.clone()))).collect::<Result<BTreeMap<_,_>>>()?;
    let runner=Runner{runtime:runtime.clone(),prepared,spec,graph,targets,bindings:binding,installation:installation.clone(),control,columns:columns.clone(),definition:definition.clone(),recipe:recipe.clone()};
        let q=graph.ordered_nodes().filter_map(|d|d.to_record()["numeric"]["output_quantum"].as_str().and_then(|s|s.parse::<BigDecimal>().ok())).min().ok_or(UNAVAILABLE)?;

        let controlled=controlled_cases(&bars[0],window,&q)?;

        let profiles=profile_inputs(&graph,&q)?;
        let mut work=bars.len();
        for (_,case) in &controlled { work=work.checked_add(case.len()).ok_or(UNAVAILABLE)?; }
        for node in &profiles { for case in rows(&node["cases"])? {work=work.checked_add(rows(&case["inputs"])?.len()).ok_or(UNAVAILABLE)?;} }
        if work>8192 {return Err(UNAVAILABLE.into());}

        let mut actual=runner.run_case(&bars,true,text(&prepared["dataset_snapshot_fingerprint"])?)?;

        let mut graph_cases=Vec::new();
        for (case_id,case) in controlled {control.check()?;let input=runner.input_rows(&case)?;let mut observation=runner.run_case(&case,false,&hash(&input)?)?;observation["case_id"]=json!(case_id);observation["rows"]=input;graph_cases.push(observation);}

        let node_profiles=runner.node_profiles(profiles)?;
    actual["graph_cases"]=json!(graph_cases);actual["node_profiles"]=json!(node_profiles);
    runtime.verify()?;installation.verify().map_err(|_|UNAVAILABLE)?;control.verify_joined()?;
    Ok(actual)
}
/// The canonical SourceRevision identity is unchanged; this helper grants nothing.
pub(crate) fn source_revision(graph:&Graph,bindings:&Value,signals:&Value,definition:&Value,recipe:&Value)->Result<SourceRevision> {
    let mut source=json!({"schema_version":1,"universe":{"kind":"SINGLE_INSTRUMENT","instruments":definition["instruments"]},"market_input_contract":{"schema_version":2,"data_kind":"BAR","bar_semantic":definition["bar_semantic"],"construction_requirement":{"schema_version":1,"kind":"EXACT_RECIPE","policy":null,"recipe":recipe},"observation_admission":"FINAL_ONLY"},"decision_graph_fingerprint":graph.fingerprint(),"implementation_bindings":bindings,"signal_semantics":signals});
    let mut identity=source.clone();identity["domain"]=json!("onlyalpha.strategy.revision");source["strategy_fingerprint"]=json!(hash(&identity)?);source["decision_graph"]=graph.to_record();
    SourceRevision::from_json(&source.to_string(),WORK).map_err(mapped)
}
fn input_rows(columns:&[Value],bars:&[OnlyBar])->Result<Value> {
        let mut result=Vec::new();
        for bar in bars {let record=bar.to_record();let mut values=serde_json::Map::new();for column in columns {let name=text(column)?;if !["open","high","low","close","volume"].contains(&name){return Err(UNAVAILABLE);}values.insert(name.into(),record[name]["value"].clone());}result.push(json!({"at_ns":event(bar)?,"values":values}));}
        Ok(json!(result))
    }
pub(crate) fn planned_graph_validation(graph:&Graph,bars:&[OnlyBar],window:&Value)->Result<(Vec<(String,Value)>,Vec<Value>)> {
    let q=graph.ordered_nodes().filter_map(|d|d.to_record()["numeric"]["output_quantum"].as_str().and_then(|s|s.parse::<BigDecimal>().ok())).min().ok_or(UNAVAILABLE)?;
    let cases=controlled_cases(bars.first().ok_or(INVALID)?,window,&q)?.into_iter().map(|(name,bars)|Ok((name,input_rows(rows(&window["dataset_columns"])?,&bars)?))).collect::<Result<Vec<_>>>()?;
    Ok((cases,profile_inputs(graph,&q)?))
}
struct Runner<'a> { runtime:Arc<crate::persistence::research_runtime::RuntimeInputHold>, prepared:&'a Value, spec:&'a Value, graph:&'a Graph, targets:Option<&'a Graph>, bindings:BTreeMap<String,Value>, installation:Arc<ChartInstallation>, control:&'a Control, columns:Vec<Value>, definition:Value, recipe:Value }
impl Runner<'_> {
    fn input_rows(&self,bars:&[OnlyBar])->Result<Value> {input_rows(&self.columns,bars)}
    fn research(&self,payload:Value)->std::result::Result<Value,PreparationError> {
        self.control.check()?;
        let hold=self.runtime.clone();
        let mut worker=AlgorithmProcess::research_resolution(&self.installation,text(&self.runtime.manifest()["runtime_generation_fingerprint"])?,Box::new(hold)).map_err(|_|UNAVAILABLE)?;
        let owner=worker.cancellation().map_err(|_|UNAVAILABLE)?;self.control.attach(owner.clone())?;
        worker.handshake_research(DEADLINE).map_err(|e|PreparationError::worker(e,owner.clone()))?;
        let mut result=worker.evaluate_research(payload,DEADLINE).map_err(|e|PreparationError::worker(e,owner.clone()))?;
        worker.terminate().map_err(|e|PreparationError::worker(e,owner.clone()))?;self.control.check()?;
        phase("research-resolution-response");
        let evaluation=result.as_object_mut().ok_or_else(||invalid())?.remove("evaluation").ok_or_else(||invalid())?;
        if result!=self.prepared["algorithm_resolution"] {return Err(invalid().into());}
        Ok(evaluation)
    }
    fn run_case(&self,bars:&[OnlyBar],restore:bool,source:&str)->std::result::Result<Value,PreparationError> {
        let input=self.input_rows(bars)?;
        phase("graph-research");
        let observed=self.research(json!({"contract":GRAPH_CONTRACT,"resolution":self.prepared["algorithm_resolution_request"],"rows":input}))?;
        let axis=rows(&input)?.iter().map(|row|row["at_ns"].clone()).collect::<Vec<_>>();
        if observed["schema_version"]!=1 || observed["contract"]!=GRAPH_CONTRACT || observed["axis"]!=json!(axis) || observed["input_fingerprint"]!=hash(&input)? {return Err(invalid().into());}
        phase("graph-feature-shape");
        let feature=if observed["feature"].is_null(){json!([])}else{
            let expected=Graph::from_record(&json!({"schema_version":1,"nodes":self.graph.to_record()["nodes"].as_array().ok_or_else(||invalid())?.iter().filter(|n|n["definition"]["kind"]!="PREDICATE").cloned().collect::<Vec<_>>()}),WORK).map_err(mapped)?;
            checked_evaluation(&observed["feature"],&expected,&axis,&input,&self.bindings)?
        };
        phase("graph-native-predicates");
        let raw=evaluate_graph_columns(self.graph,&input,&feature)?;
        phase("graph-feature-columns");
        let research_outputs=encode_columns(rows(&raw["outputs"] )?,self.graph,&self.bindings,"research_implementation_fingerprint",bars.len())?;
        phase("graph-target-columns");
        let targets=match self.targets {Some(targets)=>checked_target_evaluation(&observed["targets"],targets,&axis,&input,&self.prepared["algorithm_resolution"] )?,None=>{if !observed["targets"].is_null(){return Err(INVALID.into());}Vec::new()}};
        phase("graph-program");
        let (program,definitions,mapping)=self.program(source,&observed["trading_capabilities"])?;
        self.control.check()?;
        let control=self.control.clone();
        let observer=Arc::new(move |owner|control.attach(owner).map_err(|error|if error.recovery_owner().is_some()||error.code().contains("UNKNOWN"){NodeFailure::Unknown}else{NodeFailure::Known}));
        let port=InstalledTradingNodes::new_owned(self.installation.clone(),program.clone(),definitions,rows(&self.prepared["algorithm_resolution_request"]["sources"] )?.clone(),self.runtime.clone(),DEADLINE,observer).map_err(|failure|match failure {NodeFailure::Known=>PreparationError::from(UNAVAILABLE),NodeFailure::Unknown=>self.control.uncertain("RESEARCH_ALGORITHM_OUTCOME_UNKNOWN")})?;
        phase("graph-stream");
        let mut executor=Executor::new(program,port).map_err(mapped)?;
        let mut streaming:BTreeMap<String,Value>=self.graph.ordered_nodes().map(|d|{let r=d.to_record();(d.fingerprint(),Value::Object(r["outputs"].as_array().unwrap().iter().map(|p|(p["name"].as_str().unwrap().to_owned(),json!([]))).collect()))}).collect();
        let mut decisions=Vec::new();let mut restoration=Value::Null;
        for (index,bar) in bars.iter().enumerate() {
            self.control.check()?;
            let outcome=executor.process(bar,&OnlyTimestamp::from_datetime(*bar.bar_end()),&hash(&json!({"source":source,"at_ns":event(bar)?}))?).map_err(|error|if error.0.contains("UNKNOWN"){self.control.uncertain("RESEARCH_ALGORITHM_OUTCOME_UNKNOWN")}else{self.control.uncertain(MISMATCH)})?.to_record();
            let checkpoint=executor.capture_checkpoint().map_err(|_|self.control.uncertain("RESEARCH_ALGORITHM_OUTCOME_UNKNOWN"))?;
            let native=rows(&checkpoint["port"]["nodes"] )?.iter().map(|row|Ok((text(&row[0])?.to_owned(),row[1].clone()))).collect::<Result<BTreeMap<_,_>>>()?;
            for definition in self.graph.ordered_nodes() {let original=definition.fingerprint();let scope=executor.program().instance_scope(bar.instrument_id(),mapping.get(&original).ok_or_else(||invalid())?);let state=native.get(&scope).ok_or_else(||invalid())?;let ports=definition.to_record()["outputs"].as_array().ok_or_else(||invalid())?.clone();let outputs=if state["receipt"].is_null()||state["cursor"]["last_event_ns"]!=event(bar)?.to_string(){Value::Object(ports.iter().map(|p|(p["name"].as_str().unwrap().to_owned(),json!({"type":"NULL","value":null}))).collect())}else{state["receipt"]["outputs"].clone()};
                for port in ports {let name=text(&port["name"])?;streaming.get_mut(&original).ok_or_else(||invalid())?[name].as_array_mut().ok_or_else(||invalid())?.push(outputs[name].clone());}
            }
            let decision=if outcome["decision"].is_null(){Value::Null}else{json!({"eligibility":outcome["decision"]["eligibility"],"entry":outcome["decision"]["entry"],"exit":outcome["decision"]["exit"]})};
            if !decision.is_null(){for role in ["eligibility","entry","exit"] {let reference=&self.spec["decision"]["signal_semantics"][role];let node=text(&reference["node_fingerprint"])?;let column=research_outputs.iter().find(|r|r["node_fingerprint"]==node).ok_or_else(||invalid())?;let value=&column["values"][text(&reference["output_name"])?][index];if decision[role]!=if value["type"]=="NULL"{json!(false)}else{value["value"].clone()}{return Err(MISMATCH.into());}}}
            decisions.push(json!({"at_ns":event(bar)?,"status":outcome["status"],"decision":decision}));
            if restore && index+1==bars.len()/2 {
                phase("graph-fresh-restore");
                // Join the original child before constructing its explicit fresh
                // candidate. The same Control never replaces an uncertain owner.
                if let Some(owner)=executor.port().cancellation().map_err(|_|UNAVAILABLE)? {owner.cancel().map_err(|e|PreparationError::worker(e,owner.clone()))?;}
                self.control.check()?;
                let mut candidate=executor.restored_candidate(checkpoint.to_string().as_bytes(),&hash(&checkpoint)?).map_err(|_|self.control.uncertain("RESEARCH_ALGORITHM_OUTCOME_UNKNOWN"))?;
                let restored=candidate.capture_checkpoint().map_err(mapped)?;
                if restored!=checkpoint {return Err(MISMATCH.into());}
                restoration=json!({"processed_rows":index+1,"before_checkpoint_fingerprint":hash(&checkpoint)?,"restored_checkpoint_fingerprint":hash(&restored)?});executor=candidate;
            }
        }
        phase("graph-comparison");
        let streaming_outputs=streaming.into_iter().map(|(node,values)|json!({"node_fingerprint":node,"implementation_fingerprint":self.bindings[&node]["trading_implementation_fingerprint"],"values":values})).collect::<Vec<_>>();
        for (research,trading) in research_outputs.iter().zip(&streaming_outputs) {if research["node_fingerprint"]!=trading["node_fingerprint"]||research["values"]!=trading["values"]{return Err(MISMATCH.into());}}
        if let Some(owner)=executor.port().cancellation().map_err(|_|UNAVAILABLE)? {owner.cancel().map_err(|e|PreparationError::worker(e,owner.clone()))?;if owner.state()!=ProcessState::Joined{return Err(self.control.uncertain(UNAVAILABLE));}}
        drop(executor);self.control.check()?;
        Ok(json!({"axis":axis,"research_outputs":research_outputs,"streaming_outputs":streaming_outputs,"target_outputs":targets,"decisions":decisions,"restoration":restoration}))
    }
    fn program(&self,source:&str,capabilities:&Value)->Result<(Program,BTreeMap<String,Definition>,BTreeMap<String,String>)> {
        let value=source_revision(self.graph,&self.spec["implementation_bindings"],&self.spec["decision"]["signal_semantics"],&self.definition,&self.recipe)?;
        crate::workers::trading_program::materialize(&value,Scope{engine:"research-observation".parse().map_err(mapped)?,runtime:"finite-observation".parse().map_err(mapped)?,cluster:"decision".parse().map_err(mapped)?},text(&self.runtime.manifest()["runtime_generation_fingerprint"])?,source,self.installation.artifact_fingerprint(),capabilities).map_err(mapped)
    }

    fn node_profiles(&self,planned:Vec<Value>)->std::result::Result<Vec<Value>,PreparationError> {
        let definitions=self.graph.ordered_nodes().map(|d|(d.fingerprint(),d.to_record())).collect::<BTreeMap<_,_>>();
        let numerical=planned.iter().filter(|n|n["definition"]["kind"]!="PREDICATE").cloned().collect::<Vec<_>>();
        let mut observed=if numerical.is_empty(){Vec::new()}else{let result=self.research(json!({"schema_version":1,"contract":PROFILE_CONTRACT,"resolution":self.prepared["algorithm_resolution_request"],"nodes":numerical}))?;exact(&result,&["schema_version","contract","nodes"])?;if result["schema_version"]!=1||result["contract"]!=PROFILE_CONTRACT{return Err(invalid().into());}rows(&result["nodes"])?.clone()};
        for node in planned.iter().filter(|n|n["definition"]["kind"]=="PREDICATE") {self.control.check()?;let definition=Definition::from_record(&node["definition"],WORK).map_err(mapped)?;let predicate=PredicateCalculation::from_record(&node["definition"]).map_err(mapped)?;let mut cases=Vec::new();
            for case in rows(&node["cases"])? {let mut research=Vec::new();let mut trading=Vec::new();for input in rows(&case["inputs"])? {self.control.check()?;let raw=Value::Object(input.as_object().ok_or_else(||invalid())?.iter().map(|(name,v)|(name.clone(),if v["type"]=="NULL"{Value::Null}else{v["value"].clone()})).collect());
                    let convert=|output:Value|->Result<Value>{Ok(json!({"value":scalar(if output["value"].is_null(){json!({"type":"NULL","value":null})}else{json!({"type":"BOOLEAN","value":output["value"]})})?}))};
                    research.push(convert(predicate.evaluate(&raw).map_err(mapped)?)?);trading.push(convert(predicate.evaluate(&raw).map_err(mapped)?)?);
                }cases.push(json!({"case_id":case["case_id"],"inputs":case["inputs"],"research_outputs":research,"trading_outputs":trading}));}
            let id=definition.fingerprint();observed.push(json!({"node_fingerprint":id,"research_implementation_fingerprint":self.bindings[&id]["research_implementation_fingerprint"],"trading_implementation_fingerprint":self.bindings[&id]["trading_implementation_fingerprint"],"cases":cases}));
        }
        if observed.len()!=planned.len(){return Err(invalid().into());}
        let plans=planned.iter().map(|n|Ok((Definition::from_record(&n["definition"],WORK).map_err(mapped)?.fingerprint(),n))).collect::<Result<BTreeMap<_,_>>>()?;
        let mut result=BTreeMap::new();
        for mut node in observed {exact(&node,&["node_fingerprint","research_implementation_fingerprint","trading_implementation_fingerprint","cases"])?;let id=text(&node["node_fingerprint"])?.to_owned();let expected=plans.get(&id).ok_or_else(||invalid())?;
            for role in ["research_implementation_fingerprint","trading_implementation_fingerprint"] {if node[role]!=self.bindings[&id][role]{return Err(invalid().into());}}
            let mut actual_cases=BTreeMap::new();for case in rows(&node["cases"])? {exact(case,&["case_id","inputs","research_outputs","trading_outputs"])?;let name=text(&case["case_id"])?;if actual_cases.insert(name,case).is_some(){return Err(invalid().into());}}
            let expected_cases=rows(&expected["cases"])?;
            if actual_cases.len()!=expected_cases.len(){return Err(invalid().into());}
            for case in expected_cases {let actual=actual_cases.get(text(&case["case_id"])?) .ok_or_else(||invalid())?.to_owned();if actual["inputs"]!=case["inputs"]||actual["research_outputs"]!=actual["trading_outputs"]||rows(&actual["research_outputs"])?.len()!=rows(&case["inputs"])?.len(){return Err(MISMATCH.into());}for output in rows(&actual["research_outputs"])? {check_typed(output,&definitions[&id]["outputs"])?;}}
            let coverage=actual_cases.keys().map(|name|(*name).to_owned()).collect::<Vec<_>>();drop(actual_cases);node["profile_covered_cases"]=json!(coverage);if result.insert(id,node).is_some(){return Err(invalid().into());}
        }
        Ok(result.into_values().collect())
    }
}
fn check_typed(values:&Value,ports:&Value)->Result<()> {
    let values=values.as_object().filter(|m|!m.is_empty()&&m.len()<=64).ok_or_else(||invalid())?;
    let ports=rows(ports)?;
    if values.len()!=ports.len(){return Err(invalid());}
    for port in ports {
        let value=values.get(text(&port["name"])?).ok_or_else(||invalid())?;
        // Profile inputs and outputs use the existing Product tagged-scalar
        // codec, whose fixed-f Decimal spelling retains scale and signed zero.
        if normalize_scalar(value,WORK).map_err(mapped)?!=*value{return Err(invalid());}
        if value["type"]=="NULL" {
            if port["nullable"]!=true{return Err(invalid());}
        }else if value["type"]!=port["data_type"]{return Err(invalid());}
    }
    Ok(())
}
fn checked_evaluation(value:&Value,graph:&Graph,axis:&[Value],input:&Value,bindings:&BTreeMap<String,Value>)->Result<Value> {
    exact(value,&["schema_version","graph_fingerprint","input_fingerprint","axis","outputs"])?;
    if value["schema_version"]!=1||value["graph_fingerprint"]!=graph.fingerprint()||value["input_fingerprint"]!=hash(input)?||value["axis"]!=json!(axis){return Err(invalid());}
    let expected=graph.ordered_nodes().map(|d|d.fingerprint()).collect::<std::collections::BTreeSet<_>>();let mut result=BTreeMap::new();
    for output in rows(&value["outputs"])? {exact(output,&["node_fingerprint","implementation_fingerprint","values"])?;let id=text(&output["node_fingerprint"])?;if !expected.contains(id)||output["implementation_fingerprint"]!=bindings.get(id).ok_or_else(||invalid())?["research_implementation_fingerprint"]||result.insert(id.to_owned(),json!({"node_fingerprint":id,"values":output["values"]})).is_some(){return Err(invalid());}}
    if result.len()!=expected.len(){return Err(invalid());}Ok(json!(result.into_values().collect::<Vec<_>>()))
}
fn encode_columns(values:&[Value],graph:&Graph,bindings:&BTreeMap<String,Value>,role:&str,count:usize)->Result<Vec<Value>> {
    let mut observed=BTreeMap::new();for row in values{exact(row,&["node_fingerprint","values"])?;if observed.insert(text(&row["node_fingerprint"])?.to_owned(),&row["values"]).is_some(){return Err(invalid());}}
    let mut result=BTreeMap::new();
    for node in graph.ordered_nodes(){let id=node.fingerprint();let record=node.to_record();let raw=observed.remove(&id).ok_or_else(||invalid())?;let ports=rows(&record["outputs"])?;if raw.as_object().ok_or_else(||invalid())?.len()!=ports.len(){return Err(invalid());}let mut columns=serde_json::Map::new();for port in ports{let column=rows(&raw[text(&port["name"])?])?;if column.len()!=count{return Err(invalid());}let name=text(&port["name"])?;
            let values=column.iter().map(|value|->Result<Value>{
                let raw=scalar(if value.is_null(){json!({"type":"NULL","value":null})}else{json!({"type":port["data_type"],"value":value})})?;
                // Only the graph comparison plane crosses into the existing
                // native receipt representation. Raw SDK/profile rows stay exact.
                let normalized=normalize_result_outputs(&json!({(name):raw})).map_err(mapped)?;
                normalized.get(name).cloned().ok_or_else(||invalid())
            }).collect::<Result<Vec<_>>>()?;for value in &values{check_typed(&json!({(text(&port["name"])?):value}),&json!([port]))?;}columns.insert(text(&port["name"])?.into(),json!(values));}result.insert(id.clone(),json!({"node_fingerprint":id,"implementation_fingerprint":bindings.get(&id).ok_or_else(||invalid())?[role],"values":columns}));}
    if !observed.is_empty(){return Err(invalid());}Ok(result.into_values().collect())
}
fn checked_target_evaluation(value:&Value,graph:&Graph,axis:&[Value],input:&Value,resolved:&Value)->Result<Vec<Value>> {
    let mut bindings=BTreeMap::new();for node in graph.ordered_nodes(){let id=node.fingerprint();let matches=rows(&resolved["nodes"] )?.iter().filter(|n|n["definition_fingerprint"]==id).collect::<Vec<_>>();if matches.len()!=1{return Err(invalid());}let actual=rows(&matches[0]["implementations"])?;if actual.len()!=1||actual[0]["backend_kind"]!="RESEARCH"{return Err(invalid());}bindings.insert(id,json!({"research_implementation_fingerprint":actual[0]["implementation_fingerprint"]}));}
    let columns=checked_evaluation(value,graph,axis,input,&bindings)?;encode_columns(rows(&columns)?,graph,&bindings,"research_implementation_fingerprint",axis.len())
}
fn statistics(spec:&RunSpecification,actual:&Value)->Result<Vec<Value>> {
    let feature=rows(&actual["research_outputs"] )?.iter().map(|r|Ok((text(&r["node_fingerprint"])?.to_owned(),r))).collect::<Result<BTreeMap<_,_>>>()?;
    let target=rows(&actual["target_outputs"] )?.iter().map(|r|Ok((text(&r["node_fingerprint"])?.to_owned(),r))).collect::<Result<BTreeMap<_,_>>>()?;
    let mut result=Vec::new();for plan in spec.statistics_intents()? {if plan["definition"]["minimum_observations"].as_u64().is_none_or(|n|n<2){return Err(invalid());}let x=&feature.get(text(&plan["feature"]["node_fingerprint"]) ?).ok_or_else(||invalid())?["values"][text(&plan["feature"]["output_name"])?];let y=&target.get(text(&plan["target"]["node_fingerprint"]) ?).ok_or_else(||invalid())?["values"][text(&plan["target"]["output_name"])?];let axis=rows(&actual["axis"])?;if rows(x)?.len()!=axis.len()||rows(y)?.len()!=axis.len(){return Err(invalid());}let rows=axis.iter().enumerate().map(|(i,t)|json!({"ts_event_ns":t,"statistic_value":null,"sample_count":u8::from(x[i]["type"]!="NULL"&&y[i]["type"]!="NULL"),"status":"INSUFFICIENT_OBSERVATIONS"})).collect::<Vec<_>>();result.push(json!({"statistics_fingerprint":hash(&plan)?,"plan":plan,"rows":rows}));}
    Ok(result)
}
fn controlled_cases(base:&OnlyBar,window:&Value,q:&BigDecimal)->Result<Vec<(String,Vec<OnlyBar>)>> {
    let count=window["warmup_bars"].as_u64().and_then(|n|n.checked_add(22)).filter(|n|*n<=8192).ok_or(UNAVAILABLE)?;
    let stride=text(&window["bar_ns"])?.parse::<u64>().map_err(mapped)?;
    let origin=OnlyTimestamp::from_datetime(*base.bar_start()).unix_nanos().clone();
    let mut result=Vec::new();for name in CASES {let mut bars=Vec::new();for index in 0..count{let mut record=base.to_record();let price=match name{"FLAT_SEQUENCE"=>BigDecimal::from(100),"POSITIVE_SLOPE_SEQUENCE"=>BigDecimal::from(100)+BigDecimal::new(BigInt::from(index),3),"NEGATIVE_SLOPE_SEQUENCE"=>BigDecimal::from(100)+BigDecimal::new(BigInt::from(count-index),3),"QUANTIZATION_BOUNDARY"=>BigDecimal::from(100)+q*BigDecimal::new(BigInt::from(if index%2==0{5}else{15}),1),"ZERO_BOUNDARY"=>BigDecimal::from(100),_=>BigDecimal::from(100+index%5)};
            let value=decimal(price)?["value"].clone();for field in ["open","high","low","close"]{record[field]=json!({"schema_version":1,"value":value,"precision":18});}
            record["volume"]=json!({"schema_version":1,"value":if name=="ZERO_BOUNDARY"&&index%3==0{"0"}else{"2"},"precision":18});
            let start=OnlyTimestamp::from_unix_nanos(&origin+BigInt::from(index)*BigInt::from(stride)).to_datetime_exact().map_err(mapped)?;let end=OnlyTimestamp::from_unix_nanos(&origin+BigInt::from(index+1)*BigInt::from(stride)).to_datetime_exact().map_err(mapped)?;
            record["bar_start"]=json!(start.to_string());record["trading_day"]=json!(start.date().to_string());for field in ["bar_end","ts_event","ts_init"]{record[field]=json!(end.to_string());}bars.push(OnlyBar::from_record(&record).map_err(mapped)?);
        }result.push((name.into(),bars));}Ok(result)
}
fn profile_inputs(graph:&Graph,q:&BigDecimal)->Result<Vec<Value>> {
    let mut result=Vec::new();let mut work=0usize;
    for node in graph.ordered_nodes(){let definition=node.to_record();let inputs=rows(&definition["inputs"])?;let outputs=rows(&definition["outputs"])?;let count=definition["warmup"]["minimum_observations"].as_u64().and_then(|n|n.checked_add(22)).ok_or(UNAVAILABLE)?.max((inputs.len() as u64)*2+3);if count>8192{return Err(UNAVAILABLE);}let nullable=inputs.iter().filter(|p|p["nullable"]==true).collect::<Vec<_>>();let booleans=inputs.iter().filter(|p|p["data_type"]=="BOOLEAN").collect::<Vec<_>>();
        let mut names=CASES.iter().copied().collect::<Vec<_>>();if !nullable.is_empty(){names.push("NULLABLE_INPUT_SEMANTICS");}if !booleans.is_empty(){names.push("BOOLEAN_TRUTH_NULL_SEMANTICS");}if outputs.len()>1{names.push("MULTI_OUTPUT_ALIGNMENT");}names.sort();let mut cases=Vec::new();
        for name in names {let count=if name=="BOOLEAN_TRUTH_NULL_SEMANTICS"{3u64.checked_pow(booleans.len() as u32).filter(|n|*n<=8192).ok_or(UNAVAILABLE)?}else{count};work=work.checked_add(usize::try_from(count).map_err(mapped)?).filter(|n|*n<=8192).ok_or(UNAVAILABLE)?;let mut values=Vec::new();
            for index in 0..count{let mut row=serde_json::Map::new();let mut truth=index;for port in inputs {let key=text(&port["name"])?;let value=match text(&port["data_type"])?{"DECIMAL"=>{let value=match name{"ZERO_BOUNDARY"=>BigDecimal::from(0),"POSITIVE_SLOPE_SEQUENCE"=>BigDecimal::from(100+index),"NEGATIVE_SLOPE_SEQUENCE"=>BigDecimal::from(100)-BigDecimal::from(index),"QUANTIZATION_BOUNDARY"=>q*BigDecimal::new(BigInt::from(if index%2==0{5}else{15}),1),"WARMUP_AND_STEADY_STATE"|"MULTI_OUTPUT_ALIGNMENT"=>BigDecimal::from(10+index%5),_=>BigDecimal::from(100)};decimal(value)?},"BOOLEAN"=>if name=="BOOLEAN_TRUTH_NULL_SEMANTICS"{let value=match truth%3{0=>json!({"type":"BOOLEAN","value":false}),1=>json!({"type":"BOOLEAN","value":true}),_=>json!({"type":"NULL","value":null})};truth/=3;value}else{json!({"type":"BOOLEAN","value":index%2==0})},_=>return Err(UNAVAILABLE)};row.insert(key.into(),value);}
                if name=="NULLABLE_INPUT_SEMANTICS"{for (position,port) in nullable.iter().enumerate(){if index==count/2+position as u64{row.insert(text(&port["name"])?.into(),json!({"type":"NULL","value":null}));}}}
                if name=="QUANTIZATION_BOUNDARY"&&definition["kind"]=="FACTOR"{for port in inputs{row.insert(text(&port["name"])?.into(),decimal(BigDecimal::from(1))?);}for (key,binding) in definition["input_bindings"].as_object().ok_or_else(||invalid())?{if binding["source"]=="bar.close"{row.insert(key.clone(),decimal(BigDecimal::from(1)+q*BigDecimal::new(BigInt::from(if index%2==0{5}else{15}),1))?);}}}
                if name=="QUANTIZATION_BOUNDARY"&&definition["kind"]=="PREDICATE" {
                    let anchor=if definition["parameters"]["literal"]["type"]=="DECIMAL"{text(&definition["parameters"]["literal"]["value"])?.parse::<BigDecimal>().map_err(mapped)?}else{BigDecimal::from(100)};
                    let step=match index%4{0=>-(q*BigDecimal::new(BigInt::from(5),1)),1=>BigDecimal::from(0),2=>q*BigDecimal::new(BigInt::from(5),1),_=>q*BigDecimal::new(BigInt::from(15),1)};
                    let mut first=true;for port in inputs {if port["data_type"]=="DECIMAL"{let value=if first{first=false;&anchor+&step}else{anchor.clone()};row.insert(text(&port["name"])?.into(),decimal(value)?);}}
                }
                check_typed(&Value::Object(row.clone()),&definition["inputs"])?;values.push(Value::Object(row));
            }cases.push(json!({"case_id":name,"inputs":values}));
        }result.push(json!({"definition":definition,"cases":cases}));
    }Ok(result)
}


#[cfg(test)]
mod scalar_boundary_tests {
    use super::*;

    #[test]
    fn product_profile_scalars_retain_scale_and_strict_port_types() {
        let ports=json!([{"name":"value","data_type":"DECIMAL","nullable":true}]);
        let scaled=json!({"type":"DECIMAL","value":"101.000000000000"});
        assert_eq!(normalize_scalar(&scaled,WORK).unwrap(),scaled);
        let output=json!({"value":scaled});
        assert_eq!(normalize_result_outputs(&output).unwrap(),json!({"value":{"type":"DECIMAL","value":"101"}}));
        assert!(check_typed(&output,&ports).is_ok(),"legal Product profile output is not a native receipt");
        for invalid in [
            json!({"value":{"type":"DECIMAL","value":101}}),
            json!({"value":{"type":"BOOLEAN","value":true}}),
            json!({"value":{"type":"DECIMAL","value":"101","extra":true}}),
            json!({"value":{"type":"DECIMAL","value":"101"},"extra":{"type":"DECIMAL","value":"1"}}),
        ] {assert!(check_typed(&invalid,&ports).is_err());}
        let nonnullable=json!([{"name":"value","data_type":"DECIMAL","nullable":false}]);
        assert!(check_typed(&json!({"value":{"type":"NULL","value":null}}),&nonnullable).is_err());
    }

    #[test]
    fn graph_observation_uses_native_numeric_values_without_rewriting_raw_profiles() {
        let fixture:Value=serde_json::from_str(include_str!("../../../tests/application/fixtures/strategy_calculations.json")).unwrap();
        let declaration=fixture["nodes"].as_array().unwrap().iter().find(|n|n["definition"]["type_id"]=="onlyalpha.operator.delay").unwrap();
        let graph=Graph::from_record(&json!({"schema_version":1,"nodes":[{"alias":"delay","definition":declaration["definition"]}]}),WORK).unwrap();
        let id=graph.ordered_nodes().next().unwrap().fingerprint();
        let raw=json!({"node_fingerprint":id,"values":{"value":[null,"101.000000000000","101.200000000000"]}});
        let original=raw.clone();
        let bindings=BTreeMap::from([(id.clone(),json!({"research_implementation_fingerprint":"a".repeat(64)}))]);
        let observed=encode_columns(&[raw.clone()],&graph,&bindings,"research_implementation_fingerprint",3).unwrap();
        assert_eq!(json!(observed),json!([{"node_fingerprint":id,"implementation_fingerprint":"a".repeat(64),"values":{"value":[
            {"type":"NULL","value":null},{"type":"DECIMAL","value":"101"},{"type":"DECIMAL","value":"101.2"}
        ]}}]));
        assert_eq!(raw,original,"the raw SDK/profile observation retains its Product spelling");
    }
}


#[cfg(test)]
mod controlled_domain_tests {
    use super::*;

    fn graph() -> Graph {
        let fixture: Value = serde_json::from_str(include_str!("../../../tests/application/fixtures/strategy_calculations.json")).unwrap();
        Graph::from_record(&json!({"schema_version":1,"nodes":fixture["nodes"].as_array().unwrap().iter().map(|node|json!({"alias":null,"definition":node["definition"]})).collect::<Vec<_>>()}),WORK).unwrap()
    }

    #[test]
    fn controlled_graph_cases_stay_in_forward_return_price_domain_and_keep_zero_volume() {
        let graph=graph();
        let stride=60_000_000_000;
        let window=super::super::decision::canonical_input_window(&graph,100*stride,820*stride,stride,["bar.close"]).unwrap();
        let base: Value=include_str!("../../../../../test-data/domain/fact-records-v1.jsonl").lines()
            .map(|line|serde_json::from_str::<Value>(line).unwrap()).find(|row|row["id"]=="bar").unwrap()["record"].clone();
        let base=OnlyBar::from_record(&base).unwrap();
        let cases=controlled_cases(&base,&window,&"0.000000000001".parse().unwrap()).unwrap();
        assert_eq!(cases.len(),CASES.len());
        for (name,bars) in &cases {
            assert_eq!(bars.len() as u64,window["warmup_bars"].as_u64().unwrap()+22);
            for bar in bars {
                let record=bar.to_record();
                for field in ["open","high","low","close"] {
                    let price:BigDecimal=record[field]["value"].as_str().unwrap().parse().unwrap();
                    assert!(price>BigDecimal::from(0),"{name} cannot send {field}=0 to the positive-price Forward Return Target");
                }
            }
            assert!(bars.windows(2).all(|pair|event(&pair[1]).unwrap()-event(&pair[0]).unwrap()==stride));
        }
        let zero=&cases.iter().find(|(name,_)|name=="ZERO_BOUNDARY").unwrap().1;
        assert!(zero.iter().any(|bar|bar.to_record()["volume"]["value"].as_str().unwrap().parse::<BigDecimal>().unwrap()==BigDecimal::from(0)));
        assert!(zero.iter().any(|bar|bar.to_record()["volume"]["value"].as_str().unwrap().parse::<BigDecimal>().unwrap()>BigDecimal::from(0)));
    }

    #[test]
    fn node_profiles_still_exercise_literal_zero_for_every_decimal_operand() {
        let graph=graph();
        let planned=profile_inputs(&graph,&"0.000000000001".parse().unwrap()).unwrap();
        assert_eq!(planned.len(),graph.ordered_nodes().count());
        for node in planned {
            let case=node["cases"].as_array().unwrap().iter().find(|case|case["case_id"]=="ZERO_BOUNDARY").unwrap();
            let inputs=case["inputs"].as_array().unwrap();
            assert!(inputs.len()>node["definition"]["warmup"]["minimum_observations"].as_u64().unwrap() as usize);
            for port in node["definition"]["inputs"].as_array().unwrap().iter().filter(|port|port["data_type"]=="DECIMAL") {
                assert!(inputs.iter().all(|row|row[port["name"].as_str().unwrap()]==json!({"type":"DECIMAL","value":"0"})),"graph-domain constraints must not remove direct zero operands from P9 profiles");
            }
        }
    }
}
