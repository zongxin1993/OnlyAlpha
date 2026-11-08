//! 将已绑定的 Reference 及配置编译为只读市场规则。
use crate::reference::{Kind, Reference, Result, decimal, fields, fingerprint, items, text};
use bigdecimal::{BigDecimal, Zero};
use onlyalpha_domain::time::OnlyUtcDateTime;
use onlyalpha_fee::Catalog;
use serde_json::{Value, json};
use std::collections::BTreeMap;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Product {
    Spot,
    Usdm,
}
#[derive(Debug)]
pub struct MarketBinding {
    product: Product,
    public: Reference,
    account: Option<Reference>,
    maker: BigDecimal,
    taker: BigDecimal,
    id: String,
}
#[derive(Debug)]
pub struct CompiledPolicy(Value);
fn resource<'a>(
    resources: &'a BTreeMap<String, Reference>,
    config: &Value,
    id: &str,
    fp: &str,
    kind: Kind,
) -> Result<&'a Reference> {
    let r = resources
        .get(text(&config[id])?)
        .ok_or("REFERENCE_RESOURCE_REQUIRED")?;
    if r.kind() != kind || r.fingerprint() != text(&config[fp])? {
        return Err("REFERENCE_BINDING_MISMATCH");
    }
    Ok(r)
}
impl MarketBinding {
    pub fn resolve(
        product: Product,
        c: &Value,
        resources: &BTreeMap<String, Reference>,
    ) -> Result<Self> {
        let (public, account) = match product {
            Product::Spot => {
                fields(
                    c,
                    &[
                        "reference_resource_id",
                        "expected_reference_fingerprint",
                        "maker_fee_rate",
                        "taker_fee_rate",
                    ],
                )?;
                (
                    resource(
                        resources,
                        c,
                        "reference_resource_id",
                        "expected_reference_fingerprint",
                        Kind::Spot,
                    )?,
                    None,
                )
            }
            Product::Usdm => {
                fields(
                    c,
                    &[
                        "public_reference_resource_id",
                        "expected_public_reference_fingerprint",
                        "account_reference_resource_id",
                        "expected_account_reference_fingerprint",
                        "requested_position_mode",
                        "requested_margin_mode",
                        "requested_leverage",
                        "maker_fee_rate",
                        "taker_fee_rate",
                    ],
                )?;
                let p = resource(
                    resources,
                    c,
                    "public_reference_resource_id",
                    "expected_public_reference_fingerprint",
                    Kind::Public,
                )?;
                let a = resource(
                    resources,
                    c,
                    "account_reference_resource_id",
                    "expected_account_reference_fingerprint",
                    Kind::Account,
                )?;
                let effective = &a.payload()["references"][0]["effective_inputs"];
                if c["requested_position_mode"] != effective["position_mode"]
                    || c["requested_margin_mode"] != effective["margin_mode"]
                    || decimal(&c["requested_leverage"])? != decimal(&effective["leverage"])?
                {
                    return Err("ACCOUNT_EFFECTIVE_TRADING_PROFILE_MISMATCH");
                }
                (p, Some(a.clone()))
            }
        };
        let maker = decimal(&c["maker_fee_rate"])?;
        let taker = decimal(&c["taker_fee_rate"])?;
        if [&maker, &taker]
            .into_iter()
            .any(|n| n < &BigDecimal::zero() || n >= &BigDecimal::from(1))
        {
            return Err("MARKET_FEE_RATE_INVALID");
        }
        let id = fingerprint(&json!([
            "CRYPTO_MARKET_RULES_NATIVE@1",
            "LIQUIDITY_SCOPED_COMMISSION@2",
            public.fingerprint(),
            account.as_ref().map(Reference::fingerprint),
            maker.normalized().to_plain_string(),
            taker.normalized().to_plain_string()
        ]))?;
        Ok(Self {
            product,
            public: public.clone(),
            account,
            maker,
            taker,
            id,
        })
    }
    pub fn fingerprint(&self) -> &str {
        &self.id
    }
    pub fn compile(&self, instrument: &str, at: OnlyUtcDateTime) -> Result<CompiledPolicy> {
        let r = self.public.resolve(instrument, at)?;
        let mut p = r.clone();
        p["timezone"] = json!("UTC");
        p["continuous_24x7"] = json!(true);
        p["settlement"] = json!("IMMEDIATE");
        p["binding_fingerprint"] = json!(self.id);
        p["as_of"] = json!(at.to_string());
        if self.product == Product::Usdm {
            p["market_product"] = json!("BINANCE_USDM");
            p["contract_type"] = json!("LINEAR");
        }
        if let Some(a) = &self.account {
            let a = a.resolve(instrument, at)?;
            let effective = &a["effective_inputs"];
            p["position_mode"] = effective["position_mode"].clone();
            p["margin_mode"] = effective["margin_mode"].clone();
            p["leverage"] = effective["leverage"].clone();
            p["margin_segments"] = a["margin_segments"].clone();
            p["account_reference"] = a["content_fingerprint"].clone();
            p["account_coverage_start"] = a["coverage_start"].clone();
            p["account_coverage_end"] = a["coverage_end"].clone();
            p["short_allowed"] = json!(true);
            validate_curve(items(&p["margin_segments"])?)?;
        } else {
            p["position_mode"] = json!("NETTING");
            p["short_allowed"] = json!(false);
            let mut dynamic = Vec::new();
            for rule in items(&p["rules"])? {
                let (reference, side_specific, names): (&str, bool, &[&str]) =
                    match rule["rule_type"].as_str() {
                        Some("PERCENT_PRICE") => (
                            "VENUE_REFERENCE_PRICE_OR_TRADE_AVERAGE",
                            false,
                            &["multiplierDown", "multiplierUp"],
                        ),
                        Some("PERCENT_PRICE_BY_SIDE") => (
                            "VENUE_REFERENCE_PRICE_OR_TRADE_AVERAGE",
                            true,
                            &[
                                "askMultiplierDown",
                                "askMultiplierUp",
                                "bidMultiplierDown",
                                "bidMultiplierUp",
                            ],
                        ),
                        Some("PRICE_RANGE") => (
                            "VENUE_REFERENCE_PRICE",
                            true,
                            &[
                                "askLimitMultDown",
                                "askLimitMultUp",
                                "bidLimitMultDown",
                                "bidLimitMultUp",
                            ],
                        ),
                        _ => continue,
                    };
                let settings: BTreeMap<_, _> = items(&rule["values"])?
                    .iter()
                    .map(|pair| (pair[0].as_str().unwrap_or(""), &pair[1]))
                    .collect();
                let mut terms = BTreeMap::new();
                for &name in names {
                    let value = settings.get(name).ok_or("DYNAMIC_PRICE_EVIDENCE")?;
                    if decimal(value)? <= BigDecimal::zero() {
                        return Err("DYNAMIC_PRICE_RULE_INVALID");
                    }
                    terms.insert(name, *value);
                }
                let window = if reference == "VENUE_REFERENCE_PRICE" {
                    None
                } else {
                    Some(
                        settings
                            .get("avgPriceMins")
                            .and_then(|v| v.as_u64())
                            .ok_or("DYNAMIC_PRICE_WINDOW")?,
                    )
                };
                dynamic.push(json!({"rule_id":rule["rule_type"],"side_specific":side_specific,"reference_kind":reference,"reference_window_minutes":window,"terms":terms,"source":"REALTIME_MARKET_REFERENCE"}));
            }
            p["dynamic_price_requirements"] = json!(dynamic);
        }
        p["policy_fingerprint"] = json!(fingerprint(&p)?);
        Ok(CompiledPolicy(p))
    }
    /// 调用方提供完整的已选 Broker Contract 与关联的 BROKER Schedules，合并后由 Fee 验证。
    pub fn fee_catalog(
        &self,
        broker_contract: &Value,
        broker_schedules: &[Value],
    ) -> Result<Catalog> {
        if broker_schedules.is_empty()
            || broker_schedules.iter().any(|r| r["namespace"] != "BROKER")
        {
            return Err("BROKER_FEE_CONTRACT_REQUIRED");
        }
        let (market, class) = if self.product == Product::Spot {
            ("BINANCE_SPOT", "CASH")
        } else {
            ("BINANCE_USDM", "DERIVATIVE")
        };
        let family = format!("{market}_CONFIGURED_BASELINE");
        let rule = |name: &str, role: &str, rate: &BigDecimal| json!({"id":name,"type":format!("{role}_FEE"),"authority":"MARKET","direction":"CHARGE","scope":"FILL","resolution":"FILL_EFFECTIVE","terms":[{"kind":"RATE","basis":"NOTIONAL","amount":rate.to_plain_string()}],"minimum":null,"maximum":null,"quantum":"0.00000001","rounding":"HALF_EVEN","pipeline":"ROUND_THEN_BOUNDS","side":null,"offset":null,"liquidity":role});
        let mut schedules = broker_schedules.to_vec();
        schedules.push(json!({"namespace":"MARKET","family":family,"version":"2","from":0,"to":null,"scope":{"market":market,"venue":"BINANCE","instrument_class":class,"currency":"USDT"},"rules":[rule("maker","MAKER",&self.maker),rule("taker","TAKER",&self.taker)]}));
        Catalog::new(json!({"schema_version":1,"market_pack":{"id":family,"version":"2","families":[family]},"broker_contract":broker_contract,"schedules":schedules})).map_err(|_|"MARKET_FEE_CATALOG_INVALID")
    }
}
fn amounts(segment: &Value, n: &BigDecimal) -> Result<(BigDecimal, BigDecimal)> {
    let initial = decimal(&segment["initial_slope"])? * n + decimal(&segment["initial_intercept"])?;
    let maintenance =
        decimal(&segment["maintenance_slope"])? * n + decimal(&segment["maintenance_intercept"])?;
    if maintenance < BigDecimal::zero() || initial < maintenance {
        return Err("MARGIN_REQUIREMENT_INVALID");
    }
    Ok((initial, maintenance))
}
fn validate_curve(segments: &[Value]) -> Result<()> {
    if segments.is_empty() || !decimal(&segments[0]["lower_bound"])?.is_zero() {
        return Err("MARGIN_DOMAIN_INCOMPLETE");
    }
    for (i, s) in segments.iter().enumerate() {
        let lo = decimal(&s["lower_bound"])?;
        if lo < BigDecimal::zero()
            || decimal(&s["initial_slope"])? < BigDecimal::zero()
            || decimal(&s["maintenance_slope"])? < BigDecimal::zero()
        {
            return Err("MARGIN_SEGMENT_INVALID");
        }
        amounts(s, &lo)?;
        if s["upper_bound"].is_null() {
            if i + 1 != segments.len() {
                return Err("MARGIN_DOMAIN_INCOMPLETE");
            }
        } else {
            let hi = decimal(&s["upper_bound"])?;
            if hi <= lo {
                return Err("MARGIN_SEGMENT_INVALID");
            }
            let here = amounts(s, &hi)?;
            if let Some(next) = segments.get(i + 1)
                && (decimal(&next["lower_bound"])? != hi || here != amounts(next, &hi)?)
            {
                return Err("MARGIN_SEGMENTS_DISCONTINUOUS");
            }
        }
    }
    Ok(())
}
impl CompiledPolicy {
    pub fn record(&self) -> &Value {
        &self.0
    }
    /// 向通用内核交付当前 USD-M 公共规则与账户资源共同覆盖的限价约束。
    pub fn static_limit_rules(
        &self,
    ) -> Result<onlyalpha_domain::market_rules::OnlyStaticLimitRules> {
        onlyalpha_domain::market_rules::OnlyStaticLimitRules::from_compiled_policy_json(
            &self.compiled_policy_json()?,
            text(&self.0["policy_fingerprint"])?,
        )
        .map_err(|_| "MARKET_LIMIT_RULES")
    }
    /// 原 compile 生产者实际计算策略指纹的正文，不包含结果指纹字段。
    pub fn compiled_policy_json(&self) -> Result<String> {
        let mut body = self.0.clone();
        body.as_object_mut()
            .ok_or("MARKET_POLICY_BODY")?
            .remove("policy_fingerprint");
        onlyalpha_metadata_json::python_json(&body.to_string(), 1024 * 1024)
            .map_err(|_| "MARKET_POLICY_BODY")
    }

