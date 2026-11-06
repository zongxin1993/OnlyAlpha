//! Frozen CN A-share cash reference, policy and market-fee library.
//! Market-specific interpretation stays here. Domain/Fee/Settlement retain their
//! generic semantics. This library grants no Runtime, Broker or LIVE admission.
mod fees;
mod policy;
mod reference;
pub use fees::{FeeComposition, FeePack};
pub use policy::{CompiledPolicy, PolicyCompiler};
pub use reference::{Reference, ReferenceAuthority};

use bigdecimal::{BigDecimal, Zero};
use onlyalpha_domain::{base::OnlyDomainModel, numeric::OnlyDecimal, time::OnlyTradingDay};
use onlyalpha_fee::digest;
use serde_json::{Value, json};
use std::{fmt, str::FromStr};

pub const PLUGIN_ID: &str = "onlyalpha-plugin-cn-ashare";
pub const PRODUCT_ID: &str = "CN_A_SHARE_CASH";
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Error(pub String);
impl fmt::Display for Error {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        output.write_str(&self.0)
    }
}
impl std::error::Error for Error {}
fn bad(code: &str) -> Error {
    Error(code.into())
}
fn boundary<T, E: fmt::Display>(value: Result<T, E>) -> Result<T, Error> {
    value.map_err(|error| Error(error.to_string()))
}
fn fields(value: &Value, required: &[&str], optional: &[&str], code: &str) -> Result<(), Error> {
    let object = value.as_object().ok_or_else(|| bad(code))?;
    if required.iter().any(|key| !object.contains_key(*key))
        || object
            .keys()
            .any(|key| !required.contains(&key.as_str()) && !optional.contains(&key.as_str()))
    {
        return Err(bad(code));
    }
    Ok(())
}
fn text<'a>(value: &'a Value, code: &str) -> Result<&'a str, Error> {
    value
        .as_str()
        .filter(|s| !s.trim().is_empty() && s.len() <= 256)
        .ok_or_else(|| bad(code))
}
fn day(value: &Value) -> Result<OnlyTradingDay, Error> {
    let parsed = boundary(OnlyTradingDay::from_record(
        &json!({"schema_version":1,"value":value}),
    ))?;
    if parsed.to_record()["value"] != *value {
        return Err(bad("REFERENCE_DATE_INVALID"));
    }
    Ok(parsed)
}
fn day_text(value: OnlyTradingDay) -> String {
    value.to_record()["value"]
        .as_str()
        .expect("Domain day")
        .into()
}
fn day_number(value: OnlyTradingDay) -> Result<u64, Error> {
    day_text(value)
        .replace('-', "")
        .parse()
        .map_err(|_| bad("FEE_DATE_INVALID"))
}
fn decimal(value: &Value, code: &str) -> Result<(OnlyDecimal, String), Error> {
    let raw = text(value, code)?;
    let number = BigDecimal::from_str(raw).map_err(|_| bad(code))?;
    let (coefficient, scale) = number.as_bigint_and_exponent();
    if number <= BigDecimal::zero()
        || coefficient.to_string().len() > 128
        || !(-18..=18).contains(&scale)
    {
        return Err(bad(code));
    }
    let canonical = number.normalized().to_plain_string();
    Ok((boundary(canonical.parse())?, canonical))
}

/// Immutable exact bundle. New native representations bind their actual Rust
/// implementation; historical Python composition digests are never substituted.
#[derive(Clone, Debug)]
pub struct Bundle {
    reference: ReferenceAuthority,
    compiler: PolicyCompiler,
    fees: FeePack,
    record: Value,
}
impl Bundle {
    pub fn reference(&self) -> &ReferenceAuthority {
        &self.reference
    }
    pub fn compiler(&self) -> &PolicyCompiler {
        &self.compiler
    }
    pub fn fees(&self) -> &FeePack {
        &self.fees
    }
    pub fn record(&self) -> Value {
        self.record.clone()
    }
    pub fn fingerprint(&self) -> String {
        digest(&self.record)
    }
}
#[derive(Clone, Copy, Debug, Default)]
pub struct Factory;
impl Factory {
    pub fn resolve(
        &self,
        plugin: &str,
        product: &str,
        version: &str,
        config: &Value,
    ) -> Result<Bundle, Error> {
        if plugin != PLUGIN_ID {
            return Err(bad("CN_A_SHARE_PROVIDER_IDENTITY_MISMATCH"));
        }
        if product != PRODUCT_ID {
            return Err(bad("UNSUPPORTED_MARKET_PRODUCT"));
        }
        let compiler = PolicyCompiler::new(version)?;
        fields(
            config,
            &["references"],
            &[],
            "INVALID_CN_A_SHARE_CONFIGURATION",
        )?;
        let values = config["references"]
            .as_array()
            .filter(|a| !a.is_empty() && a.len() <= 4096)
            .ok_or_else(|| bad("INVALID_CN_A_SHARE_CONFIGURATION"))?;
        let reference = ReferenceAuthority::new(
            values
                .iter()
                .map(Reference::from_record)
                .collect::<Result<_, _>>()?,
        )?;
        let fees = FeePack::new();
        let record = json!({"schema_version":1,"implementation":"onlyalpha-market-cn-ashare/Rust",
            "provider_plugin_id":PLUGIN_ID,"product_id":PRODUCT_ID,"product_version":version,
            "reference":reference.record(),"compiler":compiler.record(),"market_fee_pack":fees.record()});
        Ok(Bundle {
            reference,
            compiler,
            fees,
            record,
        })
    }
}
