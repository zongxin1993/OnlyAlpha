use crate::{
    Components,
    backtest_result::cluster_summary,
    model::*,
    perpetual::{funding_pair, mark_fact, nanos, validate_admission_after_funding, validate_mark_order},
    perpetual_fees::{Fees, fill_day},
    planning::{
        admission_quantity_precision, allocation_before, allocation_witness,
        checked_admission_request, validate_admission_intent, validate_fill_price,
    },
    reconciliation::{compare_snapshot_totals, fee_application_entry},
    working::equity_points,
};
use bigdecimal::BigDecimal;
use onlyalpha_domain::{
    base::OnlyDomainModel, enums::OnlyOrderStatus, execution::OnlyOrderSnapshot,
    identifiers::OnlyInstrumentId, numeric::OnlyDecimal, time::OnlyTimestamp,
};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

pub struct VerifiedFiniteBacktestResult {
    equity_points: Vec<Value>,
    closed_cycles: BTreeMap<String, usize>,
}

impl VerifiedFiniteBacktestResult {
    pub fn equity_points(&self) -> &[Value] {
        &self.equity_points
    }

    pub fn closed_cycles(&self) -> &BTreeMap<String, usize> {
        &self.closed_cycles
    }
}

/// Checks the retained finite Execution transcript against its frozen inputs.
pub fn verify_finite_backtest_result(
    result: &Value,
    account_checkpoint: &Value,
    configuration: &Value,
    kernel_artifact: &str,
    input_pin: &str,
    initial_ns: i64,
    final_ns: i64,
) -> Result<VerifiedFiniteBacktestResult, Error> {
    row(
        result,
        &[
            "semantic_version",
            "completion_scope",
            "scope",
            "manifest",
            "source",
            "run",
            "closure",
            "execution",
            "runtime_performance",
            "final_account",
            "final_positions",
            "final_allocations",
            "final_ledgers",
            "orders",
            "trades",
            "facts",
            "cluster_results",
            "account_equity_timeline",
            "cluster_equity_timelines",
            "reconciliation",
            "diagnostics",
        ],
    )?;
    let mut genesis = Components::new(configuration.clone())?;
    if configuration["runtime_kind"] != "BACKTEST"
        || result["scope"] != *configuration
        || result["semantic_version"] != "BACKTEST_RESULT@1"
        || result["completion_scope"] != "EXECUTION_TRANSCRIPT"
        || result["diagnostics"] != json!([])
        || initial_ns > final_ns
    {
        return Err(err("RESULT_FINITE_SCOPE"));
    }
    let initial = OnlyTimestamp::from_unix_nanos(initial_ns.into());
    let initial_time = initial.to_record();
    let final_time = OnlyTimestamp::from_unix_nanos(final_ns.into()).to_record();
    if result["run"]
        != json!({"status":"COMPLETED","requested_outcome":{"schema_version":1,"status":"COMPLETED","reason":null},"initial_time":initial_time,"final_time":final_time})
    {
        return Err(err("RESULT_FINITE_RUN"));
    }
    fp(&json!(kernel_artifact))?;
    fp(&json!(input_pin))?;
    let facts = array(&result["facts"])?;
    let orders = array(&result["orders"])?;
    let trades = array(&result["trades"])?;
    let perpetual_epoch = (configuration["schema_version"] == 3)
        .then(|| genesis.perpetual_epoch_ns())
        .transpose()?;
    let mut inputs = Vec::with_capacity(facts.len());
    let mut applied = Vec::with_capacity(facts.len());
    let mut input_ids = BTreeSet::new();
    let mut source_refs = BTreeSet::new();
    let mut causes = BTreeSet::new();
    let mut broker_facts = BTreeMap::new();
    let mut market_facts = BTreeMap::new();
    let mut last_mark: Option<onlyalpha_domain::market::OnlyReferencePriceFact> = None;
    let mut funding_boundaries = BTreeSet::new();
    let market_cut = perpetual_epoch.map(|_| genesis.funding_cut()).transpose()?;
    let mut expected_trades = Vec::new();
    let mut previous = 0;
    for (index, fact) in facts.iter().enumerate() {
        fields(fact, &["sequence", "transaction", "input"])?;
        let input = &fact["input"];
        let runtime_sequence = genesis.validate_planning_input(input)?;
        let time = input["time"]
            .as_i64()
            .ok_or_else(|| err("RESULT_INPUT_TIME"))?;
        let cause = text(&fact["transaction"])?
            .strip_prefix("ETX-")
            .ok_or_else(|| err("RESULT_FINITE_FACT"))?;
        let op = text(&input["op"])?;
        let valid_operation = if perpetual_epoch.is_some() {
            matches!(
                op,
                "ADMIT"
                    | "SUBMISSION"
                    | "ACCEPT"
                    | "CANCEL"
                    | "FILL"
                    | "TERMINAL"
                    | "MARK"
                    | "FUNDING"
            )
        } else {
            matches!(
                op,
                "ADMIT"
                    | "SUBMISSION"
                    | "ACCEPT"
                    | "CANCEL"
                    | "FILL"
                    | "TERMINAL"
                    | "VALUATION"
                    | "SETTLEMENT_MATURITY"
            )
        };
        if !valid_operation
            || !input["payload"].is_object()
            || text(&input["trading_day"])?.len() != 10
            || uint(&input["day_index"])? == 0
            || !(initial_ns..=final_ns).contains(&time)
            || runtime_sequence <= previous
            || !input_ids.insert(text(&input["input_id"])?)
            || !source_refs.insert(text(&input["source_ref"])?)
            || fact["sequence"] != index + 1
            || cause != hash(input)
            || !causes.insert(cause)
        {
            return Err(err("RESULT_FINITE_FACT"));
        }
        previous = runtime_sequence;
        inputs.push(input);
        if let Some(epoch) = perpetual_epoch {
            genesis.validate_perpetual_input_context(input, epoch)?;
            if op == "ADMIT" {
                if let Some(&settled) = funding_boundaries.last() {
                    validate_admission_after_funding(uint(&input["time"])?, settled)?;
                }
                genesis.validate_perpetual_admission_request(input)?;
            }
            if matches!(op, "ACCEPT" | "FILL" | "TERMINAL") {
                let identity = genesis.validate_perpetual_broker_input(input)?;
                let broker = &input["payload"]["broker"];
                if let Some(original) = broker_facts.insert(identity.identity().to_owned(), broker)
                {
                    if original != broker {
                        return Err(err("RESULT_FINITE_BROKER_FACT"));
                    }
                    continue;
                }
            }
            if matches!(op, "MARK" | "FUNDING") {
                let payload = &input["payload"];
                row(
                    payload,
                    if op == "MARK" {
                        &["fact"]
                    } else {
                        &["fact", "mark_fact_id"]
                    },
                )?;
                let raw = &payload["fact"];
                let identity = id(&raw["fact_id"])?;
                if !market_cut
                    .as_ref()
                    .expect("perpetual market cut")
                    .contains(raw)
                {
                    return Err(err("RESULT_FINITE_MARKET_FACT"));
                }
                let duplicate = market_facts.insert((op, identity), payload);
                if duplicate.is_some_and(|original| original != payload) {
                    return Err(err("RESULT_FINITE_MARKET_FACT"));
                }
                let visible = uint(&input["time"])?;
                if op == "MARK" {
                    let mark = mark_fact(configuration, raw)?;
                    if nanos(*mark.ts_init())? > visible {
                        return Err(err("RESULT_FINITE_MARKET_FACT"));
                    }
                    if duplicate.is_some() {
                        continue;
                    }
                    if let Some(prior) = &last_mark {
                        validate_mark_order(&mark, prior)?;
                    }
                    last_mark = Some(mark);
                } else {
                    let mark_id = id(&payload["mark_fact_id"])?;
                    let mark = market_facts
                        .get(&("MARK", mark_id))
                        .ok_or_else(|| err("RESULT_FINITE_MARKET_FACT"))?;
                    let funding = funding_pair(configuration, &mark["fact"], raw)?;
                    if nanos(*funding.ts_init())? > visible {
                        return Err(err("RESULT_FINITE_MARKET_FACT"));
                    }
                    if duplicate.is_some() {
                        continue;
                    }
                    if !funding_boundaries.insert(nanos(*funding.funding_time())?) {
                        return Err(err("RESULT_FINITE_MARKET_FACT"));
                    }
                }
            }
        }
        applied.push((cause, input));
        if op == "FILL" {
            expected_trades.push(fact);
        }
    }
    let config_digest = hash(configuration);
    let source = json!({"schema_version":1,"kind":"UNPUBLISHED_MEMORY_EXECUTION","configuration":config_digest,"inputs":digest(&serde_json::to_vec(&inputs)?),"rows":facts.len()});
    if !trades.iter().eq(expected_trades)
        || result["source"] != source
        || result["manifest"]
            != json!({"schema_version":1,"configuration":config_digest,"kernel_artifact":kernel_artifact,"input_pin":input_pin,"initial_time":initial_time,"final_time":final_time,"inputs":facts.iter().map(|fact| text(&fact["transaction"]).map(|s| &s[4..])).collect::<Result<Vec<_>, _>>()?})
        || result["closure"]
            != json!({"complete":true,"observed":facts.len(),"expected":facts.len()})
        || result["execution"]
            != json!({"transaction_count":facts.len(),"order_count":orders.len(),"trade_count":trades.len()})
    {
        return Err(err("RESULT_FINITE_TRANSCRIPT"));
    }
    let initial_ledger = genesis.ledger.clone();
    let verified_trades = verify_orders_and_positions(
        result,
        &mut genesis,
        configuration,
        &inputs,
        &applied,
        market_cut.as_ref(),
    )?;
    let occurrences = expected_occurrences(&applied, &verified_trades)?;
    let by_cause = applied.into_iter().collect();
    let equity_points = verify_account(
        result,
        &genesis,
        &initial,
        &by_cause,
        &inputs,
        &occurrences,
        &verified_trades.fees,
    )?;
    verify_account_commands(
        result,
        account_checkpoint,
        &genesis,
        &by_cause,
        &verified_trades,
    )?;
    if let Some(cut) = &market_cut {
        let encoded = serde_json::to_vec(account_checkpoint)?;
        let fingerprint = text(&result["runtime_performance"]["account_checkpoint"])?;
        let account = std::sync::Arc::make_mut(&mut genesis.account);
        boundary(account.restore_with_funding(&encoded, fingerprint, &genesis.position, cut))?;
        if boundary(account.performance(&initial))?.record() != result["runtime_performance"] {
            return Err(err("RESULT_FINITE_ACCOUNT_PERFORMANCE"));
        }
    }
    let clusters = verify_ledgers(result, &genesis, &initial_ledger, &initial_time)?;
    let (totals, differences) = compare_snapshot_totals(
        &configuration["initial_cash"],
        &result["final_account"],
        array(&result["final_ledgers"])?.iter(),
        &clusters,
        genesis.precision,
    )?;
    if !differences.is_empty()
        || result["reconciliation"]
            != json!({"schema_version":1,"source":source,"status":"MATCHED","totals":totals,"differences":[]})
    {
        return Err(err("RESULT_FINITE_RECONCILIATION"));
    }
    // Admission uses the owners' live reservations and maintenance state at each prefix.
    let replay_admissions = perpetual_epoch.is_some()
        || configuration["profiles"]
            .as_object()
            .expect("validated profiles")
            .values()
            .any(|profile| {
                profile["rules"]
                    .as_array()
                    .is_some_and(|rules| !rules.is_empty())
            });
    if replay_admissions
        && let Some(last_admit) = inputs.iter().rposition(|input| input["op"] == "ADMIT")
    {
        let mut prefix = Components::new(configuration.clone())?;
        for input in &inputs[..=last_admit] {
            prefix.apply_operation(input)?;
        }
    }
    Ok(VerifiedFiniteBacktestResult {
        equity_points,
        closed_cycles: verified_trades.closed_cycles,
    })
}

