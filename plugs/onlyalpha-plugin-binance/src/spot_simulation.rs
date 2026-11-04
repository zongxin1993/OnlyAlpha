//! Explicit experimental Spot model inputs. No venue admission, I/O or mutable economics.
use bigdecimal::{BigDecimal, Zero};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    execution::OnlyOrderSnapshot,
    fee::{
        OnlyBrokerFeeContractIdentity, OnlyFeeAssessment, OnlyFeeAssessmentInput,
        OnlyFeeComponentIdentity, OnlyFeeScheduleIdentity, OnlyFeeSubject, OnlyFeeTargetComponent,
        OnlyLocalFeeFinality, OnlyMarketFeePackIdentity, OnlyOrderFeeApplicabilityScopeIdentity,
        OnlyOrderFeeApplicabilityScopeIdentityInput, OnlyOrderFeeEstimate,
        OnlyOrderFeeEstimateInput, OnlyOrderFeePolicyBinding, OnlyOrderFeePolicyBindingInput,
        OnlyOrderFundingPlan, OnlyOrderFundingPlanInput,
    },
    identifiers::{OnlyIdentifier, OnlyTradeId},
    instrument::OnlyInstrument,
    numeric::{OnlyDecimal, only_add, only_quantize},
    time::{OnlyTimestamp, OnlyTradingDay},
    value::{OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity},
};
use onlyalpha_fee::{Binding, Catalog, digest};
use serde_json::{Value, json};
use std::{fmt, str::FromStr};

const PROFILE: &str = "BINANCE_SPOT_EXPERIMENTAL_NEXT_OPEN";
const MARKET: &str = "BINANCE_SPOT_MODEL";
const BROKER: &str = "BINANCE_SPOT_SIMULATION";
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Error(pub String);
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for Error {}
fn bad(code: &str) -> Error {
    Error(format!("SPOT_SIMULATION_{code}"))
}
fn boundary<T, E: fmt::Display>(result: Result<T, E>) -> Result<T, Error> {
    result.map_err(|e| Error(e.to_string()))
}
fn fields(v: &Value, keys: &[&str]) -> Result<(), Error> {
    if v.as_object()
        .is_none_or(|m| m.len() != keys.len() || keys.iter().any(|k| !m.contains_key(*k)))
    {
        return Err(bad("FIELDS"));
    }
    Ok(())
}
fn text(v: &Value) -> Result<&str, Error> {
    v.as_str()
        .filter(|s| !s.is_empty() && s.len() <= 256)
        .ok_or_else(|| bad("TEXT"))
}
fn sha(v: &Value) -> Result<&str, Error> {
    let s = text(v)?;
    if s.len() != 64
        || !s
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(bad("FINGERPRINT"));
    }
    Ok(s)
}
fn number(v: &Value) -> Result<BigDecimal, Error> {
    let s = text(v)?;
    if s.len() > 128 {
        return Err(bad("DECIMAL_BOUND"));
    }
    let n = BigDecimal::from_str(s).map_err(|_| bad("DECIMAL"))?;
    let (coefficient, scale) = n.as_bigint_and_exponent();
    if coefficient.to_string().len() > 128 || !(-18..=18).contains(&scale) || n < BigDecimal::zero()
    {
        return Err(bad("DECIMAL_BOUND"));
    }
    Ok(n)
}
fn precision(v: &Value) -> Result<u8, Error> {
    v.as_u64()
        .filter(|n| *n <= 18)
        .map(|n| n as u8)
        .ok_or_else(|| bad("PRECISION"))
}
fn boolean(v: &Value) -> Result<bool, Error> {
    v.as_bool().ok_or_else(|| bad("BOOLEAN"))
}
fn filter<'a>(raw: &'a Value, name: &str) -> Result<Option<&'a Value>, Error> {
    let mut values = raw["filters"]
        .as_array()
        .filter(|a| a.len() <= 64)
        .ok_or_else(|| bad("FILTERS"))?
        .iter()
        .filter(|f| f["filterType"] == name);
    let first = values.next();
    if values.next().is_some() {
        return Err(bad("DUPLICATE_FILTER"));
    }
    Ok(first)
}
fn money(value: &BigDecimal, currency: &OnlyCurrency) -> Result<OnlyMoney, Error> {
    let n: OnlyDecimal = boundary(value.to_plain_string().parse())?;
    let quantum: OnlyDecimal = boundary(format!("1E-{}", currency.precision()).parse())?;
    boundary(OnlyMoney::new(
        boundary(only_quantize(&n, &quantum))?,
        currency.clone(),
    ))
}
fn exact_money(value: &Value, currency: &OnlyCurrency) -> Result<OnlyMoney, Error> {
    let n = number(value)?;
    let m = money(&n, currency)?;
    if BigDecimal::from_str(&m.amount().to_string()).map_err(|_| bad("MONEY"))? != n {
        return Err(bad("MONEY_PRECISION"));
    }
    Ok(m)
}

