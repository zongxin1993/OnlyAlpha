//! The admitted Application process. Kernel transitions remain direct typed calls.
use onlyalpha_backtest::{Inputs, RunLoop, RunSpec, Trading};
use onlyalpha_calculation_bridge::{StrategyNodes, StrategyPreparation, Worker, fingerprint};
use onlyalpha_domain::{
    base::OnlyDomainModel, calendar::OnlyTradingCalendar, identifiers::OnlyInstrumentId,
    market::OnlyBarType,
};
use onlyalpha_market_data_pipeline::{construction::*, delivery::*, state::*, *};
use onlyalpha_strategy::*;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    error::Error,
    fs::{self, OpenOptions},
    io::{BufRead, Read, Write},
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};
type Result<T> = std::result::Result<T, Box<dyn Error>>;
const PROTOCOL: &str = "onlyalpha.backtest.driver/1";
const MAX_FRAME: u64 = 32 * 1024 * 1024;
const DEADLINE: Duration = Duration::from_secs(10);
type Runtime = RunLoop<Trading<StrategyNodes>>;
fn text<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str()
        .ok_or_else(|| format!("BACKTEST_PLAN_FIELD_{k}").into())
}
fn line(reader: &mut impl BufRead) -> Result<Value> {
    let mut raw = String::new();
    reader.take(MAX_FRAME + 1).read_line(&mut raw)?;
    if raw.is_empty() || raw.len() as u64 > MAX_FRAME || !raw.ends_with('\n') {
        return Err("BACKTEST_FRAME_INVALID".into());
    }
    let value: Value = serde_json::from_str(&raw)?;
    if raw != format!("{value}\n") {
        return Err("BACKTEST_FRAME_NONCANONICAL".into());
    }
    Ok(value)
}
fn write(sequence: u64, payload: Value) -> Result<()> {
    let raw = json!({"protocol":PROTOCOL,"sequence":sequence,"payload":payload}).to_string();
    if raw.len() as u64 > MAX_FRAME {
        return Err("BACKTEST_REPLY_BOUND".into());
    }
    println!("{raw}");
    std::io::stdout().flush()?;
    Ok(())
}
fn prepare_root(root: &Path, initialize: bool) -> Result<bool> {
    if root.is_symlink() {
        return Err("BACKTEST_RUNTIME_ROOT_LINK".into());
    }
    let fresh = if initialize {
        match fs::create_dir(root) {
            Ok(()) => true,
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => false,
            Err(error) => return Err(error.into()),
        }
    } else {
        false
    };
    let journal = root.join("runtime.sqlite3");
    if !fresh && (!root.is_dir() || journal.is_symlink() || !journal.is_file()) {
        return Err("BACKTEST_NATIVE_HISTORY_UNAVAILABLE".into());
    }
    Ok(fresh)
}
fn create(plan: &Value, root: &Path, artifact: &str, initialize: bool) -> Result<Runtime> {
    let python = PathBuf::from(text(plan, "python")?);
    let generation = text(plan, "generation")?;
    let worker_artifact = text(plan, "worker_artifact")?;
    let source = text(plan, "source")?;
    let input = Inputs::from_record(&plan["inputs"])?;
    let original = &plan["strategy"];
    let mut worker =
        Worker::spawn_hosted(&python, generation.into(), worker_artifact.into(), DEADLINE)?;
    let nodes = original["decision_graph"]["nodes"]
        .as_array()
        .ok_or("BACKTEST_GRAPH")?;
    let public_ids = plan["node_identities"]
        .as_array()
        .ok_or("BACKTEST_NODE_IDENTITIES")?;
    if nodes.len() != public_ids.len() {
        return Err("BACKTEST_GRAPH_CLOSURE".into());
    }
    let mut mapping = BTreeMap::<String, String>::new();
    let mut descriptors = vec![];
    let mut requests = BTreeMap::new();
    for (row, identity) in nodes.iter().zip(public_ids) {
        let d = &row["definition"];
        let mut bindings = d["input_bindings"].clone();
        for reference in bindings
            .as_object_mut()
            .ok_or("BACKTEST_BINDINGS")?
            .values_mut()
        {
            if let Some(parent) = reference["node_fingerprint"].as_str() {
                reference["node_fingerprint"] =
                    json!(mapping.get(parent).ok_or("BACKTEST_GRAPH_ORDER")?);
            }
        }
        let request = json!({"schema_version":1,"op":"RESOLVE","reference":{"kind":d["kind"],"type_id":d["type_id"],"semantic_version":d["semantic_version"]},"parameters":d["parameters"],"input_bindings":bindings});
        let descriptor = StrategyNodes::resolve(&mut worker, request.clone(), DEADLINE)
            .map_err(|_| "BACKTEST_NODE_UNAVAILABLE")?;
        let id = descriptor.definition.fingerprint();
        if mapping
            .insert(
                identity.as_str().ok_or("BACKTEST_NODE_ID")?.into(),
                id.clone(),
            )
            .is_some()
        {
            return Err("BACKTEST_DUPLICATE_NODE".into());
        }
        requests.insert(id, request);
        descriptors.push(descriptor);
    }
    let revision = Revision::from_product(original.clone(), descriptors, mapping)?;
    let config = &plan["configuration"];
    let scope = Scope {
        engine: text(config, "engine")?.parse()?,
        runtime: text(config, "runtime")?.parse()?,
        cluster: text(plan, "cluster")?.parse()?,
    };
    let program = Program::new(revision, scope.clone(), generation, source, worker_artifact)?;
    let strategy = Executor::new(
        program.clone(),
        StrategyNodes::new(python, program, requests, DEADLINE)
            .map_err(|_| "BACKTEST_NODES_UNAVAILABLE")?,
    )?;
    let calendar = Arc::new(OnlyTradingCalendar::from_record(&plan["calendar"])?);
    let semantic = strategy.program().revision().semantic().clone();
    if strategy.program().revision().recipe().to_record()["kind"] != "PROVIDER_NATIVE" {
        return Err("BACKTEST_RECIPE_UNSUPPORTED".into());
    }
    let instrument: OnlyInstrumentId = text(plan, "instrument_id")?.parse()?;
    let bar_type = OnlyBarType::from_record(
        &json!({"schema_version":2,"instrument_id":instrument.to_record(),"semantic":semantic.to_record()}),
    )?;
    let graph =
        OnlyConstructionGraph::new(vec![OnlyConstructionInput::Bar(bar_type.clone())], vec![])?;
    let source_program = SourceProgram::new(
        source,
        calendar,
        Arc::new(OnlyConstructionRegistry::default()),
        artifact,
        graph.clone(),
    )?;
    let cluster = ClusterProgram {
        cluster: scope.cluster,
        subscription: OnlyBarSubscription::new(
            "backtest-strategy",
            vec![bar_type.clone()],
            graph,
            Some(bar_type),
            OnlyBarFreshness::LatestClosed,
        )?,
    };
    let pipeline = PipelineProgram::new(
        OnlyMarketDataStateScope::new(scope.engine, scope.runtime),
        generation,
        128,
        vec![source_program],
        vec![cluster],
        vec![],
        artifact,
    )?;
    let preparation = StrategyPreparation::new(pipeline, strategy)?;
    let initial_ns: onlyalpha_clock::BigInt = text(plan, "initial_ns")?.parse()?;
    let trading = Trading::new(
        preparation,
        worker,
        plan["trading"].clone(),
        initial_ns.clone(),
    )?;
    let spec = RunSpec {
        work_id: text(plan, "work_id")?.into(),
        configuration: config.clone(),
        kernel_artifact: artifact.into(),
        driver_artifact: artifact.into(),
        initial_ns,
    };
    if !prepare_root(root, initialize)? {
        Ok(RunLoop::open(root, spec, input, trading)?)
    } else {
        Ok(RunLoop::create(root, spec, input, trading)?)
    }
}
fn publish_projection(path: &Path, bytes: &[u8]) -> Result<()> {
    let directory = path.parent().ok_or("BACKTEST_PROJECTION_PATH")?;
    if directory.is_symlink() || path.is_symlink() {
        return Err("BACKTEST_PROJECTION_LINK".into());
    }
    if path.exists() {
        if !path.is_file() || fs::read(path)? != bytes {
            return Err("BACKTEST_EVENT_CONFLICT".into());
        }
        return Ok(());
    }
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or("BACKTEST_PROJECTION_PATH")?;
    let temporary = directory.join(format!(".{name}.tmp"));
    if temporary.is_symlink() {
        return Err("BACKTEST_PROJECTION_LINK".into());
    }
    if temporary.exists() {
        if !temporary.is_file() {
            return Err("BACKTEST_PROJECTION_PATH".into());
        }
        // Only this exact event/report's unpublished stage is disposable.
        fs::remove_file(&temporary)?;
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    fs::rename(&temporary, path)?;
    fs::File::open(directory)?.sync_all()?;
    Ok(())
}

fn fields(value: &Value, expected: &[&str]) -> Result<()> {
    if value.as_object().is_none_or(|fields| {
        fields.len() != expected.len() || expected.iter().any(|key| !fields.contains_key(*key))
    }) {
        return Err("BACKTEST_COMMAND_FIELDS".into());
    }
    Ok(())
}

fn accept(root: &Path, event: &Value) -> std::result::Result<(), onlyalpha_backtest::Error> {
    let operation = || -> Result<()> {
        let id = text(event, "event_id")?;
        if id.is_empty()
            || !id
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
        {
            return Err("BACKTEST_EVENT_ID".into());
        }
        let directory = root.join("events");
        fs::create_dir_all(&directory)?;
        let path = directory.join(format!("{id}.json"));
        let bytes = event.to_string();
        publish_projection(&path, bytes.as_bytes())?;
        Ok(())
    };
    operation().map_err(|e| onlyalpha_backtest::Error(e.to_string()))
}
fn main_inner() -> Result<()> {
    let executable = std::env::current_exe()?;
    let artifact = fingerprint(&fs::read(&executable)?);
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if args == ["--describe"] {
        let target = match std::env::consts::ARCH {
            "aarch64" => "aarch64-unknown-linux-gnu",
            "x86_64" => "x86_64-unknown-linux-gnu",
            _ => return Err("BACKTEST_TARGET".into()),
        };
        println!(
            "{}",
            json!({"protocol":PROTOCOL,"artifact":artifact,"target":target,"version":env!("CARGO_PKG_VERSION")})
        );
        return Ok(());
    }
    if args == ["--verify-result"] {
        const BOUND: u64 = 128 * 1024 * 1024;
        let mut raw = String::new();
        std::io::stdin().take(BOUND + 1).read_to_string(&mut raw)?;
        if raw.len() as u64 > BOUND {
            return Err("BACKTEST_VERIFY_BOUND".into());
        }
        let value: Value = serde_json::from_str(&raw)?;
        fields(&value, &["result", "trace", "plan"])?;
        let canonical = value.to_string();
        if raw != canonical
            || value["trace"]["binding"]["driver_artifact"] != artifact
            || value["trace"]["binding"]["kernel_artifact"] != artifact
        {
            return Err("BACKTEST_VERIFY_CONTEXT".into());
        }
        let scratch = executable
            .parent()
            .ok_or("BACKTEST_VERIFY_ROOT")?
            .join("proof");
        if scratch.exists() || value["plan"]["native_artifact"] != artifact {
            return Err("BACKTEST_VERIFY_CONTEXT".into());
        }
        let steps = value["trace"]["steps"]
            .as_array()
            .filter(|steps| !steps.is_empty() && steps.len() <= 65536)
            .ok_or("BACKTEST_VERIFY_STEPS")?;
        let mut run = create(&value["plan"], &scratch, &artifact, true)?;
        if run.trace()?["binding"] != value["trace"]["binding"] {
            return Err("BACKTEST_VERIFY_BINDING".into());
        }
        for row in steps {
            let cause = &row["step"]["cause"];
            match cause["kind"].as_str() {
                Some("BAR") => {
                    if !run.step()? {
                        return Err("BACKTEST_VERIFY_PREFIX".into());
                    }
                }
                Some("PAUSE") => run.pause()?,
                Some("RESUME") => run.resume()?,
                Some("TERMINATE")
                    if cause["outcome"]
                        == json!({"schema_version":1,"status":"COMPLETED","reason":null}) =>
                {
                    run.terminate("COMPLETED", None)?
                }
                _ => return Err("BACKTEST_VERIFY_TRANSITION".into()),
            }
            // Acknowledge only the disposable replay projection; never dispatch externally.
            run.deliver(|_| Ok(()))?;
        }
        if run.trace()? != value["trace"] || run.result()?["execution_result"] != value["result"] {
            return Err("BACKTEST_VERIFY_REDERIVATION".into());
        }
        println!(
            "{}",
            json!({"verified_result":value["result"]["result_fingerprint"]})
        );
        return Ok(());
    }
    if !args.is_empty() {
        return Err("BACKTEST_ARGUMENTS".into());
    }
    let mut input = std::io::stdin().lock();
    let first = line(&mut input)?;
    if first["protocol"] != PROTOCOL
        || first["sequence"] != 0
        || first["op"] != "OPEN"
        || first["plan"]["native_artifact"] != artifact
    {
        return Err("BACKTEST_OPEN_IDENTITY".into());
    }
    fields(
        &first,
        &["protocol", "sequence", "op", "root", "plan", "initialize"],
    )?;
    fields(
        &first["plan"],
        &[
            "schema_version",
            "work_id",
            "native_artifact",
            "generation",
            "worker_artifact",
            "python",
            "configuration",
            "strategy",
            "inputs",
            "node_identities",
            "source",
            "cluster",
            "calendar",
            "instrument_id",
            "trading",
            "initial_ns",
        ],
    )?;
    if first["plan"]["schema_version"] != 1 {
        return Err("BACKTEST_PLAN_SCHEMA".into());
    }
    let root = PathBuf::from(text(&first, "root")?);
    if root.is_symlink() {
        return Err("BACKTEST_RUNTIME_ROOT_LINK".into());
    }
    let mut run = create(
        &first["plan"],
        &root,
        &artifact,
        first["initialize"]
            .as_bool()
            .ok_or("BACKTEST_INITIALIZE_INVALID")?,
    )?;
    write(0, run.progress()?)?;
    let mut sequence = 1u64;
    loop {
        let request = line(&mut input)?;
        if request["protocol"] != PROTOCOL || request["sequence"] != sequence {
            return Err("BACKTEST_COMMAND_SEQUENCE".into());
        }
        let operation = text(&request, "op")?;
        if operation == "TERMINATE" {
            if request.get("reason").is_some() {
                fields(
                    &request,
                    &["protocol", "sequence", "op", "status", "reason"],
                )?;
            } else {
                fields(&request, &["protocol", "sequence", "op", "status"])?;
            }
        } else {
            fields(&request, &["protocol", "sequence", "op"])?;
        }
        let response = match operation {
            "STEP" => {
                let advanced = match run.step() {
                    Ok(value) => value,
                    Err(error) if error.0.ends_with("_Rejected") => {
                        write(
                            sequence,
                            json!({"error":{"code":"BACKTEST_NATIVE_EXECUTION_REJECTED"}}),
                        )?;
                        return Ok(());
                    }
                    Err(error) => return Err(error.into()),
                };
                run.deliver(|event| accept(&root, event))?;
                json!({"advanced":advanced,"progress":run.progress()?})
            }
            "STATUS" => run.progress()?,
            "PAUSE" => {
                run.pause()?;
                run.progress()?
            }
            "RESUME" => {
                run.resume()?;
                run.progress()?
            }
            "FINISH" => {
                run.finish_input()?;
                run.progress()?
            }
            "EXPORT" => {
                let proof = run.result()?;
                let reports = root.join("reports");
                fs::create_dir_all(&reports)?;
                let mut entries = serde_json::Map::new();
                for (name, value) in [
                    ("result.json", proof["execution_result"].clone()),
                    ("replay-proof.json", proof),
                    ("replay-trace.json", run.trace()?),
                ] {
                    let bytes = serde_json::to_vec(&value)?;
                    let path = reports.join(name);
                    publish_projection(&path, &bytes)?;
                    entries.insert(
                        name.into(),
                        json!({"sha256":fingerprint(&bytes),"size":bytes.len()}),
                    );
                }
                fs::File::open(&reports)?.sync_all()?;
                json!({"files":entries})
            }
            "TERMINATE" => {
                let status = text(&request, "status")?;
                if !matches!(status, "COMPLETED" | "CANCELLED" | "INCOMPLETE") {
                    return Err("BACKTEST_TERMINAL_COMMAND".into());
                }
                let reason = request
                    .get("reason")
                    .map(|value| value.as_str().ok_or("BACKTEST_TERMINAL_REASON"))
                    .transpose()?;
                if reason.is_some_and(|value| {
                    value.is_empty()
                        || value.len() > 128
                        || !value.bytes().all(|b| b.is_ascii_uppercase() || b == b'_')
                }) {
                    return Err("BACKTEST_TERMINAL_REASON".into());
                }
                if status == "COMPLETED" && reason.is_some() {
                    return Err("BACKTEST_TERMINAL_REASON".into());
                }
                run.terminate(
                    status,
                    if status == "COMPLETED" {
                        None
                    } else {
                        Some(reason.unwrap_or("PRODUCT_CONTROL"))
                    },
                )?;
                run.progress()?
            }
            "RESULT" => run.result()?,
            "TRACE" => run.trace()?,
            "CLOSE" => {
                write(sequence, run.progress()?)?;
                return Ok(());
            }
            _ => return Err("BACKTEST_COMMAND".into()),
        };
        write(sequence, response)?;
        sequence = sequence.checked_add(1).ok_or("BACKTEST_COMMAND_BOUND")?;
    }
}
fn main() {
    if let Err(error) = main_inner() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn missing_history_cannot_grant_initialization() {
        let root =
            std::env::temp_dir().join(format!("onlyalpha-backtest-history-{}", std::process::id()));
        assert!(!root.exists());
        let outcome = prepare_root(&root, false);
        let created = root.exists();
        if created {
            fs::remove_dir_all(&root).unwrap();
        }
        assert!(
            outcome.is_err(),
            "a recovery attempt cannot initialize missing history"
        );
        assert!(
            !created,
            "recovery cannot create a missing runtime directory"
        );
        fs::create_dir(&root).unwrap();
        let outcome = prepare_root(&root, true);
        fs::remove_dir_all(&root).unwrap();
        assert!(
            outcome.is_err(),
            "even a first attempt cannot reuse an empty existing runtime"
        );
        assert!(prepare_root(&root, true).unwrap());
        fs::write(root.join("runtime.sqlite3"), b"owned journal").unwrap();
        assert!(!prepare_root(&root, false).unwrap());
        assert!(!prepare_root(&root, true).unwrap());
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn projection_recovers_partial_stage_and_never_overwrites_a_conflicting_fact() {
        let root = std::env::temp_dir().join(format!(
            "onlyalpha-backtest-projection-{}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        fs::create_dir(root.join("events")).unwrap();
        let stage = root.join("events/.event-1.json.tmp");
        fs::write(&stage, b"partial").unwrap();
        let event = json!({"event_id":"event-1","payload":"durable fact"});
        accept(&root, &event).unwrap();
        assert!(
            !stage.exists(),
            "a crash stage must not block or pollute replay"
        );
        assert_eq!(
            fs::read(root.join("events/event-1.json")).unwrap(),
            event.to_string().as_bytes()
        );
        accept(&root, &event).unwrap();
        assert!(accept(&root, &json!({"event_id":"event-1","payload":"different"})).is_err());
        assert_eq!(
            fs::read(root.join("events/event-1.json")).unwrap(),
            event.to_string().as_bytes()
        );
        fs::remove_dir_all(root).unwrap();
    }
}