fn array(value: &Value) -> Result<&[Value], Error> {
    value
        .as_array()
        .map(Vec::as_slice)
        .ok_or_else(|| err("RESULT_FINITE_ARRAY"))
}

fn fields(value: &Value, keys: &[&str]) -> Result<(), Error> {
    if !value
        .as_object()
        .is_some_and(|map| map.len() == keys.len() && keys.iter().all(|key| map.contains_key(*key)))
    {
        return Err(err("RESULT_FINITE_FIELDS"));
    }
    Ok(())
}

fn same_fields(value: &Value, template: &Value) -> Result<(), Error> {
    if !value
        .as_object()
        .zip(template.as_object())
        .is_some_and(|(value, template)| value.keys().eq(template.keys()))
    {
        return Err(err("RESULT_FINITE_FIELDS"));
    }
    Ok(())
}

fn fixed(value: &Value, precision: u8) -> Result<BigDecimal, Error> {
    let n = exact(value)?;
    if *value != n.with_scale(i64::from(precision)).to_plain_string() {
        return Err(err("RESULT_FINITE_AMOUNT"));
    }
    Ok(n)
}

fn analytical(value: &Value, precision: u8) -> Result<(), Error> {
    if *value != exact_record(&exact(value)?, precision) {
        return Err(err("RESULT_FINITE_AMOUNT"));
    }
    Ok(())
}

fn flags(value: &Value) -> Result<BTreeSet<&str>, Error> {
    let rows = array(value)?;
    let names = rows.iter().map(text).collect::<Result<BTreeSet<_>, _>>()?;
    if !rows
        .iter()
        .filter_map(Value::as_str)
        .eq(names.iter().copied())
    {
        return Err(err("RESULT_FINITE_FLAGS"));
    }
    Ok(names)
}

#[derive(Default)]
struct ExpectedOccurrences<'a> {
    account: Vec<(&'a str, &'static str, String)>,
    margin: BTreeSet<&'a str>,
}

fn expected_occurrences<'a>(
    inputs: &[(&'a str, &'a Value)],
    trades: &VerifiedTrades<'a>,
) -> Result<ExpectedOccurrences<'a>, Error> {
    let mut expected = ExpectedOccurrences::default();
    let mut buys = BTreeSet::new();
    for &(cause, input) in inputs {
        let payload = &input["payload"];
        let op = text(&input["op"])?;
        if op == "ADMIT" && payload["request"]["side"] == "BUY" {
            buys.insert(id(&payload["order"])?);
        }
        let buy = payload["order"]
            .as_str()
            .is_some_and(|order| buys.contains(order));
        let commands: &[_] = match op {
            "ADMIT" if buy => &[("RESERVE", 2), ("STAGE", 3)],
            "SUBMISSION" if buy && payload["outcome"] == "UNKNOWN" => &[("STAGE", 0)],
            "ACCEPT" | "CANCEL" if buy => &[("STAGE", 0)],
            "TERMINAL" if buy => &[("RELEASE", 0)],
            "FILL" => &[("TRADE", 0)],
            "FUNDING" => &[("ECONOMIC", 0)],
            _ => &[],
        };
        let input_id = text(&input["input_id"])?;
        for &(kind, suffix) in commands {
            expected.account.push((cause, kind, format!("{input_id}-{suffix}")));
        }
        if op == "SETTLEMENT_MATURITY" && trades.account_payloads.contains_key(cause) {
            expected.account.push((cause, "SETTLE", format!("{input_id}-0")));
        }
        if trades.valuation_positions.contains_key(cause) {
            expected.account.push((cause, "VALUATION", format!("{input_id}-0")));
        }
        if let Some(effects) = trades.margin_effects.get(cause) {
            expected.account.extend(effects.iter().map(|effect| {
                (cause, "MARGIN", Components::margin_command_id(input, effect))
            }));
        }
        if matches!(op, "ADMIT" | "FILL" | "TERMINAL")
            && payload["collateral"]["kind"] == "MARGIN"
        {
            expected.margin.insert(cause);
        }
    }
    Ok(expected)
}

fn verify_fee_prefix(
    cumulative: &mut BigDecimal,
    application: Option<&Value>,
    snapshot: &Value,
    precision: u8,
) -> Result<(), Error> {
    if let Some(application) = application {
        *cumulative +=
            fixed(&application["charges"], precision)? - fixed(&application["rebates"], precision)?;
    }
    if exact(&snapshot["fees"])? != *cumulative {
        return Err(err("RESULT_FINITE_TRADE_FEES"));
    }
    Ok(())
}