/// Frozen original exchangeInfo occurrence. Current rules are not historical venue evidence.
#[derive(Clone, Debug)]
pub struct SpotRuleSnapshot {
    value: Value,
}
impl SpotRuleSnapshot {
    pub fn capture(
        raw_symbol: Value,
        captured_at: OnlyTimestamp,
        source_ref: &str,
    ) -> Result<Self, Error> {
        if raw_symbol.to_string().len() > 65536
            || source_ref.len() > 256
            || boundary(OnlyIdentifier::new(source_ref))?.value() != source_ref
            || captured_at
                .to_unix_nanos()
                .to_string()
                .parse::<u64>()
                .is_err()
        {
            return Err(bad("SNAPSHOT_BOUND"));
        }
        if raw_symbol["symbol"] != "BTCUSDT"
            || raw_symbol["baseAsset"] != "BTC"
            || raw_symbol["quoteAsset"] != "USDT"
            || raw_symbol["status"] != "TRADING"
            || raw_symbol["isSpotTradingAllowed"] != true
            || raw_symbol["orderTypes"]
                .as_array()
                .is_none_or(|a| !a.iter().any(|v| v == "MARKET"))
        {
            return Err(bad("SYMBOL_CAPABILITY"));
        }
        precision(&raw_symbol["baseAssetPrecision"])?;
        precision(&raw_symbol["quoteAssetPrecision"])?;
        precision(&raw_symbol["quoteCommissionPrecision"])?;
        let lot = filter(&raw_symbol, "LOT_SIZE")?.ok_or_else(|| bad("LOT_SIZE_REQUIRED"))?;
        for f in [Some(lot), filter(&raw_symbol, "MARKET_LOT_SIZE")?]
            .into_iter()
            .flatten()
        {
            let minimum = number(&f["minQty"])?;
            let maximum = number(&f["maxQty"])?;
            number(&f["stepSize"])?;
            if minimum > maximum {
                return Err(bad("QUANTITY_RANGE"));
            }
        }
        if number(&lot["stepSize"])?.is_zero() || number(&lot["maxQty"])?.is_zero() {
            return Err(bad("LOT_SIZE_UNAVAILABLE"));
        }
        let min = filter(&raw_symbol, "MIN_NOTIONAL")?;
        let range = filter(&raw_symbol, "NOTIONAL")?;
        if min.is_none() && range.is_none() {
            return Err(bad("NOTIONAL_REQUIRED"));
        }
        if let Some(f) = min {
            number(&f["minNotional"])?;
            boolean(&f["applyToMarket"])?;
        }
        if let Some(f) = range {
            if number(&f["minNotional"])? > number(&f["maxNotional"])? {
                return Err(bad("NOTIONAL_RANGE"));
            }
            boolean(&f["applyMinToMarket"])?;
            boolean(&f["applyMaxToMarket"])?;
        }
        for f in [min, range].into_iter().flatten() {
            if f["avgPriceMins"].as_u64().is_none_or(|n| n > 1440) {
                return Err(bad("NOTIONAL_REFERENCE"));
            }
        }
        let mut value = json!({"schema_version":1,"kind":"BINANCE_SPOT_RULE_SNAPSHOT","captured_at":captured_at.to_record(),"source_ref":source_ref,"source_digest":digest(&raw_symbol),"raw_symbol":raw_symbol});
        value["fingerprint"] = json!(digest(&value));
        Ok(Self { value })
    }
    /// A fresh simulation configuration from this capture, never a metadata/history update.
    pub fn model_instrument(&self) -> Result<OnlyInstrument, Error> {
        let raw = &self.value["raw_symbol"];
        let mut model = boundary(crate::spot_normalize::instrument(raw))?.to_record();
        let currency = |code: &Value, digits: &Value| -> Result<Value, Error> {
            let value = json!({"schema_version":1,"code":text(code)?,"precision":precision(digits)?,"currency_type":"CRYPTO"});
            Ok(boundary(OnlyCurrency::from_record(&value))?.to_record())
        };
        let quote = currency(&raw["quoteAsset"], &raw["quoteAssetPrecision"])?;
        model["quote_currency"] = quote.clone();
        model["settlement_currency"] = quote;
        model["base_currency"] = currency(&raw["baseAsset"], &raw["baseAssetPrecision"])?;
        boundary(OnlyInstrument::from_record(&model))
    }
    pub fn record(&self) -> Value {
        self.value.clone()
    }
    pub fn from_record(v: &Value) -> Result<Self, Error> {
        fields(
            v,
            &[
                "schema_version",
                "kind",
                "captured_at",
                "source_ref",
                "raw_symbol",
                "source_digest",
                "fingerprint",
            ],
        )?;
        let result = Self::capture(
            v["raw_symbol"].clone(),
            boundary(OnlyTimestamp::from_record(&v["captured_at"]))?,
            text(&v["source_ref"])?,
        )?;
        if result.value != *v {
            return Err(bad("SNAPSHOT_CONFLICT"));
        }
        Ok(result)
    }
    fn rule_reason(
        &self,
        quantity: &BigDecimal,
        reference: &BigDecimal,
    ) -> Result<Option<&'static str>, Error> {
        if quantity <= &BigDecimal::zero() || reference <= &BigDecimal::zero() {
            return Err(bad("POSITIVE_REQUIRED"));
        }
        let raw = &self.value["raw_symbol"];
        for name in ["LOT_SIZE", "MARKET_LOT_SIZE"] {
            if let Some(f) = filter(raw, name)? {
                let step = number(&f["stepSize"])?;
                if quantity < &number(&f["minQty"])?
                    || quantity > &number(&f["maxQty"])?
                    || (!step.is_zero() && !(quantity % &step).is_zero())
                {
                    return Ok(Some(if name == "LOT_SIZE" {
                        "LOT_SIZE"
                    } else {
                        "MARKET_LOT_SIZE"
                    }));
                }
            }
        }
        let notional = quantity * reference;
        if let Some(f) = filter(raw, "MIN_NOTIONAL")?
            && boolean(&f["applyToMarket"])?
            && notional < number(&f["minNotional"])?
        {
            return Ok(Some("MIN_NOTIONAL"));
        }
        if let Some(f) = filter(raw, "NOTIONAL")?
            && ((boolean(&f["applyMinToMarket"])? && notional < number(&f["minNotional"])?)
                || (boolean(&f["applyMaxToMarket"])? && notional > number(&f["maxNotional"])?))
        {
            return Ok(Some("NOTIONAL"));
        }
        Ok(None)
    }
}