    /// 只验证静态限价委托规则；动态价格、可用余额、权限和风控另需各自证据。
    pub fn validate_limit(&self, price: &BigDecimal, quantity: &BigDecimal) -> Result<()> {
        let r = &self.0;
        if r["provider_status"] != "TRADING"
            || (r.get("spot_trading_allowed").is_some()
                && (r["spot_trading_allowed"] != true
                    || r["compatibility_status"] != "COMPATIBLE"
                    || !items(&r["venue_order_types"])?.contains(&json!("LIMIT"))))
        {
            return Err("MARKET_NOT_TRADABLE");
        }
        for (n, step, min, max) in [
            (price, "price_tick", "minimum_price", "maximum_price"),
            (
                quantity,
                "quantity_step",
                "minimum_quantity",
                "maximum_quantity",
            ),
        ] {
            if n <= &BigDecimal::zero()
                || !(n % decimal(&r[step])?).is_zero()
                || (!r[min].is_null() && n < &decimal(&r[min])?)
                || (!r[max].is_null() && n > &decimal(&r[max])?)
            {
                return Err("MARKET_INCREMENT_OR_RANGE");
            }
        }
        let multiplier = if r.get("contract_multiplier").is_some() {
            decimal(&r["contract_multiplier"])?
        } else {
            BigDecimal::from(1)
        };
        let n = price * quantity * multiplier;
        if !r["minimum_notional"].is_null() && n < decimal(&r["minimum_notional"])? {
            return Err("NOTIONAL_BELOW_MINIMUM");
        }
        if !r["maximum_notional"].is_null() && n > decimal(&r["maximum_notional"])? {
            return Err("NOTIONAL_ABOVE_MAXIMUM");
        }
        Ok(())
    }
    pub fn margin_requirement(&self, n: &BigDecimal) -> Result<(BigDecimal, BigDecimal)> {
        let segments = items(&self.0["margin_segments"])?;
        for (i, s) in segments.iter().enumerate() {
            if n >= &decimal(&s["lower_bound"])?
                && (s["upper_bound"].is_null()
                    || n < &decimal(&s["upper_bound"])?
                    || (i + 1 == segments.len() && n == &decimal(&s["upper_bound"])?))
            {
                return amounts(s, n);
            }
        }
        Err("MARGIN_NOTIONAL_OUTSIDE_COMPILED_DOMAIN")
    }
}
