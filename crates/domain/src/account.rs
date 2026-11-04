//! Immutable account-domain values. No account state transitions or store authority.
use crate::{
    base::{domain_model, invalid},
    errors::OnlyDomainError,
    value::{OnlyCurrency, OnlyMoney},
};

domain_model!(OnlyBalance,OnlyBalanceInput,1,None,{
 currency:OnlyCurrency,
 total:OnlyMoney,
 available:OnlyMoney,
 locked:OnlyMoney,
});
impl OnlyBalance {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        for amount in [self.total(), self.available(), self.locked()] {
            if amount.currency() != self.currency() {
                return Err(OnlyDomainError::CurrencyMismatch(
                    "balance components must use balance currency".into(),
                ));
            }
            if amount.amount().is_negative() && !amount.amount().is_zero() {
                return Err(invalid("balance components cannot be negative"));
            }
        }
        if self.available().checked_add(self.locked())? != *self.total() {
            return Err(invalid("balance total must equal available plus locked"));
        }
        Ok(())
    }
}

use crate::{
    enums::{OnlyMarginMode, OnlyPositionDirection},
    identifiers::{OnlyAccountId, OnlyInstrumentId, OnlyPositionId, OnlyTradeId},
    numeric::only_add,
    time::OnlyUtcDateTime,
    value::{OnlyPrice, OnlyQuantity, OnlyRate},
};
use std::collections::HashSet;

domain_model!(OnlyFee,OnlyFeeInput,1,None,{amount:OnlyMoney,description:String});
domain_model!(OnlyCommission,OnlyCommissionInput,1,None,{amount:OnlyMoney});
domain_model!(OnlyMargin,OnlyMarginInput,1,None,{initial:OnlyMoney,maintenance:OnlyMoney});
domain_model!(OnlyPnL,OnlyPnLInput,1,None,{realized:OnlyMoney,unrealized:OnlyMoney});
domain_model!(OnlySlippage,OnlySlippageInput,1,None,{amount:OnlyMoney,rate:Option<OnlyRate>});
domain_model!(OnlyAccountEquity,OnlyAccountEquityInput,1,None,{total:OnlyMoney,available:OnlyMoney,locked:OnlyMoney,position_value:OnlyMoney,unrealized_pnl:OnlyMoney});
domain_model!(OnlyPosition,OnlyPositionInput,1,None,{
 position_id:OnlyPositionId,account_id:OnlyAccountId,instrument_id:OnlyInstrumentId,direction:OnlyPositionDirection,
 quantity:OnlyQuantity,available_quantity:OnlyQuantity,average_open_price:Option<OnlyPrice>,pnl:OnlyPnL,
 opened_at:Option<OnlyUtcDateTime>,updated_at:OnlyUtcDateTime,closed_at:Option<OnlyUtcDateTime>,trade_ids:Vec<OnlyTradeId>,
 frozen_quantity:Option<OnlyQuantity>,today_quantity:Option<OnlyQuantity>,yesterday_quantity:Option<OnlyQuantity>,
 settlement_currency:Option<OnlyCurrency>,margin_mode:Option<OnlyMarginMode>,
});
domain_model!(OnlyAccount,OnlyAccountInput,1,None,{
 account_id:OnlyAccountId,base_currency:Option<OnlyCurrency>,margin_mode:OnlyMarginMode,balances:Vec<OnlyBalance>,
 positions:Vec<OnlyPosition>,equity:Option<OnlyAccountEquity>,updated_at:OnlyUtcDateTime,
});
domain_model!(OnlyPortfolio,OnlyPortfolioInput,1,None,{
 accounts:Vec<OnlyAccount>,reporting_currency:Option<OnlyCurrency>,total_equity:Option<OnlyMoney>,as_of:OnlyUtcDateTime,
});
fn nonnegative(money: &OnlyMoney) -> Result<(), OnlyDomainError> {
    if money.amount().is_negative() && !money.amount().is_zero() {
        return Err(invalid("amount cannot be negative"));
    }
    Ok(())
}
fn same_currency(values: &[&OnlyMoney]) -> Result<(), OnlyDomainError> {
    if values
        .windows(2)
        .any(|pair| pair[0].currency() != pair[1].currency())
    {
        return Err(OnlyDomainError::CurrencyMismatch(
            "components require one currency".into(),
        ));
    }
    Ok(())
}
impl OnlyFee {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        nonnegative(self.amount())
    }
}
impl OnlyCommission {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        nonnegative(self.amount())
    }
}
impl OnlyMargin {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        same_currency(&[self.initial(), self.maintenance()])?;
        nonnegative(self.initial())?;
        nonnegative(self.maintenance())
    }
}
impl OnlyPnL {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        same_currency(&[self.realized(), self.unrealized()])
    }
    pub fn total(&self) -> Result<OnlyMoney, OnlyDomainError> {
        self.realized().checked_add(self.unrealized())
    }
}
impl OnlySlippage {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        Ok(())
    }
}
impl OnlyAccountEquity {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        same_currency(&[
            self.total(),
            self.available(),
            self.locked(),
            self.position_value(),
            self.unrealized_pnl(),
        ])
    }
}
impl OnlyPosition {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        let f = &self.fields;
        if f.quantity.precision() != f.available_quantity.precision()
            || f.available_quantity.value() > f.quantity.value()
        {
            return Err(invalid("position available quantity mismatch"));
        }
        if let Some(frozen) = &f.frozen_quantity
            && (frozen.precision() != f.quantity.precision()
                || only_add(f.available_quantity.value(), frozen.value())? > *f.quantity.value())
        {
            return Err(invalid("position frozen quantity mismatch"));
        }
        if let (Some(today), Some(yesterday)) = (&f.today_quantity, &f.yesterday_quantity)
            && only_add(today.value(), yesterday.value())? != *f.quantity.value()
        {
            return Err(invalid("today plus yesterday must equal position quantity"));
        }
        if f.direction == OnlyPositionDirection::Flat {
            if !f.quantity.value().is_zero() || f.average_open_price.is_some() {
                return Err(invalid(
                    "flat position requires zero quantity and no open price",
                ));
            }
        } else if f.quantity.value().is_zero() || f.average_open_price.is_none() {
            return Err(invalid("open position requires quantity and average price"));
        }
        if f.opened_at.is_some_and(|opened| f.updated_at < opened)
            || f.closed_at.is_some_and(|closed| closed < f.updated_at)
        {
            return Err(invalid("position timestamps are not ordered"));
        }
        Ok(())
    }
}
impl OnlyAccount {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        let f = &self.fields;
        let mut currencies = HashSet::new();
        let mut positions = HashSet::new();
        if f.balances
            .iter()
            .any(|balance| !currencies.insert(balance.currency()))
        {
            return Err(invalid("duplicate account balance currency"));
        }
        if f.positions.iter().any(|position| {
            position.account_id() != &f.account_id || !positions.insert(position.position_id())
        }) {
            return Err(invalid(
                "account positions require one owner and unique identity",
            ));
        }
        if let Some(equity) = &f.equity {
            let base = f
                .base_currency
                .as_ref()
                .ok_or_else(|| invalid("reported account equity requires base currency"))?;
            if equity.total().currency() != base {
                return Err(OnlyDomainError::CurrencyMismatch(
                    "account equity must use base currency".into(),
                ));
            }
        }
        Ok(())
    }
}
impl OnlyPortfolio {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        let mut accounts = HashSet::new();
        if self
            .accounts()
            .iter()
            .any(|account| !accounts.insert(account.account_id()))
        {
            return Err(invalid("duplicate portfolio account"));
        }
        if self
            .total_equity()
            .as_ref()
            .is_some_and(|total| self.reporting_currency().as_ref() != Some(total.currency()))
        {
            return Err(OnlyDomainError::CurrencyMismatch(
                "portfolio total requires reporting currency".into(),
            ));
        }
        Ok(())
    }
}

