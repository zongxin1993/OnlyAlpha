//! Native WebSocket wire types, used by the actual maintained framing adapter.
use crate::wire::strict_object;
use crate::wire::*;
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;
fn required_nullable<'de, D: serde::Deserializer<'de>, T: Deserialize<'de>>(
    d: D,
) -> Result<Option<T>, D::Error> {
    Option::deserialize(d)
}
fn present_nullable<'de, D: serde::Deserializer<'de>, T: Deserialize<'de>>(
    d: D,
) -> Result<Option<Option<T>>, D::Error> {
    Option::deserialize(d).map(Some)
}
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataStreamSourceReferenceDto {
    #[schema(min_length = 1)]
    pub integration_id: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub integration_revision_fingerprint: String,
    #[schema(min_length = 1)]
    pub expected_type_id: String,
}
strict_object!(MarketDataStreamSourceReferenceDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataBarClosedDtoEvent {
    #[serde(rename = "BAR_CLOSED")]
    BARCLOSED,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataBarClosedDto {
    pub schema_version: Version2,
    pub source_id: String,
    pub instrument_id: String,
    pub bar_semantic: MarketDataBarSemanticDto,
    pub bar: MarketDataBarDto,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub timing: Option<MarketDataIngressTimingDto>,
    pub event: MarketDataBarClosedDtoEvent,
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub sequence: String,
}
strict_object!(MarketDataBarClosedDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataBarPreviewDtoEvent {
    #[serde(rename = "BAR_PREVIEW")]
    BARPREVIEW,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataBarPreviewDto {
    pub schema_version: Version2,
    pub source_id: String,
    pub instrument_id: String,
    pub bar_semantic: MarketDataBarSemanticDto,
    pub bar: MarketDataBarDto,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub timing: Option<MarketDataIngressTimingDto>,
    pub event: MarketDataBarPreviewDtoEvent,
}
strict_object!(MarketDataBarPreviewDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataBaseCursorDtoEvent {
    #[serde(rename = "BASE_CURSOR")]
    BASECURSOR,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataBaseCursorDto {
    pub schema_version: Version2,
    pub event: MarketDataBaseCursorDtoEvent,
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub sequence: String,
}
strict_object!(MarketDataBaseCursorDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataIngressTimingDto {
    #[schema(min_length = 1)]
    pub stream_id: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub provider_event_ns: Option<String>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub ingress_received_ns: Option<String>,
}
strict_object!(MarketDataIngressTimingDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataStateDtoEvent {
    #[serde(rename = "STATE")]
    STATE,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataStateDtoState {
    #[serde(rename = "CONNECTING")]
    CONNECTING,
    #[serde(rename = "RECOVERING")]
    RECOVERING,
    #[serde(rename = "READY")]
    READY,
    #[serde(rename = "DEGRADED")]
    DEGRADED,
    #[serde(rename = "FAILED")]
    FAILED,
    #[serde(rename = "CLOSED")]
    CLOSED,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataStateDto {
    pub schema_version: Version2,
    pub event: MarketDataStateDtoEvent,
    pub state: MarketDataStateDtoState,
}
strict_object!(MarketDataStateDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataStreamErrorDtoEvent {
    #[serde(rename = "ERROR")]
    ERROR,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataStreamErrorDto {
    pub schema_version: Version2,
    pub event: MarketDataStreamErrorDtoEvent,
    pub code: String,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present_nullable"
    )]
    pub detail: Option<Option<String>>,
}
strict_object!(MarketDataStreamErrorDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataSubscribedDtoEvent {
    #[serde(rename = "SUBSCRIBED")]
    SUBSCRIBED,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataSubscribedDtoResolutionMode {
    #[serde(rename = "PROVIDER_NATIVE")]
    PROVIDERNATIVE,
    #[serde(rename = "DERIVED")]
    DERIVED,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataSubscribedDto {
    pub schema_version: Version2,
    pub event: MarketDataSubscribedDtoEvent,
    pub stream_id: String,
    pub source_id: String,
    pub instrument_id: String,
    pub resolution_mode: MarketDataSubscribedDtoResolutionMode,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub resolution_plan_fingerprint: String,
    #[schema(minimum = 1, maximum = 240)]
    pub cursor_bar_stride_minutes: i64,
}
strict_object!(MarketDataSubscribedDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum StreamSubscribeOperation {
    #[serde(rename = "SUBSCRIBE_BAR")]
    SUBSCRIBEBAR,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct StreamSubscribe {
    pub schema_version: Version2,
    pub operation: StreamSubscribeOperation,
    pub source_reference: MarketDataStreamSourceReferenceDto,
    #[schema(min_length = 1)]
    pub instrument_id: String,
    pub bar_semantic: MarketDataBarSemanticDto,
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub resume_after_sequence: String,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present_nullable"
    )]
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub resume_plan_fingerprint: Option<Option<String>>,
}
strict_object!(StreamSubscribe);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(untagged)]
pub enum StreamEvent {
    Variant0(MarketDataSubscribedDto),
    Variant1(MarketDataStateDto),
    Variant2(MarketDataBaseCursorDto),
    Variant3(MarketDataBarPreviewDto),
    Variant4(MarketDataBarClosedDto),
    Variant5(MarketDataStreamErrorDto),
}

/// Pure owned WS type registry, independent of all Host resources.
#[derive(utoipa::OpenApi)]
#[openapi(components(schemas(StreamSubscribe, StreamEvent)))]
struct StreamContract;
pub fn document() -> serde_json::Value {
    use utoipa::{OpenApi, ToSchema};
    serde_json::json!({"contract":StreamContract::openapi(),"message_roots":{"subscribe":StreamSubscribe::name(),"event":StreamEvent::name()}})
}