fn verify_account(
    result: &Value,
    genesis: &Components,
    initial: &OnlyTimestamp,
    inputs_by_cause: &BTreeMap<&str, &Value>,
    inputs: &[&Value],
    occurrences: &ExpectedOccurrences<'_>,
    fees: &BTreeMap<&str, Value>,
) -> Result<Vec<Value>, Error> {
    let p = genesis.precision;
    let original = boundary(genesis.account.performance(initial))?.record();
    let performance = &result["runtime_performance"];
    same_fields(performance, &original)?;
    let summary = &performance["summary"];
    same_fields(summary, &original["summary"])?;
    let unsigned = performance
        .as_object()
        .expect("checked fields")
        .iter()
        .filter(|(key, _)| key.as_str() != "id")
        .collect::<BTreeMap<_, _>>();
    let identity = format!("AP-{}", digest(&serde_json::to_vec(&unsigned)?));
    fp(&performance["account_checkpoint"])?;
    let timeline = array(&performance["timeline"])?;
    let first = &original["timeline"][0];
    let last = timeline
        .last()
        .ok_or_else(|| err("RESULT_ACCOUNT_TIMELINE"))?;
    let final_snapshot = &result["final_account"];
    if [
        "schema_version",
        "semantic_version",
        "scope",
        "initial_time",
    ]
    .iter()
    .any(|f| performance[*f] != original[*f])
        || performance["id"] != identity
        || result["account_equity_timeline"] != performance["timeline"]
        || timeline.first() != Some(first)
        || last["snapshot"] != *final_snapshot
        || (timeline.len() == 1
            && performance["account_checkpoint"] != original["account_checkpoint"])
        || final_snapshot["status"] != "ACTIVE"
        || exact(&final_snapshot["reserved"])? != 0
        || exact(&final_snapshot["reserved_margin"])? != 0
    {
        return Err(err("RESULT_FINITE_ACCOUNT"));
    }
    let mut trade_sequence = Value::Null;
    let mut expected = occurrences.account.iter().peekable();
    let mut required_margin = occurrences.margin.clone();
    let mut time = first["time"]
        .as_i64()
        .ok_or_else(|| err("RESULT_ACCOUNT_TIMELINE"))?;
    let mut quality = BTreeSet::new();
    let mut commands = BTreeSet::new();
    let mut cumulative_fees = exact(&first["snapshot"]["fees"])?;
    for (index, point) in timeline.iter().enumerate().skip(1) {
        same_fields(point, first)?;
        let provenance = &point["provenance"];
        fields(
            provenance,
            &[
                "kind",
                "command",
                "cause",
                "upstream_cause",
                "source_time",
                "outcome",
            ],
        )?;
        let cause = text(&provenance["upstream_cause"])?;
        let input = inputs_by_cause
            .get(cause)
            .ok_or_else(|| err("RESULT_ACCOUNT_CAUSE"))?;
        let command = id(&provenance["command"])?;
        let kind = text(&provenance["kind"])?;
        let op = text(&input["op"])?;
        if kind == "MARGIN" && genesis.config["schema_version"] != 3 {
            let fingerprint = command
                .strip_prefix("MACMD-")
                .ok_or_else(|| err("RESULT_FINITE_ACCOUNT_POINT"))?;
            fp(&json!(fingerprint))?;
            let required = occurrences.margin.contains(cause);
            if (!required && op != "MARK") || expected.peek().is_some_and(|next| next.0 == cause) {
                return Err(err("RESULT_FINITE_ACCOUNT_POINT"));
            }
            required_margin.remove(cause);
        } else {
            let (expected_cause, expected_kind, expected_command) = expected
                .next()
                .ok_or_else(|| err("RESULT_FINITE_ACCOUNT_OCCURRENCES"))?;
            if cause != *expected_cause || kind != *expected_kind {
                return Err(err("RESULT_FINITE_ACCOUNT_OCCURRENCES"));
            }
            if command != expected_command.as_str() {
                return Err(err("RESULT_FINITE_ACCOUNT_POINT"));
            }
        }
        fp(&provenance["cause"])?;
        time = time.max(
            input["time"]
                .as_i64()
                .ok_or_else(|| err("RESULT_INPUT_TIME"))?,
        );
        let snapshot = &point["snapshot"];
        verify_account_snapshot(snapshot, &first["snapshot"], p)?;
        quality.extend(flags(&snapshot["flags"])?);
        if kind == "TRADE" {
            trade_sequence = input["runtime_sequence"].clone();
        }
        let application = if kind == "TRADE" {
            Some(
                fees.get(cause)
                    .ok_or_else(|| err("RESULT_FINITE_TRADE_FEES"))?,
            )
        } else {
            None
        };
        verify_fee_prefix(&mut cumulative_fees, application, snapshot, p)?;
        if !commands.insert(command)
            || provenance["outcome"] != "Applied"
            || point["source"] != kind
            || point["sequence"] != index
            || point["account_sequence"] != index
            || snapshot["sequence"] != index
            || snapshot["trade_sequence"] != trade_sequence
            || point["source_time"] != input["time"]
            || provenance["source_time"] != input["time"]
            || point["cause"] != provenance["cause"]
            || point["time"] != time
            || snapshot["time"] != time
            || point["external_cash_flow"] != first["external_cash_flow"]
            || point["external_cash_flow_occurred"] != false
        {
            return Err(err("RESULT_FINITE_ACCOUNT_POINT"));
        }
    }
    if expected.next().is_some() || !required_margin.is_empty() {
        return Err(err("RESULT_FINITE_ACCOUNT_OCCURRENCES"));
    }
    let equity = equity_points(inputs.iter().copied(), performance)?;
    let last_equity = equity
        .last()
        .ok_or_else(|| err("RESULT_ACCOUNT_TIMELINE"))?;
    let initial_equity = fixed(&summary["initial_equity"], p)?;
    let final_equity = fixed(&summary["final_equity"], p)?;
    if equity.iter().any(|point| point["drawdown"].is_null()) {
        quality.insert("NON_POSITIVE_HIGH_WATER_MARK");
    }
    if initial_equity <= 0 {
        quality.insert("ZERO_INITIAL_EQUITY");
    }
    for field in ["return_since_start", "current_drawdown", "maximum_drawdown"] {
        if !summary[field].is_null() {
            fixed(&summary[field], 8)?;
        }
    }
    let current = &summary["current_drawdown"];
    let initial_nav: OnlyDecimal = text(&summary["initial_equity"])?.parse()?;
    let final_nav: OnlyDecimal = text(&summary["final_equity"])?.parse()?;
    let recorded_return: Option<OnlyDecimal> = summary["return_since_start"]
        .as_str()
        .map(str::parse)
        .transpose()?;
    let actual_return = boundary(onlyalpha_account::equity_drawdown(&final_nav, &initial_nav))?;
    if summary["authority"] != "ACCOUNT"
        || summary["drawdown_basis"] != "ACCOUNT_EQUITY"
        || summary["valuation_count"] != timeline.len()
        || summary["quality_flags"] != json!(quality)
        || summary["initial_equity"] != first["snapshot"]["equity"]
        || summary["final_equity"] != final_snapshot["equity"]
        || summary["external_cash_flow"] != original["summary"]["external_cash_flow"]
        || summary["external_cash_flow_occurred"] != false
        || recorded_return != actual_return
        || ["realized_pnl", "unrealized_pnl", "fees"]
            .iter()
            .any(|f| summary[*f] != final_snapshot[*f])
        || fixed(&summary["net_pnl"], p)? != final_equity - initial_equity
        || fixed(&summary["high_water_mark"], p)? != exact(&last_equity["high_water_mark"])?
        || current.is_null() != last_equity["drawdown"].is_null()
        || (!current.is_null() && exact(current)? != exact(&last_equity["drawdown"])?)
    {
        return Err(err("RESULT_FINITE_ACCOUNT_SUMMARY"));
    }
    Ok(equity)
}

