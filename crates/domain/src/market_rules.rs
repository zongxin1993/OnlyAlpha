//! Effective-dated rule values; market selection and parameter authority remain in plugins.
use crate::{
    base::{domain_model, invalid},
    enums::{OnlyLiquiditySide, OnlyOffset, OnlyOrderSide},
    errors::OnlyDomainError,
    numeric::{
        OnlyDecimal, OnlyRoundingMode, only_multiply, only_quantize_with_rounding, only_remainder,
    },
    time::OnlyUtcDateTime,
    value::{OnlyMoney, OnlyPrice, OnlyQuantity, OnlyRate},
};
use bigdecimal::num_bigint::BigInt;

domain_model!(OnlyValidationResult,OnlyValidationResultInput,1,None,{violations:Vec<String>});
impl OnlyValidationResult {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        Ok(())
    }
    pub fn is_valid(&self) -> bool {
        self.violations().is_empty()
    }
}
domain_model!(OnlyLotSizeRule,OnlyLotSizeRuleInput,1,None,{buy_increment:OnlyDecimal,sell_increment:OnlyDecimal});
impl OnlyLotSizeRule {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if [self.buy_increment(), self.sell_increment()]
            .iter()
            .any(|value| value.is_negative() || value.is_zero())
        {
            return Err(invalid("lot increments must be positive"));
        }
        Ok(())
    }
    pub fn validates(
        &self,
        side: OnlyOrderSide,
        quantity: &OnlyQuantity,
    ) -> Result<bool, OnlyDomainError> {
        let increment = if side == OnlyOrderSide::Buy {
            self.buy_increment()
        } else {
            self.sell_increment()
        };
        Ok(only_remainder(quantity.value(), increment)?.is_zero())
    }
}
domain_model!(OnlySettlementRule,OnlySettlementRuleInput,1,None,{settlement_days:BigInt,allow_same_day_sell:bool,allowed_offsets:Vec<OnlyOffset>});
impl OnlySettlementRule {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if self.settlement_days() < &BigInt::from(0) {
            return Err(invalid("settlement days cannot be negative"));
        }
        Ok(())
    }
}
domain_model!(OnlyPriceLimitRule,OnlyPriceLimitRuleInput,1,None,{lower:Option<OnlyPrice>,upper:Option<OnlyPrice>});
impl OnlyPriceLimitRule {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        Ok(())
    }
    pub fn validates(&self, price: &OnlyPrice) -> bool {
        self.lower()
            .as_ref()
            .is_none_or(|lower| price.value() >= lower.value())
            && self
                .upper()
                .as_ref()
                .is_none_or(|upper| price.value() <= upper.value())
    }
}
domain_model!(OnlyPriceLadder,OnlyPriceLadderInput,1,None,{steps:Vec<(Option<OnlyDecimal>,OnlyDecimal)>});
impl OnlyPriceLadder {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        Ok(())
    }
    pub fn increment_for(&self, price: &OnlyPrice) -> Result<&OnlyDecimal, OnlyDomainError> {
        self.steps()
            .iter()
            .find(|(upper, _)| upper.as_ref().is_none_or(|upper| price.value() <= upper))
            .map(|(_, increment)| increment)
            .ok_or_else(|| invalid("price ladder requires an open final bound"))
    }
}
domain_model!(OnlyTickScheme,OnlyTickSchemeInput,1,None,{ladder:OnlyPriceLadder});
impl OnlyTickScheme {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        Ok(())
    }
    pub fn validates(&self, price: &OnlyPrice) -> Result<bool, OnlyDomainError> {
        Ok(only_remainder(price.value(), self.ladder().increment_for(price)?)?.is_zero())
    }
}
domain_model!(OnlyFeeSchedule,OnlyFeeScheduleInput,1,None,{
 schedule_id:String,maker_rate:OnlyRate,taker_rate:OnlyRate,minimum_fee:OnlyMoney,effective_from:OnlyUtcDateTime,effective_to:Option<OnlyUtcDateTime>,
});
impl OnlyFeeSchedule {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if self
            .effective_to()
            .is_some_and(|end| end <= *self.effective_from())
        {
            return Err(invalid(
                "fee schedule effective interval must be increasing",
            ));
        }
        Ok(())
    }
    pub fn calculate(
        &self,
        notional: &OnlyMoney,
        liquidity: OnlyLiquiditySide,
    ) -> Result<OnlyMoney, OnlyDomainError> {
        if notional.currency() != self.minimum_fee().currency() {
            return Err(invalid("fee notional currency mismatch"));
        }
        let rate = if liquidity == OnlyLiquiditySide::Maker {
            self.maker_rate()
        } else {
            self.taker_rate()
        };
        let raw = only_multiply(notional.amount(), rate.value())?;
        let amount = if raw < *self.minimum_fee().amount() {
            self.minimum_fee().amount().clone()
        } else {
            raw
        };
        let quantum = format!("1E-{}", notional.currency().precision()).parse()?;
        OnlyMoney::new(
            only_quantize_with_rounding(&amount, &quantum, OnlyRoundingMode::Down)?,
            notional.currency().clone(),
        )
    }
    pub fn is_effective_at(&self, timestamp: OnlyUtcDateTime) -> bool {
        timestamp >= *self.effective_from() && self.effective_to().is_none_or(|end| timestamp < end)
    }
}
domain_model!(OnlyFeeScheduleCatalog,OnlyFeeScheduleCatalogInput,1,None,{schedules:Vec<OnlyFeeSchedule>});
impl OnlyFeeScheduleCatalog {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        Ok(())
    }
    pub fn resolve(
        &self,
        schedule_id: &str,
        as_of: OnlyUtcDateTime,
    ) -> Result<&OnlyFeeSchedule, OnlyDomainError> {
        let mut matches = self.schedules().iter().filter(|schedule| {
            schedule.schedule_id() == schedule_id && schedule.is_effective_at(as_of)
        });
        let result = matches
            .next()
            .ok_or_else(|| invalid("no effective fee schedule"))?;
        if matches.next().is_some() {
            return Err(invalid("ambiguous effective fee schedule"));
        }
        Ok(result)
    }
}
domain_model!(OnlyTradingRule,OnlyTradingRuleInput,1,None,{minimum_notional:Option<OnlyMoney>});
impl OnlyTradingRule {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        Ok(())
    }
}

