use crate::*;
use onlyalpha_domain::{
    calendar::{OnlySessionProfile, OnlyTradingCalendar},
    identifiers::OnlyInstrumentId,
    market_rules::{OnlyLotSizeRule, OnlyPriceLimitRule, OnlyTickScheme},
    numeric::{
        OnlyRoundingMode, only_add, only_divide, only_multiply, only_quantize_with_rounding,
        only_subtract,
    },
    value::OnlyPrice,
};

#[derive(Clone, Debug)]
pub struct PolicyCompiler {
    version: String,
    record: Value,
}
impl PolicyCompiler {
    pub fn new(version: &str) -> Result<Self, Error> {
        if !matches!(version, "2025.1" | "2026.07") {
            return Err(bad("UNSUPPORTED_MARKET_PRODUCT_VERSION"));
        }
        Ok(Self {
            version: version.into(),
            record: json!({"schema_version":1,"kind":"CN_A_SHARE_POLICY_COMPILER",
            "product_version":version,"timezone":"Asia/Shanghai","source":"ADR0056/FROZEN_PROFILE","session":sessions(version)?.to_record(),
            "price_limits":{"main_normal":"0.1","main_risk_warning":if version=="2025.1"{"0.05"}else{"0.1"},"star_chinext":"0.2"},
            "settlement":settlement_policy(),"position_mode":"NETTING","short_selling":"DISABLED"}),
        })
    }
    pub fn record(&self) -> Value {
        self.record.clone()
    }
    pub fn fingerprint(&self) -> String {
        digest(&self.record)
    }
    pub fn compile(
        &self,
        authority: &ReferenceAuthority,
        instrument: &OnlyInstrumentId,
        trading_day: OnlyTradingDay,
    ) -> Result<CompiledPolicy, Error> {
        let date = day_text(trading_day);
        if (self.version == "2025.1" && !("2025-01-01".."2026-07-06").contains(&date.as_str()))
            || (self.version == "2026.07" && date.as_str() < "2026-07-06")
        {
            return Err(bad("MARKET_PRODUCT_VERSION_NOT_EFFECTIVE"));
        }
        let reference = authority.resolve(instrument, trading_day)?;
        let raw = reference.record();
        let board = text(&raw["board"], "REFERENCE_BOARD_UNSUPPORTED")?;
        let star = board == "STAR";
        let growth = star || board == "CHINEXT";
        let rate_text = if growth {
            "0.2"
        } else if self.version == "2025.1" && raw["st_status"] == true {
            "0.05"
        } else {
            "0.1"
        };
        let rate: OnlyDecimal = boundary(rate_text.parse())?;
        let (close, _) = decimal(&raw["previous_close"], "REFERENCE_PREVIOUS_CLOSE_INVALID")?;
        let (tick, _) = decimal(&raw["price_tick"], "REFERENCE_PRICE_TICK_INVALID")?;
        let one: OnlyDecimal = boundary("1".parse())?;
        let mut upper = to_tick(
            &boundary(only_multiply(&close, &boundary(only_add(&one, &rate))?))?,
            &tick,
        )?;
        let mut lower = to_tick(
            &boundary(only_multiply(
                &close,
                &boundary(only_subtract(&one, &rate))?,
            ))?,
            &tick,
        )?;
        if boundary(only_subtract(&upper, &close))? < tick {
            upper = boundary(only_add(&close, &tick))?;
        }
        if boundary(only_subtract(&close, &lower))? < tick {
            lower = boundary(only_subtract(&close, &tick))?;
        }
        if lower.is_negative() {
            return Err(bad("REFERENCE_PRICE_BAND_INVALID"));
        }
        let precision = u8::try_from(tick.fractional_precision())
            .map_err(|_| bad("REFERENCE_PRICE_TICK_INVALID"))?;
        let prices = boundary(OnlyPriceLimitRule::from_record(&json!({"schema_version":1,
            "lower":boundary(OnlyPrice::new(lower,precision))?.to_record(),"upper":boundary(OnlyPrice::new(upper,precision))?.to_record()})))?;
        let lots = boundary(OnlyLotSizeRule::from_record(
            &json!({"schema_version":1,"buy_increment":if star{"1"}else{"100"},"sell_increment":"1"}),
        ))?;
        let ticks = boundary(OnlyTickScheme::from_record(
            &json!({"schema_version":1,"ladder":{"schema_version":1,"steps":[[null,raw["price_tick"]]]}}),
        ))?;
        let sessions = sessions(&self.version)?;
        let record = json!({"schema_version":1,"product_id":PRODUCT_ID,"product_version":self.version,
            "instrument_id":instrument.to_string(),"trading_day":date,"reference_fingerprint":reference.fingerprint(),
            "compiler_fingerprint":self.fingerprint(),"currency":"CNY","contract_multiplier":"1",
            "session_timezone":"Asia/Shanghai","status":if raw["suspended"]==true{"SUSPENDED"}else{"TRADABLE"},"session":sessions.to_record(),
            "price_policy":{"previous_close":raw["previous_close"],"daily_limit_rate":rate.to_string(),"tick":raw["price_tick"],
                "rounding":"HALF_UP_TO_TICK","limits":prices.to_record(),"tick_scheme":ticks.to_record()},
            "quantity_policy":{"minimum_buy_quantity":if star{"200"}else{"100"},"buy_quantity_increment":if star{"1"}else{"100"},
                "sell_quantity_increment":"1","round_lot_size":raw["lot_size"],"odd_lot_liquidation_allowed":true,
                "odd_lot_requires_all_unreserved_available":true,"lot_rule":lots.to_record()},
            "position_policy":{"allow_flip":false,"mode":"NETTING","short_selling":"DISABLED"},
            "dynamic_price_cage":{"status":"NOT_EVALUATED","reason":"REALTIME_QUOTE_AUTHORITY_UNAVAILABLE"},
            "settlement_policy":settlement_policy()});
        Ok(CompiledPolicy {
            record,
            prices,
            lots,
            ticks,
            sessions,
            trading_day,
            venue: instrument.venue().to_string(),
        })
    }
}
fn to_tick(value: &OnlyDecimal, tick: &OnlyDecimal) -> Result<OnlyDecimal, Error> {
    let units = boundary(only_divide(value, tick))?;
    // Do not turn a non-terminating division approximation into a market bound.
    // Ordinary A-share decimal ticks are exact; otherwise fail closed.
    if boundary(only_multiply(&units, tick))? != *value {
        return Err(bad("PRICE_TICK_DIVISION_INEXACT"));
    }
    let whole = boundary(only_quantize_with_rounding(
        &units,
        &boundary("1".parse())?,
        OnlyRoundingMode::HalfUp,
    ))?;
    boundary(only_multiply(&whole, tick))
}
fn sessions(version: &str) -> Result<OnlySessionProfile, Error> {
    let entries = [
        (
            "opening_auction",
            "09:15:00",
            "09:25:00",
            "OPEN_AUCTION",
            false,
        ),
        ("pre_open", "09:25:00", "09:30:00", "PRE_OPEN", false),
        ("morning", "09:30:00", "11:30:00", "CONTINUOUS", true),
        (
            "midday_break",
            "11:30:00",
            "13:00:00",
            "MIDDAY_BREAK",
            false,
        ),
        ("afternoon", "13:00:00", "14:57:00", "CONTINUOUS", true),
        (
            "closing_auction",
            "14:57:00",
            "15:00:00",
            "CLOSING_AUCTION",
            false,
        ),
    ];
    boundary(OnlySessionProfile::from_record(
        &json!({"schema_version":1,"profile_id":{"schema_version":1,"value":format!("CN_A_SHARE_DAY@{version}")},
        "sessions":entries.iter().map(|(name,opens,closes,kind,orders)|json!({"schema_version":1,"name":name,
            "opens_at":opens,"closes_at":closes,"session_type":kind,"belongs_to_trading_day_offset":0,"allows_orders":orders,"allows_market_data":true})).collect::<Vec<_>>()}),
    ))
}
fn settlement_policy() -> Value {
    json!({"id":"CN_A_SHARE_T1","version":"1","asset_booked":0,"asset_trade_available":1,
        "cash_booked":0,"cash_trade_available":0,"cash_withdrawable":1,"legal_settled":1})
}
#[derive(Clone, Debug)]
pub struct CompiledPolicy {
    record: Value,
    prices: OnlyPriceLimitRule,
    lots: OnlyLotSizeRule,
    ticks: OnlyTickScheme,
    sessions: OnlySessionProfile,
    trading_day: OnlyTradingDay,
    venue: String,
}
impl CompiledPolicy {
    pub fn record(&self) -> Value {
        self.record.clone()
    }
    pub fn fingerprint(&self) -> String {
        digest(&self.record)
    }
    pub fn price_limits(&self) -> &OnlyPriceLimitRule {
        &self.prices
    }
    pub fn lot_rule(&self) -> &OnlyLotSizeRule {
        &self.lots
    }
    pub fn tick_scheme(&self) -> &OnlyTickScheme {
        &self.ticks
    }
    pub fn sessions(&self) -> &OnlySessionProfile {
        &self.sessions
    }
    /// Resolve dates only against the caller's actual immutable calendar.
    /// No synthetic holiday or venue calendar is installed by the factory.
    pub fn settlement_schedule(&self, calendar: &OnlyTradingCalendar) -> Result<Value, Error> {
        if calendar.venue_id().to_string() != self.venue
            || calendar.timezone().name() != "Asia/Shanghai"
        {
            return Err(bad("SETTLEMENT_CALENDAR_SCOPE"));
        }
        boundary(onlyalpha_settlement::resolve_schedule(
            &calendar.to_record(),
            &self.record["settlement_policy"],
            &day_text(self.trading_day),
        ))
    }
}
