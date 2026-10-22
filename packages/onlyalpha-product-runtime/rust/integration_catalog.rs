//! Immutable compiled authoring projection; no discovery I/O or runtime grants.
use onlyalpha_integration_contract::{Error, IntegrationTypeId, authoring::Registration};
use std::collections::BTreeMap;

pub struct AuthoringCatalog {
    registrations: BTreeMap<String, Registration>,
}
impl AuthoringCatalog {
    /// Node composition supplies its finite installed set, never an HTTP payload.
    /// Duplicate type identity is invalid, including different plugin versions.
    pub fn new(registrations: Vec<Registration>) -> Result<Self, Error> {
        let mut installed = BTreeMap::new();
        for registration in registrations {
            let id = registration.descriptor().id().value().to_owned();
            if installed.insert(id, registration).is_some() {
                return Err(Error::Type);
            }
        }
        Ok(Self {
            registrations: installed,
        })
    }
    pub fn get(&self, id: &IntegrationTypeId) -> Option<&Registration> {
        self.registrations.get(id.value())
    }
    pub fn iter(&self) -> impl ExactSizeIterator<Item = &Registration> {
        self.registrations.values()
    }
}