fn verify_account_commands(
    result: &Value,
    checkpoint: &Value,
    genesis: &Components,
    inputs_by_cause: &BTreeMap<&str, &Value>,
    trades: &VerifiedTrades<'_>,
) -> Result<(), Error> {
    let account_payloads = &trades.account_payloads;
    let performance = &result["runtime_performance"];
    let commands = boundary(genesis.account.checkpoint_commands(
        checkpoint,
        text(&performance["account_checkpoint"])?,
        &result["final_account"],
    ))?;
    let timeline = array(&performance["timeline"])?;
    if commands.len() + 1 != timeline.len() {
        return Err(err("RESULT_FINITE_ACCOUNT_OCCURRENCES"));
    }
    let mut margin_owner = genesis.margin_owner()?;
    let mut rounding_adjustment = exact(&timeline[0]["snapshot"]["realized_rounding_adjustment"])?;
    for ((command, receipt), points) in commands.iter().zip(timeline.windows(2)) {
        let before = &points[0]["snapshot"];
        let after = &points[1]["snapshot"];
        let provenance = &points[1]["provenance"];
        let cause = text(&provenance["upstream_cause"])?;
        if provenance["cause"] != *receipt
            || command["cause"] != cause
            || command["command_id"] != provenance["command"]
            || command["op"] != provenance["kind"]
            || command["time"] != provenance["source_time"]
        {
            return Err(err("RESULT_FINITE_ACCOUNT_RECEIPT"));
        }
        let input = inputs_by_cause[cause];
        let payload = &command["payload"];
        let source = &input["payload"];
        let operation = text(&command["op"])?;
        let matches_source = match operation {
            "RESERVE" => account_payloads.get(cause) == Some(payload),
            "STAGE" => {
                let stage = match text(&input["op"])? {
                    "ADMIT" => "SENT_TO_BROKER",
                    "SUBMISSION" => "SUBMIT_UNKNOWN",
                    "ACCEPT" => "BROKER_ACKNOWLEDGED",
                    "CANCEL" => "CANCEL_REQUESTED",
                    _ => return Err(err("RESULT_FINITE_ACCOUNT_COMMAND_SOURCE")),
                };
                payload["reservation"] == source["order"] && payload["stage"] == stage
            }
            "RELEASE" => {
                let outcome = if genesis.config["schema_version"] == 3 {
                    &source["broker"]["record"]["kind"]
                } else {
                    &source["outcome"]
                };
                payload["reservation"] == source["order"] && &payload["outcome"] == outcome
            }
            "TRADE" => {
                let expected = account_payloads
                    .get(cause)
                    .and_then(Value::as_object)
                    .ok_or_else(|| err("RESULT_FINITE_ACCOUNT_COMMAND_SOURCE"))?;
                rounding_adjustment += trades
                    .rounding_deltas
                    .get(cause)
                    .ok_or_else(|| err("RESULT_FINITE_ACCOUNT_ROUNDING"))?;
                if exact(&payload["realized_rounding_adjustment"])? != rounding_adjustment {
                    return Err(err("RESULT_FINITE_ACCOUNT_ROUNDING"));
                }
                if expected.get("position_evidence") != Some(&payload["position_evidence"])
                    || payload["position_evidence"] != after["position_evidence"]
                {
                    return Err(err("RESULT_FINITE_ACCOUNT_POSITION"));
                }
                expected.iter().all(|(key, value)| payload[key] == *value)
                    && exact(&payload["realized_pnl_delta"])?
                        == exact(&after["realized_pnl"])? - exact(&before["realized_pnl"])?
                    && exact(&payload["market_value_delta"])?
                        == exact(&after["market_value"])? - exact(&before["market_value"])?
                    && payload["unrealized_pnl"] == after["unrealized_pnl"]
                    && payload["realized_rounding_adjustment"]
                        == after["realized_rounding_adjustment"]
            }
            "VALUATION" => {
                let position_digest = trades
                    .valuation_positions
                    .get(cause)
                    .ok_or_else(|| err("RESULT_FINITE_ACCOUNT_POSITION"))?;
                if hash(&payload["position"]) != *position_digest {
                    return Err(err("RESULT_FINITE_ACCOUNT_POSITION"));
                }
                let intent = &payload["intent"];
                let mut expected = if input["op"] == "MARK" {
                    let raw = &source["fact"];
                    let fact = mark_fact(&genesis.config, raw)?;
                    let sequence = &input["runtime_sequence"];
                    json!({"schema_version":1,"valuation":raw["fact_id"],"version":sequence,"economic_version":before["economic_version"],"position_evidence":position_digest,"marks":[{"schema_version":1,"instrument":genesis.config["perpetual"]["instrument"],"mark":raw["value"]["value"],"precision":raw["value"]["precision"],"source_ref":raw["fact_id"],"family":"MARK","version":sequence,"time":nanos(*fact.ts_event())?,"as_of_sequence":sequence}]})
                } else {
                    source.clone()
                };
                expected["time"] = input["time"].clone();
                intent == &expected
                    && intent["economic_version"] == before["economic_version"]
                    && intent["position_evidence"] == position_digest.as_str()
                    && after["position_evidence"] == position_digest.as_str()
            }
            "ECONOMIC" => account_payloads.get(cause) == Some(payload),
            "SETTLE" => {
                account_payloads.get(cause) == Some(payload)
                    && exact(&payload["amount"])?
                        == exact(&after["withdrawable"])? - exact(&before["withdrawable"])?
            }
            "MARGIN" if genesis.config["schema_version"] == 3 => trades
                .margin_effects
                .get(cause)
                .into_iter()
                .flatten()
                .any(|effect| {
                    command["command_id"] == Components::margin_command_id(input, effect)
                        && effect.replay_input() == *payload
                }),
            "MARGIN" => {
                let margin = &payload["command"];
                if margin["time"] != input["time"] {
                    return Err(err("RESULT_FINITE_ACCOUNT_COMMAND_SOURCE"));
                }
                let action = text(&margin["action"])?;
                let expected = match (action, text(&input["op"])?) {
                    ("RELEASE_RESERVED", "FILL" | "TERMINAL") => {
                        let state = boundary(margin_owner.snapshot(id(&margin["reservation"])?))?;
                        if state["order"] != source["order"]
                            || (input["op"] == "FILL"
                                && account_payloads.get(cause).is_none_or(|fill| {
                                    fill["terminal_fill"] != true || fill["side"] != "BUY"
                                }))
                        {
                            return Err(err("RESULT_FINITE_ACCOUNT_COMMAND_SOURCE"));
                        }
                        Components::derived_margin(
                            input,
                            &state,
                            action,
                            state["unfilled"].clone(),
                            state["reserved"].clone(),
                            json!("0.00"),
                        )
                    }
                    ("RESERVE", "ADMIT") | ("OCCUPY", "FILL") => {
                        source["collateral"]["instruction"].clone()
                    }
                    ("RELEASE_OCCUPIED", "FILL") => {
                        let mut original = margin.clone();
                        original
                            .as_object_mut()
                            .ok_or_else(|| err("RESULT_FINITE_ACCOUNT_COMMAND_SOURCE"))?
                            .remove("source_fingerprint");
                        if margin["source_fingerprint"] != hash(&original)
                            || margin["source_order"] != source["order"]
                        {
                            return Err(err("RESULT_FINITE_ACCOUNT_COMMAND_SOURCE"));
                        }
                        margin.clone()
                    }
                    _ => return Err(err("RESULT_FINITE_ACCOUNT_COMMAND_SOURCE")),
                };
                let effect = boundary(margin_owner.apply(&expected))?;
                &effect.replay_input() == payload
                    && command["command_id"]
                        == format!(
                            "MACMD-{}",
                            hash(&json!([input["input_id"], effect.record()["id"]]))
                        )
            }
            _ => false,
        };
        if exact(&after["realized_rounding_adjustment"])? != rounding_adjustment {
            return Err(err("RESULT_FINITE_ACCOUNT_ROUNDING"));
        }
        if !matches_source {
            return Err(err("RESULT_FINITE_ACCOUNT_COMMAND_SOURCE"));
        }
        let cash_delta = match operation {
            "TRADE" => {
                let principal = if genesis.config["schema_version"] == 3 {
                    BigDecimal::from(0)
                } else if payload["side"] == "BUY" {
                    -exact(&payload["notional"])?
                } else {
                    exact(&payload["notional"])?
                };
                principal - exact(&payload["charges"])? + exact(&payload["rebates"])?
            }
            "ECONOMIC" => exact(&payload["amount"])?,
            _ => BigDecimal::from(0),
        };
        let economic_change = matches!(operation, "TRADE" | "ECONOMIC" | "MARGIN" | "SETTLE");
        let valuation_version = if operation == "VALUATION" {
            &payload["intent"]["version"]
        } else {
            &before["valuation_version"]
        };
        if exact(&after["cash"])? != exact(&before["cash"])? + cash_delta
            || uint(&before["economic_version"])?.checked_add(u64::from(economic_change))
                != Some(uint(&after["economic_version"])?)
            || &after["valuation_version"] != valuation_version
            || (operation != "TRADE" && after["realized_pnl"] != before["realized_pnl"])
        {
            return Err(err("RESULT_FINITE_ACCOUNT_TRANSITION"));
        }
        if matches!(operation, "TRADE" | "VALUATION") {
            let (market, unrealized) = trades
                .valuations
                .get(cause)
                .ok_or_else(|| err("RESULT_FINITE_ACCOUNT_VALUATION"))?;
            if exact(&after["market_value"])? != *market
                || exact(&after["unrealized_pnl"])? != *unrealized
            {
                return Err(err("RESULT_FINITE_ACCOUNT_VALUATION"));
            }
        } else if ["market_value", "unrealized_pnl", "position_evidence"]
            .iter()
            .any(|field| after[*field] != before[*field])
        {
            return Err(err("RESULT_FINITE_ACCOUNT_VALUATION"));
        }
    }
    Ok(())
}

