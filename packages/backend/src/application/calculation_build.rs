//! 精确图的受控构建证明。仅构建准备可产生；作业执行及恢复只消费原证明。
use super::{
    factor_content::hash, research_admission::PreparationError, research_run_execution::Control,
};
use crate::persistence::{postgres::bounds, research_runtime::RuntimeInputHold};
use onlyalpha_calculation::product::Graph;
use onlyalpha_calculation_bridge::ChartInstallation;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp};
use serde_json::{Value, json};
use std::sync::Arc;
use tokio_postgres::{Client, Transaction};
const INVALID: &str = "CALCULATION_BUILD_PROOF_MISMATCH";
const MISSING: &str = "CALCULATION_BUILD_PROOF_MISSING";
const UNAVAILABLE: &str = "CALCULATION_BUILD_PROOF_UNAVAILABLE";
const LIMIT: usize = 8 * 1024 * 1024;
const CONTRACT: &str = "ONLYALPHA_CALCULATION_BUILD_PROOF_V1";
type Result<T> = std::result::Result<T, &'static str>;
#[track_caller]
fn mismatch() -> &'static str {
    eprintln!(
        "[calculation-build] invalid line={}",
        std::panic::Location::caller().line()
    );
    INVALID
}
#[track_caller]
fn array(value: &Value) -> Result<&Vec<Value>> {
    value.as_array().ok_or_else(mismatch)
}
fn canonical(value: &Value) -> Result<String> {
    let raw = onlyalpha_metadata_json::canonical_json(&value.to_string(), LIMIT * 8)
        .map_err(|_| UNAVAILABLE)?;
    if raw.len() > LIMIT {
        return Err(UNAVAILABLE);
    }
    Ok(raw)
}
/// Strip only Target inputs and observations. All signal definitions, exact
/// parameters, Source artifacts and installed implementation records remain.
pub(crate) fn signal_preparation(prepared: &Value) -> Result<Value> {
    let mut value = json!({"algorithm_resolution_request":prepared["algorithm_resolution_request"],"algorithm_resolution":prepared["algorithm_resolution"]});
    if value["algorithm_resolution"]["contract"] == "ONLYALPHA_NATIVE_SIGNAL_TARGET_RESOLUTION_V1" {
        value["algorithm_resolution_request"]["target_resolution_request"] = Value::Null;
        value["algorithm_resolution"]["target_resolution"] = Value::Null;
    }
    let request = &mut value["algorithm_resolution_request"];
    let instances = array(&request["instances"])?
        .iter()
        .filter(|n| n["type_reference"]["kind"] != "TARGET")
        .cloned()
        .collect::<Vec<_>>();
    request["instances"] = json!(instances);
    request["target_artifact"] = Value::Null;
    let observation = &mut value["algorithm_resolution"];
    let nodes = array(&observation["nodes"])?
        .iter()
        .filter(|n| n["definition"]["kind"] != "TARGET")
        .cloned()
        .collect::<Vec<_>>();
    observation["nodes"] = json!(nodes);
    observation["target_artifact_sha256"] = Value::Null;
    observation["target_resources_fingerprint"] = Value::Null;
    Ok(value)
}
pub(crate) fn context(
    prepared: &Value,
    spec: &Value,
    definition: &Value,
    recipe: &Value,
) -> Result<Value> {
    let graph =
        Graph::from_record(&spec["decision"]["decision_graph"], LIMIT).map_err(|_| mismatch())?;
    let requirements =
        onlyalpha_calculation::finite_input::requirements(&graph, 8192).map_err(|_| mismatch())?;
    let columns = requirements
        .sources()
        .iter()
        .map(|s| {
            s.strip_prefix("bar.")
                .filter(|s| ["open", "high", "low", "close", "volume"].contains(s))
                .ok_or_else(mismatch)
        })
        .collect::<Result<Vec<_>>>()?;
    let stride = definition["bar_semantic"]["formation"]["stride_minutes"]
        .as_u64()
        .and_then(|n| n.checked_mul(60_000_000_000))
        .filter(|n| *n > 0)
        .ok_or_else(mismatch)?;
    if definition["instruments"].as_array().map(Vec::len) != Some(1) {
        return Err(mismatch());
    }
    let end = OnlyTimestamp::from_unix_nanos(stride.into())
        .to_datetime_exact()
        .map_err(|_| mismatch())?
        .to_string();
    let instrument = definition["instruments"][0]
        .as_str()
        .ok_or_else(mismatch)?
        .parse::<onlyalpha_domain::identifiers::OnlyInstrumentId>()
        .map_err(|_| mismatch())?;
    let seed = json!({"schema_version":1,"bar_type":{"schema_version":2,"instrument_id":instrument.to_record(),"semantic":definition["bar_semantic"]},
        "open":{"schema_version":1,"value":"100","precision":18},"high":{"schema_version":1,"value":"100","precision":18},"low":{"schema_version":1,"value":"100","precision":18},"close":{"schema_version":1,"value":"100","precision":18},"volume":{"schema_version":1,"value":"2","precision":18},"quote_volume":null,"turnover":null,"trade_count":null,"open_interest":null,
        "bar_start":"1970-01-01T00:00:00Z","bar_end":end,"ts_event":end,"ts_init":end,"is_closed":true,"revision":0,"adjustment_type":definition["bar_semantic"]["adjustment_policy"],"trading_day":"1970-01-01","session_type":"CONTINUOUS"});
    let seed = OnlyBar::from_record(&seed)
        .map_err(|_| mismatch())?
        .to_record();
    let signal = signal_preparation(prepared)?;
    Ok(
        json!({"schema_version":1,"contract":CONTRACT,"decision":spec["decision"],"implementation_bindings":spec["implementation_bindings"],"execution_binding":prepared["execution_binding"],
        "algorithm_resolution_request_fingerprint":hash(&signal["algorithm_resolution_request"] )?,"algorithm_resolution_fingerprint":hash(&signal["algorithm_resolution"] )?,
        "market_profile":{"instruments":definition["instruments"],"bar_semantic":definition["bar_semantic"],"construction_recipe":recipe},"seed":seed,
        "window":{"warmup_bars":requirements.history(),"bar_ns":stride.to_string(),"dataset_columns":columns}}),
    )
}
/// Validate the complete retained proof and deterministic corpus, without
/// executing either mathematical implementation or creating a new proof.
pub(crate) fn verify(proof: &Value, expected: &Value) -> Result<()> {
    super::private_strategy::exact(
        proof,
        &[
            "schema_version",
            "contract",
            "build_key",
            "context",
            "graph_cases",
            "node_profiles",
            "proof_fingerprint",
        ],
    )?;
    let mut body = proof.clone();
    body.as_object_mut()
        .ok_or_else(mismatch)?
        .remove("proof_fingerprint");
    if proof["schema_version"] != 1
        || proof["contract"] != CONTRACT
        || proof["context"] != *expected
        || proof["build_key"] != hash(expected)?
        || proof["proof_fingerprint"] != hash(&body)?
    {
        return Err(mismatch());
    }
    let graph = Graph::from_record(&expected["decision"]["decision_graph"], LIMIT)
        .map_err(|_| mismatch())?;
    let seed = OnlyBar::from_record(&expected["seed"]).map_err(|_| mismatch())?;
    let (cases, profiles) =
        super::strategy_research::planned_graph_validation(&graph, &[seed], &expected["window"])?;
    if array(&proof["graph_cases"])?.len() != cases.len()
        || array(&proof["node_profiles"])?.len() != profiles.len()
    {
        return Err(mismatch());
    }
    for (actual, (name, inputs)) in array(&proof["graph_cases"])?.iter().zip(cases) {
        if actual["case_id"] != name || actual["rows"] != inputs || !actual["restoration"].is_null()
        {
            return Err(mismatch());
        }
        crate::persistence::strategy_validation::verify_controlled_case(
            &graph,
            &expected["implementation_bindings"],
            &expected["decision"]["signal_semantics"],
            actual,
        )?;
    }
    for planned in profiles {
        let node =
            onlyalpha_calculation::product::Definition::from_record(&planned["definition"], LIMIT)
                .map_err(|_| mismatch())?;
        let observed = array(&proof["node_profiles"])?
            .iter()
            .filter(|p| p["node_fingerprint"] == node.fingerprint())
            .collect::<Vec<_>>();
        if observed.len() != 1
            || array(&observed[0]["cases"])?.len() != array(&planned["cases"])?.len()
        {
            return Err(mismatch());
        }
        for (actual, planned) in array(&observed[0]["cases"])?
            .iter()
            .zip(array(&planned["cases"])?)
        {
            if actual["case_id"] != planned["case_id"] || actual["inputs"] != planned["inputs"] {
                return Err(mismatch());
            }
        }
    }
    crate::persistence::research_evidence::strategy::equivalence::derive(
        &graph,
        &expected["implementation_bindings"],
        proof,
    )
    .map_err(|_| mismatch())?;
    Ok(())
}
pub(crate) fn verify_reference(
    prepared: &Value,
    spec: &Value,
    definition: &Value,
    recipe: &Value,
    observation: &Value,
) -> Result<()> {
    let proof = &prepared["build_certification"];
    verify(proof, &context(prepared, spec, definition, recipe)?)?;
    if observation["build_certification"] != reference(proof)
        || observation["graph_cases"] != proof["graph_cases"]
        || observation["node_profiles"] != proof["node_profiles"]
    {
        return Err(mismatch());
    }
    Ok(())
}
pub(crate) fn reference(proof: &Value) -> Value {
    json!({"build_key":proof["build_key"],"proof_fingerprint":proof["proof_fingerprint"]})
}
pub(crate) struct Inputs {
    pub programs: Vec<crate::application::factor_build::ReadyFactorBinding>,
    pub runtime: Arc<RuntimeInputHold>,
    pub prepared: Value,
    pub specification: Value,
    pub definition: Value,
    pub recipe: Value,
    pub installation: Arc<ChartInstallation>,
    pub control: Control,
}
async fn read(tx: &Transaction<'_>, key: &str, expected: &Value) -> Result<Option<Value>> {
    let row=tx.query_opt("SELECT octet_length(payload),CASE WHEN octet_length(payload)<=8388608 THEN payload END,proof_fingerprint FROM public.calculation_build_proof WHERE build_key=$1",&[&key]).await.map_err(|_| UNAVAILABLE)?;
    let Some(row) = row else {
        return Ok(None);
    };
    if row.get::<_, i32>(0) > LIMIT as i32 {
        return Err(UNAVAILABLE);
    }
    let raw: String = row.get::<_, Option<String>>(1).ok_or(UNAVAILABLE)?;
    let mut proof: Value = serde_json::from_str(&raw).map_err(|_| mismatch())?;
    if canonical(&proof)? != raw || proof.get("proof_fingerprint").is_some() {
        return Err(mismatch());
    }
    proof["proof_fingerprint"] = json!(row.get::<_, String>(2));
    verify(&proof, expected)?;
    Ok(Some(proof))
}
pub(crate) async fn verify_fact(tx: &Transaction<'_>, proof: &Value) -> Result<()> {
    if proof.is_null() {
        return Err(MISSING);
    }
    let key = proof["build_key"]
        .as_str()
        .filter(|s| crate::is_sha256_hex(s))
        .ok_or_else(mismatch)?;
    let actual = read(tx, key, &proof["context"]).await?.ok_or(MISSING)?;
    if actual != *proof {
        return Err(mismatch());
    }
    Ok(())
}
/// The read path never repairs. Initial explicit construction preparation may
/// build under one transaction lock; a second concurrent builder receives Busy.
pub(crate) async fn prepare(
    client: &mut Client,
    inputs: Inputs,
    allow_build: bool,
) -> std::result::Result<Value, PreparationError> {
    let timing = std::time::Instant::now();
    inputs.runtime.verify()?;
    inputs.installation.verify().map_err(|_| UNAVAILABLE)?;
    inputs.control.check()?;
    let expected = context(
        &inputs.prepared,
        &inputs.specification,
        &inputs.definition,
        &inputs.recipe,
    )?;
    let key = hash(&expected)?;
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .read_only(!allow_build)
        .start()
        .await
        .map_err(|_| UNAVAILABLE)?;
    bounds(&tx).await.map_err(|_| UNAVAILABLE)?;
    if let Some(proof) = read(&tx, &key, &expected).await? {
        inputs.runtime.verify()?;
        inputs.installation.verify().map_err(|_| UNAVAILABLE)?;
        inputs.control.check()?;
        tx.commit().await.map_err(|_| UNAVAILABLE)?;
        eprintln!(
            "[calculation-build] phase=proof-loaded elapsed_us={}",
            timing.elapsed().as_micros()
        );
        return Ok(proof);
    }
    if !allow_build {
        return Err(MISSING.into());
    }
    tx.batch_execute("SET LOCAL synchronous_commit=on")
        .await
        .map_err(|_| UNAVAILABLE)?;
    let lock = i64::from_str_radix(&key[..15], 16).map_err(|_| mismatch())?;
    if !tx
        .query_one("SELECT pg_catalog.pg_try_advisory_xact_lock($1)", &[&lock])
        .await
        .map_err(|_| UNAVAILABLE)?
        .get::<_, bool>(0)
    {
        return Err("CALCULATION_BUILD_PROOF_BUSY".into());
    }
    if let Some(proof) = read(&tx, &key, &expected).await? {
        inputs.runtime.verify()?;
        inputs.installation.verify().map_err(|_| UNAVAILABLE)?;
        inputs.control.check()?;
        tx.commit().await.map_err(|_| UNAVAILABLE)?;
        eprintln!(
            "[calculation-build] phase=proof-loaded elapsed_us={}",
            timing.elapsed().as_micros()
        );
        return Ok(proof);
    }
    let inputs_native = inputs.prepared["algorithm_resolution"]["contract"]
        == "ONLYALPHA_NATIVE_SIGNAL_TARGET_RESOLUTION_V1";
    let guarded = inputs.control.clone();
    let runtime = inputs.runtime.clone();
    let installation = inputs.installation.clone();
    let built =
        tokio::task::spawn_blocking(move || super::strategy_research::certify_graph(inputs))
            .await
            .map_err(|_| guarded.uncertain("CALCULATION_BUILD_PROOF_OUTCOME_UNKNOWN"))??;
    if inputs_native {
        guarded.check()?;
    } else {
        guarded.verify_joined()?;
    }
    runtime.verify()?;
    installation.verify().map_err(|_| UNAVAILABLE)?;
    verify(&built, &expected)?;
    let mut body = built.clone();
    body.as_object_mut()
        .ok_or_else(mismatch)?
        .remove("proof_fingerprint");
    let raw = canonical(&body)?;
    let fingerprint = built["proof_fingerprint"].as_str().ok_or_else(mismatch)?;
    tx.execute("INSERT INTO public.calculation_build_proof(build_key,proof_fingerprint,payload) VALUES($1,$2,$3)",&[&key,&fingerprint,&raw]).await.map_err(|_| UNAVAILABLE)?;
    tx.commit()
        .await
        .map_err(|_| guarded.uncertain("CALCULATION_BUILD_PROOF_OUTCOME_UNKNOWN"))?;
    eprintln!(
        "[calculation-build] phase=proof-built elapsed_us={}",
        timing.elapsed().as_micros()
    );
    Ok(built)
}
