//! Compiled public configuration authoring only. No runtime or Probe admission.
use onlyalpha_integration_contract::{
    Category, Descriptor, Error,
    authoring::{PluginProjection, Registration},
};
use onlyalpha_metadata_json as metadata;
use serde_json::value::RawValue;

const DAILY_DESCRIPTOR: &str = r#"{"capabilities":["CALENDARS","HISTORICAL_BARS","INSTRUMENTS","SUPPORTS_RUNTIME_CHECKPOINT:STATELESS"],"category":"DATA_SOURCE","configuration_contract":{"fields":[{"advanced":false,"default":"none","description":"","display_name":"Price adjustment","enum_values":["hfq","none","qfq"],"exclusive_minimum":false,"field_id":"adjustment","maximum":null,"minimum":null,"required":false,"secret":false,"value_kind":"ENUM"},{"advanced":true,"default":"prefer_cache","description":"","display_name":"Historical cache policy","enum_values":["cache_only","force_refresh","prefer_cache"],"exclusive_minimum":false,"field_id":"cache_policy","maximum":null,"minimum":null,"required":false,"secret":false,"value_kind":"ENUM"},{"advanced":false,"default":"1d","description":"","display_name":"Frequency","enum_values":["1d"],"exclusive_minimum":false,"field_id":"frequency","maximum":null,"minimum":null,"required":false,"secret":false,"value_kind":"ENUM"},{"advanced":true,"default":true,"description":"","display_name":"Strict validation","enum_values":[],"exclusive_minimum":false,"field_id":"strict_validation","maximum":null,"minimum":null,"required":false,"secret":false,"value_kind":"BOOLEAN"},{"advanced":false,"default":null,"description":"","display_name":"Token","enum_values":[],"exclusive_minimum":false,"field_id":"token","maximum":null,"minimum":null,"required":true,"secret":true,"value_kind":"STRING"}],"fingerprint":"555d8bb154881a3ee7647fec8d556e4b33418241df093b34ff4b011f2f110cfd","schema_version":1},"description":"Authenticated daily historical market data from Tushare.","display_name":"Tushare Daily Market Data","implementation_id":"tushare","implementation_version":"0.1.0","probe_contract":{"default_probe_instrument":"000001.SZ","fingerprint":"5ae4704cedae6aed148c25553fe87808de1a82281a57c4e0373f29186b4aa489","probe_checks":["AUTHENTICATION","CONNECTIVITY","HISTORICAL_DATA"],"probe_mode":"DEFAULT_INSTRUMENT","probe_version":1,"user_selectable_probe_instrument":true},"provider_id":"tushare","public_api_version":"1.1","schema_version":1,"type_id":"tushare.daily.market_data"}"#;
/// Exact installed authoring declaration and real provider validation function.
pub fn daily_authoring(work: usize) -> Result<Registration, Error> {
    Registration::new(
        PluginProjection::new(
            Category::DataSource,
            "tushare",
            "0.1.0",
            "1.1",
            vec![
                "CALENDARS".into(),
                "HISTORICAL_BARS".into(),
                "INSTRUMENTS".into(),
                "SUPPORTS_RUNTIME_CHECKPOINT:STATELESS".into(),
            ],
        )?,
        Descriptor::from_json(DAILY_DESCRIPTOR, work)?,
        validate_daily,
    )
}

fn configuration_error(error: metadata::Error) -> Error {
    match error {
        metadata::Error::Invalid => Error::Configuration,
        metadata::Error::Unavailable => Error::Unavailable,
    }
}
fn string(value: &RawValue) -> Result<String, Error> {
    serde_json::from_str(value.get()).map_err(|_| Error::Configuration)
}

fn validate_daily(input: &RawValue, _: usize) -> Result<(), Error> {
    let values = metadata::object_fields(input.get()).map_err(configuration_error)?;
    // This implementation supports daily bars and these explicit adjustment/
    // cache modes. The declaration cannot expand executable support by itself.
    for (key, raw) in values {
        let valid = match key.as_str() {
            "frequency" => string(raw)? == "1d",
            "adjustment" => matches!(string(raw)?.as_str(), "none" | "qfq" | "hfq"),
            "cache_policy" => matches!(
                string(raw)?.as_str(),
                "cache_only" | "prefer_cache" | "force_refresh"
            ),
            "strict_validation" => matches!(raw.get(), "true" | "false"),
            _ => false,
        };
        if !valid {
            return Err(Error::Configuration);
        }
    }
    Ok(())
}
