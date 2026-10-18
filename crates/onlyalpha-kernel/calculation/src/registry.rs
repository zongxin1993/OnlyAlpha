use crate::{Result, TypeDefinition, TypeReference, record::err};
use std::collections::BTreeMap;
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Backend {
    Research,
    Trading,
}
pub struct Registration<P> {
    definition: TypeDefinition,
    backend: Backend,
    provider: P,
}
impl<P> Registration<P> {
    pub fn definition(&self) -> &TypeDefinition {
        &self.definition
    }
    pub fn backend(&self) -> Backend {
        self.backend
    }
    pub fn provider(&self) -> &P {
        &self.provider
    }
}
pub struct Registry<P> {
    registrations: BTreeMap<(TypeReference, Backend), Registration<P>>,
}
impl<P> Default for Registry<P> {
    fn default() -> Self {
        Self::new()
    }
}
impl<P> Registry<P> {
    pub fn new() -> Self {
        Self {
            registrations: BTreeMap::new(),
        }
    }
    pub fn register(
        &mut self,
        definition: TypeDefinition,
        backend: Backend,
        provider: P,
    ) -> Result<()> {
        let key = (definition.reference().clone(), backend);
        if self.registrations.contains_key(&key) {
            return Err(err("DUPLICATE_BACKEND"));
        }
        if self.registrations.values().any(|r| {
            r.definition.reference() == definition.reference() && r.definition != definition
        }) {
            return Err(err("CROSS_BACKEND_TYPE_CONFLICT"));
        }
        self.registrations.insert(
            key,
            Registration {
                definition,
                backend,
                provider,
            },
        );
        Ok(())
    }
    pub fn resolve(&self, reference: &TypeReference, backend: Backend) -> Result<&Registration<P>> {
        self.registrations
            .get(&(reference.clone(), backend))
            .ok_or_else(|| err("EXACT_BACKEND_UNAVAILABLE"))
    }
    pub fn resolve_type(&self, reference: &TypeReference) -> Result<&TypeDefinition> {
        self.registrations
            .values()
            .find(|r| r.definition.reference() == reference)
            .map(|r| &r.definition)
            .ok_or_else(|| err("EXACT_TYPE_UNAVAILABLE"))
    }
    pub fn registrations(&self) -> Vec<&Registration<P>> {
        self.registrations.values().collect()
    }
    pub fn types(&self) -> Vec<&TypeDefinition> {
        let mut types = BTreeMap::new();
        for r in self.registrations.values() {
            types
                .entry(r.definition.reference())
                .or_insert(&r.definition);
        }
        types.into_values().collect()
    }
}