fn verify_account_snapshot(snapshot: &Value, template: &Value, p: u8) -> Result<(), Error> {
    same_fields(snapshot, template)?;
    for field in [
        "engine",
        "runtime",
        "account",
        "gateway",
        "generation",
        "currency",
        "account_type",
    ] {
        if snapshot[field] != template[field] {
            return Err(err("RESULT_FINITE_ACCOUNT_SCOPE"));
        }
    }
    for field in [
        "reserved_margin",
        "occupied_margin",
        "released_margin",
        "available_margin",
        "cash",
        "reserved",
        "unsettled",
        "trade_available",
        "withdrawable",
        "market_value",
        "equity",
        "fees",
    ] {
        fixed(&snapshot[field], p)?;
    }
    for field in [
        "realized_pnl",
        "unrealized_pnl",
        "realized_rounding_adjustment",
    ] {
        analytical(&snapshot[field], p)?;
    }
    for field in ["economic_version", "valuation_version"] {
        uint(&snapshot[field])?;
    }
    if !snapshot["position_evidence"].is_null() {
        fp(&snapshot["position_evidence"])?;
    }
    let flags = flags(&snapshot["flags"])?;
    if snapshot["status"]
        != if flags.is_empty() {
            "ACTIVE"
        } else {
            "RECONCILING"
        }
        || exact(&snapshot["cash"])? + exact(&snapshot["market_value"])?
            != exact(&snapshot["equity"])?
    {
        return Err(err("RESULT_FINITE_ACCOUNT_SNAPSHOT"));
    }
    let maintenance_unavailable = flags.contains("MAINTENANCE_UNAVAILABLE");
    if maintenance_unavailable {
        if !snapshot["maintenance_required"].is_null() {
            return Err(err("RESULT_FINITE_MAINTENANCE"));
        }
    } else {
        fixed(&snapshot["maintenance_required"], p)?;
    }
    if snapshot["account_type"] == "LINEAR_PERPETUAL" {
        fixed(&snapshot["collateral"], p)?;
        if snapshot["maintenance_status"]
            != if maintenance_unavailable {
                "UNAVAILABLE"
            } else {
                "CURRENT"
            }
        {
            return Err(err("RESULT_FINITE_MAINTENANCE"));
        }
        if !snapshot["maintenance_to_equity"].is_null() {
            fixed(&snapshot["maintenance_to_equity"], 8)?;
        }
        let confirmed = &snapshot["last_confirmed_maintenance"];
        if !confirmed.is_null() {
            fields(confirmed, &["amount", "time", "source_ref"])?;
            fixed(&confirmed["amount"], p)?;
            id(&confirmed["source_ref"])?;
            uint(&confirmed["time"])?;
        }
    }
    Ok(())
}

fn verify_ledgers(
    result: &Value,
    projected: &Components,
    initial: &onlyalpha_strategy_ledger::Manager,
    initial_time: &Value,
) -> Result<Vec<String>, Error> {
    let clusters = projected.config["capitals"]
        .as_object()
        .expect("validated capitals")
        .keys()
        .cloned()
        .collect::<Vec<_>>();
    let finals = array(&result["final_ledgers"])?;
    let results = array(&result["cluster_results"])?;
    let timelines = array(&result["cluster_equity_timelines"])?;
    if [finals, results, timelines].iter().any(|rows| rows.len() != clusters.len()) {
        return Err(err("RESULT_FINITE_LEDGER_SCOPE"));
    }
    let mut expected = BTreeMap::<_, Vec<_>>::new();
    for point in projected.ledger.equity_occurrences() {
        expected.entry(text(&point["cluster"])?).or_default().push(point);
    }
    for (index, cluster) in clusters.iter().enumerate() {
        let timeline = &timelines[index];
        fields(timeline, &["cluster", "points"])?;
        let points = array(&timeline["points"])?;
        let initial_snapshot = boundary(initial.snapshot(cluster))?;
        let first = json!({"timeline_sequence":0,"source":"LEDGER_CREATED","time":initial_time,"snapshot":initial_snapshot});
        let final_ledger = &finals[index];
        if timeline["cluster"] != *cluster
            || points.first() != Some(&first)
            || results[index]
                != json!({"cluster":cluster,"revision":projected.config["profiles"][cluster]["revision"],"cluster_performance":{"authority":"STRATEGY_LEDGER","summary":cluster_summary(final_ledger)},"final_ledger":final_ledger})
        {
            return Err(err("RESULT_FINITE_LEDGER_SCOPE"));
        }
        let original = expected.remove(cluster.as_str()).unwrap_or_default();
        if points.len() != original.len() + 1 {
            return Err(err("RESULT_FINITE_LEDGER_OCCURRENCES"));
        }
        for ((ordinal, entry), expected) in points.iter().enumerate().skip(1).zip(original) {
            fields(entry, &["timeline_sequence", "source", "point"])?;
            let point = &entry["point"];
            same_fields(point, expected)?;
            if entry["timeline_sequence"] != ordinal
                || entry["source"] != "LEDGER_OCCURRENCE"
                || ["sequence", "cluster", "time", "cause", "status"]
                    .iter()
                    .any(|key| point[*key] != expected[*key])
            {
                return Err(err("RESULT_FINITE_LEDGER_OCCURRENCES"));
            }
            verify_ledger_snapshot(&point["snapshot"], &expected["snapshot"])?;
        }
        let expected_final = boundary(projected.ledger.snapshot(cluster))?;
        verify_ledger_snapshot(final_ledger, &expected_final)?;
        if final_ledger["flags"] != json!([]) || exact(&final_ledger["reserved"])? != 0 {
            return Err(err("RESULT_FINITE_LEDGER_FINAL"));
        }
    }
    Ok(clusters)
}

fn verify_ledger_snapshot(snapshot: &Value, expected: &Value) -> Result<(), Error> {
    if snapshot == expected {
        return Ok(());
    }
    for (fields, code) in [
        (&["realized_rounding_adjustment"][..], "RESULT_FINITE_LEDGER_ROUNDING"),
        (&["fees"][..], "RESULT_FINITE_TRADE_FEES"),
        (&["simple_return", "daily_return"][..], "RESULT_FINITE_LEDGER_RETURN"),
    ] {
        if fields.iter().any(|field| snapshot[*field] != expected[*field]) {
            return Err(err(code));
        }
    }
    Err(err("RESULT_FINITE_LEDGER_SNAPSHOT"))
}

struct OrderOrigin<'a> {
    snapshot: &'a Value,
    admission: &'a Value,
    cluster: &'a str,
    instrument: String,
    quantity_precision: u8,
    sequence: u64,
}

struct VerifiedTrades<'a> {
    closed_cycles: BTreeMap<String, usize>,
    fees: BTreeMap<&'a str, Value>,
    rounding_deltas: BTreeMap<&'a str, BigDecimal>,
    account_payloads: BTreeMap<String, Value>,
    valuations: BTreeMap<&'a str, (BigDecimal, BigDecimal)>,
    valuation_positions: BTreeMap<&'a str, String>,
    margin_effects: BTreeMap<&'a str, Vec<onlyalpha_margin::Effect>>,
}

