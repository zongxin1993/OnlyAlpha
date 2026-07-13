"""Market-neutral domain enumerations."""

from enum import StrEnum


class OnlyDirection(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OnlyOffset(StrEnum):
    NONE = "NONE"
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    CLOSE_TODAY = "CLOSE_TODAY"
    CLOSE_YESTERDAY = "CLOSE_YESTERDAY"


class OnlyOrderStatus(StrEnum):
    INITIALIZED = "INITIALIZED"
    DENIED = "DENIED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    PENDING_CANCEL = "PENDING_CANCEL"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    FILLED = "FILLED"


class OnlyOrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    STOP_LIMIT = "STOP_LIMIT"
    MARKET_IF_TOUCHED = "MARKET_IF_TOUCHED"
    LIMIT_IF_TOUCHED = "LIMIT_IF_TOUCHED"
    TRAILING_STOP_MARKET = "TRAILING_STOP_MARKET"
    TRAILING_STOP_LIMIT = "TRAILING_STOP_LIMIT"


class OnlyOrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OnlyRuntimeMode(StrEnum):
    LIVE = "LIVE"
    PAPER = "PAPER"
    BACKTEST = "BACKTEST"
    RESEARCH = "RESEARCH"


class OnlyMarketType(StrEnum):
    CASH = "CASH"
    MARGIN = "MARGIN"
    DERIVATIVE = "DERIVATIVE"
    OTC = "OTC"


class OnlyExchange(StrEnum):
    XSHG = "XSHG"
    XSHE = "XSHE"
    XHKG = "XHKG"
    XNAS = "XNAS"
    XNYS = "XNYS"
    CFFEX = "CFFEX"
    SHFE = "SHFE"
    DCE = "DCE"
    CZCE = "CZCE"
    INE = "INE"
    BINANCE = "BINANCE"
    OKX = "OKX"
    BYBIT = "BYBIT"
    OTC = "OTC"


class OnlyAssetClass(StrEnum):
    EQUITY = "EQUITY"
    FUND = "FUND"
    INDEX = "INDEX"
    COMMODITY = "COMMODITY"
    FX = "FX"
    CRYPTOCURRENCY = "CRYPTOCURRENCY"
    SYNTHETIC = "SYNTHETIC"


class OnlyInstrumentType(StrEnum):
    EQUITY = "EQUITY"
    ETF = "ETF"
    FUND = "FUND"
    FUTURE = "FUTURE"
    OPTION = "OPTION"
    INDEX = "INDEX"
    COMMODITY = "COMMODITY"
    FX_PAIR = "FX_PAIR"
    CRYPTO_SPOT = "CRYPTO_SPOT"
    CRYPTO_FUTURE = "CRYPTO_FUTURE"
    CRYPTO_PERPETUAL = "CRYPTO_PERPETUAL"
    SYNTHETIC = "SYNTHETIC"


class OnlyCurrencyType(StrEnum):
    FIAT = "FIAT"
    CRYPTO = "CRYPTO"
    COMMODITY = "COMMODITY"


class OnlySettlementType(StrEnum):
    CASH = "CASH"
    PHYSICAL = "PHYSICAL"


class OnlyOptionType(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


class OnlyExerciseStyle(StrEnum):
    AMERICAN = "AMERICAN"
    EUROPEAN = "EUROPEAN"
    BERMUDAN = "BERMUDAN"


class OnlyMarginMode(StrEnum):
    CASH = "CASH"
    CROSS = "CROSS"
    ISOLATED = "ISOLATED"
    PORTFOLIO = "PORTFOLIO"


class OnlyPositionDirection(StrEnum):
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


class OnlyContractType(StrEnum):
    LINEAR = "LINEAR"
    INVERSE = "INVERSE"
    QUANTO = "QUANTO"


class OnlyTimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    GTD = "GTD"
    DAY = "DAY"


class OnlyLiquiditySide(StrEnum):
    MAKER = "MAKER"
    TAKER = "TAKER"
    UNKNOWN = "UNKNOWN"


class OnlyBookType(StrEnum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class OnlyBarAggregation(StrEnum):
    TIME = "TIME"
    TICK = "TICK"
    VOLUME = "VOLUME"
    VALUE = "VALUE"


class OnlyPriceType(StrEnum):
    LAST = "LAST"
    BID = "BID"
    ASK = "ASK"
    MID = "MID"
    MARK = "MARK"


class OnlyAggregationSource(StrEnum):
    EXTERNAL = "EXTERNAL"
    INTERNAL = "INTERNAL"


class OnlyAdjustmentType(StrEnum):
    RAW = "RAW"
    FORWARD = "FORWARD"
    BACKWARD = "BACKWARD"


class OnlySessionType(StrEnum):
    PRE_OPEN = "PRE_OPEN"
    OPEN_AUCTION = "OPEN_AUCTION"
    CONTINUOUS = "CONTINUOUS"
    MIDDAY_BREAK = "MIDDAY_BREAK"
    CLOSING_AUCTION = "CLOSING_AUCTION"
    PRE_MARKET = "PRE_MARKET"
    REGULAR = "REGULAR"
    POST_MARKET = "POST_MARKET"
    NIGHT = "NIGHT"
    AUCTION = "AUCTION"
    MAINTENANCE = "MAINTENANCE"
    CLOSED = "CLOSED"


class OnlyTimeDisplayMode(StrEnum):
    UTC = "UTC"
    MARKET = "MARKET"
    USER_LOCAL = "USER_LOCAL"


class OnlySecurityStatus(StrEnum):
    ACTIVE = "ACTIVE"
    HALTED = "HALTED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    DELISTED = "DELISTED"
