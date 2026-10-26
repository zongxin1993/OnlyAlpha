//! Binance configuration authoring and public Spot REST. Product owns admission,
//! persistence and publication; provider I/O remains inside this plugin.
use onlyalpha_integration_contract::{
    Category, Descriptor, Error,
    authoring::{PluginProjection, Registration},
};
use onlyalpha_metadata_json as metadata;
use serde_json::value::RawValue;

const SPOT_DESCRIPTOR: &str = r#"{"capabilities":["CALENDARS","HISTORICAL_BARS","INSTRUMENTS","LIVE_BARS","LIVE_RECONNECT","SUPPORTS_RUNTIME_CHECKPOINT:STATELESS"],"category":"DATA_SOURCE","configuration_contract":{"fields":[{"advanced":false,"default":"PUBLIC_MARKET_DATA","description":"","display_name":"Endpoint Profile","enum_values":["API1","API2","API3","API4","DEFAULT","GCP","PUBLIC_MARKET_DATA","STANDARD"],"exclusive_minimum":false,"field_id":"endpoint_profile","maximum":null,"minimum":null,"required":false,"secret":false,"value_kind":"ENUM"},{"advanced":false,"default":"GLOBAL","description":"","display_name":"Market Environment","enum_values":["GLOBAL","SPOT_TESTNET","US"],"exclusive_minimum":false,"field_id":"environment","maximum":null,"minimum":null,"required":false,"secret":false,"value_kind":"ENUM"},{"advanced":true,"default":8388608,"description":"","display_name":"Maximum response bytes","enum_values":[],"exclusive_minimum":false,"field_id":"max_response_bytes","maximum":null,"minimum":1,"required":false,"secret":false,"value_kind":"INTEGER"},{"advanced":true,"default":1048576,"description":"","display_name":"Maximum WebSocket message bytes","enum_values":[],"exclusive_minimum":false,"field_id":"max_ws_message_bytes","maximum":null,"minimum":1,"required":false,"secret":false,"value_kind":"INTEGER"},{"advanced":true,"default":120,"description":"","display_name":"Maximum realtime resume bars","enum_values":[],"exclusive_minimum":false,"field_id":"realtime_resume_max_bars","maximum":1000,"minimum":1,"required":false,"secret":false,"value_kind":"INTEGER"},{"advanced":true,"default":0.5,"description":"","display_name":"Initial reconnect delay","enum_values":[],"exclusive_minimum":true,"field_id":"reconnect_initial_seconds","maximum":300.0,"minimum":0.0,"required":false,"secret":false,"value_kind":"DURATION"},{"advanced":true,"default":30.0,"description":"","display_name":"Maximum reconnect delay","enum_values":[],"exclusive_minimum":true,"field_id":"reconnect_max_seconds","maximum":300.0,"minimum":0.0,"required":false,"secret":false,"value_kind":"DURATION"},{"advanced":true,"default":100000,"description":"","display_name":"Recovery buffer events","enum_values":[],"exclusive_minimum":false,"field_id":"recovery_buffer_max_events","maximum":null,"minimum":1,"required":false,"secret":false,"value_kind":"INTEGER"},{"advanced":true,"default":1000,"description":"","display_name":"REST page size","enum_values":[],"exclusive_minimum":false,"field_id":"rest_page_size","maximum":1000,"minimum":1,"required":false,"secret":false,"value_kind":"INTEGER"},{"advanced":true,"default":10.0,"description":"","display_name":"Request timeout","enum_values":[],"exclusive_minimum":true,"field_id":"timeout_seconds","maximum":30.0,"minimum":0.0,"required":false,"secret":false,"value_kind":"DURATION"}],"fingerprint":"e80cded8771a4c2256c08899f1250dee5149477af8bfc13e9ead6e44c3df78b3","schema_version":1},"description":"Public historical, realtime, reference, and calendar data for Binance Spot.","display_name":"Binance Spot Market Data","implementation_id":"binance-native","implementation_version":"0.11.0","probe_contract":{"default_probe_instrument":"BTCUSDT","fingerprint":"14603270e1e1e263a2e2a5a1e71960a229efb38e99b491d752e748afc7dab1d5","probe_checks":["CONNECTIVITY","HISTORICAL_DATA","REALTIME_DATA","REFERENCE_DATA"],"probe_mode":"DEFAULT_INSTRUMENT","probe_version":1,"user_selectable_probe_instrument":true},"provider_id":"binance","public_api_version":"1.1","schema_version":1,"type_id":"binance.spot.market_data"}"#;
/// Exact installed authoring declaration and real provider validation function.
pub fn spot_authoring(work: usize) -> Result<Registration, Error> {
    Registration::new(
        PluginProjection::new(
            Category::DataSource,
            "binance-native",
            "0.11.0",
            "1.1",
            vec![
                "CALENDARS".into(),
                "HISTORICAL_BARS".into(),
                "INSTRUMENTS".into(),
                "LIVE_BARS".into(),
                "LIVE_RECONNECT".into(),
                "SUPPORTS_RUNTIME_CHECKPOINT:STATELESS".into(),
            ],
        )?,
        Descriptor::from_json(SPOT_DESCRIPTOR, work)?,
        validate_spot,
    )
}