/// Immutable explicit model configuration. Fee targets come from the canonical Fee Catalog.
#[derive(Clone)]
pub struct SpotSimulationPolicy {
    snapshot: SpotRuleSnapshot,
    execution: Value,
    currency: OnlyCurrency,
    catalog: Catalog,
    binding: Value,
}
impl SpotSimulationPolicy {
    pub fn new(snapshot: SpotRuleSnapshot, execution: Value) -> Result<Self, Error> {
        let currency = boundary(OnlyCurrency::from_record(&execution["currency"]))?;
        let raw = &snapshot.value["raw_symbol"];
        if execution.to_string().len() > 65536
            || execution["runtime_kind"] != "BACKTEST"
            || execution["currency"] != currency.to_record()
            || currency.code() != "USDT"
            || currency.precision() != precision(&raw["quoteAssetPrecision"])?
            || currency.precision() != precision(&raw["quoteCommissionPrecision"])?
            || currency.to_record()["currency_type"] != "CRYPTO"
            || execution["instruments"]
                .as_array()
                .is_none_or(|a| a.len() != 1)
            || execution["instruments"][0]["id"] != "BTCUSDT.BINANCE"
            || execution["profiles"]
                .as_object()
                .is_none_or(|m| m.len() != 1)
        {
            return Err(bad("EXPERIMENTAL_PROFILE"));
        }
        for k in ["engine", "runtime", "account", "gateway"] {
            text(&execution[k])?;
        }
        sha(&execution["generation"])?;
        let account = text(&execution["account"])?;
        let quantum = format!("1E-{}", currency.precision());
        let rule = |zero: bool| json!({"id":if zero{"explicit-zero-broker"}else{"model-spot-commission"},"type":if zero{"BROKER_COMMISSION"}else{"EXCHANGE_FEE"},"authority":if zero{"BROKER"}else{"VENUE"},"direction":"CHARGE","scope":"FILL","resolution":"ORDER_FIXED","terms":if zero{json!([{"kind":"FIXED","amount":"0"}])}else{json!([{"kind":"RATE","basis":"NOTIONAL","amount":"0.001"}])},"minimum":null,"maximum":null,"quantum":quantum,"rounding":"HALF_EVEN","pipeline":"BOUNDS_THEN_ROUND","side":null,"offset":null,"liquidity":null});
        let catalog = boundary(Catalog::new(
            json!({"schema_version":1,"market_pack":{"id":"BINANCE_SPOT_MODEL_FEE_001","version":"1","families":["spot-model-fee"]},"broker_contract":{"id":"BACKTEST_EXPLICIT_ZERO_BROKER","version":"1","broker":BROKER,"account":account,"families":["explicit-zero"]},"schedules":[{"namespace":"MARKET","family":"spot-model-fee","version":"1","from":1,"to":null,"scope":{"market":MARKET,"venue":"BINANCE","instrument_class":"CASH","currency":"USDT"},"rules":[rule(false)]},{"namespace":"BROKER","family":"explicit-zero","version":"1","from":1,"to":null,"scope":{"broker":BROKER,"account":account,"currency":"USDT"},"rules":[rule(true)]}]}),
        ))?;
        let mut settlement = json!({"id":"BINANCE_SPOT_MODEL_CASH","asset_booked":0,"asset_trade_available":0,"cash_booked":0,"cash_trade_available":0,"cash_withdrawable":0,"legal_settled":0});
        settlement["version"] = json!(digest(&settlement));
        let binding = json!({"schema_version":1,"kind":PROFILE,"configuration":digest(&execution),"reference_policy":"MODEL_NEXT_OPEN","rules_snapshot":snapshot.record(),"rules_fingerprint":snapshot.value["fingerprint"],"settlement_currency":currency.to_record(),"fee_catalog":catalog.record(),"settlement_policy":settlement});
        Ok(Self {
            snapshot,
            execution,
            currency,
            catalog,
            binding,
        })
    }
    pub fn binding(&self) -> Value {
        self.binding.clone()
    }
    fn context(&self, v: &Value, fill: bool) -> Result<(u64, u64), Error> {
        let mut keys = vec![
            "schema_version",
            "time",
            "day_index",
            "trading_day",
            "cause",
        ];
        if fill {
            keys.push("trade");
        }
        fields(v, &keys)?;
        let time = v["time"].as_u64().ok_or_else(|| bad("TIME"))?;
        let day = v["day_index"]
            .as_u64()
            .filter(|n| *n > 0)
            .ok_or_else(|| bad("DAY"))?;
        if v["schema_version"] != 1 {
            return Err(bad("SCHEMA"));
        }
        sha(&v["cause"])?;
        let trading_day = boundary(OnlyTradingDay::from_record(
            &json!({"schema_version":1,"value":v["trading_day"]}),
        ))?;
        if trading_day.to_record()["value"] != v["trading_day"] {
            return Err(bad("DAY_CANONICAL"));
        }
        if fill {
            let id = boundary(OnlyTradeId::new(text(&v["trade"])?))?;
            if id.value() != text(&v["trade"])? {
                return Err(bad("TRADE_CANONICAL"));
            }
        }
        Ok((time, day))
    }
    fn order(&self, v: &Value) -> Result<OnlyOrderSnapshot, Error> {
        if v.to_string().len() > 65536 {
            return Err(bad("ORDER_BOUND"));
        }
        for key in ["quantity", "remaining_quantity", "filled_quantity"] {
            number(&v[key]["value"])?;
        }
        number(&v["cumulative_price_quantity"])?;
        let s = boundary(OnlyOrderSnapshot::from_record(v))?;
        if s.to_record() != *v
            || self.execution["runtime"] != s.runtime_id().value()
            || self.execution["account"] != s.account_id().value()
            || s.instrument_id().to_string() != "BTCUSDT.BINANCE"
            || v["order_type"] != "MARKET"
            || !v["price"].is_null()
            || v["quantity"]["precision"] != self.execution["instruments"][0]["quantity_precision"]
            || self.execution["profiles"][s.cluster_id().value()]["revision"].is_null()
            || v["fill_count"] != 0
            || !s.filled_quantity().value().is_zero()
            || s.remaining_quantity() != s.quantity()
            || v["execution_intent"]["position_side"] != "LONG"
            || v["execution_intent"]["position_mode"] != "NETTING"
            || v["execution_intent"]["position_effect"]
                != if v["side"] == "BUY" { "OPEN" } else { "CLOSE" }
        {
            return Err(bad("ORDER_SCOPE_OR_SHAPE"));
        }
        sha(&self.execution["profiles"][s.cluster_id().value()]["revision"])?;
        Ok(s)
    }
    fn fee_binding(&self, order: &OnlyOrderSnapshot, day: u64) -> Result<Binding, Error> {
        let r = order.to_record();
        let subject = json!({"engine":self.execution["engine"],"runtime":self.execution["runtime"],"account":self.execution["account"],"broker":BROKER,"gateway":self.execution["gateway"],"generation":self.execution["generation"],"runtime_kind":"BACKTEST","cluster":order.cluster_id().value(),"revision":self.execution["profiles"][order.cluster_id().value()]["revision"],"order":order.order_id().value(),"instrument":order.instrument_id().to_string(),"market":MARKET,"venue":"BINANCE","instrument_class":"CASH","currency":self.currency.to_record(),"side":r["side"],"offset":r["execution_intent"]["position_effect"]});
        boundary(self.catalog.bind(subject, day))
    }
    fn domain_binding(
        &self,
        order: &OnlyOrderSnapshot,
        at: OnlyTimestamp,
    ) -> Result<OnlyOrderFeePolicyBinding, Error> {
        let catalog = self.catalog.record();
        let market: Vec<_> = catalog["schedules"]
            .as_array()
            .expect("validated")
            .iter()
            .filter(|s| s["namespace"] == "MARKET")
            .cloned()
            .collect();
        let broker: Vec<_> = catalog["schedules"]
            .as_array()
            .expect("validated")
            .iter()
            .filter(|s| s["namespace"] == "BROKER")
            .cloned()
            .collect();
        let pack = boundary(OnlyMarketFeePackIdentity::from_record(
            &json!({"schema_version":1,"pack_id":catalog["market_pack"]["id"],"pack_version":catalog["market_pack"]["version"],"fingerprint":digest(&json!([catalog["market_pack"],market]))}),
        ))?;
        let contract = boundary(OnlyBrokerFeeContractIdentity::from_record(
            &json!({"schema_version":1,"contract_id":catalog["broker_contract"]["id"],"contract_version":catalog["broker_contract"]["version"],"broker_id":BROKER,"account_scope":{"schema_version":1,"scope_type":"EXACT_ACCOUNT","account_id":order.account_id().to_record()},"fingerprint":digest(&json!([catalog["broker_contract"],broker]))}),
        ))?;
        let applicability = boundary(OnlyOrderFeeApplicabilityScopeIdentity::create(
            OnlyOrderFeeApplicabilityScopeIdentityInput {
                market_product_id: PROFILE.into(),
                market: MARKET.into(),
                venue: "BINANCE".into(),
                instrument_class: "CASH".into(),
                broker_id: BROKER.into(),
                account_id: order.account_id().clone(),
                instrument_id: order.instrument_id().clone(),
                charge_currency: self.currency.clone(),
                fingerprint: String::new(),
            },
        ))?;
        let fixed = catalog["schedules"].as_array().expect("validated").iter().map(|s| boundary(OnlyFeeScheduleIdentity::from_record(&json!({"schema_version":1,"authority":s["namespace"],"schedule_id":s["family"],"version":s["version"],"fingerprint":digest(s)})))).collect::<Result<Vec<_>, _>>()?;
        boundary(OnlyOrderFeePolicyBinding::create(
            OnlyOrderFeePolicyBindingInput {
                runtime_id: order.runtime_id().clone(),
                account_id: order.account_id().clone(),
                cluster_id: order.cluster_id().clone(),
                order_id: order.order_id().clone(),
                instrument_id: order.instrument_id().clone(),
                market_product_id: PROFILE.into(),
                market_product_version: "1".into(),
                market_fee_pack: pack,
                broker_fee_contract: contract,
                applicability_scope: applicability,
                order_fixed_schedules: fixed,
                fill_effective_families: vec![],
                charge_currency: self.currency.clone(),
                bound_at: at,
                fingerprint: String::new(),
            },
        ))
    }
    fn basis(&self, quantity: &BigDecimal, notional: &BigDecimal) -> Value {
        json!({"notional":notional.to_plain_string(),"quantity":quantity.to_plain_string(),"contracts":null,"currency":self.currency.code()})
    }
    fn assessment(
        &self,
        native: &Value,
        binding: &OnlyOrderFeePolicyBinding,
        trade: Option<OnlyTradeId>,
    ) -> Result<OnlyFeeAssessment, Error> {
        let catalog = self.catalog.record();
        let mut charges: OnlyDecimal = boundary("0".parse())?;
        let mut rebates: OnlyDecimal = boundary("0".parse())?;
        let mut components = vec![];
        for c in native["components"]
            .as_array()
            .ok_or_else(|| bad("FEE_COMPONENTS"))?
        {
            let i = &c["identity"];
            let source = if i["namespace"] == "MARKET" {
                &catalog["market_pack"]["id"]
            } else {
                &catalog["broker_contract"]["id"]
            };
            let identity = boundary(OnlyFeeComponentIdentity::from_record(
                &json!({"schema_version":1,"fee_type":i["type"],"authority":i["authority"],"source_id":source,"schedule_id":i["family"],"schedule_version":i["version"],"schedule_fingerprint":i["schedule"],"rule_id":i["rule"],"rule_fingerprint":i["rule_fingerprint"],"calculation_scope":i["scope"],"resolution_policy":i["resolution"],"economic_direction":i["direction"]}),
            ))?;
            let raw = exact_money(&c["raw"], &self.currency)?;
            let target = exact_money(&c["target"], &self.currency)?;
            if i["direction"] == "CHARGE" {
                charges = boundary(only_add(&charges, target.amount()))?;
            } else {
                rebates = boundary(only_add(&rebates, target.amount()))?;
            }
            components.push(boundary(OnlyFeeTargetComponent::from_record(&json!({"schema_version":1,"identity":identity.to_record(),"raw_amount":raw.to_record(),"bounded_amount":raw.to_record(),"target_amount":target.to_record(),"local_finality":"MODEL_CONFIRMED"})))?);
        }
        let subject = boundary(OnlyFeeSubject::from_record(
            &json!({"schema_version":1,"runtime_id":binding.runtime_id().to_record(),"account_id":binding.account_id().to_record(),"cluster_id":binding.cluster_id().to_record(),"order_id":binding.order_id().to_record(),"instrument_id":binding.instrument_id().to_record()}),
        ))?;
        boundary(OnlyFeeAssessment::new(OnlyFeeAssessmentInput {
            assessment_id: format!("MODEL-FEE-{}", digest(native)),
            subject,
            trade_id: trade,
            components,
            total_charges: exact_money(&json!(charges.to_string()), &self.currency)?,
            total_rebates: exact_money(&json!(rebates.to_string()), &self.currency)?,
            policy_fingerprint: digest(&catalog),
            resolution_fingerprint: digest(native),
            local_finality: OnlyLocalFeeFinality::ModelConfirmed,
            binding: binding.clone(),
        }))
    }
    /// Pure same-policy entry cost analysis. This is neither venue admission nor an execution fact.
    pub fn analytical_entry_quote(
        &self,
        price: &OnlyPrice,
        quantity: &OnlyQuantity,
        context: &Value,
    ) -> Result<Value, Error> {
        let (time, day) = self.context(context, false)?;
        if json!(quantity.precision()) != self.execution["instruments"][0]["quantity_precision"] {
            return Err(bad("QUANTITY_PRECISION"));
        }
        let q = number(&json!(quantity.value().to_string()))?;
        let p = number(&json!(price.value().to_string()))?;
        if let Some(reason) = self.snapshot.rule_reason(&q, &p)? { return Err(bad(reason)); }
        let (cluster, profile) = self.execution["profiles"].as_object().expect("validated profile").iter().next().expect("one profile");
        text(&json!(cluster))?;
        sha(&profile["revision"])?;
        let notional = &p * &q;
        let subject = json!({"engine":self.execution["engine"],"runtime":self.execution["runtime"],"account":self.execution["account"],"broker":BROKER,"gateway":self.execution["gateway"],"generation":self.execution["generation"],"runtime_kind":"BACKTEST","cluster":cluster,"revision":profile["revision"],"instrument":"BTCUSDT.BINANCE","market":MARKET,"venue":"BINANCE","instrument_class":"CASH","currency":self.currency.to_record(),"side":"BUY","offset":"OPEN"});
        let quote = boundary(self.catalog.quote_one_fill(subject, day, time, self.basis(&q, &notional), None))?;
        let record = quote.record();
        let charges = exact_money(&record["charges"], &self.currency)?;
        let rebates = exact_money(&record["rebates"], &self.currency)?;
        Ok(json!({"schema_version":1,"kind":"ANALYTICAL_ESTIMATE","reference_policy":"MODEL_NEXT_OPEN","venue_acceptance_proven":false,"policy_fingerprint":digest(&self.binding),"rules_fingerprint":self.binding["rules_fingerprint"],"execution_price":price.to_record(),"quantity":quantity.to_record(),"context":context,"gross_notional":money(&notional,&self.currency)?.to_record(),"charges":charges.to_record(),"rebates":rebates.to_record(),"fee_quote":record,"fee_quote_fingerprint":quote.fingerprint()}))
    }
    pub fn admission(
        &self,
        value: &Value,
        reference: &OnlyPrice,
        context: &Value,
    ) -> Result<Value, Error> {
        let (time, day) = self.context(context, false)?;
        let order = self.order(value)?;
        if order.fee_policy_binding().is_some() {
            return Err(bad("ALREADY_BOUND"));
        }
        let price = number(&json!(reference.value().to_string()))?;
        let quantity = number(&json!(order.quantity().value().to_string()))?;
        let reason = self.snapshot.rule_reason(&quantity, &price)?;
        let notional = &price * &quantity;
        let provenance = json!({"schema_version":1,"kind":"MODEL_RULE_DECISION","verdict":if reason.is_none(){"MODEL_ACCEPT"}else{"MODEL_REJECT"},"reference_policy":"MODEL_NEXT_OPEN","venue_acceptance_proven":false,"rules_snapshot":self.snapshot.record(),"reference_price":reference.to_record(),"exact_notional":notional.to_plain_string(),"reason":reason,"time":time,"cause":context["cause"]});
        if let Some(reason) = reason {
            return Ok(
                json!({"schema_version":1,"accepted":false,"reason":reason,"market_provenance":provenance}),
            );
        }
        let native_binding = self.fee_binding(&order, day)?;
        let basis = self.basis(&quantity, &notional);
        let estimate = boundary(self.catalog.estimate(
            &native_binding,
            day,
            basis.clone(),
            basis.clone(),
            1,
            Some(1),
        ))?;
        let native = boundary(self.catalog.assess(
            &native_binding,
            day,
            "estimate",
            time,
            basis.clone(),
            basis,
            None,
        ))?
        .record();
        let binding = self.domain_binding(&order, OnlyTimestamp::from_unix_nanos(time.into()))?;
        let assessment = self.assessment(&native, &binding, None)?;
        let reservation = exact_money(&estimate["reservation_charge"], &self.currency)?;
        if assessment.total_charges() != &reservation
            || assessment.total_charges().to_record()["amount"] != estimate["expected"]["charges"]
            || assessment.total_charges().to_record()["amount"] != estimate["maximum"]["charges"]
        {
            return Err(bad("FEE_ESTIMATE_RELATION"));
        }
        let domain_estimate = boundary(OnlyOrderFeeEstimate::new(OnlyOrderFeeEstimateInput {
            expected: assessment.clone(),
            maximum: assessment.clone(),
            reservation_charge: reservation.clone(),
            estimated_rebate: assessment.total_rebates().clone(),
            assumptions_fingerprint: text(&estimate["assumptions"])?.into(),
        }))?;
        let notional = money(&notional, &self.currency)?;
        let principal = if value["side"] == "BUY" {
            notional.clone()
        } else {
            money(&BigDecimal::zero(), &self.currency)?
        };
        let funding = boundary(OnlyOrderFundingPlan::new(OnlyOrderFundingPlanInput {
            order_id: order.order_id().clone(),
            principal_reservation: principal.clone(),
            fee_reservation: reservation.clone(),
            total_reservation: boundary(principal.checked_add(&reservation))?,
            binding_fingerprint: binding.fingerprint().clone(),
            estimate_fingerprint: domain_estimate.assumptions_fingerprint().clone(),
        }))?;
        Ok(
            json!({"schema_version":1,"accepted":true,"contract":{"binding":binding.to_record(),"estimate":domain_estimate.to_record(),"funding":funding.to_record()},"fee_budget":reservation.amount().to_string(),"notional":notional.to_record(),"settlement_policy":self.binding["settlement_policy"],"market_provenance":provenance,"native_fee_binding":native_binding.record(),"native_fee_estimate":estimate}),
        )
    }
    pub fn fill(
        &self,
        value: &Value,
        price: &OnlyPrice,
        quantity: &OnlyQuantity,
        context: &Value,
    ) -> Result<Value, Error> {
        let (time, day) = self.context(context, true)?;
        let order = self.order(value)?;
        if quantity != order.quantity() || quantity.value().is_zero() {
            return Err(bad("WHOLE_FILL_REQUIRED"));
        }
        let installed = order
            .fee_policy_binding()
            .as_ref()
            .ok_or_else(|| bad("FEE_BINDING_REQUIRED"))?;
        let expected = self.domain_binding(&order, installed.bound_at().clone())?;
        if expected != *installed {
            return Err(bad("FEE_BINDING_CONFLICT"));
        }
        let q = number(&json!(quantity.value().to_string()))?;
        let p = number(&json!(price.value().to_string()))?;
        if p.is_zero() {
            return Err(bad("FILL_PRICE"));
        }
        let notional = p * &q;
        let basis = self.basis(&q, &notional);
        let binding = self.fee_binding(&order, day)?;
        let native = boundary(self.catalog.assess(
            &binding,
            day,
            text(&context["trade"])?,
            time,
            basis.clone(),
            basis,
            None,
        ))?
        .record();
        let assessment = self.assessment(
            &native,
            installed,
            Some(boundary(OnlyTradeId::new(text(&context["trade"])?))?),
        )?;
        Ok(
            json!({"schema_version":1,"charge_target":assessment.total_charges().amount().to_string(),"rebate_target":assessment.total_rebates().amount().to_string(),"gross_notional":money(&notional,&self.currency)?.to_record(),"settlement_policy":self.binding["settlement_policy"],"native_fee_assessment":native}),
        )
    }
}
