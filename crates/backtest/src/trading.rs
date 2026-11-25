//! Pure canonical BAR valuation transport helpers for finite in-memory execution.
use crate::{Error, MarketInput, boundary, err, hash, next_open::NativeExecution};
use onlyalpha_domain::{base::OnlyDomainModel, numeric::OnlyDecimal};
use serde_json::{Value, json};

/// One canonical transport derivation for actual BAR valuation.
/// Values confer no execution permission.
pub(crate) struct BarOperation<'a> {
    pub(crate) kind: &'a str,
    pub(crate) payload: Value,
    pub(crate) cause: &'a str,
}

pub(crate) fn bar_request(
    binding: &Value,
    input: &MarketInput,
    now: u64,
    sequence: usize,
    operation: BarOperation<'_>,
    day_index: Value,
) -> Value {
    let BarOperation {
        kind: op,
        payload,
        cause,
    } = operation;
    let config = &binding["policy"]["execution"];
    let program = &binding["program"];
    let n = sequence as u64 + 1;
    let id = format!(
        "REPLAY-{}",
        hash(
            &json!({"market":input.identity(),"cause":cause,"sequence":n,"op":op,"payload":payload,"program":binding})
        )
    );
    json!({"schema_version":1,"engine":config["engine"],"runtime":config["runtime"],"account":config["account"],"gateway":config["gateway"],"generation":config["generation"],"runtime_kind":"BACKTEST","cluster":program["scope"]["cluster"],"revision":program["revision"]["strategy_fingerprint"],"input_id":id,"source_ref":format!("CAUSE-{}",hash(&json!([input.identity(),cause,n,op]))),"time":now,"runtime_sequence":n,"trading_day":input.bar().to_record()["trading_day"],"day_index":day_index,"op":op,"payload":payload})
}

// Pure quantity predicate over the caller's complete owning Ready view. It
// supplies neither source freshness nor an execution/valuation capability.
fn native_bar_has_exposure(state: &Value) -> Result<bool, Error> {
    let accounts = state["position_accounts"]
        .as_array()
        .ok_or_else(|| err("POSITION"))?;
    let allocations = state["position_allocations"]
        .as_array()
        .ok_or_else(|| err("POSITION"))?;
    if accounts.is_empty() && !allocations.is_empty() {
        return Err(err("POSITION"));
    }
    let mut exposed = false;
    for book in accounts.iter().chain(allocations) {
        let quantity: OnlyDecimal = boundary(
            book["snapshot"]["quantity"]
                .as_str()
                .ok_or_else(|| err("POSITION"))?
                .parse(),
        )?;
        exposed |= !quantity.is_zero();
    }
    Ok(exposed)
}

pub(crate) fn valuation_input(
    binding: &Value,
    input: &MarketInput,
    now: u64,
    c: &impl NativeExecution,
    day_index: Value,
) -> Result<Option<Value>, Error> {
    let state = c.position_order_view()?;
    let positions = state["position_accounts"]
        .as_array()
        .ok_or_else(|| err("POSITION"))?;
    match binding["policy"]["schema_version"].as_u64() {
        Some(2) => {
            if binding["opening_profile"] != json!({"schema_version":1,"kind":"OPEN_CLOSE_V1"})
                || binding["policy"]["policy"]["kind"] != "NEXT_OPEN_LONG_ONLY_V1"
            {
                return Err(err("TRADING_CONTEXT"));
            }
            if !native_bar_has_exposure(&state)? {
                return Ok(None);
            }
        }
        _ => return Err(err("TRADING_CONTEXT")),
    }
    let n = c.sequence() as u64 + 1;
    let marks = positions
        .iter()
        .map(|p| {
            if p["instrument"] != input.bar().instrument_id().to_string() {
                return Err(err("MARK_SOURCE"));
            }
            Ok(json!({"schema_version":1,"instrument":p["instrument"],"mark":input.bar().to_record()["close"]["value"],"source_ref":format!("BAR-{}",input.identity()),"family":"CLOSED_BAR","version":n,"time":now,"as_of_sequence":n}))
        })
        .collect::<Result<Vec<_>, Error>>()?;
    let payload = json!({"schema_version":1,"valuation":format!("VALUATION-{}",input.identity()),"version":n,"position_evidence":state["position_checkpoint_fingerprint"],"economic_version":state["economic_version"],"marks":marks});
    Ok(Some(bar_request(
        binding,
        input,
        now,
        c.sequence(),
        BarOperation {
            kind: "VALUATION",
            payload,
            cause: &input.identity(),
        },
        day_index,
    )))
}