/// Pure settlement-currency formulas. Quanto always requires an external explicit model.
pub struct OnlyPnLCalculator;
impl OnlyPnLCalculator {
    pub fn unrealized(
        instrument: &crate::instrument::OnlyInstrument,
        direction: OnlyPositionDirection,
        quantity: &OnlyQuantity,
        entry_price: &OnlyPrice,
        current_price: &OnlyPrice,
    ) -> Result<OnlyMoney, OnlyDomainError> {
        use crate::{
            enums::OnlyContractType,
            instrument::OnlyInstrumentKind,
            numeric::{OnlyDecimal, only_divide, only_multiply, only_quantize, only_subtract},
        };
        let specification = instrument.specification();
        if direction == OnlyPositionDirection::Flat {
            if !quantity.value().is_zero() {
                return Err(invalid("flat PnL requires zero quantity"));
            }
            let quantum =
                format!("1E-{}", specification.settlement_currency().precision()).parse()?;
            return OnlyMoney::new(
                only_quantize(&"0".parse()?, &quantum)?,
                specification.settlement_currency().clone(),
            );
        }
        let sign: OnlyDecimal = if direction == OnlyPositionDirection::Long {
            "1"
        } else {
            "-1"
        }
        .parse()?;
        let contract = match instrument.kind() {
            OnlyInstrumentKind::Future(terms) | OnlyInstrumentKind::CryptoFuture(terms) => {
                terms.contract_type
            }
            OnlyInstrumentKind::CryptoPerpetual(contract) => *contract,
            _ => OnlyContractType::Linear,
        };
        let difference = match contract {
            OnlyContractType::Inverse => {
                let one = "1".parse()?;
                only_subtract(
                    &only_divide(&one, entry_price.value())?,
                    &only_divide(&one, current_price.value())?,
                )?
            }
            OnlyContractType::Quanto => {
                return Err(invalid("quanto PnL requires an explicit conversion model"));
            }
            OnlyContractType::Linear => {
                if specification.quote_currency() != specification.settlement_currency() {
                    return Err(invalid(
                        "linear cross-currency PnL requires an explicit conversion model",
                    ));
                }
                only_subtract(current_price.value(), entry_price.value())?
            }
        };
        let amount = only_multiply(
            &only_multiply(
                &only_multiply(&sign, quantity.value())?,
                specification.contract_multiplier().value(),
            )?,
            &difference,
        )?;
        let quantum = format!("1E-{}", specification.settlement_currency().precision()).parse()?;
        OnlyMoney::new(
            only_quantize(&amount, &quantum)?,
            specification.settlement_currency().clone(),
        )
    }
}
