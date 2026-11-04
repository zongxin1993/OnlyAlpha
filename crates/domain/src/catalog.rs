//! Pure effective-dated catalogs; no latest substitution or mutable registry.
use crate::{
    base::{OnlyDomainModel, invalid, record},
    errors::OnlyDomainError,
    identifiers::OnlyInstrumentId,
    instrument::{OnlyInstrument, OnlyInstrumentSpecification},
    time::OnlyUtcDateTime,
};
use serde_json::{Value, json};
use std::collections::HashSet;

/// An explicit concrete type supplies its own strict reader, including any extension tags.
/// Plugins can use a typed enum for built-ins plus extensions; no guessed or erased subtype.
pub trait OnlyInstrumentModel: OnlyDomainModel {
    fn specification(&self) -> &OnlyInstrumentSpecification;
}
impl OnlyInstrumentModel for OnlyInstrument {
    fn specification(&self) -> &OnlyInstrumentSpecification {
        self.specification()
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyInstrumentCatalog<I = OnlyInstrument> {
    instruments: Vec<I>,
}
impl<I: OnlyInstrumentModel> OnlyInstrumentCatalog<I> {
    pub fn new(instruments: Vec<I>) -> Result<Self, OnlyDomainError> {
        let mut keys = HashSet::new();
        if instruments.iter().any(|instrument| {
            let f = instrument.specification();
            !keys.insert((f.instrument_id(), f.instrument_version()))
        }) {
            return Err(invalid("instrument catalog contains a duplicate version"));
        }
        Ok(Self { instruments })
    }
    pub fn instruments(&self) -> &[I] {
        &self.instruments
    }
    pub fn resolve(
        &self,
        instrument_id: &OnlyInstrumentId,
        as_of: OnlyUtcDateTime,
    ) -> Result<&I, OnlyDomainError> {
        let mut matching = self.instruments.iter().filter(|item| {
            item.specification().instrument_id() == instrument_id
                && item.specification().is_effective_at(as_of)
        });
        let item = matching
            .next()
            .ok_or_else(|| invalid("no effective instrument version"))?;
        if matching.next().is_some() {
            return Err(invalid("ambiguous effective instrument version"));
        }
        Ok(item)
    }
}
impl<I: OnlyInstrumentModel> OnlyDomainModel for OnlyInstrumentCatalog<I> {
    fn to_record(&self) -> Value {
        json!({"schema_version":1,"instruments":self.instruments.iter().map(OnlyDomainModel::to_record).collect::<Vec<_>>()})
    }
    fn from_record(value: &Value) -> Result<Self, OnlyDomainError> {
        (|| {
            let row = record(value, 1, &["instruments"])?;
            let items = row["instruments"]
                .as_array()
                .ok_or_else(|| invalid("catalog instruments must be an array"))?;
            Self::new(items.iter().map(I::from_record).collect::<Result<_, _>>()?)
        })()
        .map_err(crate::value::serialization)
    }
}
