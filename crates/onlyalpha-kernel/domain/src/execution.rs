//! Immutable execution inputs and snapshots. The Order component owns state transitions.
use crate::{
    base::{domain_model, invalid, whitespace},
    enums::{
        OnlyLiquiditySide, OnlyOffset, OnlyOrderSide, OnlyOrderStatus, OnlyOrderType,
        OnlyTimeInForce,
    },
    errors::OnlyDomainError,
    fee::{OnlyOrderFeeEstimate, OnlyOrderFeePolicyBinding, OnlyOrderFundingPlan},
    identifiers::{
        OnlyAccountId, OnlyClientOrderId, OnlyClusterId, OnlyInstrumentId, OnlyOrderId,
        OnlyOrderRequestId, OnlyRuntimeId, OnlyTradeId, OnlyVenueOrderId, OnlyVenueTradeId,
    },
    numeric::{OnlyDecimal, only_add},
    time::{OnlyTimestamp, OnlyUtcDateTime},
    trading::OnlyExecutionIntent,
    value::{OnlyMoney, OnlyPrice, OnlyQuantity},
};
use bigdecimal::num_bigint::BigInt;
use std::collections::BTreeMap;

domain_model!(OnlyOrderRequest,OnlyOrderRequestInput,1,None,{
 request_id:OnlyOrderRequestId,instrument_id:OnlyInstrumentId,side:OnlyOrderSide,order_type:OnlyOrderType,quantity:OnlyQuantity,time_in_force:OnlyTimeInForce,account_id:Option<OnlyAccountId>,offset:OnlyOffset,price:Option<OnlyPrice>,stop_price:Option<OnlyPrice>,expire_time:Option<OnlyTimestamp>,tags:Vec<String>,metadata:BTreeMap<String,String>,execution_intent:Option<OnlyExecutionIntent>,
},prepare=OnlyOrderRequest::prepare_fields);
fn normalize_intent(
    intent: Option<OnlyExecutionIntent>,
    side: OnlyOrderSide,
    offset: OnlyOffset,
) -> Result<OnlyExecutionIntent, OnlyDomainError> {
    let intent = match intent {
        Some(intent) => intent,
        None => OnlyExecutionIntent::from_offset(side, offset, None)?,
    };
    if intent.side() != side {
        return Err(invalid(
            "order side conflicts with canonical execution intent",
        ));
    }
    Ok(intent)
}
impl OnlyOrderRequest {
    fn prepare_fields(
        mut fields: OnlyOrderRequestInput,
    ) -> Result<OnlyOrderRequestInput, OnlyDomainError> {
        fields.execution_intent = Some(normalize_intent(
            fields.execution_intent,
            fields.side,
            fields.offset,
        )?);
        Ok(fields)
    }
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if self.quantity().value().is_zero() {
            return Err(invalid("order quantity must be positive"));
        }
        match self.order_type() {
            OnlyOrderType::Limit => {
                if self
                    .price()
                    .as_ref()
                    .is_none_or(|price| price.value().is_zero() || price.value().is_negative())
                {
                    return Err(invalid("LIMIT order requires a positive price"));
                }
            }
            OnlyOrderType::Market => {
                if self.price().is_some() {
                    return Err(invalid("MARKET order cannot contain a price"));
                }
            }
            _ => return Err(invalid("unsupported first-phase order type")),
        }
        if self.stop_price().is_some() {
            return Err(invalid(
                "stop orders are not implemented in the first Order phase",
            ));
        }
        if *self.time_in_force() == OnlyTimeInForce::Gtd && self.expire_time().is_none() {
            return Err(invalid("GTD order requires expire_time"));
        }
        Ok(())
    }
    pub fn limit_price(&self) -> &Option<OnlyPrice> {
        self.price()
    }
}
domain_model!(OnlyCancelOrderRequest,OnlyCancelOrderRequestInput,1,None,{request_id:OnlyOrderRequestId,order_id:OnlyOrderId,reason:String,metadata:BTreeMap<String,String>},prepare=OnlyCancelOrderRequest::prepare_fields);
impl OnlyCancelOrderRequest {
    fn prepare_fields(
        mut fields: OnlyCancelOrderRequestInput,
    ) -> Result<OnlyCancelOrderRequestInput, OnlyDomainError> {
        fields.reason = fields.reason.trim_matches(whitespace).into();
        Ok(fields)
    }
    fn validate(&self) -> Result<(), OnlyDomainError> {
        Ok(())
    }
}
domain_model!(OnlyOrderRejection,OnlyOrderRejectionInput,1,None,{code:String,message:String});
impl OnlyOrderRejection {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        Ok(())
    }
}
domain_model!(OnlyOrderFailure,OnlyOrderFailureInput,1,None,{code:String,message:String});
impl OnlyOrderFailure {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        Ok(())
    }
}
domain_model!(OnlyOrderRef,OnlyOrderRefInput,1,None,{runtime_id:OnlyRuntimeId,order_id:OnlyOrderId});
impl OnlyOrderRef {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        Ok(())
    }
}
domain_model!(OnlyOrderFill,OnlyOrderFillInput,1,None,{
 trade_id:OnlyTradeId,order_id:OnlyOrderId,price:OnlyPrice,quantity:OnlyQuantity,ts_event:OnlyTimestamp,ts_init:OnlyTimestamp,venue_trade_id:Option<OnlyVenueTradeId>,venue_order_id:Option<OnlyVenueOrderId>,liquidity_side:OnlyLiquiditySide,external_sequence:Option<BigInt>,external_event_id:Option<String>,metadata:BTreeMap<String,String>,reference_price:Option<OnlyPrice>,
});
impl OnlyOrderFill {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if self.quantity().value().is_zero()
            || self.price().value().is_zero()
            || self.price().value().is_negative()
        {
            return Err(invalid("fill quantity and price must be positive"));
        }
        if self.ts_init() < self.ts_event()
            || self
                .external_sequence()
                .as_ref()
                .is_some_and(|sequence| sequence < &BigInt::from(0))
        {
            return Err(invalid("fill time or external sequence is invalid"));
        }
        Ok(())
    }
}
domain_model!(OnlyOrderSnapshot,OnlyOrderSnapshotInput,4,None,{
 order_id:OnlyOrderId,request_id:OnlyOrderRequestId,client_order_id:OnlyClientOrderId,venue_order_id:Option<OnlyVenueOrderId>,runtime_id:OnlyRuntimeId,cluster_id:OnlyClusterId,account_id:OnlyAccountId,instrument_id:OnlyInstrumentId,side:OnlyOrderSide,offset:OnlyOffset,order_type:OnlyOrderType,time_in_force:OnlyTimeInForce,quantity:OnlyQuantity,price:Option<OnlyPrice>,stop_price:Option<OnlyPrice>,expire_time:Option<OnlyTimestamp>,status:OnlyOrderStatus,filled_quantity:OnlyQuantity,remaining_quantity:OnlyQuantity,average_fill_price:Option<OnlyPrice>,created_at:OnlyTimestamp,updated_at:OnlyTimestamp,submitted_at:Option<OnlyTimestamp>,accepted_at:Option<OnlyTimestamp>,cancel_requested_at:Option<OnlyTimestamp>,cancelled_at:Option<OnlyTimestamp>,filled_at:Option<OnlyTimestamp>,rejected_at:Option<OnlyTimestamp>,expired_at:Option<OnlyTimestamp>,failed_at:Option<OnlyTimestamp>,version:BigInt,last_external_sequence:Option<BigInt>,rejection:Option<OnlyOrderRejection>,failure:Option<OnlyOrderFailure>,tags:Vec<String>,metadata:BTreeMap<String,String>,fill_count:BigInt,cumulative_price_quantity:OnlyDecimal,last_trade_id:Option<OnlyTradeId>,historical_fill_identity_missing:bool,fee_policy_binding:Option<OnlyOrderFeePolicyBinding>,fee_estimate:Option<OnlyOrderFeeEstimate>,funding_plan:Option<OnlyOrderFundingPlan>,execution_intent:Option<OnlyExecutionIntent>,
},prepare=OnlyOrderSnapshot::prepare_fields);
impl OnlyOrderSnapshot {
    fn prepare_fields(
        mut fields: OnlyOrderSnapshotInput,
    ) -> Result<OnlyOrderSnapshotInput, OnlyDomainError> {
        fields.execution_intent = Some(normalize_intent(
            fields.execution_intent,
            fields.side,
            fields.offset,
        )?);
        Ok(fields)
    }
    fn validate(&self) -> Result<(), OnlyDomainError> {
        let f = &self.fields;
        if f.quantity.value().is_zero() {
            return Err(invalid("order snapshot quantity must be positive"));
        }
        if f.version < BigInt::from(1) {
            return Err(invalid("order snapshot version must be positive"));
        }
        if *f.quantity.value() != only_add(f.filled_quantity.value(), f.remaining_quantity.value())?
        {
            return Err(invalid("order quantity authority is not conserved"));
        }
        if f.fill_count < BigInt::from(0) {
            return Err(invalid("fill_count cannot be negative"));
        }
        if f.filled_quantity.value().is_zero() && f.fill_count != BigInt::from(0) {
            return Err(invalid("unfilled order cannot have fills"));
        }
        if !f.filled_quantity.value().is_zero()
            && (f.fill_count == BigInt::from(0)
                || f.average_fill_price.is_none()
                || f.cumulative_price_quantity.is_zero()
                || f.cumulative_price_quantity.is_negative())
        {
            return Err(invalid(
                "filled quantity requires complete cumulative fill authority",
            ));
        }
        if f.fill_count == BigInt::from(0)
            && (f.average_fill_price.is_some() || !f.cumulative_price_quantity.is_zero())
        {
            return Err(invalid("zero fills require empty price authority"));
        }
        if f.status == OnlyOrderStatus::PartiallyFilled
            && (f.filled_quantity.value().is_zero()
                || f.filled_quantity.value() >= f.quantity.value())
        {
            return Err(invalid(
                "PARTIALLY_FILLED order requires a partial quantity",
            ));
        }
        if f.status == OnlyOrderStatus::Filled
            && (f.filled_quantity != f.quantity
                || !f.remaining_quantity.value().is_zero()
                || f.filled_at.is_none())
        {
            return Err(invalid(
                "FILLED order requires complete quantity and filled_at",
            ));
        }
        if f.historical_fill_identity_missing {
            if f.last_trade_id.is_some()
                || f.fill_count != BigInt::from(1)
                || f.status != OnlyOrderStatus::Filled
            {
                return Err(invalid(
                    "historical missing fill identity requires one completed whole fill",
                ));
            }
        } else if f.last_trade_id.is_none() != (f.fill_count == BigInt::from(0)) {
            return Err(invalid("last_trade_id presence must agree with fill_count"));
        }
        let contracts = [
            f.fee_policy_binding.is_some(),
            f.fee_estimate.is_some(),
            f.funding_plan.is_some(),
        ];
        if contracts.iter().any(|value| *value) && contracts.iter().any(|value| !*value) {
            return Err(invalid("Order fee contract must be installed atomically"));
        }
        if let (Some(binding), Some(estimate), Some(funding)) =
            (&f.fee_policy_binding, &f.fee_estimate, &f.funding_plan)
        {
            if binding.runtime_id() != &f.runtime_id
                || binding.account_id() != &f.account_id
                || binding.cluster_id() != &f.cluster_id
                || binding.order_id() != &f.order_id
                || binding.instrument_id() != &f.instrument_id
                || funding.order_id() != &f.order_id
            {
                return Err(invalid("Order fee contract scope mismatch"));
            }
            if estimate.expected().binding() != binding
                || funding.binding_fingerprint() != binding.fingerprint()
                || funding.estimate_fingerprint() != estimate.assumptions_fingerprint()
            {
                return Err(invalid(
                    "Order fee artifacts do not match the installed binding",
                ));
            }
        }
        Ok(())
    }
}
domain_model!(OnlyTrade,OnlyTradeInput,1,None,{
 trade_id:OnlyTradeId,order_id:OnlyOrderId,account_id:OnlyAccountId,instrument_id:OnlyInstrumentId,side:OnlyOrderSide,offset:OnlyOffset,price:OnlyPrice,quantity:OnlyQuantity,commission:OnlyMoney,liquidity_side:OnlyLiquiditySide,executed_at:OnlyUtcDateTime,initialized_at:Option<OnlyUtcDateTime>,
});
impl OnlyTrade {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if self
            .initialized_at()
            .is_some_and(|init| init < *self.executed_at())
        {
            return Err(invalid("trade initialized_at cannot precede executed_at"));
        }
        if self.quantity().value().is_zero()
            || (self.commission().amount().is_negative() && !self.commission().amount().is_zero())
        {
            return Err(invalid("trade quantity or commission is invalid"));
        }
        Ok(())
    }
    pub fn fee(&self) -> &OnlyMoney {
        self.commission()
    }
    pub fn ts_event(&self) -> OnlyUtcDateTime {
        *self.executed_at()
    }
    pub fn ts_init(&self) -> OnlyUtcDateTime {
        self.initialized_at().unwrap_or(*self.executed_at())
    }
}