fn verify_orders_and_positions<'a>(
    result: &Value,
    genesis: &mut Components,
    configuration: &Value,
    inputs: &[&Value],
    applied: &[(&'a str, &'a Value)],
    market_cut: Option<&crate::MarketSourceCut>,
) -> Result<VerifiedTrades<'a>, Error> {
    let instruments = array(&configuration["instruments"])?
        .iter()
        .map(|spec| Ok((id(&spec["id"])?, spec)))
        .collect::<Result<BTreeMap<_, _>, Error>>()?;
    let fee_config = &genesis.meta["fee_authority"];
    let mut fee_owner = boundary(onlyalpha_fee::Manager::new(
        fee_config["config"].clone(),
        usize::try_from(uint(&fee_config["capacity"])?)
            .map_err(|_| err("RECONCILIATION_FEE_CAPACITY"))?,
    ))?;
    let mut fees = BTreeMap::new();
    let mut rounding_deltas = BTreeMap::new();
    let mut account_payloads = BTreeMap::new();
    let multiplier = genesis.contract_multiplier()?;
    let perpetual = configuration["schema_version"] == 3;
    let orders = array(&result["orders"])?;
    let admissions = inputs
        .iter()
        .copied()
        .filter(|input| input["op"] == "ADMIT");
    if admissions.clone().count() != orders.len() {
        return Err(err("RESULT_FINITE_ORDERS"));
    }
    let mut origins = BTreeMap::new();
    for (order, admission) in orders.iter().zip(admissions) {
        fields(order, &["snapshot", "submission", "creation"])?;
        let snapshot = &order["snapshot"];
        let decoded = OnlyOrderSnapshot::from_record(snapshot)?;
        let payload = &admission["payload"];
        let request = &payload["request"];
        let cluster = id(&admission["cluster"])?;
        let order_id = id(&payload["order"])?;
        let instrument = OnlyInstrumentId::from_record(&request["instrument_id"])?.to_string();
        let spec = instruments
            .get(instrument.as_str())
            .ok_or_else(|| err("RESULT_FINITE_POSITION_SCOPE"))?;
        let quantity_precision = if perpetual {
            checked_admission_request(request)?;
            validate_admission_intent(request, text(&request["side"])?)?;
            admission_quantity_precision(spec, request)?
        } else {
            uint(&spec["quantity_precision"])? as u8
        };
        if decoded.to_record() != *snapshot
            || !matches!(
                decoded.status(),
                OnlyOrderStatus::Filled
                    | OnlyOrderStatus::Cancelled
                    | OnlyOrderStatus::Expired
                    | OnlyOrderStatus::Rejected
                    | OnlyOrderStatus::Failed
            )
            || order["submission"] != "RESOLVED"
            || snapshot["runtime_id"]["value"] != configuration["runtime"]
            || snapshot["account_id"]["value"] != configuration["account"]
            || snapshot["cluster_id"]["value"] != cluster
            || snapshot["order_id"]["value"] != order_id
            || snapshot["created_at"]["unix_nanos"] != admission["time"]
            || snapshot["historical_fill_identity_missing"] != false
            || order["creation"]
                != json!({"schema_version":1,"op":"CREATE","cluster_id":cluster,"account_id":configuration["account"],"request":request,"cause":hash(admission)})
            || [
                "request_id",
                "instrument_id",
                "side",
                "offset",
                "order_type",
                "time_in_force",
                "quantity",
                "price",
                "stop_price",
                "expire_time",
                "tags",
                "metadata",
                "execution_intent",
            ]
            .iter()
            .any(|field| snapshot[*field] != request[*field])
        {
            return Err(err("RESULT_FINITE_ORDER"));
        }
        if !perpetual && request["side"] == "BUY" {
            let funding = &payload["fee_contract"]["funding"];
            let amount = nonnegative(&funding["principal_reservation"]["amount"])?
                + nonnegative(&payload["fee_budget"])?;
            account_payloads.insert(
                hash(admission),
                json!({"schema_version":1,"reservation":order_id,"order":order_id,"amount":money(&amount,genesis.precision)?}),
            );
        }
        let origin = OrderOrigin {
            snapshot,
            admission,
            cluster,
            instrument,
            quantity_precision,
            sequence: uint(&admission["runtime_sequence"])?,
        };
        if origins.insert(order_id, origin).is_some() {
            return Err(err("RESULT_FINITE_ORDER"));
        }
    }
    for input in inputs.iter().copied().filter(|input| {
        matches!(
            input["op"].as_str(),
            Some("SUBMISSION" | "ACCEPT" | "CANCEL" | "TERMINAL" | "FILL")
        )
    }) {
        let order = id(&input["payload"]["order"])?;
        let origin = origins
            .get(order)
            .ok_or_else(|| err("RESULT_FINITE_ORDER"))?;
        if input["cluster"] != origin.cluster
            || input["revision"] != origin.admission["revision"]
            || uint(&input["runtime_sequence"])? <= origin.sequence
        {
            return Err(err("RESULT_FINITE_ORDER"));
        }
    }
    let mut trade_ids = BTreeSet::new();
    let mut valuations = BTreeMap::new();
    let mut valuation_positions = BTreeMap::new();
    let mut fill_marks = BTreeMap::<(&str, &str), BigDecimal>::new();
    let mut latest_mark = None;
    let mut margin = perpetual.then(|| genesis.margin_owner()).transpose()?;
    let mut margin_effects = BTreeMap::<_, Vec<_>>::new();
    let mut settlement = (!perpetual)
        .then(|| genesis.settlement_owner())
        .transpose()?;
    for &(cause, input) in applied {
        let payload = &input["payload"];
        match text(&input["op"])? {
            "ADMIT" => {
                let order = id(&payload["order"])?;
                let origin = &origins[order];
                if let Some(owner) = &mut margin {
                    boundary(genesis.position.admit_new_risk())?;
                    let request = &payload["request"];
                    let notional = nonnegative(&request["price"]["value"])?
                        * nonnegative(&request["quantity"]["value"])?
                        * &multiplier;
                    genesis.create_order(input, order)?;
                    let snapshot = boundary(genesis.order.get(origin.cluster, order))?;
                    let contract = Fees::new(configuration, uint(&input["day_index"])?)?
                        .contract(&snapshot, uint(&input["time"])?, &notional)?;
                    genesis.bind_order_fee(input, order, &contract)?;
                    genesis.begin_order_submission(input, order)?;
                    let amount = exact(&contract["funding"]["fee_reservation"]["amount"])?;
                    account_payloads.insert(cause.into(), json!({"schema_version":1,"reservation":order,"order":order,"amount":money(&amount,genesis.precision)?}));
                    let collateral = genesis.perpetual_collateral(input, request, None, &notional, owner)?;
                    let effect = boundary(owner.apply(&collateral["instruction"]))?;
                    margin_effects.entry(cause).or_default().push(effect);
                    std::sync::Arc::make_mut(&mut genesis.meta)["orders"][order] =
                        json!({"request":request});
                }
                if let Some(owner) = &mut settlement {
                    genesis.create_order(input, order)?;
                    genesis.bind_order_fee(input, order, &payload["fee_contract"])?;
                    genesis.begin_order_submission(input, order)?;
                    genesis.admit_settlement_order(
                        owner,
                        input,
                        &origin.instrument,
                        origin.quantity_precision,
                    )?;
                }
                if boundary(genesis.ledger.snapshot(origin.cluster))?["lifecycle"] == "CREATED" {
                    let activate = genesis.ledger_command(input, "ACTIVATE", json!({"schema_version":1}), 0);
                    genesis.ledger_apply(&activate)?;
                }
                if origin.snapshot["side"] == "SELL" {
                    genesis.reserve_position(input, &origin.instrument)?;
                    genesis.stage_position(input, "SENT_TO_BROKER", 3)?;
                } else {
                    let reserve = genesis.ledger_command(input, "RESERVE", account_payloads[cause].clone(), 2);
                    genesis.ledger_apply(&reserve)?;
                    let stage = genesis.ledger_command(input, "STAGE", json!({"schema_version":1,"reservation":payload["order"],"stage":"SENT_TO_BROKER"}), 3);
                    genesis.ledger_apply(&stage)?;
                }
                continue;
            }
            op @ ("ACCEPT" | "CANCEL" | "TERMINAL" | "SUBMISSION") => {
                let order = id(&payload["order"])?;
                let origin = origins
                    .get(order)
                    .ok_or_else(|| err("RESULT_FINITE_ORDER"))?;
                match op {
                    "SUBMISSION" => genesis.apply_order_submission(input)?,
                    "CANCEL" => genesis.apply_order_cancel(input)?,
                    _ if perpetual => {
                        genesis.perpetual_broker_order(input)?;
                        genesis.apply_native_order_fact(input, order, &payload["broker"]["record"])?;
                    }
                    "ACCEPT" => genesis.apply_spot_order_accept(input, order)?,
                    _ => genesis.apply_order_terminal(input, order)?,
                }
                if origin.snapshot["side"] == "SELL" {
                    match op {
                        "ACCEPT" => genesis.stage_position(input, "BROKER_ACKNOWLEDGED", 0)?,
                        "CANCEL" | "TERMINAL" => {
                            genesis.release_position(input, op == "TERMINAL")?
                        }
                        _ if payload["outcome"] == "UNKNOWN" => {
                            boundary(genesis.position.reservation(order))?;
                        }
                        _ => {}
                    }
                } else if op == "TERMINAL" {
                    let outcome = if perpetual { &payload["broker"]["record"]["kind"] } else { &payload["outcome"] };
                    let release = genesis.ledger_command(input, "RELEASE", json!({"schema_version":1,"reservation":order,"outcome":outcome}), 0);
                    genesis.ledger_apply(&release)?;
                } else if let Some(stage) = match op {
                    "ACCEPT" => Some("BROKER_ACKNOWLEDGED"),
                    "CANCEL" => Some("CANCEL_REQUESTED"),
                    "SUBMISSION" if payload["outcome"] == "UNKNOWN" => Some("SUBMIT_UNKNOWN"),
                    _ => None,
                } {
                    let stage = genesis.ledger_command(input, "STAGE", json!({"schema_version":1,"reservation":order,"stage":stage}), 0);
                    genesis.ledger_apply(&stage)?;
                }
                if op == "TERMINAL" && let Some(owner) = &mut margin {
                    let state = owner.snapshots().into_iter()
                        .find(|state| state["order"] == order)
                        .ok_or_else(|| err("EXECUTION_MARGIN_NOT_ADMITTED"))?;
                    let command = Components::derived_margin(
                        input, &state, "RELEASE_RESERVED", state["unfilled"].clone(),
                        state["reserved"].clone(), json!("0.00"),
                    );
                    margin_effects.entry(cause).or_default().push(boundary(owner.apply(&command))?);
                }
                continue;
            }
            "SETTLEMENT_MATURITY" => {
                let owner = settlement
                    .as_mut()
                    .ok_or_else(|| err("RESULT_FINITE_SETTLEMENT"))?;
                let (effect, instrument) = Components::settlement_effect(owner, input)?;
                if let Some(payload) = genesis.settle_position(input, &effect, &instrument)? {
                    let command = genesis.ledger_command(input, "SETTLEMENT", payload, 0);
                    genesis.ledger_apply(&command)?;
                }
                if exact(&effect["cash_amount"])? != 0 {
                    account_payloads.insert(cause.into(), json!({"schema_version":1,"instruction":effect["id"],"source_trade":effect["trade"],"amount":effect["cash_amount"]}));
                }
                continue;
            }
            "FUNDING" => {
                let cut = market_cut.ok_or_else(|| err("RESULT_FINITE_MARKET_FACT"))?;
                let effect = boundary(genesis.position.funding(
                    cut,
                    &json!({"schema_version":1,"mark":payload["mark_fact_id"],"funding":payload["fact"]["fact_id"]}),
                ))?;
                let flow = effect.record();
                let command = genesis.ledger_command(input, "FUNDING", Value::Null, 0);
                if boundary(std::sync::Arc::make_mut(&mut genesis.ledger).apply_funding(&command, &effect))?.status
                    != onlyalpha_strategy_ledger::Status::Applied
                {
                    return Err(err("RESULT_FINITE_LEDGER_OCCURRENCES"));
                }
                account_payloads.insert(cause.into(), json!({"schema_version":1,"kind":"FUNDING","instrument":flow["instrument"],"cashflow":flow["cashflow"],"source_fact":flow["source_fact"],"amount":flow["amount"],"funding_source":effect.reference(),"trade_lineage":effect.account_lineage()}));
                continue;
            }
            "MARK" | "VALUATION" => {
                let exposure = genesis.position.current_exposure();
                let accounts = array(&exposure["accounts"])?;
                let mut marks = BTreeMap::new();
                if input["op"] == "MARK" {
                    let mark = &payload["fact"]["value"]["value"];
                    latest_mark = Some(mark);
                    genesis.record_perpetual_mark(&payload["fact"])?;
                    let owner = margin.as_mut().expect("native Margin");
                    let effects = genesis.mark_margin_effects(input, owner)?;
                    if !effects.is_empty() {
                        margin_effects.insert(cause, effects);
                    }
                    if accounts.is_empty() {
                        continue;
                    }
                    marks.insert(
                        id(&configuration["perpetual"]["instrument"])?,
                        nonnegative(mark)?,
                    );
                } else {
                    for mark in array(&payload["marks"])? {
                        if marks
                            .insert(id(&mark["instrument"])?, nonnegative(&mark["mark"])?)
                            .is_some()
                        {
                            return Err(err("RESULT_FINITE_ACCOUNT_VALUATION"));
                        }
                    }
                }
                if marks.len() != accounts.len() || marks.values().any(|mark| mark == &0) {
                    return Err(err("RESULT_FINITE_ACCOUNT_VALUATION"));
                }
                let mut books = Vec::with_capacity(accounts.len());
                for row in accounts {
                    let mark = marks
                        .get(text(&row["instrument"])?)
                        .ok_or_else(|| err("RESULT_FINITE_ACCOUNT_VALUATION"))?;
                    books.push((&row["snapshot"], mark));
                }
                valuations.insert(
                    cause,
                    position_value(books.into_iter(), &multiplier, genesis.precision, perpetual)?,
                );
                let ledger_valuation = if input["op"] == "MARK" {
                    json!({"valuation":payload["fact"]["fact_id"],"version":input["runtime_sequence"],"marks":[{"instrument":configuration["perpetual"]["instrument"],"mark":payload["fact"]["value"]["value"]}]})
                } else {
                    payload.clone()
                };
                genesis.value_ledgers(input, &ledger_valuation, &exposure)?;
                valuation_positions
                    .insert(cause, boundary(genesis.position.checkpoint_record())?.1);
                for ((_, instrument), mark) in &mut fill_marks {
                    *mark = marks[instrument].clone();
                }
                continue;
            }
            "FILL" => {}
            _ => return Err(err("RESULT_FINITE_FACT")),
        }
        let order = id(&payload["order"])?;
        let origin = origins
            .get(order)
            .ok_or_else(|| err("RESULT_FINITE_ORDER_TRADE"))?;
        let native = (configuration["schema_version"] == 3)
            .then_some(&payload["broker"]["record"]["payload"]["fill"]);
        let (quantity, price, trade) = if let Some(fill) = native {
            (
                &fill["quantity"]["value"],
                &fill["price"]["value"],
                &fill["trade_id"]["value"],
            )
        } else {
            (&payload["quantity"], &payload["price"], &payload["trade"])
        };
        let quantity = exact(quantity)?;
        let price = exact(price)?;
        let trade = id(trade)?;
        let sequence = uint(&input["runtime_sequence"])?;
        if !trade_ids.insert(trade) {
            return Err(err("RESULT_FINITE_ORDER_TRADE"));
        }
        validate_fill_price(&origin.admission["payload"]["request"], &price, &quantity)?;
        let application = if let Some(native) = native {
            let snapshot = genesis.perpetual_broker_order(input)?;
            let before = snapshot.to_record();
            let day = uint(&origin.admission["day_index"])?;
            let effective = fill_day(day, uint(&origin.admission["time"])?, native)?;
            let assessment = Fees::new(configuration, effective)?.fill(
                &snapshot,
                day,
                native,
                &exact(&before["filled_quantity"]["value"])?,
                &exact(&before["cumulative_price_quantity"])?,
            )?;
            boundary(fee_owner.apply(&assessment))?
        } else {
            boundary(fee_owner.apply_admitted_target(&payload["fees"]))?
        }
        .record();
        let fee = fee_application_entry(&application, origin.cluster, order, trade)?;
        if native.is_none() && fee["fee_instruction"] != payload["fees"]["instruction"] {
            return Err(err("RESULT_FINITE_TRADE_FEES"));
        }
        let fill_notional = &price * &quantity;
        let gross = &fill_notional * &multiplier;
        let (notional, venue_trade, cash_withdrawable, bucket) = if let Some(native) = native {
            (
                money(
                    &gross.with_scale_round(
                        i64::from(genesis.precision),
                        bigdecimal::RoundingMode::HalfEven,
                    ),
                    genesis.precision,
                )?,
                &native["venue_trade_id"]["value"],
                true,
                "SETTLED",
            )
        } else {
            let settlement = &payload["settlement"];
            let day = text(&input["trading_day"])?;
            let schedule = boundary(onlyalpha_settlement::resolve_schedule(
                &settlement["calendar"],
                &settlement["policy"],
                day,
            ))?;
            if ["asset_booked", "cash_booked", "cash_trade_available"]
                .iter()
                .any(|key| schedule[key] != day)
            {
                return Err(err("RESULT_FINITE_SETTLEMENT"));
            }
            let unsettled =
                origin.snapshot["side"] == "BUY" && schedule["asset_trade_available"] != day;
            (
                settled_money(
                    settlement,
                    "gross_notional",
                    &gross,
                    &configuration["currency"],
                    genesis.precision,
                )?,
                &payload["venue_trade"],
                schedule["cash_withdrawable"] == day,
                if unsettled { "UNSETTLED" } else { "SETTLED" },
            )
        };
        let buy = origin.snapshot["side"] == "BUY";
        let snapshot = if perpetual {
            genesis.apply_native_order_fact(input, order, &payload["broker"]["record"])?
        } else {
            genesis.apply_spot_order_fill(input, order)?
        };
        let terminal = snapshot["status"] == "FILLED";
        let instrument = origin.instrument.as_str();
        if let (Some(owner), Some(native)) = (&mut margin, native) {
            let collateral = genesis.perpetual_collateral(
                input, &origin.admission["payload"]["request"], Some(native), &gross, owner,
            )?;
            let effect = boundary(owner.apply(&collateral["instruction"]))?;
            let effects = margin_effects.entry(cause).or_default();
            effects.push(effect);
            if terminal {
                let state = boundary(owner.snapshot(id(&collateral["instruction"]["reservation"])?))?;
                let release = Components::derived_margin(
                    input, &state, "RELEASE_RESERVED", state["unfilled"].clone(),
                    state["reserved"].clone(), json!("0.00"),
                );
                effects.push(boundary(owner.apply(&release))?);
            }
            effects.extend(genesis.mark_margin_effects(input, owner)?);
        }
        let before_allocation = match genesis.position.cluster(origin.cluster, instrument) {
            Ok(snapshot) => Some(snapshot),
            Err(e) if e.0 == "POSITION_ALLOCATION_NOT_FOUND" => None,
            Err(e) => return Err(Error(e.0)),
        };
        let ledger_before = allocation_before(before_allocation.as_ref(), genesis.precision)?;
        let before_cost = exact(&ledger_before["cost"])?;
        let command = genesis.position_trade_command(
            input,
            instrument,
            &origin.admission["payload"]["request"],
            &fee,
            bucket,
            terminal,
        )?;
        let fact = genesis.position_apply(&command)?;
        let position = boundary(genesis.position.account(instrument))?;
        let allocation = boundary(genesis.position.cluster(origin.cluster, instrument))?;
        let cost_delta = exact(&allocation["cost"])? - before_cost;
        let realized = exact(&fact["realized_pnl"])?;
        rounding_deltas.insert(
            cause,
            onlyalpha_strategy_ledger::realized_rounding_delta(
                perpetual,
                buy,
                &cost_delta,
                &exact(&json!(notional))?,
                &realized,
            ),
        );
        if let Some(owner) = &mut settlement {
            let instruction = genesis.settlement_instruction(
                input,
                &command["payload"],
                &json!({"notional":notional,"rebates":fee["rebates"]}),
                &position,
                &allocation,
            )?;
            boundary(owner.register(&instruction))?;
        }
        let mark = if perpetual {
            latest_mark.ok_or_else(|| err("RESULT_FINITE_ACCOUNT_VALUATION"))?
        } else {
            &payload["valuation"]["mark"]
        };
        let mark = nonnegative(mark)?;
        if mark == 0 {
            return Err(err("RESULT_FINITE_ACCOUNT_VALUATION"));
        }
        let ledger_after = allocation_witness(&allocation, genesis.precision)?;
        let ledger_trade = genesis.ledger_command(input,"TRADE",json!({"schema_version":1,"trade":trade,"execution":format!("ETX-{cause}"),"venue_trade":venue_trade,"order":order,"fee_instruction":fee["fee_instruction"],"source_sequence":sequence,"side":origin.snapshot["side"],"instrument":instrument,"notional":notional,"charges":fee["charges"],"rebates":fee["rebates"],"reservation":buy.then_some(order),"terminal_fill":terminal,"before":ledger_before,"after":ledger_after,"allocation_evidence":hash(&allocation),"mark":mark.normalized().to_plain_string(),"multiplier":multiplier.normalized().to_plain_string()}),0);
        if perpetual {
            let evidence = boundary(genesis.position.trade_evidence(trade))?;
            if boundary(std::sync::Arc::make_mut(&mut genesis.ledger).apply_position_trade(&ledger_trade, &evidence))?.status
                != onlyalpha_strategy_ledger::Status::Applied
            {
                return Err(err("RESULT_FINITE_LEDGER_OCCURRENCES"));
            }
        } else {
            genesis.ledger_apply(&ledger_trade)?;
        }
        fill_marks.insert((origin.cluster, instrument), mark);
        // Execution TRADE rounds each spot allocation, unlike account-wide VALUATION.
        let exposure = genesis.position.current_exposure();
        let mut books = Vec::new();
        for row in array(&exposure["allocations"])? {
            let key = (text(&row["cluster"])?, text(&row["instrument"])?);
            let mark = fill_marks
                .get(&key)
                .ok_or_else(|| err("RESULT_FINITE_ACCOUNT_VALUATION"))?;
            books.push((&row["snapshot"], mark));
        }
        valuations.insert(
            cause,
            position_value(books.into_iter(), &multiplier, genesis.precision, perpetual)?,
        );
        let mut account_payload = json!({"trade":trade,"execution":format!("ETX-{cause}"),"venue_trade":venue_trade,"order":order,"sequence":sequence,"side":origin.snapshot["side"],"notional":notional,"fee_instruction":fee["fee_instruction"],"charges":fee["charges"],"rebates":fee["rebates"],"realized_pnl_delta":exact_record(&realized,genesis.precision),"position_evidence":hash(&position),"reservation":buy.then_some(order),"terminal_fill":terminal,"cash_withdrawable":cash_withdrawable});
        if perpetual {
            account_payload["trade_evidence"] = command["payload"]["trade_evidence"].clone();
        }
        account_payloads.insert(cause.into(), account_payload);
        fees.insert(cause, fee);
    }
    for (order, origin) in &origins {
        let snapshot = boundary(genesis.order.get(origin.cluster, order))?;
        if snapshot.to_record() != *origin.snapshot
            || boundary(genesis.order.submission(origin.cluster, order))? != "RESOLVED"
        {
            return Err(err("RESULT_FINITE_ORDER_SNAPSHOT"));
        }
    }
    let exposure = genesis.position.current_exposure();
    for (name, owner) in [
        ("final_positions", "accounts"),
        ("final_allocations", "allocations"),
    ] {
        let actual = array(&result[name])?;
        let expected = array(&exposure[owner])?;
        if actual.len() != expected.len() {
            return Err(err("RESULT_FINITE_POSITIONS"));
        }
        for (actual, expected) in actual.iter().zip(expected) {
            same_fields(actual, expected)?;
            if actual["instrument"] != expected["instrument"]
                || actual["cluster"] != expected["cluster"]
            {
                return Err(err("RESULT_FINITE_POSITION_SCOPE"));
            }
            for (field, code) in [
                ("cost", "RESULT_FINITE_POSITION_COST"),
                ("average", "RESULT_FINITE_POSITION_AVERAGE"),
            ] {
                if actual["snapshot"][field] != expected["snapshot"][field] {
                    return Err(err(code));
                }
            }
            if actual != expected {
                return Err(err("RESULT_FINITE_POSITION_SNAPSHOT"));
            }
        }
    }
    let mut closed_cycles: BTreeMap<_, _> = configuration["capitals"]
        .as_object()
        .expect("validated capitals")
        .keys()
        .map(|cluster| (cluster.clone(), 0usize))
        .collect();
    for allocation in array(&exposure["allocations"])? {
        let cluster = text(&allocation["cluster"])?;
        let book = &allocation["snapshot"];
        let closed = uint(&book["cycle"])? - u64::from(book["status"] == "OPEN");
        *closed_cycles.get_mut(cluster).expect("validated cluster") += closed as usize;
    }
    Ok(VerifiedTrades {
        closed_cycles,
        fees,
        rounding_deltas,
        account_payloads,
        valuations,
        valuation_positions,
        margin_effects,
    })
}

fn position_value<'a>(
    books: impl Iterator<Item = (&'a Value, &'a BigDecimal)>,
    multiplier: &BigDecimal,
    precision: u8,
    perpetual: bool,
) -> Result<(BigDecimal, BigDecimal), Error> {
    let round = |value: BigDecimal| {
        value.with_scale_round(i64::from(precision), bigdecimal::RoundingMode::HalfEven)
    };
    let mut market = BigDecimal::from(0);
    let mut cost = BigDecimal::from(0);
    for (book, mark) in books {
        let gross = exact(&book["quantity"])? * mark * multiplier;
        market += if perpetual { gross } else { round(gross) };
        cost += exact(&book["cost"])? * multiplier;
    }
    let unrealized = &market - cost;
    if perpetual {
        market = round(unrealized.clone());
    }
    Ok((market, unrealized))
}
