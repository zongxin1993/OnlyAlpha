# Account cash reference vectors

Literal balances independently specified from cash conservation. Python's actual AccountManager handles simple valid flows; formal AccountTradeReducer handles fee/rebate, Reservation deltas and valuation. Rust consumes the same cases. Common economics do not certify old reader parity, Runtime activation or deployment/history migration.

Each case declares its reference path. `manager_and_reducer` uses both actual Python paths; `reducer_only` covers an authoritative rebate greater than purchase cost. Python direct AccountTradeCashFlow rejects its negative net fee, so that older DTO is explicitly excluded from that case's comparison, while the formal typed fee/reducer and Rust must still match its independent literal result. This is a classified reference deviation, not a fallback or whole-module parity claim.
