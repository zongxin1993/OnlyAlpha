//! Canonical financial Domain. No Runtime, storage, network or provider authority.

pub mod enums;
pub mod errors;

pub mod base;
pub mod identifiers;
pub mod numeric;
mod unicode_data;
pub mod value;

pub mod trading;

pub mod ranges;
pub mod time;
mod tzdb_rules;

pub mod account;

pub mod market_rules;

pub mod fee;

pub mod calendar;

pub mod venue;

pub mod instrument;

pub mod catalog;

pub mod market;

pub mod execution;
