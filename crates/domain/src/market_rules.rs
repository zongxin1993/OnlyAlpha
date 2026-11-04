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
