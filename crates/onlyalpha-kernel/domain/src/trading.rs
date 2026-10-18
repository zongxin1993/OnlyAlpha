//! Orthogonal, normalized economic intent; no broker or execution authority.
use crate::enums::domain_enum;
use crate::{
    base::{OnlyDomainModel, invalid, record, text},
    enums::{OnlyOffset, OnlyOrderSide},
    errors::OnlyDomainError,
};
use serde_json::{Value, json};
use std::str::FromStr;
domain_enum! {OnlyPositionSide {Long=>"LONG",Short=>"SHORT",Flat=>"FLAT"}}
domain_enum! {OnlyPositionMode {Netting=>"NETTING",Hedging=>"HEDGING"}}
domain_enum! {OnlyPositionEffect {Open=>"OPEN",Close=>"CLOSE",Auto=>"AUTO",CloseToday=>"CLOSE_TODAY",CloseYesterday=>"CLOSE_YESTERDAY",ReduceOnly=>"REDUCE_ONLY"}}
domain_enum! {OnlyCloseScope {Any=>"ANY",Today=>"TODAY",Yesterday=>"YESTERDAY"}}
domain_enum! {OnlyExposureConstraint {None=>"NONE",ReduceOnly=>"REDUCE_ONLY"}}
domain_enum! {OnlyTargetExposure {Long=>"LONG",Flat=>"FLAT",Short=>"SHORT"}}
domain_enum! {OnlyReferencePriceKind {Trade=>"TRADE",Mark=>"MARK",Index=>"INDEX",Settlement=>"SETTLEMENT"}}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct OnlyExecutionIntent {
    side: OnlyOrderSide,
    position_side: OnlyPositionSide,
    position_effect: OnlyPositionEffect,
    close_scope: OnlyCloseScope,
    exposure_constraint: OnlyExposureConstraint,
    position_mode: OnlyPositionMode,
}
impl OnlyExecutionIntent {
    pub fn new(
        side: OnlyOrderSide,
        position_side: OnlyPositionSide,
        position_effect: OnlyPositionEffect,
        close_scope: OnlyCloseScope,
        exposure_constraint: OnlyExposureConstraint,
        position_mode: OnlyPositionMode,
    ) -> Result<Self, OnlyDomainError> {
        if position_side == OnlyPositionSide::Flat {
            return Err(invalid("EXECUTION_INTENT_POSITION_SIDE_REQUIRED"));
        }
        if !matches!(
            position_effect,
            OnlyPositionEffect::Open | OnlyPositionEffect::Close
        ) {
            return Err(invalid("EXECUTION_INTENT_EFFECT_NOT_NORMALIZED"));
        }
        let buy = (position_side == OnlyPositionSide::Long)
            == (position_effect == OnlyPositionEffect::Open);
        if (side == OnlyOrderSide::Buy) != buy {
            return Err(invalid("EXECUTION_INTENT_SIDE_EFFECT_CONFLICT"));
        }
        if position_effect == OnlyPositionEffect::Open {
            if close_scope != OnlyCloseScope::Any {
                return Err(invalid("EXECUTION_INTENT_OPEN_CLOSE_SCOPE_CONFLICT"));
            }
            if exposure_constraint == OnlyExposureConstraint::ReduceOnly {
                return Err(invalid("EXECUTION_INTENT_REDUCE_ONLY_OPEN_CONFLICT"));
            }
        }
        Ok(Self {
            side,
            position_side,
            position_effect,
            close_scope,
            exposure_constraint,
            position_mode,
        })
    }
    pub fn from_offset(
        side: OnlyOrderSide,
        offset: OnlyOffset,
        position_side: Option<OnlyPositionSide>,
    ) -> Result<Self, OnlyDomainError> {
        let opening = offset == OnlyOffset::Open
            || (offset == OnlyOffset::None && side == OnlyOrderSide::Buy);
        let resolved = position_side.unwrap_or(
            if offset == OnlyOffset::None || (side == OnlyOrderSide::Buy) == opening {
                OnlyPositionSide::Long
            } else {
                OnlyPositionSide::Short
            },
        );
        Self::new(
            side,
            resolved,
            if opening {
                OnlyPositionEffect::Open
            } else {
                OnlyPositionEffect::Close
            },
            match offset {
                OnlyOffset::CloseToday => OnlyCloseScope::Today,
                OnlyOffset::CloseYesterday => OnlyCloseScope::Yesterday,
                _ => OnlyCloseScope::Any,
            },
            OnlyExposureConstraint::None,
            OnlyPositionMode::Netting,
        )
    }
    pub const fn side(&self) -> OnlyOrderSide {
        self.side
    }
    pub const fn position_side(&self) -> OnlyPositionSide {
        self.position_side
    }
    pub const fn position_effect(&self) -> OnlyPositionEffect {
        self.position_effect
    }
    pub const fn close_scope(&self) -> OnlyCloseScope {
        self.close_scope
    }
    pub const fn exposure_constraint(&self) -> OnlyExposureConstraint {
        self.exposure_constraint
    }
    pub const fn position_mode(&self) -> OnlyPositionMode {
        self.position_mode
    }
    pub fn reduces_exposure(&self) -> bool {
        self.position_effect == OnlyPositionEffect::Close
    }
}
impl OnlyDomainModel for OnlyExecutionIntent {
    fn to_record(&self) -> Value {
        json!({"schema_version":2,"side":self.side.as_str(),"position_side":self.position_side.as_str(),"position_effect":self.position_effect.as_str(),"close_scope":self.close_scope.as_str(),"exposure_constraint":self.exposure_constraint.as_str(),"position_mode":self.position_mode.as_str()})
    }
    fn from_record(value: &Value) -> Result<Self, OnlyDomainError> {
        (|| {
            let row = record(
                value,
                2,
                &[
                    "side",
                    "position_side",
                    "position_effect",
                    "close_scope",
                    "exposure_constraint",
                    "position_mode",
                ],
            )?;
            Self::new(
                text(&row["side"], "side")?.parse()?,
                text(&row["position_side"], "position_side")?.parse()?,
                text(&row["position_effect"], "position_effect")?.parse()?,
                text(&row["close_scope"], "close_scope")?.parse()?,
                text(&row["exposure_constraint"], "exposure_constraint")?.parse()?,
                text(&row["position_mode"], "position_mode")?.parse()?,
            )
        })()
        .map_err(crate::value::serialization)
    }
}

crate::base::domain_field!(OnlyExecutionIntent);