// 市场插件编译的静态限价约束。有效期取所有参与资源区间的交集。
domain_model!(OnlyStaticLimitRules,OnlyStaticLimitRulesInput,1,None,{
    instrument_id:crate::identifiers::OnlyInstrumentId,binding:String,policy:String,tradable:bool,
    effective_from:OnlyUtcDateTime,effective_to:Option<OnlyUtcDateTime>,price_tick:OnlyDecimal,
    quantity_step:OnlyDecimal,minimum_price:Option<OnlyDecimal>,maximum_price:Option<OnlyDecimal>,
    minimum_quantity:Option<OnlyDecimal>,maximum_quantity:Option<OnlyDecimal>,
    minimum_notional:Option<OnlyDecimal>,maximum_notional:Option<OnlyDecimal>,multiplier:OnlyDecimal,
});
impl OnlyStaticLimitRules {
    /// 从市场生产者原编译正文推导规则；原策略身份绑定正文的确切字节。
    pub fn from_compiled_policy_json(raw: &str, policy: &str) -> Result<Self, OnlyDomainError> {
        use crate::base::OnlyDomainModel;
        use sha2::{Digest, Sha256};
        let digest: String = Sha256::digest(raw.as_bytes())
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        if raw.len() > 1024 * 1024 || digest != policy {
            return Err(invalid("compiled market policy identity mismatch"));
        }
        let p: serde_json::Value =
            serde_json::from_str(raw).map_err(|_| invalid("compiled market policy JSON"))?;
        let time = |key: &str| -> Result<OnlyUtcDateTime, OnlyDomainError> {
            p[key]
                .as_str()
                .ok_or_else(|| invalid("compiled market policy time"))?
                .parse()
        };
        let start = time("coverage_start")?
            .max(time("account_coverage_start")?)
            .max(time("as_of")?);
        let mut end = None;
        for key in ["coverage_end", "account_coverage_end"] {
            if !p[key].is_null() {
                let value = time(key)?;
                end = Some(end.map_or(value, |old: OnlyUtcDateTime| old.min(value)));
            }
        }
        let inst: crate::identifiers::OnlyInstrumentId = p["instrument_id"]
            .as_str()
            .ok_or_else(|| invalid("compiled market instrument"))?
            .parse()?;
        let mut rules = serde_json::json!({"schema_version":1,"instrument_id":inst.to_record(),"binding":p["binding_fingerprint"],"policy":policy,"tradable":p["provider_status"]=="TRADING","effective_from":start.to_string(),"effective_to":end.map(|v|v.to_string()),"multiplier":p["contract_multiplier"]});
        for key in [
            "price_tick",
            "minimum_price",
            "maximum_price",
            "quantity_step",
            "minimum_quantity",
            "maximum_quantity",
            "minimum_notional",
            "maximum_notional",
        ] {
            rules[key] = p[key].clone();
        }
        Self::from_record(&rules)
    }
    /// 从同一原编译正文取得消费者依赖的通用经济字段，保留完整原策略身份校验。
    pub fn compiled_economics(
        raw: &str,
        policy: &str,
    ) -> Result<serde_json::Value, OnlyDomainError> {
        Self::from_compiled_policy_json(raw, policy)?;
        let p: serde_json::Value =
            serde_json::from_str(raw).map_err(|_| invalid("compiled market policy JSON"))?;
        Self::normalize_economics(
            serde_json::json!({"instrument":p["instrument_id"],"market_product":p["market_product"],"contract_type":p["contract_type"],"position_mode":p["position_mode"],"margin_mode":p["margin_mode"],"settlement_currency":p["settlement_currency"],"multiplier":p["contract_multiplier"],"margin_segments":p["margin_segments"],"funding_schedule":p["funding_schedule"]}),
        )
    }
    /// 规范化同一个通用经济投影，用于原生产者与实际配置的值比较。
    pub fn normalize_economics(
        mut p: serde_json::Value,
    ) -> Result<serde_json::Value, OnlyDomainError> {
        let decimal = |v: &serde_json::Value| -> Result<serde_json::Value, OnlyDomainError> {
            let n: OnlyDecimal = v
                .as_str()
                .ok_or_else(|| invalid("market economic decimal"))?
                .parse()?;
            Ok(serde_json::json!(n.canonical().to_string()))
        };
        for key in [
            "instrument",
            "market_product",
            "contract_type",
            "position_mode",
            "margin_mode",
            "settlement_currency",
        ] {
            if p[key].as_str().is_none_or(|v| v.is_empty()) {
                return Err(invalid("market economic identity"));
            }
        }
        let instrument: crate::identifiers::OnlyInstrumentId =
            p["instrument"].as_str().expect("validated").parse()?;
        if p["instrument"] != instrument.to_string() {
            return Err(invalid("market economic instrument"));
        }
        p["multiplier"] = decimal(&p["multiplier"])?;
        let segments = p["margin_segments"]
            .as_array_mut()
            .filter(|s| !s.is_empty() && s.len() <= 128)
            .ok_or_else(|| invalid("market economic margin curve"))?;
        for segment in segments {
            let keys = [
                "lower_bound",
                "upper_bound",
                "initial_slope",
                "initial_intercept",
                "maintenance_slope",
                "maintenance_intercept",
            ];
            if segment
                .as_object()
                .is_none_or(|r| r.len() != keys.len() || keys.iter().any(|k| !r.contains_key(*k)))
            {
                return Err(invalid("market economic segment"));
            }
            for key in keys {
                if key != "upper_bound" || !segment[key].is_null() {
                    segment[key] = decimal(&segment[key])?;
                }
            }
        }
        let schedule = &p["funding_schedule"];
        let keys = [
            "interval_seconds",
            "boundary_offset_seconds",
            "valuation_price_kind",
            "provider_semantic_version",
        ];
        if schedule
            .as_object()
            .is_none_or(|r| r.len() != keys.len() || keys.iter().any(|k| !r.contains_key(*k)))
            || schedule["interval_seconds"].as_u64().is_none_or(|n| n == 0)
            || schedule["boundary_offset_seconds"].as_u64().is_none()
            || schedule["valuation_price_kind"].as_str().is_none()
            || schedule["provider_semantic_version"]
                .as_str()
                .is_none_or(|v| v.is_empty())
        {
            return Err(invalid("market economic funding schedule"));
        }
        Ok(p)
    }
    /// 完整静态约束身份，包含原编译策略、binding 与生效区间。
    pub fn content_fingerprint(&self) -> String {
        use crate::base::OnlyDomainModel;
        use sha2::{Digest, Sha256};
        Sha256::digest(self.to_record().to_string().as_bytes())
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect()
    }

