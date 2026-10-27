//! Native workstation wire DTOs. These types author the served and exported contract.
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;
// Serde's derived struct decoder also accepts positional sequences. Public JSON
// objects use the same single declaration through Serde's remote helper, with
// map-only admission at each nested declared object boundary.
macro_rules! strict_object {
    ($name:ident) => {
        impl serde::Serialize for $name {
            fn serialize<S: serde::Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
                Self::serialize(self, s)
            }
        }
        impl<'de> serde::Deserialize<'de> for $name {
            fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                struct Object;
                impl<'de> serde::de::Visitor<'de> for Object {
                    type Value = $name;
                    fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                        f.write_str("a JSON object")
                    }
                    fn visit_map<M: serde::de::MapAccess<'de>>(
                        self,
                        map: M,
                    ) -> Result<Self::Value, M::Error> {
                        $name::deserialize(serde::de::value::MapAccessDeserializer::new(map))
                    }
                }
                d.deserialize_map(Object)
            }
        }
    };
}
pub(crate) use strict_object;
// serde_json arbitrary-precision numbers retain their native numeric decoder
// inside untagged scalar unions; f64's generic content decoder cannot do so.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(transparent)]
pub struct JsonNumber(pub serde_json::Number);
impl utoipa::PartialSchema for JsonNumber {
    fn schema() -> utoipa::openapi::RefOr<utoipa::openapi::schema::Schema> {
        utoipa::openapi::ObjectBuilder::new()
            .schema_type(utoipa::openapi::schema::Type::Number)
            .into()
    }
}
impl utoipa::ToSchema for JsonNumber {}

/// A required JSON null, shared by decoding and the exported schema.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(transparent)]
pub struct JsonNull(pub ());
impl utoipa::PartialSchema for JsonNull {
    fn schema() -> utoipa::openapi::RefOr<utoipa::openapi::schema::Schema> {
        utoipa::openapi::ObjectBuilder::new()
            .schema_type(utoipa::openapi::schema::Type::Null)
            .into()
    }
}
impl utoipa::ToSchema for JsonNull {}

/// Required nullable fields decode explicit null but reject omission.
fn required_nullable<'de, D: serde::Deserializer<'de>, T: Deserialize<'de>>(
    d: D,
) -> Result<Option<T>, D::Error> {
    Option::deserialize(d)
}
// Output selection is ordered, but a member cannot be requested twice.
fn unique_output_members<'de, D: serde::Deserializer<'de>>(d: D) -> Result<Vec<String>, D::Error> {
    let members = Vec::<String>::deserialize(d)?;
    if members
        .iter()
        .collect::<std::collections::BTreeSet<_>>()
        .len()
        != members.len()
    {
        return Err(serde::de::Error::custom("duplicate output member"));
    }
    Ok(members)
}
// Preserve omission separately from present null on optional nullable fields.
fn present_nullable<'de, D: serde::Deserializer<'de>, T: Deserialize<'de>>(
    d: D,
) -> Result<Option<Option<T>>, D::Error> {
    Option::deserialize(d).map(Some)
}

