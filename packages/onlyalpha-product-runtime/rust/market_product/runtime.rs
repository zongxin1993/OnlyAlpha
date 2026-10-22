use super::*;
use crate::{
    integration_configuration::{Lifecycle, RuntimeBinding},
    integration_postgres::Snapshot,
    source_access::{Permission, Reference, Selection, Session},
};
use onlyalpha_domain::base::OnlyDomainModel;
use onlyalpha_integration_contract::{
    Category,
    source::{Clock, Factory, Resource, Trust},
};
use std::{collections::BTreeMap, sync::Arc};
/// Host reads and verifies the actual selected executable artifact. Source-only
/// metadata cannot qualify native bytes. Trusted composition is the constructor.
pub struct Installed {
    factory: Arc<dyn Factory>,
    artifact: String,
}
impl Installed {
    pub fn from_executable(
        factory: Arc<dyn Factory>,
        actual_executable_bytes: &[u8],
    ) -> Result<Self> {
        if actual_executable_bytes.is_empty()
            || !crate::is_sha256_hex(factory.implementation_fingerprint())
        {
            return Err(Error::Invalid);
        }
        Ok(Self {
            factory,
            artifact: hash(actual_executable_bytes),
        })
    }
}
pub trait GenerationAdmission {
    fn require_exact(&self, generation: &str, artifact: &str, implementation: &str) -> Result<()>;
}
pub struct Resolver {
    installed: BTreeMap<String, Installed>,
    trust: Trust,
    clock: Arc<dyn Clock>,
}
pub struct Resolved {
    pub(super) selection: Selection,
    pub(super) binding: RuntimeBinding,
    pub(super) resource: Arc<dyn Resource>,
    pub(super) artifact: String,
    pub(super) implementation: String,
    pub(super) data_version: String,
    pub(super) probe_contract: String,
    pub(super) probe_configuration: Option<String>,
    pub(super) probe_symbol: String,
    pub(super) clock: Arc<dyn Clock>,
}
impl Resolver {
    pub fn new(installed: Vec<Installed>, trust: Trust, clock: Arc<dyn Clock>) -> Result<Self> {
        let mut map = BTreeMap::new();
        for entry in installed {
            let id = entry.factory.descriptor().id().value().to_owned();
            if map.insert(id, entry).is_some() {
                return Err(Error::Invalid);
            }
        }
        Ok(Self {
            installed: map,
            trust,
            clock,
        })
    }
    /// Eligible current configured Sources, derived from real verified snapshots.
    /// Only a proved grant/lifecycle mismatch is omitted; missing implementation
    /// or corrupt proof remains an explicit unavailable/error outcome.
    pub fn sources(
        &self,
        snapshots: &[Snapshot],
        session: &Session,
    ) -> Result<(Vec<Resolved>, super::queries::AuthorizedBatch)> {
        session.check_active()?;
        let mut resources = vec![];
        let mut rows = vec![];
        for snapshot in snapshots {
            let owner = snapshot.integration().record();
            if owner.lifecycle != Lifecycle::Active {
                continue;
            }
            let Some(revision) = owner.current_revision_fingerprint.as_deref() else {
                continue;
            };
            let reference = Reference::new(
                owner.integration_id.value(),
                revision,
                Some(owner.type_id.value()),
            )?;
            if session
                .require_reference(&reference, Permission::ClosedHistory)
                .is_err()
            {
                session.check_active()?;
                continue;
            }
            let r = self.resolve(snapshot, &reference, session, None)?;
            rows.push(serde_json::json!({"integration_id":reference.integration_id(),"integration_revision_fingerprint":reference.revision(),"display_name":owner.display_name,"type_id":owner.type_id.value(),"source_id":r.identity().source_id,"environment":r.identity().environment,"new_work_status":"AVAILABLE","new_work_unavailable_code":null,"history_read_policy":"EXACT_SEALED_PROOF","is_current_revision":true,"time_bar_capability":{"provider_base_semantic":super::queries::semantic(1)?.to_record(),"minimum_window_minutes":1,"maximum_window_minutes":240,"derived_algorithm":"TIME_BAR@1"}}));
            resources.push(r);
        }
        let selections = resources
            .iter()
            .map(|r| (r.selection.clone(), Permission::ClosedHistory))
            .collect();
        let projection = super::queries::AuthorizedBatch::new(
            serde_json::json!({"schema_version":1,"sources":rows}),
            session,
            selections,
        )?;
        Ok((resources, projection))
    }
    pub fn resolve(
        &self,
        snapshot: &Snapshot,
        reference: &Reference,
        session: &Session,
        generation: Option<(&str, &dyn GenerationAdmission)>,
    ) -> Result<Resolved> {
        session.require_reference(reference, Permission::ClosedHistory)?;
        let resolved = self.resolve_exact(snapshot, reference, generation)?;
        session.require_selection(&resolved.selection, Permission::ClosedHistory)?;
        Ok(resolved)
    }
    /// Owner-authorized configuration Probe is independent of chart read grants.
    /// Factory construction performs no provider I/O; admission precedes Probe.
    pub fn resolve_for_probe(
        &self,
        snapshot: &Snapshot,
        reference: &Reference,
        admission: &dyn super::ProbeAdmission,
        attempt_id: &str,
    ) -> Result<Resolved> {
        if !crate::command::uuid4(attempt_id) {
            return Err(Error::Invalid);
        }
        let resolved = self.resolve_exact(snapshot, reference, None)?;
        admission.require_probe(&resolved.selection, attempt_id)?;
        Ok(resolved)
    }
    fn resolve_exact(
        &self,
        snapshot: &Snapshot,
        reference: &Reference,
        generation: Option<(&str, &dyn GenerationAdmission)>,
    ) -> Result<Resolved> {
        let owner = snapshot.integration().record();
        if owner.integration_id.value() != reference.integration_id()
            || owner.lifecycle != Lifecycle::Active
        {
            return Err(Error::Selection);
        }
        let (revision, bindings) = snapshot
            .history()
            .iter()
            .find(|(r, _)| r.record().revision_fingerprint == reference.revision())
            .ok_or(Error::Selection)?;
        let r = revision.record();
        if r.integration_id != owner.integration_id
            || r.type_id != owner.type_id
            || reference
                .expected_type_id()
                .is_some_and(|id| id != r.type_id.value())
        {
            return Err(Error::Corrupt);
        }
        let installed = self
            .installed
            .get(r.type_id.value())
            .ok_or(Error::Unavailable)?;
        let descriptor = installed.factory.descriptor();
        // Exact current contract only. Old metadata remains readable but cannot select
        // an unavailable executable, even when type_id/public API happen to agree.
        if descriptor.category() != Category::DataSource
            || descriptor.fingerprint() != r.type_descriptor_fingerprint
        {
            return Err(Error::Selection);
        }
        let stored = onlyalpha_integration_contract::Descriptor::from_json(
            r.type_descriptor_document.raw().get(),
            64 * 1024 * 1024,
        )
        .map_err(|_| Error::Corrupt)?;
        if stored.fingerprint() != descriptor.fingerprint() {
            return Err(Error::Selection);
        }
        let publication = crate::integration_resolver::resolve_publication(
            r.integration_id.clone(),
            descriptor,
            &r.configuration_document,
            r.probe_configuration_document.as_ref(),
            bindings,
            64 * 1024 * 1024,
        )
        .map_err(|_| Error::Corrupt)?;
        if publication
            .revision_fingerprint()
            .map_err(|_| Error::Corrupt)?
            != r.revision_fingerprint
        {
            return Err(Error::Corrupt);
        }
        if !bindings.is_empty() {
            return Err(Error::Unavailable);
        }
        installed
            .factory
            .validate_configuration(r.configuration_document.raw())
            .map_err(|_| Error::Corrupt)?;
        let admitted_generation = if let Some((id, admission)) = generation {
            if !crate::is_sha256_hex(id) {
                return Err(Error::Invalid);
            }
            admission.require_exact(
                id,
                &installed.artifact,
                installed.factory.implementation_fingerprint(),
            )?;
            Some(id)
        } else {
            None
        };
        let binding =
            RuntimeBinding::from_revision(revision, Category::DataSource, admitted_generation)
                .map_err(|_| Error::Corrupt)?;
        let resource = installed.factory.create(
            r.configuration_document.raw(),
            &self.trust,
            Arc::clone(&self.clock),
        )?;
        let identity = resource.identity();
        let reference = Reference::new(
            reference.integration_id(),
            reference.revision(),
            Some(r.type_id.value()),
        )?;
        let selection = Selection::new(reference, &identity.source_id, &identity.environment)?;
        let descriptor_json: Value =
            serde_json::from_str(descriptor.document().get()).map_err(|_| Error::Corrupt)?;
        let probe_contract = descriptor_json["probe_contract"]["fingerprint"]
            .as_str()
            .ok_or(Error::Selection)?
            .to_owned();
        let probe_configuration = r.probe_configuration_fingerprint.clone();
        let probe_config = r
            .probe_configuration_document
            .as_ref()
            .map(|d| serde_json::from_str::<Value>(d.raw().get()))
            .transpose()
            .map_err(|_| Error::Corrupt)?;
        let probe_symbol = probe_config
            .as_ref()
            .and_then(|d| d["instrument"].as_str())
            .or_else(|| descriptor_json["probe_contract"]["default_probe_instrument"].as_str())
            .ok_or(Error::Corrupt)?
            .to_owned();
        Ok(Resolved {
            selection,
            clock: Arc::clone(&self.clock),
            probe_contract,
            probe_configuration,
            probe_symbol,
            binding,
            resource,
            artifact: installed.artifact.clone(),
            implementation: fp(
                &serde_json::json!({"implementation_contract":installed.factory.implementation_fingerprint(),"executable_artifact":installed.artifact}),
            )?,
            data_version: format!(
                "{}@{}",
                r.type_id.value(),
                serde_json::from_str::<Value>(descriptor.document().get())
                    .map_err(|_| Error::Corrupt)?["public_api_version"]
                    .as_str()
                    .ok_or(Error::Corrupt)?
            ),
        })
    }
}
impl Resolved {
    pub fn selection(&self) -> &Selection {
        &self.selection
    }
    pub fn binding_fingerprint(&self) -> &str {
        self.binding.fingerprint()
    }
    pub fn artifact_fingerprint(&self) -> &str {
        &self.artifact
    }
    pub fn implementation_fingerprint(&self) -> &str {
        &self.implementation
    }
    pub fn identity(&self) -> &onlyalpha_integration_contract::source::MarketIdentity {
        self.resource.identity()
    }
}
impl Resolver {
    /// Original metadata and current executable admission are separate facts.
    /// Explicit pure identity witnesses never qualify a historical executable.
    pub fn sources_with_history(
        &self,
        snapshots: &[Snapshot],
        session: &Session,
        identities: &[(
            Reference,
            onlyalpha_integration_contract::source::MarketIdentity,
        )],
    ) -> Result<(Vec<Resolved>, super::queries::AuthorizedBatch)> {
        session.check_active()?;
        let mut resources = vec![];
        let mut rows = vec![];
        let mut selections = vec![];
        for (reference, identity) in identities {
            let snapshot = snapshots
                .iter()
                .find(|s| {
                    s.integration().record().integration_id.value() == reference.integration_id()
                })
                .ok_or(Error::Selection)?;
            let selected =
                super::history::original_selection(snapshot, reference, session, identity)?;
            let current = self.resolve(snapshot, reference, session, None);
            let (status, code) = match &current {
                Ok(_) => ("AVAILABLE", None),
                Err(e) => ("UNAVAILABLE", Some(e.code())),
            };
            rows.push(serde_json::json!({"integration_id":reference.integration_id(),"integration_revision_fingerprint":reference.revision(),"display_name":snapshot.integration().record().display_name,"type_id":reference.expected_type_id(),"source_id":identity.source_id,"environment":identity.environment,"new_work_status":status,"new_work_unavailable_code":code,"history_read_policy":"EXACT_SEALED_PROOF","is_current_revision":snapshot.integration().record().current_revision_fingerprint.as_deref()==Some(reference.revision()),"time_bar_capability":{"provider_base_semantic":super::queries::semantic(1)?.to_record(),"minimum_window_minutes":1,"maximum_window_minutes":240,"derived_algorithm":"TIME_BAR@1"}}));
            selections.push((selected, Permission::ClosedHistory));
            if let Ok(resource) = current {
                resources.push(resource);
            }
        }
        Ok((
            resources,
            super::queries::AuthorizedBatch::new(
                serde_json::json!({"schema_version":1,"sources":rows}),
                session,
                selections,
            )?,
        ))
    }
}