const USDM_DESCRIPTOR: &str = r#"{"capabilities":["CALENDARS","HISTORICAL_BARS","HISTORICAL_FUNDING_RATES","HISTORICAL_REFERENCE_PRICES","INSTRUMENTS","SUPPORTS_RUNTIME_CHECKPOINT:STATELESS"],"category":"DATA_SOURCE","configuration_contract":{"fields":[{"advanced":true,"default":8388608,"description":"","display_name":"Maximum response bytes","enum_values":[],"exclusive_minimum":false,"field_id":"max_response_bytes","maximum":null,"minimum":1,"required":false,"secret":false,"value_kind":"INTEGER"},{"advanced":true,"default":"https://fapi.binance.com","description":"","display_name":"REST base URL","enum_values":[],"exclusive_minimum":false,"field_id":"rest_base_url","maximum":null,"minimum":null,"required":false,"secret":false,"value_kind":"STRING"},{"advanced":true,"default":1000,"description":"","display_name":"REST page size","enum_values":[],"exclusive_minimum":false,"field_id":"rest_page_size","maximum":1500,"minimum":1,"required":false,"secret":false,"value_kind":"INTEGER"},{"advanced":true,"default":10.0,"description":"","display_name":"Request timeout","enum_values":[],"exclusive_minimum":true,"field_id":"timeout_seconds","maximum":30.0,"minimum":0.0,"required":false,"secret":false,"value_kind":"DURATION"}],"fingerprint":"39a3e01fd2ccbb85d9457199c3017495495b4001f2c56eee3ee92b999b294f7d","schema_version":1},"description":"Public historical market and reference data for Binance USD-M Futures.","display_name":"Binance USD-M Market Data","implementation_id":"binance-usdm","implementation_version":"0.9.8","probe_contract":null,"provider_id":"binance","public_api_version":"1.1","schema_version":1,"type_id":"binance.usdm.market_data"}"#;
/// Exact installed authoring declaration and real provider validation function.
pub fn usdm_authoring(work: usize) -> Result<Registration, Error> {
    Registration::new(
        PluginProjection::new(
            Category::DataSource,
            "binance-usdm",
            "0.9.8",
            "1.1",
            vec![
                "CALENDARS".into(),
                "HISTORICAL_BARS".into(),
                "HISTORICAL_FUNDING_RATES".into(),
                "HISTORICAL_REFERENCE_PRICES".into(),
                "INSTRUMENTS".into(),
                "SUPPORTS_RUNTIME_CHECKPOINT:STATELESS".into(),
            ],
        )?,
        Descriptor::from_json(USDM_DESCRIPTOR, work)?,
        validate_usdm,
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

fn validate_spot(input: &RawValue, _: usize) -> Result<(), Error> {
    let values = metadata::object_fields(input.get()).map_err(configuration_error)?;
    let environment = values
        .get("environment")
        .map(|value| string(value))
        .transpose()?
        .unwrap_or_else(|| "GLOBAL".into());
    let default_profile = if environment == "GLOBAL" {
        "PUBLIC_MARKET_DATA"
    } else {
        "DEFAULT"
    };
    let profile = values
        .get("endpoint_profile")
        .map(|value| string(value))
        .transpose()?
        .unwrap_or_else(|| default_profile.into());
    let supported = match environment.as_str() {
        "GLOBAL" => matches!(
            profile.as_str(),
            "PUBLIC_MARKET_DATA" | "STANDARD" | "GCP" | "API1" | "API2" | "API3" | "API4"
        ),
        "US" => profile == "DEFAULT",
        "SPOT_TESTNET" => matches!(profile.as_str(), "DEFAULT" | "GCP"),
        _ => false,
    };
    let initial = values
        .get("reconnect_initial_seconds")
        .map(|v| v.get().parse::<f64>().map_err(|_| Error::Configuration))
        .transpose()?
        .unwrap_or(0.5);
    let maximum = values
        .get("reconnect_max_seconds")
        .map(|v| v.get().parse::<f64>().map_err(|_| Error::Configuration))
        .transpose()?
        .unwrap_or(30.0);
    if !supported || !(0.0 < initial && initial <= maximum && maximum <= 300.0) {
        return Err(Error::Configuration);
    }
    Ok(())
}
fn validate_usdm(input: &RawValue, _: usize) -> Result<(), Error> {
    let values = metadata::object_fields(input.get()).map_err(configuration_error)?;
    let base = values
        .get("rest_base_url")
        .map(|v| string(v))
        .transpose()?
        .unwrap_or_else(|| "https://fapi.binance.com".into());
    // http 1.5.0 limits an owned URI to u16::MAX-1 bytes. This is a parser
    // resource limit, not evidence that a larger configuration is malformed.
    if base.len() > usize::from(u16::MAX) - 1 {
        return Err(Error::Unavailable);
    }
    let uri = base
        .parse::<http::Uri>()
        .map_err(|_| Error::Configuration)?;
    let authority = uri.authority().ok_or(Error::Configuration)?;
    if uri.scheme_str() != Some("https")
        || authority.host().is_empty()
        || authority.as_str().contains(['@', '%'])
        || uri.query().is_some()
        || base.contains('#')
        || (authority.as_str() != authority.host() && !authority.port_u16().is_some_and(|p| p > 0))
    {
        return Err(Error::Configuration);
    }
    Ok(())
}

pub mod spot_rest;

pub mod spot_normalize;

pub mod spot_source;
/// Pure market-identity witness for reading immutable original Source history.
/// This validates the ORIGINAL declaration/value kinds; it neither constructs
/// a current Resource nor qualifies an old descriptor for new provider work.
pub fn spot_history_identity(
    descriptor: &Descriptor,
    configuration: &RawValue,
) -> Result<onlyalpha_integration_contract::source::MarketIdentity, Error> {
    if descriptor.id().value() != "binance.spot.market_data"
        || descriptor.category() != Category::DataSource
    {
        return Err(Error::Type);
    }
    let fields = metadata::object_fields(configuration.get()).map_err(configuration_error)?;
    for (name, value) in &fields {
        let field = descriptor
            .fields()
            .iter()
            .find(|f| f.id() == name)
            .ok_or(Error::Configuration)?;
        if field.secret() || !field.accepts(value) {
            return Err(Error::Configuration);
        }
    }
    if descriptor
        .fields()
        .iter()
        .any(|f| f.required() && !f.secret() && !fields.contains_key(f.id()))
    {
        return Err(Error::Configuration);
    }
    let environment = fields
        .get("environment")
        .map(|v| string(v))
        .transpose()?
        .ok_or(Error::Configuration)?;
    let profile = fields
        .get("endpoint_profile")
        .map(|v| string(v))
        .transpose()?
        .ok_or(Error::Configuration)?;
    let source = match (environment.as_str(), profile.as_str()) {
        (
            "GLOBAL",
            "PUBLIC_MARKET_DATA" | "STANDARD" | "GCP" | "API1" | "API2" | "API3" | "API4",
        ) => "binance.spot.market_data.live",
        ("US", "DEFAULT") => "binance.spot.market_data.us",
        ("SPOT_TESTNET", "DEFAULT" | "GCP") => "binance.spot.market_data.spot_testnet",
        _ => return Err(Error::Configuration),
    };
    Ok(onlyalpha_integration_contract::source::MarketIdentity {
        provider: "binance".into(),
        venue: "BINANCE".into(),
        market: "SPOT".into(),
        environment,
        source_id: source.into(),
    })
}