// The same literal authors strict decoding, serialization and leaf schema.
macro_rules! integer_literal {
    ($name:ident,$value:literal) => {
        #[derive(Clone, Debug)]
        pub struct $name;
        impl serde::Serialize for $name {
            fn serialize<S: serde::Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
                s.serialize_i64($value)
            }
        }
        impl<'de> serde::Deserialize<'de> for $name {
            fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                if i64::deserialize(d)? == $value {
                    Ok(Self)
                } else {
                    Err(serde::de::Error::custom("unsupported integer literal"))
                }
            }
        }
        impl utoipa::PartialSchema for $name {
            fn schema() -> utoipa::openapi::RefOr<utoipa::openapi::schema::Schema> {
                utoipa::openapi::ObjectBuilder::new()
                    .schema_type(utoipa::openapi::schema::Type::Integer)
                    .enum_values(Some([$value]))
                    .into()
            }
        }
        impl utoipa::ToSchema for $name {}
    };
}
integer_literal!(VersionNegative999999, -999999);
integer_literal!(Version0, 0);
integer_literal!(Version1, 1);
integer_literal!(Version2, 2);
integer_literal!(Version3, 3);
integer_literal!(Version28, 28);
integer_literal!(Version2000, 2000);
integer_literal!(Version10000, 10000);
integer_literal!(Version999999, 999999);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyBooleanDtoType {
    #[serde(rename = "BOOLEAN")]
    BOOLEAN,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyBooleanDto {
    pub r#type: ChartStudyBooleanDtoType,
    pub value: bool,
}
strict_object!(ChartStudyBooleanDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyCalculationDtoBackend {
    #[serde(rename = "RESEARCH")]
    RESEARCH,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyCalculationDtoKind {
    #[serde(rename = "INDICATOR")]
    INDICATOR,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(untagged)]
pub enum ChartStudyCalculationDtoNormalizedTypedParametersItem {
    Variant0(ChartStudyIntegerDto),
    Variant1(ChartStudyStringDto),
    Variant2(ChartStudyDecimalDto),
    Variant3(ChartStudyBooleanDto),
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyCalculationDto {
    pub backend: ChartStudyCalculationDtoBackend,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub capability_projection_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub catalog_generation_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub definition_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub descriptor_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub implementation_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub invocation_implementation_fingerprint: String,
    pub kind: ChartStudyCalculationDtoKind,
    pub normalized_definition: ChartStudyDefinitionDto,
    pub normalized_typed_parameters:
        std::collections::BTreeMap<String, ChartStudyCalculationDtoNormalizedTypedParametersItem>,
    pub numeric: ChartStudyNumericDto,
    pub numeric_execution_binding: ChartStudyNumericBindingDto,
    #[schema(min_items = 1, max_items = 16)]
    pub output_members: Vec<ChartStudyOutputDto>,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub provider_content_fingerprint: String,
    #[schema(min_length = 1, max_length = 256)]
    pub provider_id: String,
    #[schema(min_length = 1, max_length = 256)]
    pub provider_version: String,
    #[schema(min_length = 1, max_length = 256)]
    pub semantic_version: String,
    #[schema(min_length = 1, max_length = 256)]
    pub type_id: String,
}
strict_object!(ChartStudyCalculationDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyCalculationRequestDtoKind {
    #[serde(rename = "INDICATOR")]
    INDICATOR,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(untagged)]
pub enum ChartStudyCalculationRequestDtoTypedParametersItem {
    Variant0(ChartStudyIntegerDto),
    Variant1(ChartStudyStringDto),
    Variant2(ChartStudyDecimalDto),
    Variant3(ChartStudyBooleanDto),
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyCalculationRequestDto {
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub expected_capability_projection_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub expected_descriptor_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub expected_implementation_fingerprint: String,
    pub kind: ChartStudyCalculationRequestDtoKind,
    #[serde(deserialize_with = "unique_output_members")]
    #[schema(value_type = std::collections::BTreeSet<String>, min_items = 1, max_items = 8)]
    pub output_members: Vec<String>,
    #[schema(min_length = 1, max_length = 256)]
    pub semantic_version: String,
    #[schema(min_length = 1, max_length = 256)]
    pub type_id: String,
    pub typed_parameters:
        std::collections::BTreeMap<String, ChartStudyCalculationRequestDtoTypedParametersItem>,
}
strict_object!(ChartStudyCalculationRequestDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyCapabilitiesDto {
    #[schema(min_items = 1, max_items = 64)]
    pub capabilities: Vec<ChartStudyCapabilityDto>,
    pub schema_version: Version2,
}
strict_object!(ChartStudyCapabilitiesDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyCapabilityDtoBackend {
    #[serde(rename = "RESEARCH")]
    RESEARCH,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyCapabilityDtoExecutionShape {
    #[serde(rename = "TIME_SERIES")]
    TIMESERIES,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyCapabilityDtoKind {
    #[serde(rename = "INDICATOR")]
    INDICATOR,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyCapabilityDto {
    pub backend: ChartStudyCapabilityDtoBackend,
    pub capability_projection: ChartStudyCapabilityProjectionDto,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub capability_projection_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub catalog_generation_fingerprint: String,
    pub descriptor: ChartStudyDescriptorDto,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub descriptor_fingerprint: String,
    pub execution_shape: ChartStudyCapabilityDtoExecutionShape,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub implementation_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub invocation_implementation_fingerprint: String,
    pub kind: ChartStudyCapabilityDtoKind,
    pub limits: ChartStudyLimitsDto,
    pub numeric_execution_binding: ChartStudyNumericBindingDto,
    #[schema(min_items = 1, max_items = 16)]
    pub output_members: Vec<String>,
    pub presentation: ChartStudyPresentationDto,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub provider_content_fingerprint: String,
    #[schema(min_length = 1, max_length = 256)]
    pub provider_id: String,
    #[schema(min_length = 1, max_length = 256)]
    pub provider_version: String,
    pub readiness_contract_version: Version1,
    #[schema(min_length = 1, max_length = 256)]
    pub semantic_version: String,
    #[schema(min_length = 1, max_length = 256)]
    pub type_id: String,
}
strict_object!(ChartStudyCapabilityDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyCapabilityProjectionDtoAuthority {
    #[serde(rename = "DISPLAY_ONLY")]
    DISPLAYONLY,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyCapabilityProjectionDtoBackend {
    #[serde(rename = "RESEARCH")]
    RESEARCH,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyCapabilityProjectionDtoDomain {
    #[serde(rename = "onlyalpha.chart-study.capability-projection")]
    OnlyalphaChartStudyCapabilityProjection,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyCapabilityProjectionDtoFiniteInitialization {
    #[serde(rename = "PARTIAL_WINDOW_AT_EXPLICIT_FINITE_START")]
    PARTIALWINDOWATEXPLICITFINITESTART,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyCapabilityProjectionDtoPublicationStatus {
    #[serde(rename = "NOT_A_RESEARCH_RESULT")]
    NOTARESEARCHRESULT,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyCapabilityProjectionDtoSourceKind {
    #[serde(rename = "CHART_STUDY_TRANSIENT")]
    CHARTSTUDYTRANSIENT,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyCapabilityProjectionDtoSupportedShape {
    #[serde(rename = "TIME_SERIES/BAR_FIELDS")]
    TIMESERIESBARFIELDS,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyCapabilityProjectionDto {
    pub authority: ChartStudyCapabilityProjectionDtoAuthority,
    pub backend: ChartStudyCapabilityProjectionDtoBackend,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub catalog_generation_fingerprint: String,
    pub descriptor: ChartStudyDescriptorDto,
    pub domain: ChartStudyCapabilityProjectionDtoDomain,
    pub finite_initialization: ChartStudyCapabilityProjectionDtoFiniteInitialization,
    pub implementation: ChartStudyManifestDto,
    pub input_support: ChartStudyInputSupportDto,
    pub invocation: ChartStudyManifestDto,
    pub limits: ChartStudyLimitsDto,
    pub numeric_binding: ChartStudyNumericBindingDto,
    #[schema(min_items = 1, max_items = 16)]
    pub output_members: Vec<String>,
    pub presentation: ChartStudyPresentationDto,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub provider_content_fingerprint: String,
    pub provider_manifest: ChartStudyProviderManifestDto,
    pub publication_status: ChartStudyCapabilityProjectionDtoPublicationStatus,
    #[schema(min_items = 1, max_items = 1)]
    pub readiness_contract_versions: Vec<Version1>,
    pub schema_version: Version2,
    pub source_kind: ChartStudyCapabilityProjectionDtoSourceKind,
    pub supported_shape: ChartStudyCapabilityProjectionDtoSupportedShape,
}
strict_object!(ChartStudyCapabilityProjectionDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyDecimalDtoType {
    #[serde(rename = "DECIMAL")]
    DECIMAL,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyDecimalDto {
    pub r#type: ChartStudyDecimalDtoType,
    #[schema(pattern = "^-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?$", max_length = 64)]
    pub value: String,
}
strict_object!(ChartStudyDecimalDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyDecimalPolicyDtoDomain {
    #[serde(rename = "onlyalpha.decimal.execution-policy")]
    OnlyalphaDecimalExecutionPolicy,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyDecimalPolicyDtoEntryFlags {
    #[serde(rename = "CLEAR")]
    CLEAR,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyDecimalPolicyDtoPolicyId {
    #[serde(rename = "onlyalpha.decimal.execution")]
    OnlyalphaDecimalExecution,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyDecimalPolicyDtoSemanticVersion {
    #[serde(rename = "1")]
    N1,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyDecimalPolicyDtoTrappedSignalsItem {
    #[serde(rename = "DivisionByZero")]
    DivisionByZero,
    #[serde(rename = "InvalidOperation")]
    InvalidOperation,
    #[serde(rename = "Overflow")]
    Overflow,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyDecimalPolicyDto {
    pub capitals: Version1,
    pub clamp: Version0,
    pub domain: ChartStudyDecimalPolicyDtoDomain,
    pub emax: Version999999,
    pub emin: VersionNegative999999,
    pub entry_flags: ChartStudyDecimalPolicyDtoEntryFlags,
    pub policy_id: ChartStudyDecimalPolicyDtoPolicyId,
    pub semantic_version: ChartStudyDecimalPolicyDtoSemanticVersion,
    #[schema(min_items = 3, max_items = 3)]
    pub trapped_signals: Vec<ChartStudyDecimalPolicyDtoTrappedSignalsItem>,
}
strict_object!(ChartStudyDecimalPolicyDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyDefinitionDtoKind {
    #[serde(rename = "INDICATOR")]
    INDICATOR,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyDefinitionDtoMissingValues {
    #[serde(rename = "FAIL")]
    FAIL,
    #[serde(rename = "PROPAGATE")]
    PROPAGATE,
    #[serde(rename = "SKIP")]
    SKIP,
    #[serde(rename = "RESET")]
    RESET,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(untagged)]
pub enum ChartStudyDefinitionDtoParametersItem {
    Null(()),
    Variant0(i64),
    Variant1(String),
    Variant2(bool),
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyDefinitionDtoTimestamp {
    #[serde(rename = "EVENT_TIME")]
    EVENTTIME,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyDefinitionDto {
    pub extensions: ChartStudyExtensionsDto,
    pub factor_kind: (),
    pub input_bindings: std::collections::BTreeMap<String, ChartStudyInputBindingDto>,
    #[schema(min_items = 1, max_items = 16)]
    pub inputs: Vec<ChartStudyPortDto>,
    pub kind: ChartStudyDefinitionDtoKind,
    pub missing_values: ChartStudyDefinitionDtoMissingValues,
    pub numeric: ChartStudyNumericDto,
    #[schema(min_items = 1, max_items = 16)]
    pub outputs: Vec<ChartStudyPortDto>,
    pub parameters: std::collections::BTreeMap<String, ChartStudyDefinitionDtoParametersItem>,
    pub schema_version: Version2,
    #[schema(min_length = 1, max_length = 256)]
    pub semantic_version: String,
    pub timestamp: ChartStudyDefinitionDtoTimestamp,
    #[schema(min_length = 1, max_length = 256)]
    pub type_id: String,
    pub warmup: ChartStudyWarmupDto,
}
strict_object!(ChartStudyDefinitionDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyDependencyDto {
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub artifact_fingerprint: Option<String>,
    #[schema(min_length = 1, max_length = 256)]
    pub dependency_id: String,
    #[schema(min_length = 1, max_length = 256)]
    pub semantic_version: String,
}
strict_object!(ChartStudyDependencyDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyDescriptorDtoExecutionShape {
    #[serde(rename = "TIME_SERIES")]
    TIMESERIES,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyDescriptorDtoKind {
    #[serde(rename = "INDICATOR")]
    INDICATOR,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyDescriptorDtoMissingValues {
    #[serde(rename = "FAIL")]
    FAIL,
    #[serde(rename = "PROPAGATE")]
    PROPAGATE,
    #[serde(rename = "SKIP")]
    SKIP,
    #[serde(rename = "RESET")]
    RESET,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyDescriptorDtoTimestamp {
    #[serde(rename = "EVENT_TIME")]
    EVENTTIME,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyDescriptorDto {
    pub execution_shape: ChartStudyDescriptorDtoExecutionShape,
    pub factor_kind: (),
    #[schema(min_items = 1, max_items = 16)]
    pub inputs: Vec<ChartStudyPortDto>,
    pub kind: ChartStudyDescriptorDtoKind,
    pub missing_values: ChartStudyDescriptorDtoMissingValues,
    pub numeric: ChartStudyNumericDto,
    #[schema(min_items = 1, max_items = 16)]
    pub outputs: Vec<ChartStudyPortDto>,
    #[schema(max_items = 16)]
    pub parameters: Vec<ChartStudyParameterDescriptorDto>,
    pub semantic_bounds: std::collections::BTreeMap<String, Option<Vec<String>>>,
    #[schema(min_length = 1, max_length = 256)]
    pub semantic_version: String,
    pub timestamp: ChartStudyDescriptorDtoTimestamp,
    #[schema(min_length = 1, max_length = 256)]
    pub type_id: String,
}
strict_object!(ChartStudyDescriptorDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyDistributionDtoKind {
    #[serde(rename = "DISTRIBUTION")]
    DISTRIBUTION,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyDistributionDto {
    #[schema(min_length = 1, max_length = 256)]
    pub distribution_name: String,
    #[schema(min_length = 1, max_length = 256)]
    pub distribution_version: String,
    pub kind: ChartStudyDistributionDtoKind,
}
strict_object!(ChartStudyDistributionDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyErrorDtoPhase {
    #[serde(rename = "QUERY")]
    QUERY,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyErrorDto {
    #[schema(min_length = 1, max_length = 256)]
    pub code: String,
    #[schema(min_length = 1, max_length = 256)]
    pub detail: String,
    pub phase: ChartStudyErrorDtoPhase,
}
strict_object!(ChartStudyErrorDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyErrorEnvelopeDto {
    pub error: ChartStudyErrorDto,
    pub schema_version: Version1,
}
strict_object!(ChartStudyErrorEnvelopeDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyEvaluateDtoAuthority {
    #[serde(rename = "DISPLAY_ONLY")]
    DISPLAYONLY,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyEvaluateDtoPublicationStatus {
    #[serde(rename = "NOT_A_RESEARCH_RESULT")]
    NOTARESEARCHRESULT,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyEvaluateDtoQueryStatus {
    #[serde(rename = "DISPLAYABLE")]
    DISPLAYABLE,
    #[serde(rename = "INPUT_INCOMPLETE")]
    INPUTINCOMPLETE,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyEvaluateDtoSourceKind {
    #[serde(rename = "CHART_STUDY_TRANSIENT")]
    CHARTSTUDYTRANSIENT,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyEvaluateDto {
    pub authority: ChartStudyEvaluateDtoAuthority,
    pub bar_semantic: MarketDataBarSemanticDto,
    pub calculation: ChartStudyCalculationDto,
    pub coverage: MarketDataCoverageDto,
    pub input: ChartStudyInputDto,
    #[schema(min_length = 1, max_length = 256)]
    pub instrument_id: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub preview: Option<ChartStudyPreviewDto>,
    pub publication_status: ChartStudyEvaluateDtoPublicationStatus,
    pub query_status: ChartStudyEvaluateDtoQueryStatus,
    pub schema_version: Version2,
    #[schema(max_items = 16)]
    pub series: Vec<ChartStudySeriesDto>,
    pub source_kind: ChartStudyEvaluateDtoSourceKind,
    pub source_selection: MarketDataSourceSelectionDto,
}
strict_object!(ChartStudyEvaluateDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyEvaluateRequestDto {
    pub bar_semantic: MarketDataBarSemanticDto,
    pub calculation: ChartStudyCalculationRequestDto,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub expected_history_projection_fingerprint: String,
    pub include_unclosed_preview: bool,
    #[schema(min_length = 1, max_length = 256)]
    pub instrument_id: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub preview_stream_id: Option<String>,
    pub schema_version: Version2,
    pub source_reference: ChartStudySourceReferenceDto,
    pub window: ChartStudyWindowDto,
}
strict_object!(ChartStudyEvaluateRequestDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyExtensionsDto {}
strict_object!(ChartStudyExtensionsDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyInputBindingDtoSource {
    #[serde(rename = "bar.open")]
    BarOpen,
    #[serde(rename = "bar.high")]
    BarHigh,
    #[serde(rename = "bar.low")]
    BarLow,
    #[serde(rename = "bar.close")]
    BarClose,
    #[serde(rename = "bar.volume")]
    BarVolume,
    #[serde(rename = "bar.start_ns")]
    BarStartNs,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyInputBindingDto {
    pub node_fingerprint: (),
    #[schema(min_length = 1, max_length = 256)]
    pub output_name: String,
    pub source: ChartStudyInputBindingDtoSource,
}
strict_object!(ChartStudyInputBindingDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyInputDtoAnchorKind {
    #[serde(rename = "BEFORE_TIME")]
    BEFORETIME,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyInputDtoInitialization {
    #[serde(rename = "FINITE_WINDOW_START")]
    FINITEWINDOWSTART,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyInputDtoResolutionMode {
    #[serde(rename = "PROVIDER_NATIVE")]
    PROVIDERNATIVE,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyInputDto {
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub aggregation_semantics_version: Option<String>,
    pub anchor_kind: ChartStudyInputDtoAnchorKind,
    #[schema(pattern = "^[1-9][0-9]{0,18}$")]
    pub before_ns: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub calendar_fingerprint: String,
    pub derived_projection_fingerprint: (),
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub history_projection_fingerprint: Option<String>,
    pub initialization: ChartStudyInputDtoInitialization,
    pub resolution_mode: ChartStudyInputDtoResolutionMode,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub resolution_plan_fingerprint: String,
    #[schema(pattern = "^[1-9][0-9]{0,18}$")]
    pub resolved_end_ns: String,
    #[schema(pattern = "^[1-9][0-9]{0,18}$")]
    pub resolved_start_ns: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub resume_after_sequence: Option<String>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub resume_plan_fingerprint: Option<String>,
    #[schema(max_items = 2000)]
    pub revision_evidence: Vec<MarketDataRevisionEvidenceDto>,
    #[schema(minimum = 1.0, maximum = 2000.0)]
    pub target_bar_count: i64,
}
strict_object!(ChartStudyInputDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyInputSupportDtoAlignment {
    #[serde(rename = "UTC_24X7")]
    UTC24X7,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyInputSupportDtoBarFormation {
    #[serde(rename = "FIXED_DURATION")]
    FIXEDDURATION,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyInputSupportDtoCoveragePolicy {
    #[serde(rename = "COMPLETE_VERIFIED_WINDOW")]
    COMPLETEVERIFIEDWINDOW,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyInputSupportDtoInstrumentPolicy {
    #[serde(rename = "EXACT_SOURCE_CATALOG")]
    EXACTSOURCECATALOG,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyInputSupportDtoPreviewMode {
    #[serde(rename = "OWNING_STREAM_SNAPSHOT")]
    OWNINGSTREAMSNAPSHOT,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyInputSupportDtoResolutionMode {
    #[serde(rename = "VERIFIED_NATIVE_OR_DERIVED")]
    VerifiedNativeOrDerived,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyInputSupportDto {
    pub alignment: ChartStudyInputSupportDtoAlignment,
    pub bar_formation: ChartStudyInputSupportDtoBarFormation,
    pub closed_only: VersionFalse,
    pub coverage_policy: ChartStudyInputSupportDtoCoveragePolicy,
    pub instrument_policy: ChartStudyInputSupportDtoInstrumentPolicy,
    pub preview_mode: ChartStudyInputSupportDtoPreviewMode,
    pub resolution_mode: ChartStudyInputSupportDtoResolutionMode,
}
strict_object!(ChartStudyInputSupportDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyIntegerDtoType {
    #[serde(rename = "INTEGER")]
    INTEGER,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyIntegerDto {
    pub r#type: ChartStudyIntegerDtoType,
    #[schema(minimum = 1.0, maximum = 10000.0)]
    pub value: i64,
}
strict_object!(ChartStudyIntegerDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyLimitsDto {
    pub max_concurrent_invocations: Version2,
    pub max_input_rows: Version2000,
    pub max_period: Version10000,
}
strict_object!(ChartStudyLimitsDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyManifestDtoBackendKind {
    #[serde(rename = "RESEARCH")]
    RESEARCH,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyManifestDto {
    pub backend_kind: ChartStudyManifestDtoBackendKind,
    pub calculation_type_reference: ChartStudyTypeReferenceDto,
    #[schema(min_length = 1, max_length = 256)]
    pub entrypoint_identity: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub implementation_bundle_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub implementation_fingerprint: String,
    #[schema(min_items = 1, max_items = 32)]
    pub resources: Vec<ChartStudyResourceDto>,
    pub schema_version: Version1,
    #[schema(min_items = 1, max_items = 8)]
    pub semantic_dependencies: Vec<ChartStudyDependencyDto>,
}
strict_object!(ChartStudyManifestDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyNumericBindingDtoDeclaredRounding {
    #[serde(rename = "CONTEXT")]
    CONTEXT,
    #[serde(rename = "ROUND_HALF_EVEN")]
    ROUNDHALFEVEN,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyNumericBindingDtoDomain {
    #[serde(rename = "onlyalpha.chart-study.decimal-binding")]
    OnlyalphaChartStudyDecimalBinding,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyNumericBindingDtoEffectiveRounding {
    #[serde(rename = "ROUND_HALF_EVEN")]
    ROUNDHALFEVEN,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyNumericBindingDtoOutputQuantum {
    #[serde(rename = "0.000000000001")]
    N0000000000001,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyNumericBindingDtoRepresentation {
    #[serde(rename = "DECIMAL")]
    DECIMAL,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyNumericBindingDtoResolutionPolicy {
    #[serde(rename = "CONTEXT_HALF_EVEN_V1")]
    CONTEXTHALFEVENV1,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyNumericBindingDto {
    pub core_policy: ChartStudyDecimalPolicyDto,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub core_policy_fingerprint: String,
    pub declared_rounding: ChartStudyNumericBindingDtoDeclaredRounding,
    pub domain: ChartStudyNumericBindingDtoDomain,
    pub effective_rounding: ChartStudyNumericBindingDtoEffectiveRounding,
    pub output_quantum: ChartStudyNumericBindingDtoOutputQuantum,
    pub precision: Version28,
    pub representation: ChartStudyNumericBindingDtoRepresentation,
    pub resolution_policy: ChartStudyNumericBindingDtoResolutionPolicy,
    pub schema_version: Version1,
}
strict_object!(ChartStudyNumericBindingDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyNumericDtoOutputQuantum {
    #[serde(rename = "0.000000000001")]
    N0000000000001,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyNumericDtoRepresentation {
    #[serde(rename = "DECIMAL")]
    DECIMAL,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyNumericDtoRounding {
    #[serde(rename = "CONTEXT")]
    CONTEXT,
    #[serde(rename = "ROUND_HALF_EVEN")]
    ROUNDHALFEVEN,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyNumericDto {
    pub output_quantum: ChartStudyNumericDtoOutputQuantum,
    pub precision: Version28,
    pub representation: ChartStudyNumericDtoRepresentation,
    pub rounding: ChartStudyNumericDtoRounding,
}
strict_object!(ChartStudyNumericDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyOutputDtoDataType {
    #[serde(rename = "DECIMAL")]
    DECIMAL,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyOutputDtoUnit {
    #[serde(rename = "PRICE")]
    PRICE,
    #[serde(rename = "RATIO")]
    RATIO,
    #[serde(rename = "VOLUME")]
    VOLUME,
    #[serde(rename = "SCALAR")]
    SCALAR,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyOutputDto {
    pub data_type: ChartStudyOutputDtoDataType,
    #[schema(min_length = 1, max_length = 256)]
    pub name: String,
    pub nullable: bool,
    pub unit: ChartStudyOutputDtoUnit,
}
strict_object!(ChartStudyOutputDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(untagged)]
pub enum ChartStudyParameterDescriptorDtoDefault {
    Variant0(i64),
    Variant1(String),
    Variant2(bool),
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(untagged)]
pub enum ChartStudyParameterDescriptorDtoEnumValuesItem {
    Variant0(i64),
    Variant1(String),
    Variant2(bool),
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(untagged)]
pub enum ChartStudyParameterDescriptorDtoMaximum {
    Variant0(i64),
    Variant1(String),
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(untagged)]
pub enum ChartStudyParameterDescriptorDtoMinimum {
    Variant0(i64),
    Variant1(String),
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyParameterDescriptorDtoParameterType {
    #[serde(rename = "INTEGER")]
    INTEGER,
    #[serde(rename = "STRING")]
    STRING,
    #[serde(rename = "DECIMAL")]
    DECIMAL,
    #[serde(rename = "BOOLEAN")]
    BOOLEAN,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyParameterDescriptorDto {
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub r#default: Option<ChartStudyParameterDescriptorDtoDefault>,
    #[schema(max_items = 32)]
    pub enum_values: Vec<Option<ChartStudyParameterDescriptorDtoEnumValuesItem>>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub maximum: Option<ChartStudyParameterDescriptorDtoMaximum>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub minimum: Option<ChartStudyParameterDescriptorDtoMinimum>,
    #[schema(min_length = 1, max_length = 256)]
    pub name: String,
    pub parameter_type: ChartStudyParameterDescriptorDtoParameterType,
    pub required: bool,
    pub uppercase: bool,
}
strict_object!(ChartStudyParameterDescriptorDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyPointDtoQuality {
    #[serde(rename = "CLOSED_COMPLETE")]
    CLOSEDCOMPLETE,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyPointDtoReadiness {
    #[serde(rename = "PARTIAL")]
    PARTIAL,
    #[serde(rename = "READY")]
    READY,
    #[serde(rename = "UNAVAILABLE")]
    UNAVAILABLE,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyPointDtoReason {
    #[serde(rename = "NONE")]
    NONE,
    #[serde(rename = "WARMUP_INCOMPLETE")]
    WARMUPINCOMPLETE,
    #[serde(rename = "VALUE_UNDEFINED")]
    VALUEUNDEFINED,
    #[serde(rename = "INPUT_UNAVAILABLE")]
    INPUTUNAVAILABLE,
    #[serde(rename = "DEPENDENCY_UNAVAILABLE")]
    DEPENDENCYUNAVAILABLE,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyPointDto {
    pub closed: VersionTrue,
    pub quality: ChartStudyPointDtoQuality,
    pub readiness: ChartStudyPointDtoReadiness,
    pub reason: ChartStudyPointDtoReason,
    #[schema(pattern = "^[1-9][0-9]{0,18}$")]
    pub time_ns: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub value: Option<String>,
}
strict_object!(ChartStudyPointDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyPortDtoDataType {
    #[serde(rename = "DECIMAL")]
    DECIMAL,
    #[serde(rename = "INTEGER")]
    INTEGER,
    #[serde(rename = "STRING")]
    STRING,
    #[serde(rename = "BOOLEAN")]
    BOOLEAN,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyPortDtoDimensionsItem {
    #[serde(rename = "TIME")]
    TIME,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyPortDto {
    pub data_type: ChartStudyPortDtoDataType,
    #[schema(min_items = 1, max_items = 1)]
    pub dimensions: Vec<ChartStudyPortDtoDimensionsItem>,
    #[schema(min_length = 1, max_length = 256)]
    pub name: String,
    pub nullable: bool,
    #[schema(min_length = 1, max_length = 256)]
    pub semantic_type: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub unit: Option<String>,
}
strict_object!(ChartStudyPortDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(untagged)]
pub enum ChartStudyPresentationDtoDefaultParametersItem {
    Variant0(i64),
    Variant1(String),
    Variant2(bool),
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyPresentationDtoPlacement {
    #[serde(rename = "PRICE_OVERLAY")]
    PRICEOVERLAY,
    #[serde(rename = "SEPARATE_PANE")]
    SEPARATEPANE,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyPresentationDto {
    #[schema(min_length = 1, max_length = 256)]
    pub category: String,
    pub default_parameters:
        std::collections::BTreeMap<String, ChartStudyPresentationDtoDefaultParametersItem>,
    pub default_variant: bool,
    #[schema(min_length = 1, max_length = 256)]
    pub display_name: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub fill: Option<Vec<String>>,
    pub placement: ChartStudyPresentationDtoPlacement,
    pub preview_supported: bool,
    #[schema(min_items = 1, max_items = 16)]
    pub series: Vec<ChartStudyPresentationSeriesDto>,
}
strict_object!(ChartStudyPresentationDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyPresentationSeriesDtoKind {
    #[serde(rename = "LINE")]
    LINE,
    #[serde(rename = "HISTOGRAM")]
    HISTOGRAM,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyPresentationSeriesDtoUnit {
    #[serde(rename = "PRICE")]
    PRICE,
    #[serde(rename = "RATIO")]
    RATIO,
    #[serde(rename = "VOLUME")]
    VOLUME,
    #[serde(rename = "SCALAR")]
    SCALAR,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyPresentationSeriesDto {
    #[schema(pattern = "^#[0-9A-Fa-f]{6}$")]
    pub color: String,
    pub default_visible: bool,
    pub kind: ChartStudyPresentationSeriesDtoKind,
    #[schema(min_length = 1, max_length = 256)]
    pub label: String,
    #[schema(min_length = 1, max_length = 256)]
    pub output_name: String,
    pub unit: ChartStudyPresentationSeriesDtoUnit,
}
strict_object!(ChartStudyPresentationSeriesDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyPreviewDtoSourceKind {
    #[serde(rename = "PREVIEW_UNCLOSED")]
    PREVIEWUNCLOSED,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyPreviewDto {
    #[schema(pattern = "^[1-9][0-9]{0,18}$")]
    pub bar_end_ns: String,
    #[schema(pattern = "^[1-9][0-9]{0,18}$")]
    pub bar_start_ns: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub revision_fingerprint: String,
    #[schema(min_items = 1, max_items = 16)]
    pub series: Vec<ChartStudyPreviewSeriesDto>,
    pub source_kind: ChartStudyPreviewDtoSourceKind,
    #[schema(min_length = 1, max_length = 256)]
    pub stream_id: String,
}
strict_object!(ChartStudyPreviewDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyPreviewPointDtoQuality {
    #[serde(rename = "PREVIEW_UNCLOSED")]
    PREVIEWUNCLOSED,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyPreviewPointDtoReadiness {
    #[serde(rename = "PARTIAL")]
    PARTIAL,
    #[serde(rename = "READY")]
    READY,
    #[serde(rename = "UNAVAILABLE")]
    UNAVAILABLE,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyPreviewPointDtoReason {
    #[serde(rename = "NONE")]
    NONE,
    #[serde(rename = "WARMUP_INCOMPLETE")]
    WARMUPINCOMPLETE,
    #[serde(rename = "VALUE_UNDEFINED")]
    VALUEUNDEFINED,
    #[serde(rename = "INPUT_UNAVAILABLE")]
    INPUTUNAVAILABLE,
    #[serde(rename = "DEPENDENCY_UNAVAILABLE")]
    DEPENDENCYUNAVAILABLE,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyPreviewPointDto {
    pub closed: VersionFalse,
    pub quality: ChartStudyPreviewPointDtoQuality,
    pub readiness: ChartStudyPreviewPointDtoReadiness,
    pub reason: ChartStudyPreviewPointDtoReason,
    #[schema(pattern = "^[1-9][0-9]{0,18}$")]
    pub time_ns: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub value: Option<String>,
}
strict_object!(ChartStudyPreviewPointDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyPreviewSeriesDto {
    #[schema(min_length = 1, max_length = 256)]
    pub output_name: String,
    pub point: ChartStudyPreviewPointDto,
}
strict_object!(ChartStudyPreviewSeriesDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyProviderManifestDtoKind {
    #[serde(rename = "INDICATOR")]
    INDICATOR,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyProviderManifestDto {
    pub kind: ChartStudyProviderManifestDtoKind,
    #[schema(min_length = 1, max_length = 256)]
    pub provider_id: String,
    #[schema(min_length = 1, max_length = 256)]
    pub provider_version: String,
    pub schema_version: Version1,
    pub source: ChartStudyDistributionDto,
}
strict_object!(ChartStudyProviderManifestDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyResourceDto {
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub byte_sha256: String,
    #[schema(min_length = 1, max_length = 256)]
    pub relative_path: String,
}
strict_object!(ChartStudyResourceDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudySeriesDto {
    #[schema(min_length = 1, max_length = 256)]
    pub output_name: String,
    #[schema(min_items = 1, max_items = 2000)]
    pub points: Vec<ChartStudyPointDto>,
}
strict_object!(ChartStudySeriesDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudySourceReferenceDto {
    #[schema(min_length = 1, max_length = 256)]
    pub expected_type_id: String,
    #[schema(min_length = 1, max_length = 256)]
    pub integration_id: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub integration_revision_fingerprint: String,
}
strict_object!(ChartStudySourceReferenceDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyStringDtoType {
    #[serde(rename = "STRING")]
    STRING,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyStringDto {
    pub r#type: ChartStudyStringDtoType,
    #[schema(min_length = 1, max_length = 256)]
    pub value: String,
}
strict_object!(ChartStudyStringDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyTypeReferenceDtoKind {
    #[serde(rename = "INDICATOR")]
    INDICATOR,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyTypeReferenceDto {
    pub kind: ChartStudyTypeReferenceDtoKind,
    #[schema(min_length = 1, max_length = 256)]
    pub semantic_version: String,
    #[schema(min_length = 1, max_length = 256)]
    pub type_id: String,
}
strict_object!(ChartStudyTypeReferenceDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyWarmupDtoPreReadyOutput {
    #[serde(rename = "PARTIAL")]
    PARTIAL,
    #[serde(rename = "NULL")]
    NULL,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyWarmupDto {
    #[schema(min_length = 1, max_length = 256)]
    pub initialization: String,
    #[schema(minimum = 1.0, maximum = 10000.0)]
    pub minimum_observations: i64,
    pub pre_ready_output: ChartStudyWarmupDtoPreReadyOutput,
    #[schema(min_length = 1, max_length = 256)]
    pub ready_condition: String,
}
strict_object!(ChartStudyWarmupDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ChartStudyWindowDtoAnchorKind {
    #[serde(rename = "BEFORE_TIME")]
    BEFORETIME,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ChartStudyWindowDto {
    pub anchor_kind: ChartStudyWindowDtoAnchorKind,
    #[schema(pattern = "^[1-9][0-9]{0,18}$")]
    pub before_ns: String,
    #[schema(minimum = 1.0, maximum = 2000.0)]
    pub target_bar_count: i64,
}
strict_object!(ChartStudyWindowDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationCommandResponseDto {
    pub command_id: String,
    pub integration_id: String,
    pub outcome_id: String,
    pub outcome_kind: String,
    pub replayed: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schema_version: Option<Version1>,
}
strict_object!(IntegrationCommandResponseDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationConfigurationContractDto {
    pub fields: Vec<IntegrationConfigurationFieldDto>,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub fingerprint: String,
    pub schema_version: Version1,
}
strict_object!(IntegrationConfigurationContractDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(untagged)]
pub enum IntegrationConfigurationFieldDtoDefault {
    Variant0(String),
    Variant2(JsonNumber),
    Variant3(bool),
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(untagged)]
pub enum IntegrationConfigurationFieldDtoMaximum {
    Variant1(JsonNumber),
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(untagged)]
pub enum IntegrationConfigurationFieldDtoMinimum {
    Variant1(JsonNumber),
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationConfigurationFieldDto {
    pub advanced: bool,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub r#default: Option<IntegrationConfigurationFieldDtoDefault>,
    pub description: String,
    pub display_name: String,
    pub enum_values: Vec<String>,
    pub exclusive_minimum: bool,
    pub field_id: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub maximum: Option<IntegrationConfigurationFieldDtoMaximum>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub minimum: Option<IntegrationConfigurationFieldDtoMinimum>,
    pub required: bool,
    pub secret: bool,
    pub value_kind: OnlyIntegrationValueKind,
}
strict_object!(IntegrationConfigurationFieldDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationCreateRequestDto {
    pub display_name: String,
    pub integration_id: String,
    pub schema_version: Version1,
    pub type_id: String,
}
strict_object!(IntegrationCreateRequestDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationDraftContractResetRequestDto {
    #[schema(minimum = 1.0)]
    pub expected_draft_version: i64,
    pub schema_version: Version1,
}
strict_object!(IntegrationDraftContractResetRequestDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationDraftDto {
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present_nullable"
    )]
    pub base_revision_fingerprint: Option<Option<String>>,
    pub created_at: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub draft_fingerprint: String,
    pub draft_version: i64,
    pub integration_id: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub pinned_type_descriptor_fingerprint: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub probe_configuration: Option<std::collections::BTreeMap<String, JsonValue>>,
    pub public_configuration: std::collections::BTreeMap<String, JsonValue>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schema_version: Option<Version1>,
    pub secret_statuses: Vec<IntegrationSecretStatusDto>,
    pub type_descriptor: IntegrationTypeDto,
    pub updated_at: String,
}
strict_object!(IntegrationDraftDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationDraftUpdateRequestDto {
    #[schema(minimum = 1.0)]
    pub expected_draft_version: i64,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub probe_configuration: Option<std::collections::BTreeMap<String, JsonValue>>,
    pub public_configuration: std::collections::BTreeMap<String, JsonValue>,
    pub schema_version: Version1,
}
strict_object!(IntegrationDraftUpdateRequestDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationDto {
    pub created_at: String,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present_nullable"
    )]
    pub current_revision_fingerprint: Option<Option<String>>,
    pub display_name: String,
    pub integration_id: String,
    pub lifecycle_state: OnlyIntegrationLifecycleState,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schema_version: Option<Version1>,
    pub type_id: String,
    pub updated_at: String,
}
strict_object!(IntegrationDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationErrorDto {
    pub code: String,
    pub detail: String,
}
strict_object!(IntegrationErrorDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationErrorEnvelopeDto {
    pub error: IntegrationErrorDto,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schema_version: Option<Version1>,
}
strict_object!(IntegrationErrorEnvelopeDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum IntegrationLifecycleUpdateRequestDtoExpectedLifecycleState {
    #[serde(rename = "ACTIVE")]
    ACTIVE,
    #[serde(rename = "DISABLED")]
    DISABLED,
    #[serde(rename = "ARCHIVED")]
    ARCHIVED,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum IntegrationLifecycleUpdateRequestDtoLifecycleState {
    #[serde(rename = "ACTIVE")]
    ACTIVE,
    #[serde(rename = "DISABLED")]
    DISABLED,
    #[serde(rename = "ARCHIVED")]
    ARCHIVED,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationLifecycleUpdateRequestDto {
    pub expected_lifecycle_state: IntegrationLifecycleUpdateRequestDtoExpectedLifecycleState,
    pub lifecycle_state: IntegrationLifecycleUpdateRequestDtoLifecycleState,
    pub schema_version: Version1,
}
strict_object!(IntegrationLifecycleUpdateRequestDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationListDto {
    pub items: Vec<IntegrationSummaryDto>,
}
strict_object!(IntegrationListDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationOperationalStatusDto {
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub checked_at: Option<String>,
    pub integration_id: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub probe_attempt_id: Option<String>,
    pub probe_supported: bool,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present_nullable"
    )]
    pub revision_fingerprint: Option<Option<String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schema_version: Option<Version1>,
    pub status: String,
}
strict_object!(IntegrationOperationalStatusDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationProbeAttemptDto {
    pub checks: Vec<IntegrationProbeCheckDto>,
    pub completed_at: String,
    pub integration_id: String,
    pub overall_status: String,
    pub probe_attempt_id: String,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present_nullable"
    )]
    pub probe_configuration_fingerprint: Option<Option<String>>,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub probe_contract_fingerprint: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub probe_instrument: Option<String>,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub revision_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub runtime_configuration_fingerprint: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schema_version: Option<Version1>,
    pub started_at: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub type_descriptor_fingerprint: String,
    pub type_id: String,
}
strict_object!(IntegrationProbeAttemptDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationProbeAttemptListDto {
    pub items: Vec<IntegrationProbeAttemptDto>,
}
strict_object!(IntegrationProbeAttemptListDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationProbeCheckDto {
    pub check: String,
    pub detail: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub error_code: Option<String>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub failure_kind: Option<String>,
    pub latency_ms: i64,
    pub observations: Vec<String>,
    pub status: String,
}
strict_object!(IntegrationProbeCheckDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationProbeContractDto {
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub default_probe_instrument: Option<String>,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub fingerprint: String,
    pub probe_checks: Vec<OnlyIntegrationProbeCheck>,
    pub probe_mode: OnlyIntegrationProbeMode,
    pub probe_version: Version1,
    pub user_selectable_probe_instrument: bool,
}
strict_object!(IntegrationProbeContractDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationProbeRequestDto {
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub expected_revision_fingerprint: String,
    pub schema_version: Version1,
}
strict_object!(IntegrationProbeRequestDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationPublishRequestDto {
    #[schema(minimum = 1.0)]
    pub expected_draft_version: i64,
    pub schema_version: Version1,
}
strict_object!(IntegrationPublishRequestDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationRevisionDto {
    pub configuration: std::collections::BTreeMap<String, JsonValue>,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub configuration_fingerprint: String,
    pub created_at: String,
    pub integration_id: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub probe_configuration: Option<std::collections::BTreeMap<String, JsonValue>>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present_nullable"
    )]
    pub probe_configuration_fingerprint: Option<Option<String>>,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub revision_fingerprint: String,
    pub revision_sequence: i64,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub runtime_configuration_fingerprint: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schema_version: Option<Version1>,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub secret_binding_fingerprint: String,
    pub secret_bindings: Vec<IntegrationSecretStatusDto>,
    pub type_descriptor: IntegrationTypeDto,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub type_descriptor_fingerprint: String,
    pub type_id: String,
}
strict_object!(IntegrationRevisionDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationRevisionListDto {
    pub items: Vec<IntegrationRevisionSummaryDto>,
}
strict_object!(IntegrationRevisionListDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationRevisionSummaryDto {
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub configuration_fingerprint: String,
    pub created_at: String,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present_nullable"
    )]
    pub probe_configuration_fingerprint: Option<Option<String>>,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub revision_fingerprint: String,
    pub revision_sequence: i64,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub runtime_configuration_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub secret_binding_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub type_descriptor_fingerprint: String,
    pub type_id: String,
}
strict_object!(IntegrationRevisionSummaryDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationSecretSetRequestDto {
    #[schema(minimum = 1.0)]
    pub expected_draft_version: i64,
    pub schema_version: Version1,
    pub secret: String,
}
strict_object!(IntegrationSecretSetRequestDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationSecretStatusDto {
    pub configured: bool,
    pub field_id: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub generation: Option<i64>,
}
strict_object!(IntegrationSecretStatusDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationSummaryDto {
    pub category: OnlyIntegrationCategory,
    pub created_at: String,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present_nullable"
    )]
    pub current_revision_fingerprint: Option<Option<String>>,
    pub display_name: String,
    pub draft_version: i64,
    pub integration_id: String,
    pub lifecycle_state: OnlyIntegrationLifecycleState,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub pinned_type_descriptor_fingerprint: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schema_version: Option<Version1>,
    pub type_id: String,
    pub updated_at: String,
}
strict_object!(IntegrationSummaryDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationTypeDto {
    pub capabilities: Vec<String>,
    pub category: OnlyIntegrationCategory,
    pub configuration_contract: IntegrationConfigurationContractDto,
    pub description: String,
    pub display_name: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub fingerprint: String,
    pub implementation_id: String,
    pub implementation_version: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub probe_contract: Option<IntegrationProbeContractDto>,
    pub provider_id: String,
    pub public_api_version: String,
    pub schema_version: Version1,
    pub type_id: String,
}
strict_object!(IntegrationTypeDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationTypeErrorDto {
    pub code: String,
    pub detail: String,
}
strict_object!(IntegrationTypeErrorDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationTypeErrorEnvelopeDto {
    pub error: IntegrationTypeErrorDto,
}
strict_object!(IntegrationTypeErrorEnvelopeDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct IntegrationTypeListDto {
    pub items: Vec<IntegrationTypeDto>,
}
strict_object!(IntegrationTypeListDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(transparent)]
pub struct JsonValue(pub serde_json::Value);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataAcquisitionDtoStatus {
    #[serde(rename = "PENDING")]
    PENDING,
    #[serde(rename = "RUNNING")]
    RUNNING,
    #[serde(rename = "COMPLETE")]
    COMPLETE,
    #[serde(rename = "FAILED")]
    FAILED,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataAcquisitionDto {
    pub acquisition_id: String,
    pub bar_semantic: MarketDataBarSemanticDto,
    pub coverage: MarketDataCoverageDto,
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub end_ns: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub failure_detail: Option<String>,
    pub instrument_id: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub integration_binding_fingerprint: Option<String>,
    pub provenance: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub revision_fingerprint: Option<String>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub revision_id: Option<String>,
    pub schema_version: Version1,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub seal_id: Option<String>,
    pub source_id: String,
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub start_ns: String,
    pub status: MarketDataAcquisitionDtoStatus,
}
strict_object!(MarketDataAcquisitionDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataAcquisitionRequestDtoProvenance {
    #[serde(rename = "REST_BACKFILL")]
    RESTBACKFILL,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataAcquisitionRequestDto {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub bar_semantic: Option<MarketDataBarSemanticDto>,
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub end_ns: String,
    #[schema(min_length = 1)]
    pub instrument_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub provenance: Option<MarketDataAcquisitionRequestDtoProvenance>,
    pub source_reference: MarketDataSourceReferenceDto,
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub start_ns: String,
}
strict_object!(MarketDataAcquisitionRequestDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataBarDto {
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub bar_end_ns: String,
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub bar_start_ns: String,
    pub close: String,
    pub closed: bool,
    pub high: String,
    pub low: String,
    pub open: String,
    pub volume: String,
}
strict_object!(MarketDataBarDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataBarSemanticDtoAdjustmentPolicy {
    #[serde(rename = "RAW")]
    RAW,
    #[serde(rename = "FORWARD")]
    FORWARD,
    #[serde(rename = "BACKWARD")]
    BACKWARD,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(untagged)]
pub enum MarketDataBarSemanticDtoFormation {
    Variant0(MarketDataFixedDurationFormationDto),
    Variant1(MarketDataCalendarPeriodFormationDto),
    Variant2(MarketDataTickCountFormationDto),
    Variant3(MarketDataVolumeFormationDto),
    Variant4(MarketDataValueFormationDto),
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataBarSemanticDto {
    pub adjustment_policy: MarketDataBarSemanticDtoAdjustmentPolicy,
    pub formation: MarketDataBarSemanticDtoFormation,
    pub price_type: OnlyPriceType,
    pub schema_version: Version3,
}
strict_object!(MarketDataBarSemanticDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataBarWindowDtoAnchorKind {
    #[serde(rename = "LATEST_CLOSED")]
    LATESTCLOSED,
    #[serde(rename = "BEFORE_TIME")]
    BEFORETIME,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataBarWindowDtoResolutionModeValue {
    #[serde(rename = "PROVIDER_NATIVE")]
    PROVIDERNATIVE,
    #[serde(rename = "DERIVED")]
    DERIVED,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataBarWindowDto {
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub aggregation_semantics_version: Option<String>,
    pub anchor_kind: MarketDataBarWindowDtoAnchorKind,
    pub bar_semantic: MarketDataBarSemanticDto,
    pub bars: Vec<MarketDataBarDto>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub calendar_fingerprint: Option<String>,
    pub closed_only: bool,
    pub coverage: MarketDataCoverageDto,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub derived_projection_fingerprint: Option<String>,
    pub display_symbol: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub history_projection_fingerprint: Option<String>,
    pub instrument_id: String,
    pub market: String,
    #[schema(minimum = 1.0)]
    pub requested_bar_count: i64,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub requested_before_ns: Option<String>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub resolution_mode: Option<MarketDataBarWindowDtoResolutionModeValue>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub resolution_plan_fingerprint: Option<String>,
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub resolved_end_ns: String,
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub resolved_start_ns: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub resume_after_sequence: Option<String>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub resume_plan_fingerprint: Option<String>,
    pub revision_evidence: Vec<MarketDataRevisionEvidenceDto>,
    pub schema_version: Version1,
    pub source_selection: MarketDataSourceSelectionDto,
    pub venue: String,
}
strict_object!(MarketDataBarWindowDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataCalendarPeriodFormationDtoAlignment {
    #[serde(rename = "UTC")]
    UTC,
    #[serde(rename = "SESSION_START")]
    SESSIONSTART,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataCalendarPeriodFormationDtoKind {
    #[serde(rename = "CALENDAR_PERIOD")]
    CALENDARPERIOD,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataCalendarPeriodFormationDtoUnit {
    #[serde(rename = "DAY")]
    DAY,
    #[serde(rename = "WEEK")]
    WEEK,
    #[serde(rename = "MONTH")]
    MONTH,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataCalendarPeriodFormationDto {
    pub alignment: MarketDataCalendarPeriodFormationDtoAlignment,
    #[schema(minimum = 1.0)]
    pub count: i64,
    pub kind: MarketDataCalendarPeriodFormationDtoKind,
    pub schema_version: Version1,
    pub unit: MarketDataCalendarPeriodFormationDtoUnit,
}
strict_object!(MarketDataCalendarPeriodFormationDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataCoverageDtoStatus {
    #[serde(rename = "COMPLETE")]
    COMPLETE,
    #[serde(rename = "INCOMPLETE")]
    INCOMPLETE,
    #[serde(rename = "UNPROVABLE")]
    UNPROVABLE,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataCoverageDto {
    pub actual_bar_count: i64,
    pub expected_bar_count: i64,
    pub gaps: Vec<MarketDataCoverageGapDto>,
    pub issues: Vec<String>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub manifest_fingerprint: Option<String>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub manifest_id: Option<String>,
    pub planned_acquisition_ranges: Vec<MarketDataCoverageGapDto>,
    pub status: MarketDataCoverageDtoStatus,
}
strict_object!(MarketDataCoverageDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataCoverageGapDto {
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub end_ns: String,
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub start_ns: String,
}
strict_object!(MarketDataCoverageGapDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataErrorDtoPhase {
    #[serde(rename = "QUERY")]
    QUERY,
    #[serde(rename = "COMMAND")]
    COMMAND,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataErrorDto {
    pub code: String,
    pub detail: String,
    pub phase: MarketDataErrorDtoPhase,
}
strict_object!(MarketDataErrorDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataErrorEnvelopeDto {
    pub error: MarketDataErrorDto,
}
strict_object!(MarketDataErrorEnvelopeDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataFixedDurationFormationDtoAlignment {
    #[serde(rename = "UTC")]
    UTC,
    #[serde(rename = "SESSION_START")]
    SESSIONSTART,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataFixedDurationFormationDtoKind {
    #[serde(rename = "FIXED_DURATION")]
    FIXEDDURATION,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataFixedDurationFormationDto {
    pub alignment: MarketDataFixedDurationFormationDtoAlignment,
    pub kind: MarketDataFixedDurationFormationDtoKind,
    pub schema_version: Version1,
    #[schema(minimum = 1.0)]
    pub stride_minutes: i64,
    #[schema(minimum = 1.0)]
    pub window_minutes: i64,
}
strict_object!(MarketDataFixedDurationFormationDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataInstrumentDto {
    pub asset_class: String,
    pub display_symbol: String,
    pub instrument_id: String,
    pub instrument_type: String,
    pub market: String,
    pub market_data_capabilities: Vec<String>,
    pub status: String,
    pub venue: String,
}
strict_object!(MarketDataInstrumentDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataInstrumentListDto {
    pub instruments: Vec<MarketDataInstrumentDto>,
    pub schema_version: Version1,
    pub source_selection: MarketDataSourceSelectionDto,
}
strict_object!(MarketDataInstrumentListDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataQuoteDtoChangeBasisValue {
    #[serde(rename = "ROLLING_24H")]
    ROLLING24H,
    #[serde(rename = "PREVIOUS_CLOSE")]
    PREVIOUSCLOSE,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataQuoteDtoStatus {
    #[serde(rename = "AVAILABLE")]
    AVAILABLE,
    #[serde(rename = "UNAVAILABLE")]
    UNAVAILABLE,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataQuoteDto {
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub change_basis: Option<MarketDataQuoteDtoChangeBasisValue>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub change_pct: Option<String>,
    pub instrument_id: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub last_price: Option<String>,
    pub status: MarketDataQuoteDtoStatus,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub ts_event_ns: Option<String>,
}
strict_object!(MarketDataQuoteDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataQuoteListDtoStatus {
    #[serde(rename = "COMPLETE")]
    COMPLETE,
    #[serde(rename = "TIMEOUT")]
    TIMEOUT,
    #[serde(rename = "UNAVAILABLE")]
    UNAVAILABLE,
    #[serde(rename = "UNSUPPORTED")]
    UNSUPPORTED,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataQuoteListDto {
    pub quotes: Vec<MarketDataQuoteDto>,
    pub schema_version: Version1,
    pub source_selection: MarketDataSourceSelectionDto,
    pub status: MarketDataQuoteListDtoStatus,
}
strict_object!(MarketDataQuoteListDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataRevisionEvidenceDto {
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub covered_end_ns: String,
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub covered_start_ns: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub manifest_fingerprint: String,
    #[schema(min_length = 1)]
    pub manifest_id: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub revision_fingerprint: String,
    #[schema(min_length = 1)]
    pub revision_id: String,
    #[schema(min_length = 1)]
    pub seal_id: String,
}
strict_object!(MarketDataRevisionEvidenceDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataSearchDto {
    pub results: Vec<MarketDataSearchResultDto>,
    pub schema_version: Version1,
    pub sources: Vec<MarketDataSearchSourceDto>,
    pub truncated: bool,
}
strict_object!(MarketDataSearchDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataSearchResultDto {
    pub instrument: MarketDataInstrumentDto,
    pub source_selection: MarketDataSourceSelectionDto,
}
strict_object!(MarketDataSearchResultDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataSearchSourceDtoStatus {
    #[serde(rename = "COMPLETE")]
    COMPLETE,
    #[serde(rename = "TIMEOUT")]
    TIMEOUT,
    #[serde(rename = "UNAVAILABLE")]
    UNAVAILABLE,
    #[serde(rename = "UNSUPPORTED")]
    UNSUPPORTED,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataSearchSourceDto {
    pub asset_classes: Vec<String>,
    pub source_selection: MarketDataSourceSelectionDto,
    pub status: MarketDataSearchSourceDtoStatus,
    pub truncated: bool,
}
strict_object!(MarketDataSearchSourceDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataSourceListDto {
    pub schema_version: Version1,
    pub sources: Vec<MarketDataSourceProjectionDto>,
}
strict_object!(MarketDataSourceListDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataSourceProjectionDto {
    pub is_current_revision: bool,
    pub new_work_status: SourceNewWorkStatus,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub new_work_unavailable_code: Option<String>,
    pub history_read_policy: SourceHistoryPolicy,
    pub display_name: String,
    pub environment: String,
    pub integration_id: String,
    pub integration_revision_fingerprint: String,
    pub source_id: String,
    pub time_bar_capability: MarketDataTimeBarCapabilityDto,
    pub type_id: String,
}
strict_object!(MarketDataSourceProjectionDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataSourceReferenceDto {
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present_nullable"
    )]
    pub expected_type_id: Option<Option<String>>,
    #[schema(min_length = 1)]
    pub integration_id: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub integration_revision_fingerprint: String,
}
strict_object!(MarketDataSourceReferenceDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataSourceSelectionDto {
    #[schema(min_length = 1)]
    pub environment: String,
    #[schema(min_length = 1)]
    pub integration_id: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub integration_revision_fingerprint: String,
    #[schema(min_length = 1)]
    pub source_id: String,
    #[schema(min_length = 1)]
    pub type_id: String,
}
strict_object!(MarketDataSourceSelectionDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataTickCountFormationDtoKind {
    #[serde(rename = "TICK_COUNT")]
    TICKCOUNT,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataTickCountFormationDto {
    #[schema(minimum = 1.0)]
    pub count: i64,
    pub kind: MarketDataTickCountFormationDtoKind,
    pub schema_version: Version1,
}
strict_object!(MarketDataTickCountFormationDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataTimeBarCapabilityDtoDerivedAlgorithmValue {
    #[serde(rename = "TIME_BAR@1")]
    TIMEBAR1,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataTimeBarCapabilityDto {
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub derived_algorithm: Option<MarketDataTimeBarCapabilityDtoDerivedAlgorithmValue>,
    pub maximum_window_minutes: i64,
    pub minimum_window_minutes: i64,
    pub provider_base_semantic: MarketDataBarSemanticDto,
}
strict_object!(MarketDataTimeBarCapabilityDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataValueFormationDtoKind {
    #[serde(rename = "VALUE")]
    VALUE,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataValueFormationDto {
    pub kind: MarketDataValueFormationDtoKind,
    pub schema_version: Version2,
    #[schema(pattern = "^[0-9]+(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")]
    pub value: String,
}
strict_object!(MarketDataValueFormationDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum MarketDataVolumeFormationDtoKind {
    #[serde(rename = "VOLUME")]
    VOLUME,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct MarketDataVolumeFormationDto {
    pub kind: MarketDataVolumeFormationDtoKind,
    #[schema(pattern = "^[0-9]+(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")]
    pub quantity: String,
    pub schema_version: Version2,
}
strict_object!(MarketDataVolumeFormationDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum OnlyIntegrationCategory {
    #[serde(rename = "DATA_SOURCE")]
    DATASOURCE,
    #[serde(rename = "BROKER")]
    BROKER,
    #[serde(rename = "AGENT_PROVIDER")]
    AGENTPROVIDER,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum OnlyIntegrationLifecycleState {
    #[serde(rename = "ACTIVE")]
    ACTIVE,
    #[serde(rename = "DISABLED")]
    DISABLED,
    #[serde(rename = "ARCHIVED")]
    ARCHIVED,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum OnlyIntegrationProbeCheck {
    #[serde(rename = "CONNECTIVITY")]
    CONNECTIVITY,
    #[serde(rename = "AUTHENTICATION")]
    AUTHENTICATION,
    #[serde(rename = "REFERENCE_DATA")]
    REFERENCEDATA,
    #[serde(rename = "HISTORICAL_DATA")]
    HISTORICALDATA,
    #[serde(rename = "REALTIME_DATA")]
    REALTIMEDATA,
    #[serde(rename = "MODEL_DISCOVERY")]
    MODELDISCOVERY,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum OnlyIntegrationProbeMode {
    #[serde(rename = "DEFAULT_INSTRUMENT")]
    DEFAULTINSTRUMENT,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum OnlyIntegrationValueKind {
    #[serde(rename = "STRING")]
    STRING,
    #[serde(rename = "INTEGER")]
    INTEGER,
    #[serde(rename = "NUMBER")]
    NUMBER,
    #[serde(rename = "BOOLEAN")]
    BOOLEAN,
    #[serde(rename = "ENUM")]
    ENUM,
    #[serde(rename = "DURATION")]
    DURATION,
    #[serde(rename = "PATH")]
    PATH,
    #[serde(rename = "STRING_INTEGER_MAP")]
    STRINGINTEGERMAP,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum OnlyPriceType {
    #[serde(rename = "LAST")]
    LAST,
    #[serde(rename = "BID")]
    BID,
    #[serde(rename = "ASK")]
    ASK,
    #[serde(rename = "MID")]
    MID,
    #[serde(rename = "MARK")]
    MARK,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum OnlyPrivateAssetKind {
    #[serde(rename = "FACTOR")]
    FACTOR,
    #[serde(rename = "STRATEGY")]
    STRATEGY,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PrivateAssetErrorDto {
    pub code: String,
    pub detail: String,
}
strict_object!(PrivateAssetErrorDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PrivateAssetErrorEnvelopeDto {
    pub error: PrivateAssetErrorDto,
}
strict_object!(PrivateAssetErrorEnvelopeDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PrivateAssetLocatorDto {
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub content_fingerprint: String,
    pub private_asset_id: String,
    pub private_asset_kind: OnlyPrivateAssetKind,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub revision_fingerprint: String,
}
strict_object!(PrivateAssetLocatorDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PrivateAssetRegistryDto {
    pub entries: Vec<PrivateAssetRegistryEntryDto>,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub registry_fingerprint: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schema_version: Option<Version1>,
}
strict_object!(PrivateAssetRegistryDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PrivateAssetRegistryEntryDto {
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub category: Option<String>,
    pub description: String,
    pub locator: PrivateAssetLocatorDto,
    pub semantic_version: String,
    pub tags: Vec<String>,
}
strict_object!(PrivateAssetRegistryEntryDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PrivateFactorRevisionDto {
    pub category: String,
    pub description: String,
    pub economic_rationale: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub factor_api_contract_fingerprint: String,
    pub factor_api_version: Version1,
    pub factor_id: String,
    pub input_contract: std::collections::BTreeMap<String, JsonValue>,
    pub output_contract: std::collections::BTreeMap<String, JsonValue>,
    pub parameter_contract: std::collections::BTreeMap<String, JsonValue>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub parent_revision_fingerprint: Option<String>,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub revision_fingerprint: String,
    pub schema_version: Version1,
    pub semantic_version: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub source_sha256: String,
    pub source_text: String,
    pub tags: Vec<String>,
}
strict_object!(PrivateFactorRevisionDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ResearchCalculationCatalogDto {
    pub calculations: Vec<ResearchCalculationCatalogItemDto>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schema_version: Option<Version2>,
}
strict_object!(ResearchCalculationCatalogDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ResearchCalculationCatalogItemDto {
    pub inputs: Vec<ResearchInputDefinitionDto>,
    pub kind: String,
    pub outputs: Vec<ResearchOutputDefinitionDto>,
    pub parameter_sweep_allowed: bool,
    pub parameters: Vec<ResearchParameterDefinitionDto>,
    pub type_reference: ResearchCalculationTypeReferenceDto,
}
strict_object!(ResearchCalculationCatalogItemDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ResearchCalculationTypeReferenceDtoKind {
    #[serde(rename = "INDICATOR")]
    INDICATOR,
    #[serde(rename = "FACTOR")]
    FACTOR,
    #[serde(rename = "TARGET")]
    TARGET,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ResearchCalculationTypeReferenceDto {
    pub kind: ResearchCalculationTypeReferenceDtoKind,
    pub semantic_version: String,
    pub type_id: String,
}
strict_object!(ResearchCalculationTypeReferenceDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ResearchInputDefinitionDto {
    pub data_type: String,
    pub dimensions: Vec<String>,
    pub name: String,
    pub nullable: bool,
    pub semantic_type: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub unit: Option<String>,
}
strict_object!(ResearchInputDefinitionDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ResearchOutputDefinitionDto {
    pub data_type: String,
    pub dimensions: Vec<String>,
    pub name: String,
    pub nullable: bool,
    pub semantic_type: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub unit: Option<String>,
}
strict_object!(ResearchOutputDefinitionDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ResearchParameterDefinitionDto {
    pub r#default: ResearchScalarDto,
    pub enum_values: Vec<ResearchScalarDto>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub maximum: Option<ResearchScalarDto>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub minimum: Option<ResearchScalarDto>,
    pub name: String,
    pub required: bool,
    pub r#type: String,
    pub uppercase: bool,
}
strict_object!(ResearchParameterDefinitionDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum ResearchScalarDtoType {
    #[serde(rename = "NULL")]
    NULL,
    #[serde(rename = "BOOLEAN")]
    BOOLEAN,
    #[serde(rename = "INTEGER")]
    INTEGER,
    #[serde(rename = "DECIMAL")]
    DECIMAL,
    #[serde(rename = "STRING")]
    STRING,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(untagged)]
pub enum ResearchScalarDtoValue {
    Variant0(bool),
    Variant1(i64),
    Variant2(String),
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct ResearchScalarDto {
    pub r#type: ResearchScalarDtoType,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub value: Option<ResearchScalarDtoValue>,
}
strict_object!(ResearchScalarDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct SaveWatchlistsDto {
    #[schema(pattern = "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")]
    pub command_id: String,
    #[schema(minimum = 0.0)]
    pub expected_version: i64,
    #[schema(max_items = 20)]
    pub lists: Vec<WatchlistDto>,
    pub schema_version: Version2,
}
strict_object!(SaveWatchlistsDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct WatchlistBookDto {
    #[schema(max_items = 20)]
    pub lists: Vec<WatchlistDto>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schema_version: Option<Version2>,
    #[schema(minimum = 0.0)]
    pub version: i64,
}
strict_object!(WatchlistBookDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct WatchlistDto {
    #[schema(pattern = "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")]
    pub list_id: String,
    #[schema(max_items = 100)]
    pub members: Vec<WatchlistMemberDto>,
    #[schema(min_length = 1, max_length = 64)]
    pub name: String,
}
strict_object!(WatchlistDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct WatchlistErrorDto {
    pub code: String,
}
strict_object!(WatchlistErrorDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct WatchlistErrorEnvelopeDto {
    pub error: WatchlistErrorDto,
}
strict_object!(WatchlistErrorEnvelopeDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct WatchlistMemberDto {
    #[schema(min_length = 1, max_length = 256)]
    pub instrument_id: String,
    pub source: WatchlistSourceDto,
}
strict_object!(WatchlistMemberDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct WatchlistSourceDto {
    #[schema(min_length = 1, max_length = 256)]
    pub expected_type_id: String,
    #[schema(min_length = 1, max_length = 256)]
    pub integration_id: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub integration_revision_fingerprint: String,
}
strict_object!(WatchlistSourceDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct NativeErrorEnvelope {
    pub schema_version: Version1,
    pub error: NativeError,
}
strict_object!(NativeErrorEnvelope);
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct NativeError {
    pub phase: NativeErrorPhase,
    pub code: String,
    pub detail: String,
}
strict_object!(NativeError);
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum NativeErrorPhase {
    QUERY,
    COMMAND,
}
// JSON boolean literals are actual strict wire types. The same constant drives
// deserialization and their leaf schema; no independent schema override exists.
macro_rules! boolean_literal {
    ($name:ident,$value:literal) => {
        #[derive(Clone, Debug)]
        pub struct $name;
        impl serde::Serialize for $name {
            fn serialize<S: serde::Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
                s.serialize_bool($value)
            }
        }
        impl<'de> serde::Deserialize<'de> for $name {
            fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                if bool::deserialize(d)? == $value {
                    Ok(Self)
                } else {
                    Err(serde::de::Error::custom("unsupported boolean literal"))
                }
            }
        }
        impl utoipa::PartialSchema for $name {
            fn schema() -> utoipa::openapi::RefOr<utoipa::openapi::schema::Schema> {
                utoipa::openapi::ObjectBuilder::new()
                    .schema_type(utoipa::openapi::schema::Type::Boolean)
                    .enum_values(Some([serde_json::json!($value)]))
                    .into()
            }
        }
        impl utoipa::ToSchema for $name {}
    };
}
boolean_literal!(VersionTrue, true);
boolean_literal!(VersionFalse, false);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum SourceNewWorkStatus {
    AVAILABLE,
    UNAVAILABLE,
}
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum SourceHistoryPolicy {
    #[serde(rename = "EXACT_SEALED_PROOF")]
    ExactSealedProof,
}
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct NativeHealthDto {
    pub status: NativeHealthStatus,
}
strict_object!(NativeHealthDto);
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum NativeHealthStatus {
    LIVE,
    READY,
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn chart_limits_admit_only_the_two_owner_resource_contract() {
        let mut raw = serde_json::json!({
            "max_input_rows": 2000,
            "max_period": 10000,
            "max_concurrent_invocations": 2
        });
        assert!(serde_json::from_value::<ChartStudyLimitsDto>(raw.clone()).is_ok());
        for invalid in [1, 3] {
            raw["max_concurrent_invocations"] = serde_json::json!(invalid);
            assert!(serde_json::from_value::<ChartStudyLimitsDto>(raw.clone()).is_err());
        }
    }
    #[test]
    fn chart_output_selection_rejects_duplicates_and_declares_the_same_constraint() {
        let mut raw = serde_json::json!({
            "expected_capability_projection_fingerprint": "a".repeat(64),
            "expected_descriptor_fingerprint": "b".repeat(64),
            "expected_implementation_fingerprint": "c".repeat(64),
            "kind": "INDICATOR", "output_members": ["first", "second"],
            "semantic_version": "1", "type_id": "indicator.test", "typed_parameters": {}
        });
        let selected: ChartStudyCalculationRequestDto =
            serde_json::from_value(raw.clone()).unwrap();
        assert_eq!(selected.output_members, vec!["first", "second"]);
        raw["output_members"] = serde_json::json!(["first", "first"]);
        assert!(serde_json::from_value::<ChartStudyCalculationRequestDto>(raw).is_err());
        let (_, contract) = crate::transport::routes::declaration();
        let value = serde_json::to_value(contract).unwrap();
        assert_eq!(
            value["components"]["schemas"]["ChartStudyCalculationRequestDto"]["properties"]["output_members"]
                ["uniqueItems"],
            true
        );
    }
    #[test]
    fn native_720_minute_semantic_preserves_the_exact_wire_value() {
        let raw = r#"{"schema_version":3,"price_type":"LAST","adjustment_policy":"RAW","formation":{"schema_version":1,"kind":"FIXED_DURATION","alignment":"SESSION_START","window_minutes":720,"stride_minutes":720}}"#;
        let decoded: MarketDataBarSemanticDto = serde_json::from_str(raw).unwrap();
        assert_eq!(
            serde_json::to_value(decoded).unwrap(),
            serde_json::from_str::<serde_json::Value>(raw).unwrap()
        );
    }
    #[test]
    fn nullable_field_schema_preserves_runtime_null_and_required_presence() {
        let (_, contract) = crate::transport::routes::declaration();
        let contract = serde_json::to_value(contract).unwrap();
        let window = &contract["components"]["schemas"]["MarketDataBarWindowDto"];
        assert_eq!(
            window["properties"]["requested_before_ns"]["type"],
            serde_json::json!(["string", "null"])
        );
        assert!(
            window["required"]
                .as_array()
                .unwrap()
                .iter()
                .any(|v| v == "requested_before_ns")
        );
    }
    #[test]
    fn numeric_scalar_schema_has_no_overlapping_integer_number_oneof() {
        let (_, contract) = crate::transport::routes::declaration();
        let contract = serde_json::to_value(contract).unwrap();
        let schemas = contract["components"]["schemas"].as_object().unwrap();
        for (name, schema) in schemas {
            if let Some(branches) = schema["oneOf"].as_array() {
                let types = branches
                    .iter()
                    .filter_map(|branch| {
                        let branch = if let Some(reference) = branch["$ref"].as_str() {
                            &schemas[reference.rsplit('/').next().unwrap()]
                        } else {
                            branch
                        };
                        branch["type"].as_str()
                    })
                    .collect::<Vec<_>>();
                assert!(
                    !(types.contains(&"integer") && types.contains(&"number")),
                    "overlapping oneOf: {name}"
                );
            }
        }
    }
    #[test]
    fn objects_reject_positional_arrays_at_every_declared_object_boundary() {
        let valid = r#"{"display_name":"Spot","integration_id":"12345678-1234-4234-9234-123456789abc","schema_version":1,"type_id":"binance.spot.market_data"}"#;
        assert!(serde_json::from_str::<IntegrationCreateRequestDto>(valid).is_ok());
        assert!(
            serde_json::from_str::<IntegrationCreateRequestDto>(
                r#"["Spot","12345678-1234-4234-9234-123456789abc",1,"binance.spot.market_data"]"#
            )
            .is_err()
        );
        let nested = r#"{"command_id":"12345678-1234-4234-9234-123456789abc","expected_version":0,"lists":[["12345678-1234-4234-9234-123456789abd",[],"Daily"]],"schema_version":2}"#;
        assert!(serde_json::from_str::<SaveWatchlistsDto>(nested).is_err());
    }
    #[test]
    fn literals_required_nullability_and_original_numeric_kinds_are_runtime_constraints() {
        for raw in ["0", "2", "1.0", "\"1\"", "true", "null"] {
            assert!(serde_json::from_str::<Version1>(raw).is_err(), "{raw}");
        }
        assert!(serde_json::from_str::<Version1>("1").is_ok());
        assert!(serde_json::from_str::<VersionTrue>("true").is_ok());
        assert!(serde_json::from_str::<VersionTrue>("false").is_err());
        let valid = r#"{"advanced":false,"default":0.5,"description":"","display_name":"Delay","enum_values":[],"exclusive_minimum":true,"field_id":"delay","maximum":null,"minimum":0.0,"required":false,"secret":false,"value_kind":"DURATION"}"#;
        let decoded = serde_json::from_str::<IntegrationConfigurationFieldDto>(valid);
        assert!(decoded.is_ok(), "{decoded:?}");
        let missing =
            r#"{"expected_draft_version":1,"public_configuration":{},"schema_version":1}"#;
        assert!(serde_json::from_str::<IntegrationDraftUpdateRequestDto>(missing).is_err());
        assert!(
            serde_json::from_str::<IntegrationDraftUpdateRequestDto>(&missing.replace(
                "\"public_configuration\":{}",
                "\"public_configuration\":{},\"probe_configuration\":null"
            ))
            .is_ok()
        );
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum TemporaryMarketDataSourceKind {
    #[serde(rename = "TEMPORARY_MARKET_DATA")]
    Temporary,
}
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum TemporaryMarketDataAuthority {
    #[serde(rename = "DISPLAY_ONLY")]
    DisplayOnly,
}
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum TemporaryMarketDataPublication {
    #[serde(rename = "NOT_A_RESEARCH_RESULT")]
    NotResearch,
}
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum TemporaryMarketDataCoverageStatus {
    #[serde(rename = "PARTIAL")]
    Partial,
    #[serde(rename = "COMPLETE")]
    Complete,
}
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct TemporaryMarketDataCoverageDto {
    pub status: TemporaryMarketDataCoverageStatus,
    #[schema(minimum = 1.0, maximum = 2000.0)]
    pub expected_bar_count: u32,
    #[schema(maximum = 2000.0)]
    pub actual_bar_count: u32,
    pub gaps: Vec<MarketDataCoverageGapDto>,
}
strict_object!(TemporaryMarketDataCoverageDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct TemporaryMarketDataWindowDto {
    pub schema_version: Version1,
    pub source_kind: TemporaryMarketDataSourceKind,
    pub authority: TemporaryMarketDataAuthority,
    pub publication_status: TemporaryMarketDataPublication,
    pub source_selection: MarketDataSourceSelectionDto,
    pub instrument_id: String,
    pub bar_semantic: MarketDataBarSemanticDto,
    pub anchor_kind: MarketDataBarWindowDtoAnchorKind,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub requested_before_ns: Option<String>,
    #[schema(minimum = 1.0, maximum = 2000.0)]
    pub requested_bar_count: u32,
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub resolved_start_ns: String,
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub resolved_end_ns: String,
    pub coverage: TemporaryMarketDataCoverageDto,
    pub bars: Vec<MarketDataBarDto>,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub window_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub calendar_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub resolution_plan_fingerprint: String,
    pub resolution_mode: MarketDataBarWindowDtoResolutionModeValue,
}
strict_object!(TemporaryMarketDataWindowDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct TemporaryChartStudyEvaluateRequestDto {
    pub schema_version: Version2,
    pub source_kind: TemporaryMarketDataSourceKind,
    #[schema(format = "uuid")]
    pub page_id: String,
    pub source_reference: ChartStudySourceReferenceDto,
    #[schema(min_length = 1, max_length = 256)]
    pub instrument_id: String,
    pub bar_semantic: MarketDataBarSemanticDto,
    pub window: ChartStudyWindowDto,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub expected_window_fingerprint: String,
    pub calculation: ChartStudyCalculationRequestDto,
}
strict_object!(TemporaryChartStudyEvaluateRequestDto);

fn bounded_chart_calculations<'de, D: serde::Deserializer<'de>>(
    d: D,
) -> Result<Vec<ChartStudyCalculationRequestDto>, D::Error> {
    let values = Vec::<ChartStudyCalculationRequestDto>::deserialize(d)?;
    if values.is_empty() || values.len() > 4 {
        return Err(serde::de::Error::custom(
            "batch requires one to four calculations",
        ));
    }
    Ok(values)
}
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct TemporaryChartStudyBatchRequestDto {
    pub schema_version: Version2,
    pub source_kind: TemporaryMarketDataSourceKind,
    #[schema(format = "uuid")]
    pub page_id: String,
    pub source_reference: ChartStudySourceReferenceDto,
    #[schema(min_length = 1, max_length = 256)]
    pub instrument_id: String,
    pub bar_semantic: MarketDataBarSemanticDto,
    pub window: ChartStudyWindowDto,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub expected_window_fingerprint: String,
    #[schema(min_items = 1, max_items = 4)]
    #[serde(deserialize_with = "bounded_chart_calculations")]
    pub calculations: Vec<ChartStudyCalculationRequestDto>,
}
strict_object!(TemporaryChartStudyBatchRequestDto);

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub enum TemporaryChartStudyBatchError {
    #[serde(rename = "CHART_STUDY_REQUEST_INVALID")]
    RequestInvalid,
}
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(tag = "status", deny_unknown_fields)]
pub enum TemporaryChartStudyBatchItemDto {
    #[serde(rename = "EVALUATED")]
    Evaluated {
        #[schema(minimum = 0, maximum = 3)]
        request_index: u8,
        evaluation: Box<TemporaryChartStudyEvaluateDto>,
    },
    #[serde(rename = "REJECTED")]
    Rejected {
        #[schema(minimum = 0, maximum = 3)]
        request_index: u8,
        error: TemporaryChartStudyBatchError,
    },
}
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct TemporaryChartStudyBatchDto {
    pub schema_version: Version2,
    pub source_kind: ChartStudyEvaluateDtoSourceKind,
    pub authority: ChartStudyEvaluateDtoAuthority,
    pub publication_status: ChartStudyEvaluateDtoPublicationStatus,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub window_fingerprint: String,
    #[schema(min_items = 1, max_items = 4)]
    pub results: Vec<TemporaryChartStudyBatchItemDto>,
}
strict_object!(TemporaryChartStudyBatchDto);
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct TemporaryChartStudyInputDto {
    pub source_kind: TemporaryMarketDataSourceKind,
    pub anchor_kind: ChartStudyInputDtoAnchorKind,
    pub initialization: ChartStudyInputDtoInitialization,
    #[schema(pattern = "^[1-9][0-9]{0,18}$")]
    pub before_ns: String,
    #[schema(minimum = 1, maximum = 2000)]
    pub target_bar_count: u32,
    #[schema(pattern = "^(?:0|[1-9][0-9]*)$")]
    pub resolved_start_ns: String,
    #[schema(pattern = "^[1-9][0-9]{0,18}$")]
    pub resolved_end_ns: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub window_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub calendar_fingerprint: String,
    #[schema(pattern = "^[0-9a-f]{64}$")]
    pub resolution_plan_fingerprint: String,
    pub resolution_mode: MarketDataBarWindowDtoResolutionModeValue,
}
strict_object!(TemporaryChartStudyInputDto);
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct TemporaryChartStudyEvaluateDto {
    pub schema_version: Version2,
    pub source_kind: ChartStudyEvaluateDtoSourceKind,
    pub authority: ChartStudyEvaluateDtoAuthority,
    pub publication_status: ChartStudyEvaluateDtoPublicationStatus,
    pub source_selection: MarketDataSourceSelectionDto,
    #[schema(min_length = 1, max_length = 256)]
    pub instrument_id: String,
    pub bar_semantic: MarketDataBarSemanticDto,
    pub input: TemporaryChartStudyInputDto,
    pub coverage: TemporaryMarketDataCoverageDto,
    pub query_status: ChartStudyEvaluateDtoQueryStatus,
    pub calculation: ChartStudyCalculationDto,
    #[schema(max_items = 16)]
    pub series: Vec<ChartStudySeriesDto>,
    pub preview: JsonNull,
}
strict_object!(TemporaryChartStudyEvaluateDto);

#[cfg(test)]
mod temporary_wire_tests {
    use super::*;
    #[test]
    fn temporary_batch_wire_rejects_unbounded_or_cross_authority_requests() {
        let calculation = serde_json::json!({"kind":"INDICATOR","type_id":"onlyalpha.indicator.sma","semantic_version":"1","typed_parameters":{},"output_members":["value"],"expected_descriptor_fingerprint":"a".repeat(64),"expected_implementation_fingerprint":"b".repeat(64),"expected_capability_projection_fingerprint":"c".repeat(64)});
        let good = serde_json::json!({"schema_version":2,"source_kind":"TEMPORARY_MARKET_DATA","page_id":"00000000-0000-4000-8000-000000000001","source_reference":{"integration_id":"source","integration_revision_fingerprint":"a".repeat(64),"expected_type_id":"test.source"},"instrument_id":"BTCUSDT.BINANCE","bar_semantic":{"schema_version":3,"formation":{"schema_version":1,"kind":"FIXED_DURATION","window_minutes":7,"stride_minutes":7,"alignment":"SESSION_START"},"price_type":"LAST","adjustment_policy":"RAW"},"window":{"anchor_kind":"BEFORE_TIME","before_ns":"6000000000000","target_bar_count":2000},"expected_window_fingerprint":"d".repeat(64),"calculations":[calculation.clone()]});
        assert!(serde_json::from_value::<TemporaryChartStudyBatchRequestDto>(good.clone()).is_ok());
        for count in [0, 5] {
            let mut bad = good.clone();
            bad["calculations"] = serde_json::json!(vec![calculation.clone(); count]);
            assert!(serde_json::from_value::<TemporaryChartStudyBatchRequestDto>(bad).is_err());
        }
        for field in [
            "calculation",
            "bars",
            "revision_evidence",
            "runtime_generation",
        ] {
            let mut bad = good.clone();
            bad[field] = serde_json::json!({});
            assert!(serde_json::from_value::<TemporaryChartStudyBatchRequestDto>(bad).is_err());
        }
        for code in [
            "CHART_STUDY_OUTPUT_INVALID",
            "REGISTRATION_CHANGED",
            "REQUEST_REJECTED",
        ] {
            let bad = serde_json::json!({"status":"REJECTED","request_index":0,"error":code});
            assert!(serde_json::from_value::<TemporaryChartStudyBatchItemDto>(bad).is_err());
        }
    }
    #[test]
    fn temporary_chart_input_decodes_both_native_and_derived_without_widening_sealed_input() {
        for mode in ["PROVIDER_NATIVE", "DERIVED"] {
            let input = serde_json::json!({"source_kind":"TEMPORARY_MARKET_DATA","anchor_kind":"BEFORE_TIME","initialization":"FINITE_WINDOW_START","before_ns":"6000000000000","target_bar_count":2000,"resolved_start_ns":"1","resolved_end_ns":"6000000000000","window_fingerprint":"a".repeat(64),"calendar_fingerprint":"b".repeat(64),"resolution_plan_fingerprint":"c".repeat(64),"resolution_mode":mode});
            assert!(
                serde_json::from_value::<TemporaryChartStudyInputDto>(input).is_ok(),
                "{mode}"
            );
        }
        assert!(serde_json::from_str::<ChartStudyInputDtoResolutionMode>("\"DERIVED\"").is_err());
    }

    #[test]
    fn temporary_preview_is_required_null_in_both_decoder_and_schema() {
        assert!(serde_json::from_str::<JsonNull>("null").is_ok());
        for value in ["{}", "[]", "true", "0", "\"preview\""] {
            assert!(serde_json::from_str::<JsonNull>(value).is_err());
        }
        let schema = serde_json::to_value(<JsonNull as utoipa::PartialSchema>::schema()).unwrap();
        assert_eq!(schema["type"], "null");
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct WorkspaceSeriesStyleDto {
    pub color: String,
    pub visible: bool,
}
strict_object!(WorkspaceSeriesStyleDto);
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct WorkspacePresentationDto {
    pub placement: String,
    pub color: String,
    #[schema(minimum = 1.0, maximum = 5.0)]
    pub line_width: f64,
    #[schema(minimum = 0.0, maximum = 1.0)]
    pub opacity: f64,
    pub visible: bool,
    pub series_styles: std::collections::BTreeMap<String, WorkspaceSeriesStyleDto>,
}
strict_object!(WorkspacePresentationDto);
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct WorkspaceStudyDto {
    pub kind: String,
    pub type_id: String,
    pub semantic_version: String,
    pub parameters: std::collections::BTreeMap<String, ResearchScalarDto>,
    #[schema(min_items = 1, max_items = 32)]
    pub output_names: Vec<String>,
    pub presentation: WorkspacePresentationDto,
}
strict_object!(WorkspaceStudyDto);
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct WorkspaceConfigurationDto {
    pub source: WatchlistSourceDto,
    pub instrument_id: String,
    pub bar_semantic: MarketDataBarSemanticDto,
    #[schema(max_items = 32)]
    pub studies: Vec<WorkspaceStudyDto>,
}
strict_object!(WorkspaceConfigurationDto);
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct SaveWorkspaceDto {
    pub schema_version: Version2,
    pub command_id: String,
    #[schema(minimum = 0.0)]
    pub expected_version: i64,
    pub configuration: WorkspaceConfigurationDto,
}
strict_object!(SaveWorkspaceDto);
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct WorkspaceBookDto {
    pub schema_version: Version2,
    #[schema(minimum = 0.0)]
    pub version: i64,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub configuration: Option<WorkspaceConfigurationDto>,
}
strict_object!(WorkspaceBookDto);

#[cfg(test)]
mod default_workspace_tests {
    use super::*;
    #[test]
    fn default_workspace_preserves_existing_half_pixel_line_width() {
        assert!(serde_json::from_str::<WorkspacePresentationDto>(r##"{"placement":"PRICE_OVERLAY","color":"#abcdef","line_width":2.5,"opacity":0.6,"visible":true,"series_styles":{}}"##).is_ok());
    }
    #[test]
    fn default_workspace_config_wire_excludes_values_and_requires_explicit_version() {
        let config = serde_json::json!({"source":{"integration_id":"source","integration_revision_fingerprint":"a".repeat(64),"expected_type_id":"test.source"},"instrument_id":"BTCUSDT.BINANCE","bar_semantic":{"schema_version":3,"formation":{"schema_version":1,"kind":"FIXED_DURATION","window_minutes":7,"stride_minutes":7,"alignment":"SESSION_START"},"price_type":"LAST","adjustment_policy":"RAW"},"studies":[]});
        let good = serde_json::json!({"schema_version":2,"command_id":"00000000-0000-4000-8000-000000000001","expected_version":0,"configuration":config});
        assert!(serde_json::from_str::<SaveWorkspaceDto>(&good.to_string()).is_ok());
        for field in ["bars", "results", "viewport", "secret", "capability"] {
            let mut bad = good.clone();
            bad["configuration"][field] = serde_json::json!([]);
            assert!(serde_json::from_str::<SaveWorkspaceDto>(&bad.to_string()).is_err());
        }
        let mut bad = good.clone();
        bad.as_object_mut().unwrap().remove("expected_version");
        assert!(serde_json::from_str::<SaveWorkspaceDto>(&bad.to_string()).is_err());
        assert!(
            serde_json::from_str::<WorkspaceBookDto>(
                r#"{"schema_version":2,"version":0,"configuration":null}"#
            )
            .is_ok()
        );
        assert!(
            serde_json::from_str::<WorkspaceBookDto>(r#"{"schema_version":2,"version":0}"#)
                .is_err()
        );
    }
}

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PrivateFactorDraftDto {
    pub schema_version: Version1,
    pub factor_id: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub base_revision_fingerprint: Option<String>,
    pub semantic_version: String,
    pub source_text: String,
    pub factor_api_version: Version1,
    pub factor_api_contract_fingerprint: String,
    pub input_contract: std::collections::BTreeMap<String, JsonValue>,
    pub parameter_contract: std::collections::BTreeMap<String, JsonValue>,
    pub output_contract: std::collections::BTreeMap<String, JsonValue>,
    pub description: String,
    pub economic_rationale: String,
    pub category: String,
    pub tags: Vec<String>,
}
strict_object!(PrivateFactorDraftDto);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PrivateFactorDisplayFieldsDto {
    pub display_name: String,
    pub usage_summary: String,
}
strict_object!(PrivateFactorDisplayFieldsDto);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PrivateFactorDisplayDto {
    pub schema_version: Version1,
    pub factor_id: String,
    pub display_name: String,
    pub usage_summary: String,
    pub edit_number: u64,
}
strict_object!(PrivateFactorDisplayDto);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct UpdatePrivateFactorDisplayDto {
    pub display_name: String,
    pub usage_summary: String,
    pub expected_display_fingerprint: String,
}
strict_object!(UpdatePrivateFactorDisplayDto);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PrivateFactorPublishedRevisionDto {
    pub display_version: u16,
    pub revision: PrivateFactorRevisionDto,
}
strict_object!(PrivateFactorPublishedRevisionDto);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct SavePrivateFactorDraftDto {
    pub draft: PrivateFactorDraftDto,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub initial_display: Option<PrivateFactorDisplayFieldsDto>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub expected_draft_fingerprint: Option<String>,
}
strict_object!(SavePrivateFactorDraftDto);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PublishPrivateFactorRevisionDto {
    pub expected_draft_fingerprint: String,
}
strict_object!(PublishPrivateFactorRevisionDto);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PrivateFactorAuthoringResultDto {
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub draft: Option<PrivateFactorDraftDto>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub draft_fingerprint: Option<String>,
    pub display: PrivateFactorDisplayDto,
    pub display_fingerprint: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub display_version: Option<u16>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub revision: Option<PrivateFactorRevisionDto>,
}
strict_object!(PrivateFactorAuthoringResultDto);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PrivateFactorAuthoringReceiptDto {
    pub schema_version: Version1,
    pub command_id: String,
    pub factor_id: String,
    pub result: PrivateFactorAuthoringResultDto,
}
strict_object!(PrivateFactorAuthoringReceiptDto);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PrivateFactorAuthoringStateDto {
    pub schema_version: Version1,
    pub factor_id: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub current_revision_fingerprint: Option<String>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub draft: Option<PrivateFactorDraftDto>,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub draft_fingerprint: Option<String>,
    pub revisions: Vec<PrivateFactorPublishedRevisionDto>,
    pub display: PrivateFactorDisplayDto,
    pub display_fingerprint: String,
}
strict_object!(PrivateFactorAuthoringStateDto);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PrivateFactorAuthoringEntryDto {
    pub factor_id: String,
    pub display: PrivateFactorDisplayDto,
    pub display_fingerprint: String,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub current_display_version: Option<u16>,
    pub has_draft: bool,
    #[serde(deserialize_with = "required_nullable")]
    #[schema(required = true)]
    pub current_revision_fingerprint: Option<String>,
}
strict_object!(PrivateFactorAuthoringEntryDto);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(remote = "Self", deny_unknown_fields)]
pub struct PrivateFactorAuthoringInventoryDto {
    pub schema_version: Version1,
    pub new_factor_defaults: PrivateFactorDisplayFieldsDto,
    pub factor_api_version: Version1,
    pub factor_api_contract_fingerprint: String,
    pub entries: Vec<PrivateFactorAuthoringEntryDto>,
}
strict_object!(PrivateFactorAuthoringInventoryDto);
