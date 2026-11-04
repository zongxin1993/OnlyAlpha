//! Exact Domain enum vocabulary corresponding to Python domain/enums.py.
use crate::errors::OnlyDomainError;
use std::str::FromStr;

macro_rules! domain_enum {
    ($name:ident { $($variant:ident => $text:literal),+ $(,)? }) => {
        #[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
        pub enum $name { $($variant),+ }
        impl $name {
            pub const fn as_str(self) -> &'static str {
                match self { $(Self::$variant => $text),+ }
            }
        }
        impl $crate::base::OnlyField for $name {
            fn encode_field(&self)->serde_json::Value {serde_json::Value::String(self.as_str().into())}
            fn decode_field(value:&serde_json::Value)->Result<Self,$crate::errors::OnlyDomainError> {$crate::base::text(value,"enum")?.parse()}
        }
        impl FromStr for $name {
            type Err = OnlyDomainError;
            fn from_str(value: &str) -> Result<Self, Self::Err> {
                match value {
                    $($text => Ok(Self::$variant)),+,
                    _ => Err(OnlyDomainError::Validation(format!("unknown {} value", stringify!($name))))
                }
            }
        }
    };
}

pub(crate) use domain_enum;

domain_enum! { OnlyDirection {
    Buy => "BUY",
    Sell => "SELL",
} }

domain_enum! { OnlyOffset {
    None => "NONE",
    Open => "OPEN",
    Close => "CLOSE",
    CloseToday => "CLOSE_TODAY",
    CloseYesterday => "CLOSE_YESTERDAY",
} }

domain_enum! { OnlyOrderStatus {
    Created => "CREATED",
    Submitted => "SUBMITTED",
    Accepted => "ACCEPTED",
    PartiallyFilled => "PARTIALLY_FILLED",
    PendingCancel => "PENDING_CANCEL",
    Cancelled => "CANCELLED",
    Expired => "EXPIRED",
    Filled => "FILLED",
    Rejected => "REJECTED",
    Failed => "FAILED",
} }

domain_enum! { OnlyOrderType {
    Market => "MARKET",
    Limit => "LIMIT",
    StopMarket => "STOP_MARKET",
    StopLimit => "STOP_LIMIT",
    MarketIfTouched => "MARKET_IF_TOUCHED",
    LimitIfTouched => "LIMIT_IF_TOUCHED",
    TrailingStopMarket => "TRAILING_STOP_MARKET",
    TrailingStopLimit => "TRAILING_STOP_LIMIT",
} }

domain_enum! { OnlyOrderSide {
    Buy => "BUY",
    Sell => "SELL",
} }

domain_enum! { OnlyRuntimeMode {
    Research => "RESEARCH",
    Backtest => "BACKTEST",
    Sim => "SIM",
    Live => "LIVE",
} }

domain_enum! { OnlyMarketType {
    Cash => "CASH",
    Margin => "MARGIN",
    Derivative => "DERIVATIVE",
    Otc => "OTC",
} }

domain_enum! { OnlyExchange {
    Xshg => "XSHG",
    Xshe => "XSHE",
    Xhkg => "XHKG",
    Xnas => "XNAS",
    Xnys => "XNYS",
    Cffex => "CFFEX",
    Shfe => "SHFE",
    Dce => "DCE",
    Czce => "CZCE",
    Ine => "INE",
    Binance => "BINANCE",
    Okx => "OKX",
    Bybit => "BYBIT",
    Otc => "OTC",
} }

domain_enum! { OnlyAssetClass {
    Equity => "EQUITY",
    Fund => "FUND",
    Index => "INDEX",
    Commodity => "COMMODITY",
    Fx => "FX",
    Cryptocurrency => "CRYPTOCURRENCY",
    Synthetic => "SYNTHETIC",
} }

domain_enum! { OnlyInstrumentType {
    Equity => "EQUITY",
    Etf => "ETF",
    Fund => "FUND",
    Future => "FUTURE",
    Option => "OPTION",
    Index => "INDEX",
    Commodity => "COMMODITY",
    FxPair => "FX_PAIR",
    CryptoSpot => "CRYPTO_SPOT",
    CryptoFuture => "CRYPTO_FUTURE",
    CryptoPerpetual => "CRYPTO_PERPETUAL",
    Synthetic => "SYNTHETIC",
} }

domain_enum! { OnlyCurrencyType {
    Fiat => "FIAT",
    Crypto => "CRYPTO",
    Commodity => "COMMODITY",
} }

domain_enum! { OnlySettlementType {
    Cash => "CASH",
    Physical => "PHYSICAL",
} }

domain_enum! { OnlyOptionType {
    Call => "CALL",
    Put => "PUT",
} }

domain_enum! { OnlyExerciseStyle {
    American => "AMERICAN",
    European => "EUROPEAN",
    Bermudan => "BERMUDAN",
} }

domain_enum! { OnlyMarginMode {
    Cash => "CASH",
    Cross => "CROSS",
    Isolated => "ISOLATED",
    Portfolio => "PORTFOLIO",
} }

domain_enum! { OnlyPositionDirection {
    Flat => "FLAT",
    Long => "LONG",
    Short => "SHORT",
} }

