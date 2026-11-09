//! 从冻结 Fee Catalog 构造同一订单的费率绑定、预留和实际成交分项。
use super::model::*;
use bigdecimal::BigDecimal;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    execution::OnlyOrderSnapshot,
    fee::*,
    numeric::{OnlyDecimal, only_add},
    time::OnlyTimestamp,
    value::{OnlyCurrency, OnlyMoney},
};
use onlyalpha_fee::{Assessment, Binding, Catalog, digest};
use serde_json::{Value, json};
fn cash(amount: &BigDecimal, currency: &OnlyCurrency) -> Result<OnlyMoney, Error> {
    let rounded = amount.with_scale_round(
        i64::from(currency.precision()),
        bigdecimal::RoundingMode::HalfEven,
    );
    Ok(OnlyMoney::new(
        rounded.to_plain_string().parse()?,
        currency.clone(),
    )?)
}
pub(crate) struct Fees<'a> {
    cfg: &'a Value,
    terms: &'a Value,
    currency: OnlyCurrency,
    catalog: Catalog,
    day: u64,
}
impl<'a> Fees<'a> {
    pub(crate) fn new(cfg: &'a Value, day: u64) -> Result<Self, Error> {
        let terms = &cfg["perpetual"];
        Ok(Self {
            cfg,
            terms,
            currency: OnlyCurrency::from_record(&cfg["currency"])?,
            catalog: boundary(Catalog::new(terms["fee_catalog"].clone()))?,
            day,
        })
    }
    fn native_binding(&self, order: &OnlyOrderSnapshot, day: u64) -> Result<Binding, Error> {
        let cfg = self.cfg;
        let r = order.to_record();
        let subject = json!({"engine":cfg["engine"],"runtime":cfg["runtime"],"account":cfg["account"],"broker":self.terms["fee_catalog"]["broker_contract"]["broker"],"gateway":cfg["gateway"],"generation":cfg["generation"],"runtime_kind":cfg["runtime_kind"],"cluster":order.cluster_id().value(),"revision":cfg["profiles"][order.cluster_id().value()]["revision"],"order":order.order_id().value(),"instrument":order.instrument_id().to_string(),"market":self.terms["market_product"],"venue":order.instrument_id().venue().value(),"instrument_class":"DERIVATIVE","currency":cfg["currency"],"side":r["side"],"offset":r["execution_intent"]["position_effect"]});
        boundary(self.catalog.bind(subject, day))
    }
    fn basis(&self, q: &BigDecimal, n: &BigDecimal) -> Value {
        json!({"quantity":q.normalized().to_plain_string(),"contracts":q.normalized().to_plain_string(),"notional":n.normalized().to_plain_string(),"currency":self.currency.code()})
    }
    fn domain_binding(
        &self,
        order: &OnlyOrderSnapshot,
        at: OnlyTimestamp,
    ) -> Result<OnlyOrderFeePolicyBinding, Error> {
        let catalog = self.catalog.record();
        let product = text(&self.terms["market_product"])?;
        let broker_id = text(&catalog["broker_contract"]["broker"])?;
        let venue = order.instrument_id().venue().value();
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
            &json!({"schema_version":1,"contract_id":catalog["broker_contract"]["id"],"contract_version":catalog["broker_contract"]["version"],"broker_id":broker_id,"account_scope":{"schema_version":1,"scope_type":"EXACT_ACCOUNT","account_id":order.account_id().to_record()},"fingerprint":digest(&json!([catalog["broker_contract"],broker]))}),
        ))?;
        let applicability = boundary(OnlyOrderFeeApplicabilityScopeIdentity::create(
            OnlyOrderFeeApplicabilityScopeIdentityInput {
                market_product_id: product.into(),
                market: product.into(),
                venue: venue.into(),
                instrument_class: "DERIVATIVE".into(),
                broker_id: broker_id.into(),
                account_id: order.account_id().clone(),
                instrument_id: order.instrument_id().clone(),
                charge_currency: self.currency.clone(),
                fingerprint: String::new(),
            },
        ))?;
        let mut fixed = Vec::new();
        let mut families = Vec::new();
        for schedule in boundary(
            self.catalog
                .selected_schedules(&self.native_binding(order, self.day)?, self.day),
        )? {
            if schedule["rules"][0]["resolution"] == "ORDER_FIXED" {
                fixed.push(OnlyFeeScheduleIdentity::from_record(&json!({"schema_version":1,"authority":schedule["namespace"],"schedule_id":schedule["family"],"version":schedule["version"],"fingerprint":digest(&schedule)}))?);
            } else {
                families.push(OnlyFeeScheduleFamilyIdentity::from_record(&json!({"schema_version":1,"authority":schedule["namespace"],"schedule_id":schedule["family"],"scope_fingerprint":digest(&schedule["scope"])}))?);
            }
        }
        boundary(OnlyOrderFeePolicyBinding::create(
            OnlyOrderFeePolicyBindingInput {
                runtime_id: order.runtime_id().clone(),
                account_id: order.account_id().clone(),
                cluster_id: order.cluster_id().clone(),
                order_id: order.order_id().clone(),
                instrument_id: order.instrument_id().clone(),
                market_product_id: product.into(),
                market_product_version: "1".into(),
                market_fee_pack: pack,
                broker_fee_contract: contract,
                applicability_scope: applicability,
                order_fixed_schedules: fixed,
                fill_effective_families: families,
                charge_currency: self.currency.clone(),
                bound_at: at,
                fingerprint: String::new(),
            },
        ))
    }
    fn assessment(
        &self,
        native: &Value,
        binding: &OnlyOrderFeePolicyBinding,
        count: u64,
    ) -> Result<OnlyFeeAssessment, Error> {
        let catalog = self.catalog.record();
        let mut charges: OnlyDecimal = boundary("0".parse())?;
        let mut rebates: OnlyDecimal = boundary("0".parse())?;
        let mut components = vec![];
        for c in native["components"]
            .as_array()
            .ok_or_else(|| err("EXECUTION_FEE_COMPONENTS"))?
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
            let raw = cash(
                &(exact(&c["raw"])? * BigDecimal::from(count)),
                &self.currency,
            )?;
            let target = cash(
                &(exact(&c["target"])? * BigDecimal::from(count)),
                &self.currency,
            )?;
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
            assessment_id: format!("FEST-{}", digest(&json!([native, count]))),
            subject,
            trade_id: None,
            components,
            total_charges: OnlyMoney::new(charges, self.currency.clone())?,
            total_rebates: OnlyMoney::new(rebates, self.currency.clone())?,
            policy_fingerprint: digest(&catalog),
            resolution_fingerprint: digest(native),
            local_finality: OnlyLocalFeeFinality::ModelConfirmed,
            binding: binding.clone(),
        }))
    }
    pub(crate) fn contract(
        &self,
        order: &OnlyOrderSnapshot,
        time: u64,
        notional: &BigDecimal,
    ) -> Result<Value, Error> {
        let binding = self.domain_binding(order, OnlyTimestamp::from_unix_nanos(time.into()))?;
        let native = self.native_binding(order, self.day)?;
        let q = dec(&order.to_record()["quantity"]["value"])?;
        let quanta = q * BigDecimal::new(1.into(), -i64::from(order.quantity().precision()));
        let count = quanta
            .normalized()
            .to_plain_string()
            .parse::<u64>()
            .map_err(|_| err("EXECUTION_FEE_BOUND"))?;
        if !(1..=4096).contains(&count) {
            return Err(err("EXECUTION_FEE_BOUND"));
        }
        let basis = self.basis(&dec(&order.to_record()["quantity"]["value"])?, notional);
        let assess = |day, role| {
            boundary(self.catalog.assess(
                &native,
                day,
                "estimate",
                time,
                basis.clone(),
                basis.clone(),
                Some(role),
            ))
        };
        let mut expected = self.assessment(&assess(self.day, "TAKER")?.record(), &binding, 1)?;
        let maker = self.assessment(&assess(self.day, "MAKER")?.record(), &binding, 1)?;
        if maker.total_charges().amount() > expected.total_charges().amount() {
            expected = maker;
        }
        let mut maximum = expected.clone();
        for day in boundary(self.catalog.effective_days(&native))? {
            for role in ["TAKER", "MAKER"] {
                let candidate = self.assessment(&assess(day, role)?.record(), &binding, count)?;
                if candidate.total_charges().amount() > maximum.total_charges().amount() {
                    maximum = candidate;
                }
            }
        }
        let reservation = maximum.total_charges().clone();
        let estimate = OnlyOrderFeeEstimate::new(OnlyOrderFeeEstimateInput {
            estimated_rebate: expected.total_rebates().clone(),
            expected,
            maximum,
            reservation_charge: reservation.clone(),
            assumptions_fingerprint: digest(&json!([
                "LINEAR_GTC_ROLE_SPLIT_BOUND@2",
                native.record(),
                basis,
                count
            ])),
        })?;
        let funding = OnlyOrderFundingPlan::new(OnlyOrderFundingPlanInput {
            order_id: order.order_id().clone(),
            principal_reservation: cash(&BigDecimal::from(0), &self.currency)?,
            fee_reservation: reservation.clone(),
            total_reservation: reservation,
            binding_fingerprint: binding.fingerprint().clone(),
            estimate_fingerprint: estimate.assumptions_fingerprint().clone(),
        })?;
        Ok(
            json!({"binding":binding.to_record(),"estimate":estimate.to_record(),"funding":funding.to_record()}),
        )
    }
    pub(crate) fn fill(
        &self,
        order: &OnlyOrderSnapshot,
        bound_day: u64,
        fill: &Value,
    ) -> Result<Assessment, Error> {
        let role = text(&fill["liquidity_side"])?;
        if !matches!(role, "MAKER" | "TAKER") {
            return Err(err("EXECUTION_FEE_ROLE"));
        }
        let b = self.native_binding(order, bound_day)?;
        let q = nonnegative(&fill["quantity"]["value"])?;
        let mult = nonnegative(&self.terms["multiplier"])?;
        let n = &q * nonnegative(&fill["price"]["value"])? * &mult;
        let snapshot = order.to_record();
        boundary(self.catalog.assess(
            &b,
            self.day,
            id(&fill["trade_id"]["value"])?,
            uint(&fill["ts_event"]["unix_nanos"])?,
            self.basis(&q, &n),
            self.basis(
                &(q + dec(&snapshot["filled_quantity"]["value"])?),
                &(n + exact(&snapshot["cumulative_price_quantity"])? * mult),
            ),
            Some(role),
        ))
    }
}
pub(crate) fn decode_assessment(v: &Value) -> Result<Assessment, Error> {
    let c = boundary(Catalog::new(v["catalog"].clone()))?;
    let b = boundary(c.bind(v["binding"]["subject"].clone(), uint(&v["binding"]["day"])?))?;
    let a = boundary(c.assess(
        &b,
        uint(&v["day"])?,
        id(&v["trade"])?,
        uint(&v["time"])?,
        v["fill"].clone(),
        v["cumulative"].clone(),
        Some(text(&v["liquidity"])?),
    ))?;
    if a.record() != *v {
        return Err(err("EXECUTION_FEE_ASSESSMENT_REPLAY"));
    }
    Ok(a)
}
