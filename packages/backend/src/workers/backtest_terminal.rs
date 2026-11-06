//! Private native-reader protocol. No Product Command, SQL owner, SDK or writer starts.
use crate::application::private_strategy::exact;
use onlyalpha_backtest::{Inputs, RunSpec, TerminalSnapshot};
use serde_json::{Value, json};
use std::{
    io::{Read, Write},
    path::{Component, Path},
};
const INVALID: &str = "BACKTEST_TERMINAL_READ_INVALID";
const HISTORICAL: &str = "BACKTEST_HISTORICAL_READER_UNAVAILABLE";
const CONTRACT: &str = "ONLYALPHA_BACKTEST_TERMINAL_READ_V1";
const BOUND: usize = 128 * 1024 * 1024;
fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str, &'static str> {
    value[key].as_str().filter(|s| !s.is_empty()).ok_or(INVALID)
}
/// Values describe an expected scope. Only the actual RO owning source supplies
/// facts; neither this request nor its observations can mint a completion seal.
pub(crate) fn read_request(request: &Value) -> Result<Value, &'static str> {
    exact(
        request,
        &[
            "schema_version",
            "contract",
            "journal_root",
            "specification",
            "inputs",
        ],
    )
    .map_err(|_| INVALID)?;
    if request["schema_version"] != 1
        || request["contract"] != CONTRACT
        || request.to_string().len() > BOUND
    {
        return Err(INVALID);
    }
    let root = text(request, "journal_root")?;
    let path = Path::new(root);
    if root.len() > 4096
        || !path.is_absolute()
        || path
            .components()
            .any(|p| !matches!(p, Component::RootDir | Component::Normal(_)))
    {
        return Err(INVALID);
    }
    let specification = &request["specification"];
    exact(
        specification,
        &[
            "work_id",
            "configuration",
            "kernel_artifact",
            "driver_artifact",
            "initial_ns",
        ],
    )
    .map_err(|_| INVALID)?;
    let kernel = text(specification, "kernel_artifact")?;
    let driver = text(specification, "driver_artifact")?;
    // This exact loaded binary owns the native semantics. A currently running
    // different Kernel never reinterprets archived history from JSON claims.
    let image = super::algorithm::describe_research_runtime(env!("CARGO_PKG_VERSION"))
        .map_err(|_| HISTORICAL)?;
    if image["artifact"] != kernel || image["artifact"] != driver {
        return Err(HISTORICAL);
    }
    let raw_ns = text(specification, "initial_ns")?;
    let initial_ns = raw_ns.parse().map_err(|_| INVALID)?;
    let inputs = Inputs::from_record(&request["inputs"]).map_err(|_| INVALID)?;
    let spec = RunSpec {
        work_id: text(specification, "work_id")?.into(),
        configuration: specification["configuration"].clone(),
        kernel_artifact: kernel.into(),
        driver_artifact: driver.into(),
        initial_ns,
    };
    if spec.initial_ns.to_string() != raw_ns {
        return Err(INVALID);
    }
    let snapshot = TerminalSnapshot::read(path, spec, &inputs, super::backtest::terminal_policy)
        .map_err(|error| {
            if error.0.contains("HISTORICAL") {
                HISTORICAL
            } else {
                INVALID
            }
        })?;
    snapshot.verify_cut().map_err(|_| INVALID)?;
    let observed = json!({"schema_version":1,"contract":CONTRACT,"reader_artifact":image["artifact"],"trace":snapshot.trace(),"proof":snapshot.proof(),"result":snapshot.result(),"state":snapshot.state()});
    if observed.to_string().len() > BOUND {
        return Err("BACKTEST_TERMINAL_READ_BOUND");
    }
    snapshot.verify_cut().map_err(|_| INVALID)?;
    Ok(observed)
}
/// This executable-only branch runs before workstation initialization. Its input
/// and output have the original finite read budget; all errors produce no seal.
pub fn run_stdio() -> Result<(), &'static str> {
    let mut bytes = Vec::new();
    std::io::stdin()
        .take(BOUND as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| INVALID)?;
    if bytes.len() > BOUND {
        return Err("BACKTEST_TERMINAL_READ_BOUND");
    }
    let request: Value = serde_json::from_slice(&bytes).map_err(|_| INVALID)?;
    if request.to_string().as_bytes() != bytes {
        return Err(INVALID);
    }
    let observed = read_request(&request)?;
    let output = serde_json::to_vec(&observed).map_err(|_| INVALID)?;
    if output.len() > BOUND {
        return Err("BACKTEST_TERMINAL_READ_BOUND");
    }
    std::io::stdout().write_all(&output).map_err(|_| INVALID)?;
    std::io::stdout().flush().map_err(|_| INVALID)
}
