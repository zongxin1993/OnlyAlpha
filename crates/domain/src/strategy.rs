//! 策略边界的规范化事实：绑定因子、只读账户视图与下单意图。
//! 这里只表达经济含义与身份，不携带执行、风控、券商或账户权威。
use crate::{
    base::invalid,
    enums::{OnlyOrderSide, OnlyOrderType, OnlyTimeInForce},
    errors::OnlyDomainError,
    identifiers::OnlyInstrumentId,
    numeric::OnlyDecimal,
    time::OnlyTimestamp,
};

/// 策略在当前事件上读到的已绑定因子值；`None` 表示该点缺失，不当作零。
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NamedFactor {
    name: String,
    value: Option<OnlyDecimal>,
}

impl NamedFactor {
    pub fn new(name: &str, value: Option<OnlyDecimal>) -> Result<Self, OnlyDomainError> {
        if name.is_empty() || name.chars().count() > 128 {
            return Err(invalid("factor name requires 1..128 characters"));
        }
        Ok(Self {
            name: name.to_owned(),
            value,
        })
    }

    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn value(&self) -> Option<&OnlyDecimal> {
        self.value.as_ref()
    }
}

/// 单只标的的只读持仓视图。数量按持有方向非负记账，方向由账户模型负责。
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReadonlyPosition {
    instrument: OnlyInstrumentId,
    quantity: OnlyDecimal,
    average_cost: Option<OnlyDecimal>,
}

impl ReadonlyPosition {
    pub fn new(
        instrument: OnlyInstrumentId,
        quantity: OnlyDecimal,
        average_cost: Option<OnlyDecimal>,
    ) -> Result<Self, OnlyDomainError> {
        if quantity.is_negative() {
            return Err(invalid("readonly position quantity cannot be negative"));
        }
        if average_cost.as_ref().is_some_and(|cost| cost.is_negative()) {
            return Err(invalid("readonly average cost cannot be negative"));
        }
        Ok(Self {
            instrument,
            quantity,
            average_cost,
        })
    }

    pub fn instrument(&self) -> &OnlyInstrumentId {
        &self.instrument
    }

    pub fn quantity(&self) -> &OnlyDecimal {
        &self.quantity
    }

    pub fn average_cost(&self) -> Option<&OnlyDecimal> {
        self.average_cost.as_ref()
    }
}

/// 策略可见的只读账户快照：说明当前状态，不授予任何操作权限。
/// 持仓按 `SYMBOL.VENUE` 排序且每只标的至多一条，保证同一快照的遍历顺序确定。
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReadonlyAccountState {
    timestamp: OnlyTimestamp,
    cash_available: OnlyDecimal,
    total_equity: OnlyDecimal,
    positions: Vec<ReadonlyPosition>,
}

impl ReadonlyAccountState {
    pub fn new(
        timestamp: OnlyTimestamp,
        cash_available: OnlyDecimal,
        total_equity: OnlyDecimal,
        mut positions: Vec<ReadonlyPosition>,
    ) -> Result<Self, OnlyDomainError> {
        positions.sort_by(|left, right| {
            left.instrument
                .to_string()
                .cmp(&right.instrument.to_string())
        });
        if positions
            .windows(2)
            .any(|pair| pair[0].instrument == pair[1].instrument)
        {
            return Err(invalid("readonly positions must be unique per instrument"));
        }
        Ok(Self {
            timestamp,
            cash_available,
            total_equity,
            positions,
        })
    }

    pub fn timestamp(&self) -> &OnlyTimestamp {
        &self.timestamp
    }

    pub fn cash_available(&self) -> &OnlyDecimal {
        &self.cash_available
    }

    pub fn total_equity(&self) -> &OnlyDecimal {
        &self.total_equity
    }

    pub fn positions(&self) -> &[ReadonlyPosition] {
        &self.positions
    }
}

/// 规范化下单意图：策略唯一被允许产出的操作，尚未经过风控、准入或执行。
///
/// 数量必须为正；限价类订单必须携带正限价，市价类订单不得携带限价；
/// 每条意图都必须写明理由码，便于审计归因。
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OrderIntent {
    instrument: OnlyInstrumentId,
    side: OnlyOrderSide,
    order_type: OnlyOrderType,
    quantity: OnlyDecimal,
    limit_price: Option<OnlyDecimal>,
    time_in_force: OnlyTimeInForce,
    reason_code: String,
}

impl OrderIntent {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        instrument: OnlyInstrumentId,
        side: OnlyOrderSide,
        order_type: OnlyOrderType,
        quantity: OnlyDecimal,
        limit_price: Option<OnlyDecimal>,
        time_in_force: OnlyTimeInForce,
        reason_code: &str,
    ) -> Result<Self, OnlyDomainError> {
        if quantity.is_negative() || quantity.is_zero() {
            return Err(invalid("order intent quantity must be positive"));
        }
        if reason_code.trim().is_empty() || reason_code.chars().count() > 128 {
            return Err(invalid(
                "order intent requires a reason code of 1..128 characters",
            ));
        }
        let priced = matches!(
            order_type,
            OnlyOrderType::Limit
                | OnlyOrderType::StopLimit
                | OnlyOrderType::LimitIfTouched
                | OnlyOrderType::TrailingStopLimit
        );
        match (&limit_price, priced) {
            (Some(price), true) => {
                if price.is_negative() || price.is_zero() {
                    return Err(invalid("order intent limit price must be positive"));
                }
            }
            (Some(_), false) => {
                return Err(invalid("order intent type does not accept a limit price"));
            }
            (None, true) => {
                return Err(invalid("order intent type requires a limit price"));
            }
            (None, false) => {}
        }
        Ok(Self {
            instrument,
            side,
            order_type,
            quantity,
            limit_price,
            time_in_force,
            reason_code: reason_code.to_owned(),
        })
    }

    pub fn instrument(&self) -> &OnlyInstrumentId {
        &self.instrument
    }

    pub const fn side(&self) -> OnlyOrderSide {
        self.side
    }

    pub const fn order_type(&self) -> OnlyOrderType {
        self.order_type
    }

    pub fn quantity(&self) -> &OnlyDecimal {
        &self.quantity
    }

    pub fn limit_price(&self) -> Option<&OnlyDecimal> {
        self.limit_price.as_ref()
    }

    pub const fn time_in_force(&self) -> OnlyTimeInForce {
        self.time_in_force
    }

    pub fn reason_code(&self) -> &str {
        &self.reason_code
    }
}
