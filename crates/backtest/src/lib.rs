//! Finite native Backtest orchestration. This library grants no Product or LIVE authority.
mod inputs;
mod native_read;
mod next_open;
mod run;
mod terminal;
mod trace;
mod trading;
pub use inputs::{Inputs, MarketInput, OpeningInput, Source};
pub use next_open::NextOpenPolicy;
pub use onlyalpha_execution::Error;
pub use run::{Candidate, Participants, RunLoop, RunSpec, StepAndDeliverError};
use serde_json::Value;
pub use terminal::TerminalSnapshot;
pub use trading::Trading;
fn err(s: &str) -> Error {
    Error(format!("BACKTEST_REPLAY_{s}"))
}
fn hash(v: &Value) -> String {
    onlyalpha_execution::digest(v.to_string().as_bytes())
}
fn boundary<T, E: std::fmt::Display>(r: Result<T, E>) -> Result<T, Error> {
    r.map_err(|e| err(&e.to_string()))
}
fn fields(v: &Value, keys: &[&str]) -> Result<(), Error> {
    if v.as_object()
        .is_none_or(|m| m.len() != keys.len() || keys.iter().any(|k| !m.contains_key(*k)))
    {
        return Err(err("FIELDS"));
    }
    Ok(())
}
fn sha(s: &str) -> Result<(), Error> {
    if s.len() != 64
        || !s
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    {
        return Err(err("IDENTITY"));
    }
    Ok(())
}

#[cfg(test)]
mod next_open_tests;

/// Pure validation by the canonical composition. No Store, candidate or execution grant is returned.
pub fn validate_configuration(configuration: &Value) -> Result<(), Error> {
    Candidate::new(configuration.clone(), vec![]).map(|_| ())
}

#[cfg(test)]
#[path = "test_support/execution.rs"]
mod execution_test_fixture;
