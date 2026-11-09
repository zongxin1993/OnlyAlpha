//! Isolated Position semantics. No Runtime activation or external effects.
mod manager;
mod valuation;
pub use valuation::ValuationEffect;
mod model;
mod reconciliation;
mod recovery;
mod reservation;
pub use manager::Manager;
pub use model::{Error, Outcome, Status, digest};
mod funding;
pub use funding::FundingEffect;
pub use onlyalpha_domain::market_source::OnlyMarketSourceCut as MarketSourceCut;

mod trade_evidence;
pub use trade_evidence::TradeEvidence;