    fn validate(&self) -> Result<(), OnlyDomainError> {
        for fp in [self.binding(), self.policy()] {
            if fp.len() != 64
                || !fp
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            {
                return Err(invalid("invalid limit rule binding"));
            }
        }
        if self
            .effective_to()
            .is_some_and(|end| end <= *self.effective_from())
            || [self.price_tick(), self.quantity_step(), self.multiplier()]
                .into_iter()
                .any(|n| n.is_zero() || n.is_negative())
        {
            return Err(invalid("invalid limit rule interval or increment"));
        }
        for (lo, hi) in [
            (self.minimum_price(), self.maximum_price()),
            (self.minimum_quantity(), self.maximum_quantity()),
            (self.minimum_notional(), self.maximum_notional()),
        ] {
            if lo.iter().chain(hi).any(|v| v.is_negative())
                || lo.as_ref().zip(hi.as_ref()).is_some_and(|(a, b)| a > b)
            {
                return Err(invalid("invalid limit rule bounds"));
            }
        }
        Ok(())
    }
    pub fn validates_at(
        &self,
        price: &OnlyPrice,
        quantity: &OnlyQuantity,
        at: OnlyUtcDateTime,
    ) -> Result<bool, OnlyDomainError> {
        let notional = only_multiply(
            &only_multiply(price.value(), quantity.value())?,
            self.multiplier(),
        )?;
        Ok(*self.tradable()
            && at >= *self.effective_from()
            && self.effective_to().is_none_or(|end| at < end)
            && !price.value().is_zero()
            && !quantity.value().is_zero()
            && only_remainder(price.value(), self.price_tick())?.is_zero()
            && only_remainder(quantity.value(), self.quantity_step())?.is_zero()
            && [
                (price.value(), self.minimum_price(), self.maximum_price()),
                (
                    quantity.value(),
                    self.minimum_quantity(),
                    self.maximum_quantity(),
                ),
                (&notional, self.minimum_notional(), self.maximum_notional()),
            ]
            .into_iter()
            .all(|(n, lo, hi)| {
                !n.is_negative()
                    && lo.as_ref().is_none_or(|v| n >= v)
                    && hi.as_ref().is_none_or(|v| n <= v)
            }))
    }
}
