//! Exact experimental participant construction. Values grant no Freeze, promotion, Run or LIVE authority.
use onlyalpha_backtest::{Error, Inputs, NextOpenPolicy, Trading};
use onlyalpha_calculation::product::Graph;
use onlyalpha_calculation_bridge::StrategyPreparation;
use bigdecimal::num_bigint::BigInt;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    numeric::OnlyDecimal,
    time::{OnlyTimestamp, OnlyUtcDateTime},
    value::{OnlyPrice, OnlyQuantity},
};
use onlyalpha_plugin_binance::spot_simulation::{SpotRuleSnapshot, SpotSimulationPolicy};
use onlyalpha_strategy::{NodePort, SourceRevision};
use serde_json::{Value, json};
const BAR_NS: u64 = 60_000_000_000;
const WORK: usize = 8 * 1024 * 1024;
fn invalid(code: &str) -> Error {
    Error(format!("BACKTEST_PREPARATION_{code}"))
}
fn boundary<T, E: std::fmt::Display>(value: Result<T, E>) -> Result<T, Error> {
    value.map_err(|e| Error(e.to_string()))
}
fn fixed_time(text: &str) -> Result<u64, Error> {
    let time: OnlyUtcDateTime = boundary(text.parse())?;
    boundary(
        OnlyTimestamp::from_datetime(time)
            .to_unix_nanos()
            .to_string()
            .parse(),
    )
}
fn ns(time: &OnlyTimestamp) -> Result<u64, Error> {
    boundary(time.to_unix_nanos().to_string().parse())
}
struct BinanceNextOpenPolicy(SpotSimulationPolicy);
impl NextOpenPolicy for BinanceNextOpenPolicy {
    fn binding(&self) -> Value {
        self.0.binding()
    }
    fn admission(
        &self,
        order: &Value,
        reference: &OnlyPrice,
        context: &Value,
    ) -> Result<Value, Error> {
        boundary(self.0.admission(order, reference, context))
    }
    fn fill(
        &self,
        order: &Value,
        price: &OnlyPrice,
        quantity: &OnlyQuantity,
        context: &Value,
    ) -> Result<Value, Error> {
        boundary(self.0.fill(order, price, quantity, context))
    }
}
/// Reconstruct only the original immutable plugin policy for terminal source
/// verification. The retained rules and complete policy capture must agree;
/// current exchange rules, SDKs and authoring state are never consulted.
pub fn terminal_policy(settings:&Value,native_policy:&Value)->Result<Box<dyn NextOpenPolicy>,Error>{
    let snapshot=boundary(SpotRuleSnapshot::from_record(&native_policy["rules_snapshot"]))?;
    let policy=boundary(SpotSimulationPolicy::new(snapshot,settings["execution"].clone()))?;
    let mut original=native_policy.clone();
    original.as_object_mut().ok_or_else(||invalid("TERMINAL_POLICY"))?.remove("execution_model").ok_or_else(||invalid("TERMINAL_POLICY"))?;
    if policy.binding()!=original{return Err(invalid("TERMINAL_POLICY"));}
    Ok(Box::new(BinanceNextOpenPolicy(policy)))
}
/// Immutable construction values only. Owning readers and Product admission must authenticate them separately.
#[derive(Clone)]
pub struct PreparedNextOpen {
    source: SourceRevision,
    inputs: Inputs,
    settings: Value,
    policy: SpotSimulationPolicy,
    window: Value,
    initial_ns: BigInt,
}
impl PreparedNextOpen {
    pub fn new(
        source: SourceRevision,
        inputs: Inputs,
        rules: SpotRuleSnapshot,
        execution: Value,
        sample_start: OnlyTimestamp,
        sample_end: OnlyTimestamp,
    ) -> Result<Self, Error> {
        onlyalpha_backtest::validate_configuration(&execution)?;
        let start = ns(&sample_start)?;
        let end = ns(&sample_end)?;
        if start != fixed_time("2025-01-03T00:00:00Z")?
            || end != fixed_time("2025-01-03T12:00:00Z")?
            || execution["runtime_kind"] != "BACKTEST"
        {
            return Err(invalid("FIXED_PROFILE"));
        }
        let source_record = source.to_record();
        let market = &source_record["market_input_contract"];
        let semantic = &market["bar_semantic"];
        if source_record["universe"]
            != json!({"kind":"SINGLE_INSTRUMENT","instruments":["BTCUSDT.BINANCE"]})
            || semantic
                != &json!({"schema_version":3,"formation":{"schema_version":1,"kind":"FIXED_DURATION","window_minutes":1,"stride_minutes":1,"alignment":"SESSION_START"},"price_type":"LAST","adjustment_policy":"RAW"})
            || market["data_kind"] != "BAR"
            || market["observation_admission"] != "FINAL_ONLY"
            || market["construction_requirement"]["kind"] != "EXACT_RECIPE"
            || market["construction_requirement"]["recipe"]["kind"] != "PROVIDER_NATIVE"
        {
            return Err(invalid("STRATEGY_SCOPE"));
        }
        let profiles = execution["profiles"]
            .as_object()
            .filter(|p| p.len() == 1)
            .ok_or_else(|| invalid("PROFILE_SCOPE"))?;
        let (cluster, profile) = profiles.iter().next().expect("one profile");
        if profile["revision"] != source.fingerprint()
            || profile["instruments"] != json!(["BTCUSDT.BINANCE"])
        {
            return Err(invalid("STRATEGY_IDENTITY"));
        }
        let amount = |v: &Value| -> Result<OnlyDecimal, Error> {
            boundary(v.as_str().ok_or_else(|| invalid("CAPITAL"))?.parse())
        };
        let capital: OnlyDecimal = boundary("10000".parse())?;
        if amount(&execution["initial_cash"])? != capital
            || amount(&execution["capitals"][cluster])? != capital
        {
            return Err(invalid("FIXED_CAPITAL"));
        }
        let instrument = boundary(rules.model_instrument())?.to_record();
        let expected_instruments = json!([{"schema_version":1,"id":"BTCUSDT.BINANCE","price_precision":instrument["price_precision"],"quantity_precision":instrument["quantity_precision"],"multiplier":"1"}]);
        if execution["instruments"] != expected_instruments
            || execution["currency"] != instrument["settlement_currency"]
        {
            return Err(invalid("INSTRUMENT_BINDING"));
        }
        let policy = boundary(SpotSimulationPolicy::new(rules, execution.clone()))?;
        let graph = boundary(Graph::from_record(&source_record["decision_graph"], WORK))?;
        let requirements = boundary(
            crate::application::strategy_research::canonical_input_window(
                &graph,
                start,
                end,
                BAR_NS,
                std::iter::empty::<&str>(),
            ),
        )?;
        let warmup = requirements["warmup_bars"]
            .as_u64()
            .ok_or_else(|| invalid("INPUT_REQUIREMENTS"))?;
        let count = (end - start) / BAR_NS;
        let total = count
            .checked_add(warmup)
            .ok_or_else(|| invalid("INPUT_BOUND"))?;
        let first = start
            .checked_sub(
                warmup
                    .checked_mul(BAR_NS)
                    .ok_or_else(|| invalid("INPUT_BOUND"))?,
            )
            .ok_or_else(|| invalid("INPUT_BOUND"))?;
        let event_start = first
            .checked_add(BAR_NS)
            .ok_or_else(|| invalid("INPUT_BOUND"))?;
        let event_end = end
            .checked_add(BAR_NS)
            .ok_or_else(|| invalid("INPUT_BOUND"))?;
        let source_pin = inputs.record();
        let sources = source_pin["sources"]
            .as_array()
            .filter(|s| s.len() == 1)
            .ok_or_else(|| invalid("SOURCE_SCOPE"))?;
        let source_id = sources[0]["source"]
            .as_str()
            .ok_or_else(|| invalid("SOURCE_SCOPE"))?;
        if inputs.records().len() as u64 != total {
            return Err(invalid("INPUT_COUNT"));
        }
        for (index, input) in inputs.records().iter().enumerate() {
            let expected_start = first
                .checked_add(
                    (index as u64)
                        .checked_mul(BAR_NS)
                        .ok_or_else(|| invalid("INPUT_BOUND"))?,
                )
                .ok_or_else(|| invalid("INPUT_BOUND"))?;
            let expected_end = expected_start
                .checked_add(BAR_NS)
                .ok_or_else(|| invalid("INPUT_BOUND"))?;
            let bar = input.bar();
            if input.source() != source_id
                || input.sequence() != index as u64 + 1
                || bar.instrument_id().to_string() != "BTCUSDT.BINANCE"
                || bar.bar_type().semantic().to_record() != *semantic
                || ns(&OnlyTimestamp::from_datetime(*bar.bar_start()))? != expected_start
                || ns(&OnlyTimestamp::from_datetime(*bar.bar_end()))? != expected_end
                || input.event_ns() != BigInt::from(expected_end)
            {
                return Err(invalid("EXACT_CLOSED_BAR_WINDOW"));
            }
        }
        let quantity = boundary(OnlyQuantity::new(
            boundary("0.01".parse())?,
            u8::try_from(
                instrument["quantity_precision"]
                    .as_u64()
                    .ok_or_else(|| invalid("INSTRUMENT"))?,
            )
            .map_err(|_| invalid("INSTRUMENT"))?,
        ))?;
        let settings = json!({"schema_version":2,"execution":execution,"instrument":instrument,"policy":{"schema_version":1,"kind":"NEXT_OPEN_LONG_ONLY_V1","quantity":quantity.to_record(),"buy_multiplier":"1.0002","sell_multiplier":"0.9998","start_ns":start.to_string(),"end_ns":end.to_string()}});
        let window = json!({"schema_version":1,"kind":"BAR_START_SAMPLE_CLOSED_EVENTS","sample_start_ns":start.to_string(),"sample_end_ns":end.to_string(),"bar_ns":BAR_NS.to_string(),"warmup_bars":warmup,"sample_bar_count":count,"total_bar_count":total,"source_bar_start_ns":first.to_string(),"source_bar_end_exclusive_ns":end.to_string(),"dataset_event_start_ns":event_start.to_string(),"dataset_event_end_exclusive_ns":event_end.to_string(),"dataset_columns":requirements["dataset_columns"]});
        Ok(Self {
            source,
            inputs,
            settings,
            policy,
            window,
            initial_ns: BigInt::from(first),
        })
    }
    pub fn record(&self) -> Value {
        json!({"schema_version":1,"contract":"ONLYALPHA_BTC_NEXT_OPEN_PREPARATION_V1","strategy_fingerprint":self.source.fingerprint(),"input_pin":self.inputs.fingerprint(),"settings":self.settings,"policy_binding":self.policy.binding(),"window":self.window,"initial_ns":self.initial_ns.to_string()})
    }
    pub fn simulation_policy(&self) -> &SpotSimulationPolicy {
        &self.policy
    }
    pub fn configuration(&self) -> &Value {
        &self.settings["execution"]
    }
    pub fn inputs(&self) -> &Inputs {
        &self.inputs
    }
    pub fn initial_ns(&self) -> &BigInt {
        &self.initial_ns
    }
    /// Consume the exact value preparation; this grants no Product or journal admission.
    pub fn into_participants<C: NodePort>(
        self,
        preparation: StrategyPreparation<C>,
    ) -> Result<Trading<C>, Error> {
        let revision = preparation.strategy().program().revision();
        if !revision.is_product_materialization()
            || revision.fingerprint() != self.source.fingerprint()
            || revision.to_record()["product"]["source"] != self.source.to_record()
            || preparation.strategy().program().source()
                != self.inputs.record()["sources"][0]["source"]
                    .as_str()
                    .ok_or_else(|| invalid("SOURCE_SCOPE"))?
        {
            return Err(invalid("PARTICIPANT_SOURCE"));
        }
        Trading::next_open(
            preparation,
            self.settings,
            Box::new(BinanceNextOpenPolicy(self.policy)),
            self.initial_ns,
        )
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::PreparedNextOpen;
    use crate::application::{private_strategy::Definition, strategy_research::DecisionGraph};
    use onlyalpha_backtest::{Inputs, MarketInput, Source};
    use onlyalpha_domain::{
        base::OnlyDomainModel,
        market::OnlyBar,
        time::{OnlyTimestamp, OnlyUtcDateTime},
        value::OnlyQuantity,
    };
    use onlyalpha_plugin_binance::spot_simulation::{SpotRuleSnapshot, SpotSimulationPolicy};
    use onlyalpha_strategy::{SourceRevision, record_fingerprint};
    use serde_json::{Value, json};
    const BAR_NS: u64 = 60_000_000_000;
    fn at(text: &str) -> OnlyTimestamp {
        OnlyTimestamp::from_datetime(text.parse::<OnlyUtcDateTime>().unwrap())
    }
    fn symbol() -> Value {
        json!({"symbol":"BTCUSDT","baseAsset":"BTC","quoteAsset":"USDT","status":"TRADING","isSpotTradingAllowed":true,"orderTypes":["LIMIT","MARKET"],"baseAssetPrecision":8,"quoteAssetPrecision":8,"baseCommissionPrecision":8,"quoteCommissionPrecision":8,"filters":[
            {"filterType":"PRICE_FILTER","minPrice":"0.01000000","maxPrice":"1000000.00000000","tickSize":"0.01000000"},
            {"filterType":"LOT_SIZE","minQty":"0.00001000","maxQty":"9000.00000000","stepSize":"0.00001000"},
            {"filterType":"MARKET_LOT_SIZE","minQty":"0.00000000","maxQty":"100.00000000","stepSize":"0.00000000"},
            {"filterType":"NOTIONAL","minNotional":"5.00000000","applyMinToMarket":true,"maxNotional":"9000000.00000000","applyMaxToMarket":false,"avgPriceMins":5}]})
    }
    fn rules() -> SpotRuleSnapshot {
        // Controlled public input, not a live exchange capture or published history.
        SpotRuleSnapshot::capture(
            symbol(),
            at("2026-11-01T00:00:00Z"),
            "controlled-model-rules",
        )
        .unwrap()
    }
    fn source_revision() -> SourceRevision {
        let calculations: Value = serde_json::from_str(include_str!(
            "../../tests/application/fixtures/strategy_calculations.json"
        ))
        .unwrap();
        let seed: Value = serde_json::from_str(include_str!(
            "../../../../examples/private-assets/strategy/simple_momentum/strategy.json"
        ))
        .unwrap();
        let mut strategy = seed["strategy"]["definition"].clone();
        strategy["calculations"] = calculations["instances"].clone();
        strategy["factor_revision_dependencies"] =
            calculations["factor_revision_dependencies"].clone();
        strategy["universe"]["instruments"] = json!(["BTCUSDT.BINANCE"]);
        strategy["signals"]["entry"]["operator"] = json!(">=");
        strategy["signals"]["entry"]["right"]["value"]["value"] = json!("0.001");
        let strategy = Definition::from_record(&strategy).unwrap();
        let decision = DecisionGraph::derive(&strategy, &calculations["nodes"]).unwrap();
        let graph = decision.graph();
        let mut bindings=graph.ordered_nodes().map(|node|json!({"node_fingerprint":node.fingerprint(),"research_implementation_fingerprint":"a".repeat(64),"trading_implementation_fingerprint":"b".repeat(64)})).collect::<Vec<_>>();
        bindings.sort_by_key(|b| b["node_fingerprint"].as_str().unwrap().to_owned());
        // Value-level public SourceRevision; publication/admission belongs to its real owners.
        let mut source = json!({"schema_version":1,"universe":{"kind":"SINGLE_INSTRUMENT","instruments":["BTCUSDT.BINANCE"]},"market_input_contract":strategy.to_record()["market_input"],"decision_graph_fingerprint":graph.fingerprint(),"implementation_bindings":bindings,"signal_semantics":decision.record()["signal_semantics"]});
        let mut identity = source.clone();
        identity["domain"] = json!("onlyalpha.strategy.revision");
        source["strategy_fingerprint"] = json!(record_fingerprint(&identity));
        source["decision_graph"] = graph.to_record();
        SourceRevision::from_json(&source.to_string(), 8 * 1024 * 1024).unwrap()
    }
    fn configuration(source: &SourceRevision) -> Value {
        json!({"schema_version":2,"account_checkpoint_version":5,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"a".repeat(64),"runtime_kind":"BACKTEST","currency":{"schema_version":1,"code":"USDT","precision":8,"currency_type":"CRYPTO"},"initial_cash":"10000.00000000","capitals":{"cluster":"10000.00000000"},"profiles":{"cluster":{"schema_version":1,"revision":source.fingerprint(),"instruments":["BTCUSDT.BINANCE"],"rules":[]}},"instruments":[{"schema_version":1,"id":"BTCUSDT.BINANCE","price_precision":2,"quantity_precision":5,"multiplier":"1"}]})
    }
    fn inputs(first_warmup: usize, omit_last: bool, extra_end: bool) -> Inputs {
        let start = at("2025-01-03T00:00:00Z").to_unix_nanos();
        let base: Value = include_str!("../../../../test-data/domain/fact-records-v1.jsonl")
            .lines()
            .map(|l| serde_json::from_str::<Value>(l).unwrap())
            .find(|v| v["id"] == "bar")
            .unwrap()["record"]
            .clone();
        let mut records = Vec::new();
        for index in first_warmup..(740 - usize::from(omit_last) + usize::from(extra_end)) {
            let ns = &start + (index as i64 - 20) * BAR_NS as i64;
            let end = &ns + BAR_NS;
            let mut bar = base.clone();
            bar["bar_type"]["instrument_id"] = json!({"schema_version":1,"symbol":{"schema_version":1,"value":"BTCUSDT"},"venue":{"schema_version":1,"value":"BINANCE"}});
            for key in ["open", "high", "low", "close"] {
                bar[key] = json!({"schema_version":1,"value":"100000.00","precision":2});
            }
            bar["volume"] = json!({"schema_version":1,"value":"100.00000","precision":5});
            let opens = OnlyTimestamp::from_unix_nanos(ns.clone())
                .to_datetime_exact()
                .unwrap();
            let closes = OnlyTimestamp::from_unix_nanos(end)
                .to_datetime_exact()
                .unwrap();
            bar["bar_start"] = json!(opens.to_string());
            for key in ["bar_end", "ts_event", "ts_init"] {
                bar[key] = json!(closes.to_string());
            }
            bar["trading_day"] = json!(opens.date().to_string());
            bar["session_type"] = json!("CONTINUOUS");
            records.push(
                MarketInput::new(
                    &"c".repeat(64),
                    records.len() as u64 + 1,
                    "controlled-v1",
                    OnlyBar::from_record(&bar).unwrap(),
                )
                .unwrap(),
            );
        }
        let source = Source::new(
            &"c".repeat(64),
            &"d".repeat(64),
            &"e".repeat(64),
            "controlled-v1",
            0,
            records.len() as u64,
        )
        .unwrap();
        Inputs::new(vec![source], records).unwrap()
    }
    pub(crate) fn prepared() -> PreparedNextOpen {
        let source = source_revision();
        let cfg = configuration(&source);
        PreparedNextOpen::new(
            source,
            inputs(0, false, false),
            rules(),
            cfg,
            at("2025-01-03T00:00:00Z"),
            at("2025-01-03T12:00:00Z"),
        )
        .unwrap()
    }
    #[test]
    fn fixed_btc_profile_binds_public_source_actual_fee_owner_and_exact_window() {
        let p = prepared();
        let r = p.record();
        let source = source_revision();
        assert_eq!(r["strategy_fingerprint"], source.fingerprint());
        assert_eq!(r["settings"]["execution"], configuration(&source));
        assert_eq!(r["settings"]["execution"]["schema_version"],2);
        assert_eq!(r["settings"]["execution"]["account_checkpoint_version"],5);
        let quantity = OnlyQuantity::from_record(&r["settings"]["policy"]["quantity"]).unwrap();
        assert_eq!(
            quantity
                .value()
                .to_string()
                .parse::<onlyalpha_domain::numeric::OnlyDecimal>()
                .unwrap(),
            "0.01".parse().unwrap()
        );
        assert_eq!(quantity.precision(), 5);
        assert_eq!(r["settings"]["policy"]["buy_multiplier"], "1.0002");
        assert_eq!(r["settings"]["policy"]["sell_multiplier"], "0.9998");
        assert_eq!(r["settings"]["instrument"]["price_precision"], 2);
        assert_eq!(
            r["settings"]["instrument"]["settlement_currency"]["precision"],
            8
        );
        assert_eq!(
            r["policy_binding"],
            SpotSimulationPolicy::new(rules(), configuration(&source))
                .unwrap()
                .binding()
        );
        assert_eq!(r["input_pin"], p.inputs().fingerprint());
        assert_eq!(r["window"]["warmup_bars"], 20);
        assert_eq!(r["window"]["sample_bar_count"], 720);
        assert_eq!(r["window"]["total_bar_count"], 740);
        assert_eq!(
            r["window"]["source_bar_start_ns"],
            at("2025-01-02T23:40:00Z").to_unix_nanos().to_string()
        );
        assert_eq!(
            r["window"]["source_bar_end_exclusive_ns"],
            at("2025-01-03T12:00:00Z").to_unix_nanos().to_string()
        );
        assert_eq!(
            r["window"]["dataset_event_start_ns"],
            at("2025-01-02T23:41:00Z").to_unix_nanos().to_string()
        );
        assert_eq!(
            r["window"]["dataset_event_end_exclusive_ns"],
            at("2025-01-03T12:01:00Z").to_unix_nanos().to_string()
        );
        assert_eq!(p.initial_ns(), &at("2025-01-02T23:40:00Z").to_unix_nanos());
    }
    #[test]
    fn final_twelve_oclock_close_is_included_and_no_twelve_oclock_bar_is_read() {
        let p = prepared();
        let rows = p.inputs().records();
        assert_eq!(rows.len(), 740);
        assert_eq!(
            rows[20].bar().bar_start(),
            &at("2025-01-03T00:00:00Z").to_datetime_exact().unwrap()
        );
        assert_eq!(
            rows[739].bar().bar_start(),
            &at("2025-01-03T11:59:00Z").to_datetime_exact().unwrap()
        );
        assert_eq!(
            rows[739].event_ns(),
            at("2025-01-03T12:00:00Z").to_unix_nanos()
        );
        let source = source_revision();
        let cfg = configuration(&source);
        assert!(
            PreparedNextOpen::new(
                source,
                inputs(0, false, true),
                rules(),
                cfg,
                at("2025-01-03T00:00:00Z"),
                at("2025-01-03T12:00:00Z")
            )
            .is_err()
        );
    }
    #[test]
    fn incomplete_warmup_or_missing_last_close_cannot_masquerade_as_complete() {
        for incomplete in [inputs(1, false, false), inputs(0, true, false)] {
            let source = source_revision();
            let cfg = configuration(&source);
            assert!(
                PreparedNextOpen::new(
                    source,
                    incomplete,
                    rules(),
                    cfg,
                    at("2025-01-03T00:00:00Z"),
                    at("2025-01-03T12:00:00Z")
                )
                .is_err()
            );
        }
    }
    #[test]
    fn changed_capital_revision_or_venue_precision_is_rejected() {
        for field in [
            "capital",
            "revision",
            "currency",
            "price_precision",
            "quantity_precision",
            "runtime_kind",
        ] {
            let source = source_revision();
            let mut cfg = configuration(&source);
            match field {
                "capital" => cfg["initial_cash"] = json!("10001.00000000"),
                "revision" => cfg["profiles"]["cluster"]["revision"] = json!("f".repeat(64)),
                "currency" => cfg["currency"]["precision"] = json!(2),
                "price_precision" => cfg["instruments"][0]["price_precision"] = json!(6),
                "quantity_precision" => cfg["instruments"][0]["quantity_precision"] = json!(8),
                _ => cfg["runtime_kind"] = json!("LIVE"),
            }
            assert!(
                PreparedNextOpen::new(
                    source,
                    inputs(0, false, false),
                    rules(),
                    cfg,
                    at("2025-01-03T00:00:00Z"),
                    at("2025-01-03T12:00:00Z")
                )
                .is_err(),
                "{field}"
            );
        }
    }
    #[test]
    fn protected_or_shifted_sample_bounds_are_rejected_before_participants() {
        let source = source_revision();
        let cfg = configuration(&source);
        assert!(
            PreparedNextOpen::new(
                source,
                inputs(0, false, false),
                rules(),
                cfg,
                at("2025-01-05T00:00:00Z"),
                at("2025-01-05T12:00:00Z")
            )
            .is_err()
        );
    }
    #[test]
    fn invalid_configuration_is_rejected_by_the_canonical_composition() {
        let source = source_revision();
        let mut cfg = configuration(&source);
        cfg["unexpected_authority"] = json!(true);
        let owning = onlyalpha_backtest::validate_configuration(&cfg).unwrap_err();
        assert_eq!(owning.0, "EXECUTION_FIELDS");
        let observed = PreparedNextOpen::new(
            source,
            inputs(0, false, false),
            rules(),
            cfg,
            at("2025-01-03T00:00:00Z"),
            at("2025-01-03T12:00:00Z"),
        )
        .err()
        .expect("invalid canonical execution configuration must fail");
        assert_eq!(observed.0, owning.0);
    }
}
