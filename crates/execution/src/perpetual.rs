//! 已冻结的线性永续条款与原始外部事实在同一 Execution 事务中消费。
use crate::{Components, model::*, perpetual_fees::Fees};
use bigdecimal::{BigDecimal, RoundingMode, Zero};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    identifiers::OnlyInstrumentId,
    market::{OnlyFundingRateFact, OnlyReferencePriceFact},
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use serde_json::{Value, json};
use std::sync::Arc;

pub(crate) fn cause(input: &Value) -> String {
    input
        .get("original_input_digest")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .unwrap_or_else(|| hash(input))
}
fn expanded(input: &Value, payload: Value) -> Value {
    let mut next = input.clone();
    next["original_input_digest"] = json!(hash(input));
    next["payload"] = payload;
    next
}
fn shape(v: &Value, version: u64, keys: &[&str]) -> Result<(), Error> {
    if v["schema_version"] != version {
        return Err(err("EXECUTION_PERPETUAL_SCHEMA"));
    }
    let mut copy = v.clone();
    copy["schema_version"] = json!(1);
    row(&copy, keys)?;
    Ok(())
}
fn fields(v: &Value, keys: &[&str]) -> Result<(), Error> {
    if v.as_object()
        .is_none_or(|m| m.len() != keys.len() || keys.iter().any(|k| !m.contains_key(*k)))
    {
        return Err(err("EXECUTION_PERPETUAL_FIELDS"));
    }
    Ok(())
}
fn curve(s: &Value, n: &BigDecimal) -> Result<(BigDecimal, BigDecimal), Error> {
    let a = nonnegative(&s["initial_slope"])? * n + dec(&s["initial_intercept"])?;
    let m = nonnegative(&s["maintenance_slope"])? * n + dec(&s["maintenance_intercept"])?;
    if a < m || m < BigDecimal::zero() {
        return Err(err("EXECUTION_MARGIN_CURVE"));
    }
    Ok((a, m))
}
fn verified_limit_rules(
    t: &Value,
) -> Result<onlyalpha_domain::market_rules::OnlyStaticLimitRules, Error> {
    let raw = t["compiled_policy_json"]
        .as_str()
        .ok_or_else(|| err("EXECUTION_LIMIT_RULE_IDENTITY"))?;
    let rules = onlyalpha_domain::market_rules::OnlyStaticLimitRules::from_compiled_policy_json(
        raw,
        text(&t["policy_fingerprint"])?,
    )?;
    let policy: Value = serde_json::from_str(raw)?;
    if policy["timezone"] != "UTC" || policy["continuous_24x7"] != true {
        return Err(err("EXECUTION_PERPETUAL_CALENDAR"));
    }
    let expected = onlyalpha_domain::market_rules::OnlyStaticLimitRules::compiled_economics(
        raw,
        text(&t["policy_fingerprint"])?,
    )?;
    let actual = onlyalpha_domain::market_rules::OnlyStaticLimitRules::normalize_economics(
        json!({"instrument":t["instrument"],"market_product":t["market_product"],"contract_type":t["contract_type"],"position_mode":t["position_mode"],"margin_mode":t["margin_mode"],"settlement_currency":t["currency"]["code"],"multiplier":t["multiplier"],"margin_segments":t["margin_segments"],"funding_schedule":t["funding_schedule"]}),
    )?;
    if expected != actual {
        return Err(err("EXECUTION_MARKET_ECONOMICS"));
    }
    if rules.to_record() != t["limit_rules"]
        || rules.content_fingerprint() != text(&t["limit_rules_fingerprint"])?
    {
        return Err(err("EXECUTION_LIMIT_RULE_IDENTITY"));
    }
    Ok(rules)
}
pub(crate) fn validate_config(cfg: &Value) -> Result<(), Error> {
    let t = &cfg["perpetual"];
    row(
        t,
        &[
            "instrument",
            "account",
            "cluster",
            "data_version",
            "source",
            "market_binding",
            "market_product",
            "policy_fingerprint",
            "limit_rules",
            "limit_rules_fingerprint",
            "compiled_policy_json",
            "source_cut_sha256",
            "execution_source_binding",
            "source_rows",
            "position_mode",
            "margin_mode",
            "contract_type",
            "multiplier",
            "currency",
            "margin_segments",
            "funding_schedule",
            "fee_catalog",
        ],
    )?;
    let cluster = id(&t["cluster"])?;
    if t["account"] != cfg["account"]
        || t["currency"] != cfg["currency"]
        || t["contract_type"] != "LINEAR"
        || t["position_mode"] != "NETTING"
        || t["margin_mode"] != "CROSS"
        || cfg["instruments"].as_array().is_none_or(|a| a.len() != 1)
        || cfg["profiles"].as_object().is_none_or(|a| a.len() != 1)
        || cfg["profiles"][cluster]["instruments"] != json!([t["instrument"]])
        || cfg["instruments"][0]["id"] != t["instrument"]
        || cfg["instruments"][0]["multiplier"] != t["multiplier"]
        || nonnegative(&t["multiplier"])?.is_zero()
    {
        return Err(err("EXECUTION_PERPETUAL_CONFIGURATION"));
    }
    for key in ["data_version", "source", "market_product"] {
        text(&t[key])?;
    }
    for key in [
        "market_binding",
        "policy_fingerprint",
        "source_cut_sha256",
        "execution_source_binding",
    ] {
        fp(&t[key])?;
    }
    crate::MarketSourceCut::read(
        &serde_json::to_vec(&t["source_rows"])?,
        text(&t["source_cut_sha256"])?,
    )?;
    let rules = verified_limit_rules(t)?;
    if rules.binding() != text(&t["market_binding"])?
        || rules.policy() != text(&t["policy_fingerprint"])?
        || rules.instrument_id().to_string() != t["instrument"].as_str().unwrap_or("")
        || rules
            .multiplier()
            .to_string()
            .parse::<BigDecimal>()
            .map_err(|_| err("EXECUTION_LIMIT_RULE_SCOPE"))?
            != nonnegative(&t["multiplier"])?
    {
        return Err(err("EXECUTION_LIMIT_RULE_SCOPE"));
    }
    let schedule = &t["funding_schedule"];
    fields(
        schedule,
        &[
            "interval_seconds",
            "boundary_offset_seconds",
            "valuation_price_kind",
            "provider_semantic_version",
        ],
    )?;
    if uint(&schedule["interval_seconds"])? <= uint(&schedule["boundary_offset_seconds"])?
        || schedule["valuation_price_kind"] != "MARK"
    {
        return Err(err("EXECUTION_FUNDING_SCHEDULE"));
    }
    text(&schedule["provider_semantic_version"])?;
    let segments = t["margin_segments"]
        .as_array()
        .filter(|s| !s.is_empty() && s.len() <= 128)
        .ok_or_else(|| err("EXECUTION_MARGIN_SEGMENTS"))?;
    let mut lower = BigDecimal::zero();
    let mut previous = None;
    for (i, s) in segments.iter().enumerate() {
        fields(
            s,
            &[
                "lower_bound",
                "upper_bound",
                "initial_slope",
                "initial_intercept",
                "maintenance_slope",
                "maintenance_intercept",
            ],
        )?;
        let here = curve(s, &lower)?;
        if i == 0 && (!here.0.is_zero() || !here.1.is_zero()) {
            return Err(err("EXECUTION_MARGIN_ORIGIN"));
        }
        if dec(&s["lower_bound"])? != lower || previous.as_ref().is_some_and(|v| v != &here) {
            return Err(err("EXECUTION_MARGIN_SEGMENT_CONTINUITY"));
        }
        if nonnegative(&s["initial_slope"])? < nonnegative(&s["maintenance_slope"])? {
            return Err(err("EXECUTION_MARGIN_INCREMENT_DOMAIN"));
        }
        if s["upper_bound"].is_null() {
            if i + 1 != segments.len() {
                return Err(err("EXECUTION_MARGIN_SEGMENT_DOMAIN"));
            }
        } else {
            let upper = dec(&s["upper_bound"])?;
            if upper <= lower {
                return Err(err("EXECUTION_MARGIN_SEGMENT_DOMAIN"));
            }
            previous = Some(curve(s, &upper)?);
            lower = upper;
        }
    }
    boundary(onlyalpha_fee::Catalog::new(t["fee_catalog"].clone()))?;
    if t["fee_catalog"]["broker_contract"]["account"] != cfg["account"] {
        return Err(err("EXECUTION_FEE_ACCOUNT"));
    }
    Ok(())
}
fn nanos(d: OnlyUtcDateTime) -> Result<u64, Error> {
    OnlyTimestamp::from_datetime(d)
        .unix_nanos()
        .to_string()
        .parse()
        .map_err(|_| err("EXECUTION_PERPETUAL_TIME"))
}
fn mark_fact(cfg: &Value, raw: &Value) -> Result<OnlyReferencePriceFact, Error> {
    bound_decimal_leaves(raw)?;
    let f = OnlyReferencePriceFact::from_record(raw)?;
    let t = &cfg["perpetual"];
    if f.to_record() != *raw
        || raw["kind"] != "MARK"
        || t["instrument"] != f.instrument_id().to_string()
        || raw["data_version"] != t["data_version"]
        || raw["source"] != t["source"]
        || nonnegative(&raw["value"]["value"])?.is_zero()
    {
        return Err(err("EXECUTION_MARK_SCOPE"));
    }
    Ok(f)
}
fn funding_pair(cfg: &Value, mark: &Value, raw: &Value) -> Result<OnlyFundingRateFact, Error> {
    let f = OnlyFundingRateFact::from_record(raw)?;
    dec(&raw["rate"])?;
    let m = mark_fact(cfg, mark)?;
    let ns = nanos(*f.funding_time())?;
    let schedule = &cfg["perpetual"]["funding_schedule"];
    if f.to_record() != *raw
        || !ns.is_multiple_of(1_000_000_000)
        || (ns / 1_000_000_000) % uint(&schedule["interval_seconds"])?
            != uint(&schedule["boundary_offset_seconds"])?
        || f.funding_time() != m.ts_event()
        || raw["source_record_hash"].is_null()
        || raw["provider_evidence_id"].is_null()
        || [
            "instrument_id",
            "data_version",
            "source",
            "source_sequence",
            "provider_evidence_id",
            "source_record_hash",
        ]
        .iter()
        .any(|k| raw[k] != mark[k])
    {
        return Err(err("EXECUTION_FUNDING_MARK_PAIR"));
    }
    Ok(f)
}
fn broker(cfg: &Value, v: &Value) -> Result<onlyalpha_broker::Fact, Error> {
    fields(v, &["record", "id", "fingerprint"])?;
    let f = boundary(onlyalpha_broker::Fact::decode(&v["record"]))?;
    if v["id"] != f.identity()
        || v["fingerprint"] != f.fingerprint()
        || [
            "engine",
            "runtime",
            "gateway",
            "generation",
            "account",
            "runtime_kind",
        ]
        .iter()
        .any(|k| v["record"]["scope"][k] != cfg[k])
    {
        return Err(err("EXECUTION_BROKER_SCOPE_OR_IDENTITY"));
    }
    Ok(f)
}
pub(crate) fn validate_metadata(cfg: &Value, p: &Value) -> Result<(), Error> {
    fields(
        p,
        &[
            "marks",
            "funding",
            "boundaries",
            "broker_facts",
            "latest_mark",
            "last_disposition",
        ],
    )?;
    let rows = |key: &str| {
        p[key]
            .as_object()
            .ok_or_else(|| err("EXECUTION_PERPETUAL_METADATA"))
    };
    let marks = rows("marks")?;
    let mut latest = None;
    for (id, raw) in marks {
        let m = mark_fact(cfg, raw)?;
        if id != m.fact_id() {
            return Err(err("EXECUTION_MARK_IDENTITY"));
        }
        if latest
            .as_ref()
            .is_none_or(|prior: &OnlyReferencePriceFact| prior.stable_order() < m.stable_order())
        {
            latest = Some(m);
        }
    }
    if p["latest_mark"] != json!(latest.as_ref().map(|m| m.fact_id())) {
        return Err(err("EXECUTION_LATEST_MARK"));
    }
    let mut boundaries = json!({});
    for (id, row) in rows("funding")? {
        let raw = &row["fact"];
        let mark = marks
            .get(text(&row["mark_fact_id"])?)
            .ok_or_else(|| err("EXECUTION_FUNDING_MARK_MISSING"))?;
        let f = funding_pair(cfg, mark, raw)?;
        let boundary = text(&raw["funding_time"])?;
        if id != f.fact_id()
            || !boundaries[boundary].is_null()
            || row["cashflow"]["account"] != cfg["account"]
            || row["cashflow"]["cluster"] != cfg["perpetual"]["cluster"]
        {
            return Err(err("EXECUTION_FUNDING_IDENTITY"));
        }
        dec(&row["cashflow"]["amount"])?;
        boundaries[boundary] = json!(id);
    }
    if boundaries != p["boundaries"] {
        return Err(err("EXECUTION_FUNDING_BOUNDARIES"));
    }
    for (id, row) in rows("broker_facts")? {
        if broker(cfg, &row["broker"])?.identity() != id {
            return Err(err("EXECUTION_BROKER_FACT_ID"));
        }
    }
    Ok(())
}
pub fn funding_boundary(raw: &Value) -> Result<u64, Error> {
    nanos(*OnlyFundingRateFact::from_record(raw)?.funding_time())
}
fn boundary_source<'a>(
    source: Option<&'a onlyalpha_broker::source::SourceHistory>,
    terms: &Value,
    at: u64,
    visible: u64,
) -> Result<(&'a Value, &'a std::collections::BTreeMap<String, String>), Error> {
    boundary(
        source
            .ok_or_else(|| err("BROKER_ECONOMIC_PREFIX_UNPROVEN"))?
            .funding_closure(text(&terms["execution_source_binding"])?, at, visible),
    )
}
fn scope(input: &Value, inst: &Value, request: &Value) -> Value {
    json!({"schema_version":1,"engine":input["engine"],"runtime":input["runtime"],"account":input["account"],"gateway":input["gateway"],"generation":input["generation"],"runtime_kind":input["runtime_kind"],"cluster":input["cluster"],"revision":input["revision"],"instrument":inst,"request":request["request_id"]["value"]})
}
impl Components {
    /// 仅消费绑定源切片与原 Broker 恢复前缀签发的观察。
    pub fn prepare_perpetual<S: crate::Store>(
        &self,
        store: &S,
        input: &Value,
        cut: &crate::MarketSourceCut,
        broker: &onlyalpha_broker::Broker,
    ) -> Result<crate::Prepared, Error> {
        if input["op"] == "FUNDING" {
            return Err(err("EXECUTION_ORIGINAL_FUNDING_STORE_REQUIRED"));
        }
        self.compute_perpetual(store, input, cut, broker, None)
    }
    pub(crate) fn compute_perpetual<S: crate::Store>(
        &self,
        store: &S,
        input: &Value,
        cut: &crate::MarketSourceCut,
        broker: &onlyalpha_broker::Broker,
        source: Option<&onlyalpha_broker::source::SourceHistory>,
    ) -> Result<crate::Prepared, Error> {
        let t = &self.config["perpetual"];
        if self.config["schema_version"] != 3 || t["source_cut_sha256"] != cut.fingerprint() {
            return Err(err("EXECUTION_SOURCE_CUT"));
        }
        let mut origin = Value::Null;
        match input["op"].as_str() {
            Some("MARK" | "FUNDING") => {
                if !cut.contains(&input["payload"]["fact"]) {
                    return Err(err("EXECUTION_SOURCE_ORIGINAL"));
                }
                if input["op"] == "FUNDING" {
                    let boundary = nanos(
                        *OnlyFundingRateFact::from_record(&input["payload"]["fact"])?
                            .funding_time(),
                    )?;
                    let visible = uint(&input["time"])?;
                    let (closure, trades) = boundary_source(source, t, boundary, visible)?;
                    for (id, original_digest) in trades {
                        let original = broker
                            .observed(id)
                            .map_err(|_| err("EXECUTION_FUNDING_UNAPPLIED_TRADE"))?;
                        if onlyalpha_broker::digest(&original.fact().record()) != *original_digest
                            || self.perp()["broker_facts"][id]["broker"]["record"]
                                != original.fact().record()
                        {
                            return Err(err("EXECUTION_FUNDING_UNAPPLIED_TRADE"));
                        }
                        if uint(&self.perp()["broker_facts"][id]["applied_at"])? > visible {
                            return Err(err("EXECUTION_FUNDING_TRADE_NOT_VISIBLE"));
                        }
                    }
                    origin = json!({"source_cut":cut.fingerprint(),"economic_prefix":closure});
                    for found in crate::model::boundary(broker.observed_trades())? {
                        let f = found.fact();
                        if uint(&f.record()["ts_event"])? <= boundary
                            && self.perp()["broker_facts"][f.identity()]["broker"]["record"]
                                != f.record()
                        {
                            return Err(err("EXECUTION_FUNDING_UNAPPLIED_TRADE"));
                        }
                    }
                }
            }
            Some("ACCEPT" | "FILL" | "TERMINAL") => {
                let p = &input["payload"];
                let original = crate::model::boundary(broker.observed(id(&p["broker"]["id"])?))?;
                let fact = original.fact();
                if fact.record() != p["broker"]["record"]
                    || p["broker"]["fingerprint"] != fact.fingerprint()
                {
                    return Err(err("EXECUTION_BROKER_ORIGINAL_CONFLICT"));
                }
                let intent = original.intent().record();
                origin = json!({"observation":original.source(),"ready_intent":intent});
                let mut found = false;
                for n in 1..=store.head()? {
                    let rec = store
                        .get(n)?
                        .ok_or_else(|| err("EXECUTION_PREFIX_MISSING"))?;
                    let prepared = rec.prepared();
                    if intent["transaction"] != prepared.id() {
                        continue;
                    }
                    let admission = prepared.input();
                    let command = &intent["command"];
                    found = rec.ready()
                        && admission["op"] == "ADMIT"
                        && admission["payload"]["request"] == command["request"]
                        && command["scope"] == fact.scope().record()
                        && command["order"] == p["order"]
                        && admission["payload"]["order"] == p["order"]
                        && intent["payload_hash"] == prepared.record()["payload_hash"];
                    break;
                }
                if !found {
                    return Err(err("EXECUTION_BROKER_ORIGINAL_COMMAND"));
                }
            }
            _ => (),
        }
        self.prepare_with_origin(store, input, origin)
    }
    pub(crate) fn funding_cut(&self) -> Result<crate::MarketSourceCut, Error> {
        let t = &self.config["perpetual"];
        Ok(crate::MarketSourceCut::read(
            &serde_json::to_vec(&t["source_rows"])?,
            text(&t["source_cut_sha256"])?,
        )?)
    }
    pub(crate) fn contract_multiplier(&self) -> Result<BigDecimal, Error> {
        if self.config["schema_version"] == 3 {
            nonnegative(&self.config["perpetual"]["multiplier"])
        } else {
            Ok(BigDecimal::from(1))
        }
    }
    fn perp(&self) -> &Value {
        &self.meta["perpetual"]
    }
    fn perp_mut(&mut self) -> &mut Value {
        &mut Arc::make_mut(&mut self.meta)["perpetual"]
    }
    fn current_mark(&self, input: &Value) -> Result<&Value, Error> {
        let key = text(&self.perp()["latest_mark"])?;
        let raw = &self.perp()["marks"][key];
        if nanos(*mark_fact(&self.config, raw)?.ts_init())? > uint(&input["time"])? {
            return Err(err("EXECUTION_MARK_UNAVAILABLE"));
        }
        Ok(raw)
    }
    fn requirements(&self, n: &BigDecimal) -> Result<(BigDecimal, BigDecimal), Error> {
        let segments = self.config["perpetual"]["margin_segments"]
            .as_array()
            .expect("validated");
        for (i, s) in segments.iter().enumerate() {
            if n >= &nonnegative(&s["lower_bound"])?
                && (s["upper_bound"].is_null()
                    || n < &nonnegative(&s["upper_bound"])?
                    || (i + 1 == segments.len() && n == &nonnegative(&s["upper_bound"])?))
            {
                let (a, m) = curve(s, n)?;
                let round = |x: BigDecimal| {
                    x.with_scale_round(i64::from(self.precision), RoundingMode::HalfEven)
                };
                return Ok((round(a), round(m)));
            }
        }
        Err(err("EXECUTION_MARGIN_NOTIONAL_DOMAIN"))
    }
    fn cash_value(&self, n: &BigDecimal) -> Result<Value, Error> {
        Ok(
            json!({"schema_version":1,"currency":self.config["currency"],"amount":money(&n.with_scale_round(i64::from(self.precision),RoundingMode::HalfEven),self.precision)?}),
        )
    }
    fn admission_initial(
        &self,
        input: &Value,
        request: &Value,
        filled: &BigDecimal,
        n: &BigDecimal,
        ordinary: BigDecimal,
    ) -> Result<BigDecimal, Error> {
        let multiplier = self.contract_multiplier()?;
        let mark = nonnegative(&self.current_mark(input)?["value"]["value"])? * &multiplier;
        let mut marked_open = BigDecimal::zero();
        let mut outstanding = Vec::new();
        let mut pending = BigDecimal::zero();
        let mut marked_pending = BigDecimal::zero();
        for row in self.margin_owner()?.snapshots() {
            marked_open += nonnegative(&row["open"])? * &mark;
            let remaining = nonnegative(&row["unfilled"])?;
            if !remaining.is_zero() {
                let limit = nonnegative(
                    &self.meta["orders"][id(&row["order"])?]["request"]["price"]["value"],
                )?;
                pending += &remaining * &limit * &multiplier;
                marked_pending += &remaining * &mark;
                outstanding.push((remaining, limit, nonnegative(&row["reserved"])?));
            }
        }
        let maximum = filled + &pending + n;
        self.requirements(&maximum)?;
        self.requirements(
            &(marked_open + marked_pending + nonnegative(&request["quantity"]["value"])? * mark),
        )?;
        if outstanding.is_empty() {
            return Ok(ordinary);
        }
        // An already dispatched order can fill after the new one. Prove its unspent
        // reservation covers every ordering, including price improvement and partial fills.
        let spec = &self.config["instruments"][0];
        let step = BigDecimal::new(
            1.into(),
            i64::try_from(uint(&spec["quantity_precision"])?)
                .map_err(|_| err("EXECUTION_QUANTITY_PRECISION"))?,
        );
        let tick = BigDecimal::new(
            1.into(),
            i64::try_from(uint(&spec["price_precision"])?)
                .map_err(|_| err("EXECUTION_PRICE_PRECISION"))?,
        );
        let p = i64::from(self.precision);
        let mut slope = BigDecimal::zero();
        let mut exact_grid = true;
        for segment in self.config["perpetual"]["margin_segments"]
            .as_array()
            .expect("validated segments")
        {
            if nonnegative(&segment["lower_bound"])? >= maximum
                || (!segment["upper_bound"].is_null()
                    && nonnegative(&segment["upper_bound"])? <= *filled)
            {
                continue;
            }
            let rate = nonnegative(&segment["initial_slope"])?;
            let quantum = &rate * &step * &tick * &multiplier;
            let intercept = dec(&segment["initial_intercept"])?;
            exact_grid &= quantum.with_scale(p) == quantum && intercept.with_scale(p) == intercept;
            slope = slope.max(rate);
        }
        let upper = |quantity: &BigDecimal, limit: &BigDecimal| {
            let quantum = &slope * &step * limit * &multiplier;
            let per_lot = if exact_grid {
                quantum
            } else {
                quantum.with_scale_round(p, RoundingMode::Down) + BigDecimal::new(1.into(), p)
            };
            (quantity / &step) * per_lot
        };
        if outstanding
            .iter()
            .any(|(quantity, limit, held)| upper(quantity, limit) > *held)
        {
            return Err(err("EXECUTION_EXISTING_MARGIN_COVERAGE"));
        }
        Ok(ordinary.max(upper(
            &nonnegative(&request["quantity"]["value"])?,
            &nonnegative(&request["price"]["value"])?,
        )))
    }
    fn collateral(
        &self,
        input: &Value,
        request: &Value,
        quantity: &Value,
        trade: Option<&Value>,
        n: &BigDecimal,
    ) -> Result<Value, Error> {
        let terms = &self.config["perpetual"];
        let order = &input["payload"]["order"];
        let state = if trade.is_some() {
            self.margin_owner()?
                .snapshots()
                .into_iter()
                .find(|s| s["order"] == *order)
                .ok_or_else(|| err("EXECUTION_MARGIN_NOT_ADMITTED"))?
        } else {
            Value::Null
        };
        // 本 profile 只开仓，实际 Position 精确成本就是累计入场基数。
        // Settlement 的货币舍入投影不能反推原名义；只有确切无仓位才为零。
        let gross = match self.position.account(text(&terms["instrument"])?) {
            Ok(position) => nonnegative(&position["cost"])? * self.contract_multiplier()?,
            Err(error) if error.0 == "POSITION_NOT_FOUND" => BigDecimal::zero(),
            Err(error) => return Err(Error(error.0)),
        };
        let (a0, m0) = self.requirements(&gross)?;
        let (a, m) = self.requirements(&(&gross + n))?;
        let mut initial = a - a0;
        if trade.is_none() {
            initial = self.admission_initial(input, request, &gross, n, initial)?;
        }
        let action = if trade.is_some() { "OCCUPY" } else { "RESERVE" };
        let mut cmd = json!({"schema_version":1,"id":format!("MINST-{}",hash(&json!([input["input_id"],action]))),"scope":scope(input,&terms["instrument"],request),"reservation":state["id"],"source_order":order,"source_trade":trade,"source_ref":input["source_ref"],"mode":"CROSS","isolation":null,"position_side":"LONG","action":action,"quantity":quantity["value"],"quantity_precision":quantity["precision"],"amount":money(&initial,self.precision)?,"maintenance":money(&if trade.is_some(){m-m0}else{BigDecimal::zero()},self.precision)?,"time":input["time"],"expected_version":state["version"].as_u64().unwrap_or(0),"before_hash":if state.is_null(){Value::Null}else{json!(hash(&state))}});
        cmd["source_fingerprint"] = json!(hash(&cmd));
        Ok(json!({"schema_version":1,"kind":"MARGIN","instruction":cmd,"close_allocation":null}))
    }
    pub(crate) fn perpetual_operation(&mut self, input: &Value) -> Result<(), Error> {
        // 此配置只支持原编译正文声明的 UTC 24x7。编译日期是第一个自然日。
        let policy: Value = serde_json::from_str(
            self.config["perpetual"]["compiled_policy_json"]
                .as_str()
                .ok_or_else(|| err("EXECUTION_LIMIT_RULE_IDENTITY"))?,
        )?;
        let epoch: OnlyUtcDateTime = policy["as_of"]
            .as_str()
            .ok_or_else(|| err("EXECUTION_PERPETUAL_TRADING_DAY"))?
            .parse()?;
        let epoch_ns = nanos(epoch)?;
        const DAY_NS: u64 = 86_400_000_000_000;
        let processing = uint(&input["time"])?;
        let expected_day = (processing / DAY_NS)
            .checked_sub(epoch_ns / DAY_NS)
            .and_then(|n| n.checked_add(1))
            .ok_or_else(|| err("EXECUTION_PERPETUAL_TRADING_DAY"))?;
        let date = OnlyTimestamp::from_unix_nanos(processing.into())
            .to_datetime()?
            .date()
            .to_string();
        if input["trading_day"] != date || uint(&input["day_index"])? != expected_day {
            return Err(err("EXECUTION_PERPETUAL_TRADING_DAY"));
        }
        if input["cluster"] != self.config["perpetual"]["cluster"] {
            return Err(err("EXECUTION_PERPETUAL_CLUSTER"));
        }
        match text(&input["op"])? {
            "MARK" => self.consume_mark(input),
            "FUNDING" => self.consume_funding(input),
            "ADMIT" => self.perpetual_admit(input),
            "ACCEPT" | "FILL" | "TERMINAL" => self.perpetual_broker(input),
            "SUBMISSION" => self.submission(input),
            "CANCEL" => self.cancel(input),
            _ => Err(err("EXECUTION_PERPETUAL_OPERATION")),
        }
    }
    fn perpetual_admit(&mut self, input: &Value) -> Result<(), Error> {
        let admitted = uint(&input["time"])?;
        for event in self.perp()["funding"]
            .as_object()
            .ok_or_else(|| err("EXECUTION_FUNDING_BOUNDARIES"))?
            .values()
        {
            if admitted <= funding_boundary(&event["fact"])? {
                return Err(err("EXECUTION_ADMISSION_AT_SETTLED_BOUNDARY"));
            }
        }
        if self.margin_owner()?.observation_capacity_reached() {
            return Err(err("MARGIN_OBSERVATION_HISTORY_LIMIT"));
        }
        if self.account.snapshot()["maintenance_status"] == "UNAVAILABLE" {
            return Err(err("MARGIN_MAINTENANCE_UNAVAILABLE"));
        }
        let p = &input["payload"];
        shape(p, 3, &["order", "request", "policy_fingerprint"])?;
        let t = &self.config["perpetual"];
        let r = &p["request"];
        let inst = OnlyInstrumentId::from_record(&r["instrument_id"])?;
        if p["policy_fingerprint"] != t["policy_fingerprint"]
            || r["side"] != "BUY"
            || r["offset"] != "OPEN"
            || r["order_type"] != "LIMIT"
            || t["instrument"] != inst.to_string()
            || r["account_id"]["value"] != input["account"]
        {
            return Err(err("EXECUTION_PERPETUAL_ORDER_SHAPE"));
        }
        let rules = verified_limit_rules(t)?;
        let price = onlyalpha_domain::value::OnlyPrice::from_record(&r["price"])?;
        let quantity = onlyalpha_domain::value::OnlyQuantity::from_record(&r["quantity"])?;
        let at = OnlyTimestamp::from_unix_nanos(uint(&input["time"])?.into()).to_datetime()?;
        if !rules.validates_at(&price, &quantity, at)? {
            return Err(err("EXECUTION_MARKET_LIMIT_RULES"));
        }
        self.current_mark(input)?;
        let order = Components::fee_order_preview_checkpoint(
            &self.config,
            &boundary(self.order.checkpoint_record())?.0,
            text(&input["cluster"])?,
            r,
            uint(&input["time"])?,
        )?;
        let n = nonnegative(&r["price"]["value"])?
            * nonnegative(&r["quantity"]["value"])?
            * self.contract_multiplier()?;
        let fees = Fees::new(&self.config, uint(&input["day_index"])?)?.contract(
            &order,
            uint(&input["time"])?,
            &n,
        )?;
        let market = json!({"schema_version":1,"verdict":"ACCEPT","source_ref":input["source_ref"],"request_digest":hash(r),"notional":self.cash_value(&n)?,"rounding":"HALF_EVEN"});
        let collateral = self.collateral(input, r, &r["quantity"], None, &n)?;
        self.admit(&expanded(input,json!({"schema_version":1,"order":p["order"],"request":r,"fee_contract":fees,"fee_budget":fees["funding"]["fee_reservation"]["amount"],"market":market,"collateral":collateral})))?;
        let relation = &mut Arc::make_mut(&mut self.meta)["orders"][id(&p["order"])?];
        relation["fee_binding_day"] = input["day_index"].clone();
        relation["fee_binding_time"] = input["time"].clone();
        Ok(())
    }
    fn perpetual_broker(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        shape(p, 2, &["order", "broker"])?;
        let fact = broker(&self.config, &p["broker"])?;
        let b = &p["broker"]["record"];
        let order = id(&p["order"])?;
        let kind = text(&b["kind"])?;
        let op = match kind {
            "ACCEPTED" => "ACCEPT",
            "TRADE" => "FILL",
            "REJECTED" | "EXPIRED" | "CANCELLED" => "TERMINAL",
            _ => return Err(err("EXECUTION_BROKER_KIND")),
        };
        let _ = self.relation(input)?;
        if fact.order() != Some(order)
            || b["correlation"] != order
            || input["op"] != op
            || !b["quality"].as_array().is_some_and(Vec::is_empty)
            || uint(&b["ts_init"])? > uint(&input["time"])?
        {
            return Err(err("EXECUTION_BROKER_RELATION"));
        }
        let existing = &self.perp()["broker_facts"][fact.identity()];
        if !existing.is_null() {
            if existing["broker"] != p["broker"] {
                return Err(err("EXECUTION_BROKER_FACT_CONFLICT"));
            }
            self.perp_mut()["last_disposition"] = json!("DUPLICATE");
            return Ok(());
        }
        let snapshot = boundary(self.order.get(text(&input["cluster"])?, order))?;
        let venue = &snapshot.to_record()["venue_order_id"]["value"];
        let payload = &b["payload"];
        let mut next = expanded(input, Value::Null);
        next["broker_record"] = b.clone();
        match op {
            "ACCEPT" => {
                next["payload"] =
                    json!({"schema_version":1,"order":order,"venue_order":payload["venue"]});
                self.accept(&next)?;
            }
            "TERMINAL" => {
                if !venue.is_null() && *venue != payload["venue"] {
                    return Err(err("EXECUTION_BROKER_VENUE"));
                }
                next["payload"] = json!({"schema_version":1,"order":order,"outcome":kind,"collateral":{"schema_version":1,"kind":"MARGIN","instruction":null,"close_allocation":null}});
                self.terminal(&next)?;
            }
            _ => {
                let f = &payload["fill"];
                if venue.is_null()
                    || *venue != f["venue_order_id"]["value"]
                    || f["ts_event"]["unix_nanos"] != b["ts_event"]
                    || f["ts_init"]["unix_nanos"] != b["ts_init"]
                    || f["external_sequence"] != b["source_sequence"]
                {
                    return Err(err("EXECUTION_BROKER_FILL_SCOPE"));
                }
                let rel = self.relation(input)?;
                let terms = &self.config["perpetual"];
                let bound_day = uint(&rel["fee_binding_day"])?;
                let bound_time = uint(&rel["fee_binding_time"])?;
                let event = uint(&b["ts_event"])?;
                if event < bound_time {
                    return Err(err("EXECUTION_BROKER_ECONOMIC_DAY"));
                }
                const DAY_NS: u64 = 86_400_000_000_000;
                let fee_day = bound_day
                    .checked_add(event / DAY_NS - bound_time / DAY_NS)
                    .ok_or_else(|| err("EXECUTION_BROKER_ECONOMIC_DAY"))?;
                let fee = Fees::new(&self.config, fee_day)?
                    .fill(&snapshot, bound_day, f)?
                    .record();
                let n = nonnegative(&f["price"]["value"])?
                    * nonnegative(&f["quantity"]["value"])?
                    * self.contract_multiplier()?;
                let trade = &f["trade_id"]["value"];
                let make = |family: &str, extra: Value| {
                    let mut v = json!({"schema_version":1,"source_ref":format!("PSRC-{}",hash(&json!([fact.identity(),family]))),"scope":scope(input,&terms["instrument"],&rel["request"]),"family":family,"currency":self.config["currency"],"version":1,"as_of_sequence":input["runtime_sequence"]});
                    v.as_object_mut()
                        .expect("record")
                        .extend(extra.as_object().expect("record").clone());
                    v["source_digest"] = json!(hash(&v));
                    v
                };
                let fee_id = format!("FAPP-{}", onlyalpha_fee::digest(&fee));
                let fee_proof = make(
                    "ORDER_FEE_ACCRUAL",
                    json!({"instruction":fee_id,"order":order,"trade":trade,"policy":rel["fee_contract"]["binding"]["fingerprint"],"assessment_fingerprint":onlyalpha_fee::digest(&fee)}),
                );
                let settlement = make(
                    "SETTLEMENT",
                    json!({"instruction":format!("PSET-{}",hash(&json!([fact.identity(),terms["policy_fingerprint"]]))),"order":order,"trade":trade,"model":"LINEAR_PERPETUAL_OPEN","calendar":null,"policy":{"id":"IMMEDIATE_LINEAR_PERPETUAL","version":terms["policy_fingerprint"],"kind":"LINEAR_PERPETUAL_OPEN"},"gross_notional":self.cash_value(&n)?,"rounding":"HALF_EVEN"}),
                );
                let valuation = make(
                    "VALUATION",
                    json!({"mark":self.current_mark(input)?["value"]["value"]}),
                );
                next["fee_assessment"] = fee;
                next["payload"] = json!({"schema_version":1,"order":order,"trade":trade,"venue_trade":f["venue_trade_id"]["value"],"venue_order":venue,"quantity":f["quantity"]["value"],"price":f["price"]["value"],"fees":fee_proof,"settlement":settlement,"valuation":valuation,"collateral":self.collateral(input,&rel["request"],&f["quantity"],Some(trade),&n)?});
                self.fill(&next)?;
                self.mark_margin(input)?;
            }
        }
        self.perp_mut()["broker_facts"][fact.identity()] = json!({"broker":p["broker"],"fee_assessment":next["fee_assessment"],"applied_at":input["time"]});
        self.perp_mut()["last_disposition"] = json!("APPLIED");
        Ok(())
    }
    fn consume_mark(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        row(p, &["fact"])?;
        let raw = &p["fact"];
        let m = mark_fact(&self.config, raw)?;
        let at = nanos(*m.ts_event())?;
        if nanos(*m.ts_init())? > uint(&input["time"])? {
            return Err(err("EXECUTION_MARK_FUTURE"));
        }
        if let Some(original) = self.perp()["marks"].get(m.fact_id()) {
            if original != raw {
                return Err(err("EXECUTION_MARK_CONFLICT"));
            }
            self.perp_mut()["last_disposition"] = json!("DUPLICATE");
            return Ok(());
        }
        if let Some(key) = self.perp()["latest_mark"].as_str() {
            let previous = mark_fact(&self.config, &self.perp()["marks"][key])?;
            if m.ts_event() == previous.ts_event()
                && m.source_sequence() == previous.source_sequence()
                && m.revision() == previous.revision()
                || m.stable_order() <= previous.stable_order()
            {
                return Err(err("EXECUTION_MARK_STALE"));
            }
        }
        let n = &input["runtime_sequence"];
        let inst = &self.config["perpetual"]["instrument"];
        if !self.position.current_exposure()["accounts"]
            .as_array()
            .expect("position accounts")
            .is_empty()
        {
            let info = json!({"schema_version":1,"valuation":m.fact_id(),"version":n,"economic_version":self.account.snapshot()["economic_version"],"position_evidence":boundary(self.position.checkpoint_record())?.1,"marks":[{"schema_version":1,"instrument":inst,"mark":raw["value"]["value"],"precision":raw["value"]["precision"],"source_ref":m.fact_id(),"family":"MARK","version":n,"time":at,"as_of_sequence":n}]});
            self.valuation(&expanded(input, info))?;
        }
        self.perp_mut()["marks"][m.fact_id()] = raw.clone();
        self.perp_mut()["latest_mark"] = json!(m.fact_id());
        self.perp_mut()["last_disposition"] = json!("APPLIED");
        self.mark_margin(input)
    }
    fn mark_margin(&mut self, input: &Value) -> Result<(), Error> {
        let mark = self.current_mark(input)?;
        let price = nonnegative(&mark["value"]["value"])? * self.contract_multiplier()?;
        let mark_id = mark["fact_id"].clone();
        let mut owner = self.margin_owner()?;
        let unit = price.normalized().to_plain_string();
        let covered = boundary(
            owner.covers_open_notional(text(&self.config["perpetual"]["instrument"])?, &unit),
        )?;
        let mut gross = BigDecimal::zero();
        for state in owner.snapshots() {
            let open = nonnegative(&state["open"])?;
            if open.is_zero() {
                continue;
            }
            let gap = state.get("observation_gap").is_some();
            let (action, maintenance) = if !covered {
                if gap {
                    continue;
                }
                ("MARK_OUTSIDE_MODEL", Value::Null)
            } else {
                let before = self.requirements(&gross)?.1;
                gross += open * &price;
                let required = self.requirements(&gross)?.1 - before;
                if (!gap && required == nonnegative(&state["maintenance"])?)
                    || (gap && owner.observation_capacity_reached())
                {
                    continue;
                }
                let action = if owner.observation_capacity_reached() {
                    "MARK_UNAVAILABLE"
                } else {
                    "MARK_MAINTENANCE"
                };
                (action, json!(money(&required, self.precision)?))
            };
            let mut cmd = json!({"schema_version":2,"id":format!("MMARK-{}",hash(&json!([mark_id,state["id"],state["version"],action]))),"scope":state["scope"],"reservation":state["id"],"source_order":state["order"],"source_trade":null,"source_ref":format!("MSRC-{}",hash(&json!([mark_id,input["source_ref"],state["id"]]))),"mode":state["mode"],"isolation":state["isolation"],"position_side":state["position_side"],"action":action,"quantity":state["open"],"quantity_precision":state["quantity_precision"],"marked_unit_notional":unit,"amount":money(&BigDecimal::zero(),self.precision)?,"maintenance":maintenance,"time":input["time"],"expected_version":state["version"],"before_hash":hash(&state)});
            cmd["source_fingerprint"] = json!(hash(&cmd));
            self.consume_margin(input, &mut owner, &cmd)?;
        }
        Ok(())
    }
    fn consume_funding(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        row(p, &["fact", "mark_fact_id"])?;
        let raw = &p["fact"];
        let mark_id = id(&p["mark_fact_id"])?;
        let mark = self.perp()["marks"]
            .get(mark_id)
            .ok_or_else(|| err("EXECUTION_FUNDING_MARK_MISSING"))?;
        let f = funding_pair(&self.config, mark, raw)?;
        if nanos(*f.ts_init())? > uint(&input["time"])? {
            return Err(err("EXECUTION_FUNDING_FUTURE"));
        }
        if let Some(old) = self.perp()["funding"].get(f.fact_id()) {
            if old["fact"] != *raw || old["mark_fact_id"] != mark_id {
                return Err(err("EXECUTION_FUNDING_CONFLICT"));
            }
            self.perp_mut()["last_disposition"] = json!("DUPLICATE");
            return Ok(());
        }
        let boundary_time = text(&raw["funding_time"])?;
        if !self.perp()["boundaries"][boundary_time].is_null() {
            return Err(err("EXECUTION_FUNDING_BOUNDARY"));
        }
        let cut = self.funding_cut()?;
        let effect = boundary(self.position.funding(
            &cut,
            &json!({"schema_version":1,"mark":mark_id,"funding":f.fact_id()}),
        ))?;
        let flow = effect.record().clone();
        let ac = self.command(input, "ECONOMIC", Value::Null, 0);
        let lc = self.ledger_command(input, "FUNDING", Value::Null, 0);
        if boundary(Arc::make_mut(&mut self.account).apply_funding(&ac, &effect))?.status
            != onlyalpha_account::Status::Applied
            || boundary(Arc::make_mut(&mut self.ledger).apply_funding(&lc, &effect))?.status
                != onlyalpha_strategy_ledger::Status::Applied
        {
            return Err(err("EXECUTION_FUNDING_PROJECTION"));
        }
        self.perp_mut()["funding"][f.fact_id()] =
            json!({"fact":raw,"mark_fact_id":mark_id,"cashflow":flow});
        self.perp_mut()["boundaries"][boundary_time] = json!(f.fact_id());
        self.perp_mut()["last_disposition"] = json!("APPLIED");
        Ok(())
    }
}
