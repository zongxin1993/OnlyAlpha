//! Compiled authoring metadata and executable public-configuration validation.
//! This projection grants no Probe, Source, runtime or execution permission.
use super::{Category, Descriptor, Error, capability, nonblank, object, read, sorted, stable};
use onlyalpha_metadata_json as metadata;
use serde_json::value::RawValue;

/// The independent plugin declaration dimensions represented by an Integration
/// Type. Full runtime factory installation remains a separate owning proof.
pub struct PluginProjection {
    category: Category,
    implementation_id: String,
    implementation_version: String,
    public_api_version: String,
    capabilities: Vec<String>,
}
impl PluginProjection {
    pub fn new(
        category: Category,
        implementation_id: &str,
        implementation_version: &str,
        public_api_version: &str,
        capabilities: Vec<String>,
    ) -> Result<Self, Error> {
        if !matches!(category, Category::DataSource | Category::Broker)
            || !stable(implementation_id)
            || !nonblank(implementation_version)
            // Preserve the existing Plugin API 1.1 supported requirements.
            || !matches!(public_api_version, "1.0" | "1.1")
            || !sorted(&capabilities)
            || capabilities.iter().any(|value| !capability(value))
        {
            return Err(Error::Type);
        }
        Ok(Self {
            category,
            implementation_id: implementation_id.into(),
            implementation_version: implementation_version.into(),
            public_api_version: public_api_version.into(),
            capabilities,
        })
    }
}

/// Constructed by node composition from real compiled plugin functions, never
/// deserialized from an HTTP request. Function addresses are not durable identity.
pub struct Registration {
    descriptor: Descriptor,
    validator: fn(&RawValue, usize) -> Result<(), Error>,
}
impl Registration {
    pub fn new(
        plugin: PluginProjection,
        descriptor: Descriptor,
        validator: fn(&RawValue, usize) -> Result<(), Error>,
    ) -> Result<Self, Error> {
        let fields = object(descriptor.document())?;
        if plugin.category != descriptor.category()
            || plugin.implementation_id != read::<String>(&fields, "implementation_id")?
            || plugin.implementation_version != read::<String>(&fields, "implementation_version")?
            || plugin.public_api_version != read::<String>(&fields, "public_api_version")?
            || plugin.capabilities != read::<Vec<String>>(&fields, "capabilities")?
        {
            return Err(Error::Type);
        }
        Ok(Self {
            descriptor,
            validator,
        })
    }
    pub fn descriptor(&self) -> &Descriptor {
        &self.descriptor
    }
    /// Validate a partial public candidate. Completeness, default filling and
    /// immutable publication stay with the canonical publication producer.
    pub fn validate_public_configuration(
        &self,
        input: &RawValue,
        work: usize,
    ) -> Result<(), Error> {
        metadata::canonical_json(input.get(), work).map_err(configuration_error)?;
        let values = metadata::object_fields(input.get()).map_err(configuration_error)?;
        for (key, value) in values {
            let index = self
                .descriptor
                .fields()
                .binary_search_by(|field| field.id().cmp(&key))
                .map_err(|_| Error::Configuration)?;
            let field = &self.descriptor.fields()[index];
            if field.secret() || !field.accepts(value) {
                return Err(Error::Configuration);
            }
        }
        (self.validator)(input, work)
    }
}
fn configuration_error(error: metadata::Error) -> Error {
    match error {
        metadata::Error::Invalid => Error::Configuration,
        metadata::Error::Unavailable => Error::Unavailable,
    }
}