domain_enum! { OnlyContractType {
    Linear => "LINEAR",
    Inverse => "INVERSE",
    Quanto => "QUANTO",
} }

domain_enum! { OnlyTimeInForce {
    Gtc => "GTC",
    Ioc => "IOC",
    Fok => "FOK",
    Gtd => "GTD",
    Day => "DAY",
} }

domain_enum! { OnlyLiquiditySide {
    Maker => "MAKER",
    Taker => "TAKER",
    Unknown => "UNKNOWN",
} }

domain_enum! { OnlyBookType {
    L1 => "L1",
    L2 => "L2",
    L3 => "L3",
} }

domain_enum! { OnlyBarAggregation {
    Time => "TIME",
    Tick => "TICK",
    Volume => "VOLUME",
    Value => "VALUE",
} }

domain_enum! { OnlyPriceType {
    Last => "LAST",
    Bid => "BID",
    Ask => "ASK",
    Mid => "MID",
    Mark => "MARK",
} }

domain_enum! { OnlyAdjustmentType {
    Raw => "RAW",
    Forward => "FORWARD",
    Backward => "BACKWARD",
} }

domain_enum! { OnlySessionType {
    PreOpen => "PRE_OPEN",
    OpenAuction => "OPEN_AUCTION",
    Continuous => "CONTINUOUS",
    MiddayBreak => "MIDDAY_BREAK",
    ClosingAuction => "CLOSING_AUCTION",
    PreMarket => "PRE_MARKET",
    Regular => "REGULAR",
    PostMarket => "POST_MARKET",
    Night => "NIGHT",
    Auction => "AUCTION",
    Maintenance => "MAINTENANCE",
    Closed => "CLOSED",
} }

domain_enum! { OnlyTimeDisplayMode {
    Utc => "UTC",
    Market => "MARKET",
    UserLocal => "USER_LOCAL",
} }

domain_enum! { OnlySecurityStatus {
    Active => "ACTIVE",
    Halted => "HALTED",
    Suspended => "SUSPENDED",
    Expired => "EXPIRED",
    Delisted => "DELISTED",
} }

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn declared_vocabulary_round_trips_and_refuses_implicit_normalization() {
        assert_eq!(OnlyDirection::from_str("BUY"), Ok(OnlyDirection::Buy));
        assert_eq!(OnlyDirection::Buy.as_str(), "BUY");
        assert_eq!(OnlyDirection::from_str("SELL"), Ok(OnlyDirection::Sell));
        assert_eq!(OnlyDirection::Sell.as_str(), "SELL");
        for invalid in ["", "unknown", " BUY", "BUY ", "buy"] {
            assert!(OnlyDirection::from_str(invalid).is_err());
        }
        assert_eq!(OnlyOffset::from_str("NONE"), Ok(OnlyOffset::None));
        assert_eq!(OnlyOffset::None.as_str(), "NONE");
        assert_eq!(OnlyOffset::from_str("OPEN"), Ok(OnlyOffset::Open));
        assert_eq!(OnlyOffset::Open.as_str(), "OPEN");
        assert_eq!(OnlyOffset::from_str("CLOSE"), Ok(OnlyOffset::Close));
        assert_eq!(OnlyOffset::Close.as_str(), "CLOSE");
        assert_eq!(
            OnlyOffset::from_str("CLOSE_TODAY"),
            Ok(OnlyOffset::CloseToday)
        );
        assert_eq!(OnlyOffset::CloseToday.as_str(), "CLOSE_TODAY");
        assert_eq!(
            OnlyOffset::from_str("CLOSE_YESTERDAY"),
            Ok(OnlyOffset::CloseYesterday)
        );
        assert_eq!(OnlyOffset::CloseYesterday.as_str(), "CLOSE_YESTERDAY");
        for invalid in ["", "unknown", " NONE", "NONE ", "none"] {
            assert!(OnlyOffset::from_str(invalid).is_err());
        }
        assert_eq!(
            OnlyOrderStatus::from_str("CREATED"),
            Ok(OnlyOrderStatus::Created)
        );
        assert_eq!(OnlyOrderStatus::Created.as_str(), "CREATED");
        assert_eq!(
            OnlyOrderStatus::from_str("SUBMITTED"),
            Ok(OnlyOrderStatus::Submitted)
        );
        assert_eq!(OnlyOrderStatus::Submitted.as_str(), "SUBMITTED");
        assert_eq!(
            OnlyOrderStatus::from_str("ACCEPTED"),
            Ok(OnlyOrderStatus::Accepted)
        );
        assert_eq!(OnlyOrderStatus::Accepted.as_str(), "ACCEPTED");
        assert_eq!(
            OnlyOrderStatus::from_str("PARTIALLY_FILLED"),
            Ok(OnlyOrderStatus::PartiallyFilled)
        );
        assert_eq!(
            OnlyOrderStatus::PartiallyFilled.as_str(),
            "PARTIALLY_FILLED"
        );
        assert_eq!(
            OnlyOrderStatus::from_str("PENDING_CANCEL"),
            Ok(OnlyOrderStatus::PendingCancel)
        );
        assert_eq!(OnlyOrderStatus::PendingCancel.as_str(), "PENDING_CANCEL");
        assert_eq!(
            OnlyOrderStatus::from_str("CANCELLED"),
            Ok(OnlyOrderStatus::Cancelled)
        );
        assert_eq!(OnlyOrderStatus::Cancelled.as_str(), "CANCELLED");
        assert_eq!(
            OnlyOrderStatus::from_str("EXPIRED"),
            Ok(OnlyOrderStatus::Expired)
        );
        assert_eq!(OnlyOrderStatus::Expired.as_str(), "EXPIRED");
        assert_eq!(
            OnlyOrderStatus::from_str("FILLED"),
            Ok(OnlyOrderStatus::Filled)
        );
        assert_eq!(OnlyOrderStatus::Filled.as_str(), "FILLED");
        assert_eq!(
            OnlyOrderStatus::from_str("REJECTED"),
            Ok(OnlyOrderStatus::Rejected)
        );
        assert_eq!(OnlyOrderStatus::Rejected.as_str(), "REJECTED");
        assert_eq!(
            OnlyOrderStatus::from_str("FAILED"),
            Ok(OnlyOrderStatus::Failed)
        );
        assert_eq!(OnlyOrderStatus::Failed.as_str(), "FAILED");
        for invalid in ["", "unknown", " CREATED", "CREATED ", "created"] {
            assert!(OnlyOrderStatus::from_str(invalid).is_err());
        }
        assert_eq!(OnlyOrderType::from_str("MARKET"), Ok(OnlyOrderType::Market));
        assert_eq!(OnlyOrderType::Market.as_str(), "MARKET");
        assert_eq!(OnlyOrderType::from_str("LIMIT"), Ok(OnlyOrderType::Limit));
        assert_eq!(OnlyOrderType::Limit.as_str(), "LIMIT");
        assert_eq!(
            OnlyOrderType::from_str("STOP_MARKET"),
            Ok(OnlyOrderType::StopMarket)
        );
        assert_eq!(OnlyOrderType::StopMarket.as_str(), "STOP_MARKET");
        assert_eq!(
            OnlyOrderType::from_str("STOP_LIMIT"),
            Ok(OnlyOrderType::StopLimit)
        );
        assert_eq!(OnlyOrderType::StopLimit.as_str(), "STOP_LIMIT");
        assert_eq!(
            OnlyOrderType::from_str("MARKET_IF_TOUCHED"),
            Ok(OnlyOrderType::MarketIfTouched)
        );
        assert_eq!(OnlyOrderType::MarketIfTouched.as_str(), "MARKET_IF_TOUCHED");
        assert_eq!(
            OnlyOrderType::from_str("LIMIT_IF_TOUCHED"),
            Ok(OnlyOrderType::LimitIfTouched)
        );
        assert_eq!(OnlyOrderType::LimitIfTouched.as_str(), "LIMIT_IF_TOUCHED");
        assert_eq!(
            OnlyOrderType::from_str("TRAILING_STOP_MARKET"),
            Ok(OnlyOrderType::TrailingStopMarket)
        );
        assert_eq!(
            OnlyOrderType::TrailingStopMarket.as_str(),
            "TRAILING_STOP_MARKET"
        );
        assert_eq!(
            OnlyOrderType::from_str("TRAILING_STOP_LIMIT"),
            Ok(OnlyOrderType::TrailingStopLimit)
        );
        assert_eq!(
            OnlyOrderType::TrailingStopLimit.as_str(),
            "TRAILING_STOP_LIMIT"
        );
        for invalid in ["", "unknown", " MARKET", "MARKET ", "market"] {
            assert!(OnlyOrderType::from_str(invalid).is_err());
        }
        assert_eq!(OnlyOrderSide::from_str("BUY"), Ok(OnlyOrderSide::Buy));
        assert_eq!(OnlyOrderSide::Buy.as_str(), "BUY");
        assert_eq!(OnlyOrderSide::from_str("SELL"), Ok(OnlyOrderSide::Sell));
        assert_eq!(OnlyOrderSide::Sell.as_str(), "SELL");
        for invalid in ["", "unknown", " BUY", "BUY ", "buy"] {
            assert!(OnlyOrderSide::from_str(invalid).is_err());
        }
        assert_eq!(
            OnlyRuntimeMode::from_str("RESEARCH"),
            Ok(OnlyRuntimeMode::Research)
        );
        assert_eq!(OnlyRuntimeMode::Research.as_str(), "RESEARCH");
        assert_eq!(
            OnlyRuntimeMode::from_str("BACKTEST"),
            Ok(OnlyRuntimeMode::Backtest)
        );
        assert_eq!(OnlyRuntimeMode::Backtest.as_str(), "BACKTEST");
        assert_eq!(OnlyRuntimeMode::from_str("SIM"), Ok(OnlyRuntimeMode::Sim));
        assert_eq!(OnlyRuntimeMode::Sim.as_str(), "SIM");
        assert_eq!(OnlyRuntimeMode::from_str("LIVE"), Ok(OnlyRuntimeMode::Live));
        assert_eq!(OnlyRuntimeMode::Live.as_str(), "LIVE");
        for invalid in ["", "unknown", " RESEARCH", "RESEARCH ", "research"] {
            assert!(OnlyRuntimeMode::from_str(invalid).is_err());
        }
        assert_eq!(OnlyMarketType::from_str("CASH"), Ok(OnlyMarketType::Cash));
        assert_eq!(OnlyMarketType::Cash.as_str(), "CASH");
        assert_eq!(
            OnlyMarketType::from_str("MARGIN"),
            Ok(OnlyMarketType::Margin)
        );
        assert_eq!(OnlyMarketType::Margin.as_str(), "MARGIN");
        assert_eq!(
            OnlyMarketType::from_str("DERIVATIVE"),
            Ok(OnlyMarketType::Derivative)
        );
        assert_eq!(OnlyMarketType::Derivative.as_str(), "DERIVATIVE");
        assert_eq!(OnlyMarketType::from_str("OTC"), Ok(OnlyMarketType::Otc));
        assert_eq!(OnlyMarketType::Otc.as_str(), "OTC");
        for invalid in ["", "unknown", " CASH", "CASH ", "cash"] {
            assert!(OnlyMarketType::from_str(invalid).is_err());
        }
        assert_eq!(OnlyExchange::from_str("XSHG"), Ok(OnlyExchange::Xshg));
        assert_eq!(OnlyExchange::Xshg.as_str(), "XSHG");
        assert_eq!(OnlyExchange::from_str("XSHE"), Ok(OnlyExchange::Xshe));
        assert_eq!(OnlyExchange::Xshe.as_str(), "XSHE");
        assert_eq!(OnlyExchange::from_str("XHKG"), Ok(OnlyExchange::Xhkg));
        assert_eq!(OnlyExchange::Xhkg.as_str(), "XHKG");
        assert_eq!(OnlyExchange::from_str("XNAS"), Ok(OnlyExchange::Xnas));
        assert_eq!(OnlyExchange::Xnas.as_str(), "XNAS");
        assert_eq!(OnlyExchange::from_str("XNYS"), Ok(OnlyExchange::Xnys));
        assert_eq!(OnlyExchange::Xnys.as_str(), "XNYS");
        assert_eq!(OnlyExchange::from_str("CFFEX"), Ok(OnlyExchange::Cffex));
        assert_eq!(OnlyExchange::Cffex.as_str(), "CFFEX");
        assert_eq!(OnlyExchange::from_str("SHFE"), Ok(OnlyExchange::Shfe));
        assert_eq!(OnlyExchange::Shfe.as_str(), "SHFE");
        assert_eq!(OnlyExchange::from_str("DCE"), Ok(OnlyExchange::Dce));
        assert_eq!(OnlyExchange::Dce.as_str(), "DCE");
        assert_eq!(OnlyExchange::from_str("CZCE"), Ok(OnlyExchange::Czce));
        assert_eq!(OnlyExchange::Czce.as_str(), "CZCE");
        assert_eq!(OnlyExchange::from_str("INE"), Ok(OnlyExchange::Ine));
        assert_eq!(OnlyExchange::Ine.as_str(), "INE");
        assert_eq!(OnlyExchange::from_str("BINANCE"), Ok(OnlyExchange::Binance));
        assert_eq!(OnlyExchange::Binance.as_str(), "BINANCE");
        assert_eq!(OnlyExchange::from_str("OKX"), Ok(OnlyExchange::Okx));
        assert_eq!(OnlyExchange::Okx.as_str(), "OKX");
        assert_eq!(OnlyExchange::from_str("BYBIT"), Ok(OnlyExchange::Bybit));
        assert_eq!(OnlyExchange::Bybit.as_str(), "BYBIT");
        assert_eq!(OnlyExchange::from_str("OTC"), Ok(OnlyExchange::Otc));
        assert_eq!(OnlyExchange::Otc.as_str(), "OTC");
        for invalid in ["", "unknown", " XSHG", "XSHG ", "xshg"] {
            assert!(OnlyExchange::from_str(invalid).is_err());
        }
        assert_eq!(
            OnlyAssetClass::from_str("EQUITY"),
            Ok(OnlyAssetClass::Equity)
        );
        assert_eq!(OnlyAssetClass::Equity.as_str(), "EQUITY");
        assert_eq!(OnlyAssetClass::from_str("FUND"), Ok(OnlyAssetClass::Fund));
        assert_eq!(OnlyAssetClass::Fund.as_str(), "FUND");
        assert_eq!(OnlyAssetClass::from_str("INDEX"), Ok(OnlyAssetClass::Index));
        assert_eq!(OnlyAssetClass::Index.as_str(), "INDEX");
        assert_eq!(
            OnlyAssetClass::from_str("COMMODITY"),
            Ok(OnlyAssetClass::Commodity)
        );
        assert_eq!(OnlyAssetClass::Commodity.as_str(), "COMMODITY");
        assert_eq!(OnlyAssetClass::from_str("FX"), Ok(OnlyAssetClass::Fx));
        assert_eq!(OnlyAssetClass::Fx.as_str(), "FX");
        assert_eq!(
            OnlyAssetClass::from_str("CRYPTOCURRENCY"),
            Ok(OnlyAssetClass::Cryptocurrency)
        );
        assert_eq!(OnlyAssetClass::Cryptocurrency.as_str(), "CRYPTOCURRENCY");
        assert_eq!(
            OnlyAssetClass::from_str("SYNTHETIC"),
            Ok(OnlyAssetClass::Synthetic)
        );
        assert_eq!(OnlyAssetClass::Synthetic.as_str(), "SYNTHETIC");
        for invalid in ["", "unknown", " EQUITY", "EQUITY ", "equity"] {
            assert!(OnlyAssetClass::from_str(invalid).is_err());
        }
        assert_eq!(
            OnlyInstrumentType::from_str("EQUITY"),
            Ok(OnlyInstrumentType::Equity)
        );
        assert_eq!(OnlyInstrumentType::Equity.as_str(), "EQUITY");
        assert_eq!(
            OnlyInstrumentType::from_str("ETF"),
            Ok(OnlyInstrumentType::Etf)
        );
        assert_eq!(OnlyInstrumentType::Etf.as_str(), "ETF");
        assert_eq!(
            OnlyInstrumentType::from_str("FUND"),
            Ok(OnlyInstrumentType::Fund)
        );
        assert_eq!(OnlyInstrumentType::Fund.as_str(), "FUND");
        assert_eq!(
            OnlyInstrumentType::from_str("FUTURE"),
            Ok(OnlyInstrumentType::Future)
        );
        assert_eq!(OnlyInstrumentType::Future.as_str(), "FUTURE");
        assert_eq!(
            OnlyInstrumentType::from_str("OPTION"),
            Ok(OnlyInstrumentType::Option)
        );
        assert_eq!(OnlyInstrumentType::Option.as_str(), "OPTION");
        assert_eq!(
            OnlyInstrumentType::from_str("INDEX"),
            Ok(OnlyInstrumentType::Index)
        );
        assert_eq!(OnlyInstrumentType::Index.as_str(), "INDEX");
        assert_eq!(
            OnlyInstrumentType::from_str("COMMODITY"),
            Ok(OnlyInstrumentType::Commodity)
        );
        assert_eq!(OnlyInstrumentType::Commodity.as_str(), "COMMODITY");
        assert_eq!(
            OnlyInstrumentType::from_str("FX_PAIR"),
            Ok(OnlyInstrumentType::FxPair)
        );
        assert_eq!(OnlyInstrumentType::FxPair.as_str(), "FX_PAIR");
        assert_eq!(
            OnlyInstrumentType::from_str("CRYPTO_SPOT"),
            Ok(OnlyInstrumentType::CryptoSpot)
        );
        assert_eq!(OnlyInstrumentType::CryptoSpot.as_str(), "CRYPTO_SPOT");
        assert_eq!(
            OnlyInstrumentType::from_str("CRYPTO_FUTURE"),
            Ok(OnlyInstrumentType::CryptoFuture)
        );
        assert_eq!(OnlyInstrumentType::CryptoFuture.as_str(), "CRYPTO_FUTURE");
        assert_eq!(
            OnlyInstrumentType::from_str("CRYPTO_PERPETUAL"),
            Ok(OnlyInstrumentType::CryptoPerpetual)
        );
        assert_eq!(
            OnlyInstrumentType::CryptoPerpetual.as_str(),
            "CRYPTO_PERPETUAL"
        );
        assert_eq!(
            OnlyInstrumentType::from_str("SYNTHETIC"),
            Ok(OnlyInstrumentType::Synthetic)
        );
        assert_eq!(OnlyInstrumentType::Synthetic.as_str(), "SYNTHETIC");
        for invalid in ["", "unknown", " EQUITY", "EQUITY ", "equity"] {
            assert!(OnlyInstrumentType::from_str(invalid).is_err());
        }
        assert_eq!(
            OnlyCurrencyType::from_str("FIAT"),
            Ok(OnlyCurrencyType::Fiat)
        );
        assert_eq!(OnlyCurrencyType::Fiat.as_str(), "FIAT");
        assert_eq!(
            OnlyCurrencyType::from_str("CRYPTO"),
            Ok(OnlyCurrencyType::Crypto)
        );
        assert_eq!(OnlyCurrencyType::Crypto.as_str(), "CRYPTO");
        assert_eq!(
            OnlyCurrencyType::from_str("COMMODITY"),
            Ok(OnlyCurrencyType::Commodity)
        );
        assert_eq!(OnlyCurrencyType::Commodity.as_str(), "COMMODITY");
        for invalid in ["", "unknown", " FIAT", "FIAT ", "fiat"] {
            assert!(OnlyCurrencyType::from_str(invalid).is_err());
        }
        assert_eq!(
            OnlySettlementType::from_str("CASH"),
            Ok(OnlySettlementType::Cash)
        );
        assert_eq!(OnlySettlementType::Cash.as_str(), "CASH");
        assert_eq!(
            OnlySettlementType::from_str("PHYSICAL"),
            Ok(OnlySettlementType::Physical)
        );
        assert_eq!(OnlySettlementType::Physical.as_str(), "PHYSICAL");
        for invalid in ["", "unknown", " CASH", "CASH ", "cash"] {
            assert!(OnlySettlementType::from_str(invalid).is_err());
        }
        assert_eq!(OnlyOptionType::from_str("CALL"), Ok(OnlyOptionType::Call));
        assert_eq!(OnlyOptionType::Call.as_str(), "CALL");
        assert_eq!(OnlyOptionType::from_str("PUT"), Ok(OnlyOptionType::Put));
        assert_eq!(OnlyOptionType::Put.as_str(), "PUT");
        for invalid in ["", "unknown", " CALL", "CALL ", "call"] {
            assert!(OnlyOptionType::from_str(invalid).is_err());
        }
        assert_eq!(
            OnlyExerciseStyle::from_str("AMERICAN"),
            Ok(OnlyExerciseStyle::American)
        );
        assert_eq!(OnlyExerciseStyle::American.as_str(), "AMERICAN");
        assert_eq!(
            OnlyExerciseStyle::from_str("EUROPEAN"),
            Ok(OnlyExerciseStyle::European)
        );
        assert_eq!(OnlyExerciseStyle::European.as_str(), "EUROPEAN");
        assert_eq!(
            OnlyExerciseStyle::from_str("BERMUDAN"),
            Ok(OnlyExerciseStyle::Bermudan)
        );
        assert_eq!(OnlyExerciseStyle::Bermudan.as_str(), "BERMUDAN");
        for invalid in ["", "unknown", " AMERICAN", "AMERICAN ", "american"] {
            assert!(OnlyExerciseStyle::from_str(invalid).is_err());
        }
        assert_eq!(OnlyMarginMode::from_str("CASH"), Ok(OnlyMarginMode::Cash));
        assert_eq!(OnlyMarginMode::Cash.as_str(), "CASH");
        assert_eq!(OnlyMarginMode::from_str("CROSS"), Ok(OnlyMarginMode::Cross));
        assert_eq!(OnlyMarginMode::Cross.as_str(), "CROSS");
        assert_eq!(
            OnlyMarginMode::from_str("ISOLATED"),
            Ok(OnlyMarginMode::Isolated)
        );
        assert_eq!(OnlyMarginMode::Isolated.as_str(), "ISOLATED");
        assert_eq!(
            OnlyMarginMode::from_str("PORTFOLIO"),
            Ok(OnlyMarginMode::Portfolio)
        );
        assert_eq!(OnlyMarginMode::Portfolio.as_str(), "PORTFOLIO");
        for invalid in ["", "unknown", " CASH", "CASH ", "cash"] {
            assert!(OnlyMarginMode::from_str(invalid).is_err());
        }
        assert_eq!(
            OnlyPositionDirection::from_str("FLAT"),
            Ok(OnlyPositionDirection::Flat)
        );
        assert_eq!(OnlyPositionDirection::Flat.as_str(), "FLAT");
        assert_eq!(
            OnlyPositionDirection::from_str("LONG"),
            Ok(OnlyPositionDirection::Long)
        );
        assert_eq!(OnlyPositionDirection::Long.as_str(), "LONG");
        assert_eq!(
            OnlyPositionDirection::from_str("SHORT"),
            Ok(OnlyPositionDirection::Short)
        );
        assert_eq!(OnlyPositionDirection::Short.as_str(), "SHORT");
        for invalid in ["", "unknown", " FLAT", "FLAT ", "flat"] {
            assert!(OnlyPositionDirection::from_str(invalid).is_err());
        }
        assert_eq!(
            OnlyContractType::from_str("LINEAR"),
            Ok(OnlyContractType::Linear)
        );
        assert_eq!(OnlyContractType::Linear.as_str(), "LINEAR");
        assert_eq!(
            OnlyContractType::from_str("INVERSE"),
            Ok(OnlyContractType::Inverse)
        );
        assert_eq!(OnlyContractType::Inverse.as_str(), "INVERSE");
        assert_eq!(
            OnlyContractType::from_str("QUANTO"),
            Ok(OnlyContractType::Quanto)
        );
        assert_eq!(OnlyContractType::Quanto.as_str(), "QUANTO");
        for invalid in ["", "unknown", " LINEAR", "LINEAR ", "linear"] {
            assert!(OnlyContractType::from_str(invalid).is_err());
        }
        assert_eq!(OnlyTimeInForce::from_str("GTC"), Ok(OnlyTimeInForce::Gtc));
        assert_eq!(OnlyTimeInForce::Gtc.as_str(), "GTC");
        assert_eq!(OnlyTimeInForce::from_str("IOC"), Ok(OnlyTimeInForce::Ioc));
        assert_eq!(OnlyTimeInForce::Ioc.as_str(), "IOC");
        assert_eq!(OnlyTimeInForce::from_str("FOK"), Ok(OnlyTimeInForce::Fok));
        assert_eq!(OnlyTimeInForce::Fok.as_str(), "FOK");
        assert_eq!(OnlyTimeInForce::from_str("GTD"), Ok(OnlyTimeInForce::Gtd));
        assert_eq!(OnlyTimeInForce::Gtd.as_str(), "GTD");
        assert_eq!(OnlyTimeInForce::from_str("DAY"), Ok(OnlyTimeInForce::Day));
        assert_eq!(OnlyTimeInForce::Day.as_str(), "DAY");
        for invalid in ["", "unknown", " GTC", "GTC ", "gtc"] {
            assert!(OnlyTimeInForce::from_str(invalid).is_err());
        }
        assert_eq!(
            OnlyLiquiditySide::from_str("MAKER"),
            Ok(OnlyLiquiditySide::Maker)
        );
        assert_eq!(OnlyLiquiditySide::Maker.as_str(), "MAKER");
        assert_eq!(
            OnlyLiquiditySide::from_str("TAKER"),
            Ok(OnlyLiquiditySide::Taker)
        );
        assert_eq!(OnlyLiquiditySide::Taker.as_str(), "TAKER");
        assert_eq!(
            OnlyLiquiditySide::from_str("UNKNOWN"),
            Ok(OnlyLiquiditySide::Unknown)
        );
        assert_eq!(OnlyLiquiditySide::Unknown.as_str(), "UNKNOWN");
        for invalid in ["", "unknown", " MAKER", "MAKER ", "maker"] {
            assert!(OnlyLiquiditySide::from_str(invalid).is_err());
        }
        assert_eq!(OnlyBookType::from_str("L1"), Ok(OnlyBookType::L1));
        assert_eq!(OnlyBookType::L1.as_str(), "L1");
        assert_eq!(OnlyBookType::from_str("L2"), Ok(OnlyBookType::L2));
        assert_eq!(OnlyBookType::L2.as_str(), "L2");
        assert_eq!(OnlyBookType::from_str("L3"), Ok(OnlyBookType::L3));
        assert_eq!(OnlyBookType::L3.as_str(), "L3");
        for invalid in ["", "unknown", " L1", "L1 ", "l1"] {
            assert!(OnlyBookType::from_str(invalid).is_err());
        }
        assert_eq!(
            OnlyBarAggregation::from_str("TIME"),
            Ok(OnlyBarAggregation::Time)
        );
        assert_eq!(OnlyBarAggregation::Time.as_str(), "TIME");
        assert_eq!(
            OnlyBarAggregation::from_str("TICK"),
            Ok(OnlyBarAggregation::Tick)
        );
        assert_eq!(OnlyBarAggregation::Tick.as_str(), "TICK");
        assert_eq!(
            OnlyBarAggregation::from_str("VOLUME"),
            Ok(OnlyBarAggregation::Volume)
        );
        assert_eq!(OnlyBarAggregation::Volume.as_str(), "VOLUME");
        assert_eq!(
            OnlyBarAggregation::from_str("VALUE"),
            Ok(OnlyBarAggregation::Value)
        );
        assert_eq!(OnlyBarAggregation::Value.as_str(), "VALUE");
        for invalid in ["", "unknown", " TIME", "TIME ", "time"] {
            assert!(OnlyBarAggregation::from_str(invalid).is_err());
        }
        assert_eq!(OnlyPriceType::from_str("LAST"), Ok(OnlyPriceType::Last));
        assert_eq!(OnlyPriceType::Last.as_str(), "LAST");
        assert_eq!(OnlyPriceType::from_str("BID"), Ok(OnlyPriceType::Bid));
        assert_eq!(OnlyPriceType::Bid.as_str(), "BID");
        assert_eq!(OnlyPriceType::from_str("ASK"), Ok(OnlyPriceType::Ask));
        assert_eq!(OnlyPriceType::Ask.as_str(), "ASK");
        assert_eq!(OnlyPriceType::from_str("MID"), Ok(OnlyPriceType::Mid));
        assert_eq!(OnlyPriceType::Mid.as_str(), "MID");
        assert_eq!(OnlyPriceType::from_str("MARK"), Ok(OnlyPriceType::Mark));
        assert_eq!(OnlyPriceType::Mark.as_str(), "MARK");
        for invalid in ["", "unknown", " LAST", "LAST ", "last"] {
            assert!(OnlyPriceType::from_str(invalid).is_err());
        }
        assert_eq!(
            OnlyAdjustmentType::from_str("RAW"),
            Ok(OnlyAdjustmentType::Raw)
        );
        assert_eq!(OnlyAdjustmentType::Raw.as_str(), "RAW");
        assert_eq!(
            OnlyAdjustmentType::from_str("FORWARD"),
            Ok(OnlyAdjustmentType::Forward)
        );
        assert_eq!(OnlyAdjustmentType::Forward.as_str(), "FORWARD");
        assert_eq!(
            OnlyAdjustmentType::from_str("BACKWARD"),
            Ok(OnlyAdjustmentType::Backward)
        );
        assert_eq!(OnlyAdjustmentType::Backward.as_str(), "BACKWARD");
        for invalid in ["", "unknown", " RAW", "RAW ", "raw"] {
            assert!(OnlyAdjustmentType::from_str(invalid).is_err());
        }
        assert_eq!(
            OnlySessionType::from_str("PRE_OPEN"),
            Ok(OnlySessionType::PreOpen)
        );
        assert_eq!(OnlySessionType::PreOpen.as_str(), "PRE_OPEN");
        assert_eq!(
            OnlySessionType::from_str("OPEN_AUCTION"),
            Ok(OnlySessionType::OpenAuction)
        );
        assert_eq!(OnlySessionType::OpenAuction.as_str(), "OPEN_AUCTION");
        assert_eq!(
            OnlySessionType::from_str("CONTINUOUS"),
            Ok(OnlySessionType::Continuous)
        );
        assert_eq!(OnlySessionType::Continuous.as_str(), "CONTINUOUS");
        assert_eq!(
            OnlySessionType::from_str("MIDDAY_BREAK"),
            Ok(OnlySessionType::MiddayBreak)
        );
        assert_eq!(OnlySessionType::MiddayBreak.as_str(), "MIDDAY_BREAK");
        assert_eq!(
            OnlySessionType::from_str("CLOSING_AUCTION"),
            Ok(OnlySessionType::ClosingAuction)
        );
        assert_eq!(OnlySessionType::ClosingAuction.as_str(), "CLOSING_AUCTION");
        assert_eq!(
            OnlySessionType::from_str("PRE_MARKET"),
            Ok(OnlySessionType::PreMarket)
        );
        assert_eq!(OnlySessionType::PreMarket.as_str(), "PRE_MARKET");
        assert_eq!(
            OnlySessionType::from_str("REGULAR"),
            Ok(OnlySessionType::Regular)
        );
        assert_eq!(OnlySessionType::Regular.as_str(), "REGULAR");
        assert_eq!(
            OnlySessionType::from_str("POST_MARKET"),
            Ok(OnlySessionType::PostMarket)
        );
        assert_eq!(OnlySessionType::PostMarket.as_str(), "POST_MARKET");
        assert_eq!(
            OnlySessionType::from_str("NIGHT"),
            Ok(OnlySessionType::Night)
        );
        assert_eq!(OnlySessionType::Night.as_str(), "NIGHT");
        assert_eq!(
            OnlySessionType::from_str("AUCTION"),
            Ok(OnlySessionType::Auction)
        );
        assert_eq!(OnlySessionType::Auction.as_str(), "AUCTION");
        assert_eq!(
            OnlySessionType::from_str("MAINTENANCE"),
            Ok(OnlySessionType::Maintenance)
        );
        assert_eq!(OnlySessionType::Maintenance.as_str(), "MAINTENANCE");
        assert_eq!(
            OnlySessionType::from_str("CLOSED"),
            Ok(OnlySessionType::Closed)
        );
        assert_eq!(OnlySessionType::Closed.as_str(), "CLOSED");
        for invalid in ["", "unknown", " PRE_OPEN", "PRE_OPEN ", "pre_open"] {
            assert!(OnlySessionType::from_str(invalid).is_err());
        }
        assert_eq!(
            OnlyTimeDisplayMode::from_str("UTC"),
            Ok(OnlyTimeDisplayMode::Utc)
        );
        assert_eq!(OnlyTimeDisplayMode::Utc.as_str(), "UTC");
        assert_eq!(
            OnlyTimeDisplayMode::from_str("MARKET"),
            Ok(OnlyTimeDisplayMode::Market)
        );
        assert_eq!(OnlyTimeDisplayMode::Market.as_str(), "MARKET");
        assert_eq!(
            OnlyTimeDisplayMode::from_str("USER_LOCAL"),
            Ok(OnlyTimeDisplayMode::UserLocal)
        );
        assert_eq!(OnlyTimeDisplayMode::UserLocal.as_str(), "USER_LOCAL");
        for invalid in ["", "unknown", " UTC", "UTC ", "utc"] {
            assert!(OnlyTimeDisplayMode::from_str(invalid).is_err());
        }
        assert_eq!(
            OnlySecurityStatus::from_str("ACTIVE"),
            Ok(OnlySecurityStatus::Active)
        );
        assert_eq!(OnlySecurityStatus::Active.as_str(), "ACTIVE");
        assert_eq!(
            OnlySecurityStatus::from_str("HALTED"),
            Ok(OnlySecurityStatus::Halted)
        );
        assert_eq!(OnlySecurityStatus::Halted.as_str(), "HALTED");
        assert_eq!(
            OnlySecurityStatus::from_str("SUSPENDED"),
            Ok(OnlySecurityStatus::Suspended)
        );
        assert_eq!(OnlySecurityStatus::Suspended.as_str(), "SUSPENDED");
        assert_eq!(
            OnlySecurityStatus::from_str("EXPIRED"),
            Ok(OnlySecurityStatus::Expired)
        );
        assert_eq!(OnlySecurityStatus::Expired.as_str(), "EXPIRED");
        assert_eq!(
            OnlySecurityStatus::from_str("DELISTED"),
            Ok(OnlySecurityStatus::Delisted)
        );
        assert_eq!(OnlySecurityStatus::Delisted.as_str(), "DELISTED");
        for invalid in ["", "unknown", " ACTIVE", "ACTIVE ", "active"] {
            assert!(OnlySecurityStatus::from_str(invalid).is_err());
        }
    }
}
