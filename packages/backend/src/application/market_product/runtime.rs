use super::*;
use crate::application::integration_configuration::{
    Lifecycle, Revision, RuntimeBinding, SecretBinding,
};
use crate::application::source_access::{Permission, Reference, Selection, Session};
use crate::persistence::integration_postgres::Snapshot;
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
    pub(super) public_configuration: Box<serde_json::value::RawValue>,
    pub(super) selection: Selection,
    pub(super) binding: RuntimeBinding,
    pub(super) resource: Arc<dyn Resource>,
    pub(super) artifact: String,
    pub(super) implementation: String,
    pub(super) data_version: String,
    pub(super) probe_contract: String,
    pub(super) probe_checks: Vec<String>,
    pub(super) probe_configuration: Option<String>,
    pub(super) probe_symbol: String,
    pub(super) clock: Arc<dyn Clock>,
}
/// 已验证的实现、原 revision 和 binding。取得这些值不会创建 Provider session。
pub(crate) struct SourceInstallation<'a> {
    resolver: &'a Resolver,
    installed: &'a Installed,
    revision: &'a Revision,
    bindings: &'a [SecretBinding],
    pub(crate) binding: RuntimeBinding,
    pub(crate) implementation: String,
}
impl SourceInstallation<'_> {
    pub(crate) fn artifact(&self) -> &str {
        &self.installed.artifact
    }
    pub(crate) fn needs_secrets(&self) -> bool {
        !self.bindings.is_empty()
    }

    /// 调用方须已核准所选 Source 的具体操作。每个绑定在原 Slot/generation 下验证和解密。
    pub(crate) async fn connect(
        &self,
        store: &mut crate::persistence::credential_postgres::Credentials<'_>,
    ) -> Result<Resolved> {
        use crate::security::credentials::{CredentialId, Slot};
        let owner = self.revision.record();
        let mut secrets = Vec::with_capacity(self.bindings.len());
        for binding in self.bindings {
            let slot = Slot::new(
                "INTEGRATION_SECRET",
                owner.integration_id.value(),
                binding.field_id(),
            )
            .map_err(|_| Error::Corrupt)?;
            let id =
                CredentialId::new(binding.credential_id().value()).map_err(|_| Error::Corrupt)?;
            let secret = store
                .read_secret_for_slot(&id, binding.generation(), &slot, 64 * 1024 * 1024)
                .await
                .map_err(|_| Error::Unavailable)?;
            secrets.push((binding.field_id(), secret));
        }
        let fields = secrets
            .iter()
            .map(|(field, secret)| (*field, secret.expose()))
            .collect::<Vec<_>>();
        self.open(&fields)
    }
}
impl Resolver {
    pub(crate) fn public_transport_trust(&self) -> &Trust {
        &self.trust
    }
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
        let resolved = self
            .installation(snapshot, reference, generation)?
            .open(&[])?;
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
        if !crate::application::command::uuid4(attempt_id) {
            return Err(Error::Invalid);
        }
        let resolved = self.installation(snapshot, reference, None)?.open(&[])?;
        admission.require_probe(&resolved.selection, attempt_id)?;
        Ok(resolved)
    }
    pub(crate) fn installation<'a>(
        &'a self,
        snapshot: &'a Snapshot,
        reference: &Reference,
        generation: Option<(&str, &dyn GenerationAdmission)>,
    ) -> Result<SourceInstallation<'a>> {
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
        let publication = crate::application::integration_resolver::resolve_publication(
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
        let implementation = fp(
            &serde_json::json!({"implementation_contract":installed.factory.implementation_fingerprint(),"executable_artifact":installed.artifact}),
        )?;
        Ok(SourceInstallation {
            resolver: self,
            installed,
            revision,
            bindings,
            binding,
            implementation,
        })
    }
}
impl SourceInstallation<'_> {
    pub(crate) fn open_public(&self) -> Result<Resolved> {
        self.open(&[])
    }
    fn open(&self, fields: &[(&str, &str)]) -> Result<Resolved> {
        if self.bindings.len() != fields.len()
            || self
                .bindings
                .iter()
                .zip(fields)
                .any(|(b, (name, _))| b.field_id() != *name)
        {
            return Err(Error::Unavailable);
        }
        let installed = self.installed;
        let r = self.revision.record();
        let descriptor = installed.factory.descriptor();
        let resource = installed.factory.create_with_credentials(
            r.configuration_document.raw(),
            &self.resolver.trust,
            Arc::clone(&self.resolver.clock),
            fields,
        )?;
        let identity = resource.identity();
        let reference = Reference::new(
            r.integration_id.value(),
            &r.revision_fingerprint,
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
            public_configuration: serde_json::value::RawValue::from_string(
                r.configuration_document.raw().get().to_owned(),
            )
            .map_err(|_| Error::Corrupt)?,
            selection,
            clock: Arc::clone(&self.resolver.clock),
            probe_contract,
            probe_checks: serde_json::from_value(
                descriptor_json["probe_contract"]["probe_checks"].clone(),
            )
            .map_err(|_| Error::Corrupt)?,
            probe_configuration,
            probe_symbol,
            binding: self.binding.clone(),
            resource,
            artifact: installed.artifact.clone(),
            implementation: self.implementation.clone(),
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
    pub(crate) fn public_configuration(&self) -> &serde_json::value::RawValue {
        &self.public_configuration
    }
    pub(crate) fn resource(&self) -> &dyn Resource {
        self.resource.as_ref()
    }
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
/// 保留原 revision 的只读历史能力和本次安装准入分别取证。
pub(crate) struct DeclaredSource<'a> {
    pub snapshot: &'a Snapshot,
    pub reference: Reference,
    pub identity: onlyalpha_integration_contract::source::MarketIdentity,
    pub day: Option<onlyalpha_domain::market::OnlyBarSemantic>,
    pub current: Result<Resolved>,
}
impl Resolver {
    pub(crate) fn sources_with_history(
        &self,
        session: &Session,
        sources: Vec<DeclaredSource<'_>>,
    ) -> Result<(Vec<Resolved>, super::queries::AuthorizedBatch)> {
        session.check_active()?;
        let mut resources = vec![];
        let mut rows = vec![];
        let mut selections = vec![];
        for DeclaredSource {
            snapshot,
            reference,
            identity,
            day,
            current,
        } in sources
        {
            let selected =
                super::history::original_selection(snapshot, &reference, session, &identity)?;
            let (status, code) = match &current {
                Ok(_) => ("AVAILABLE", None),
                Err(e) => ("UNAVAILABLE", Some(e.code())),
            };
            let mut row = serde_json::json!({"integration_id":reference.integration_id(),"integration_revision_fingerprint":reference.revision(),"display_name":snapshot.integration().record().display_name,"type_id":reference.expected_type_id(),"source_id":identity.source_id,"environment":identity.environment,"new_work_status":status,"new_work_unavailable_code":code,"history_read_policy":"EXACT_SEALED_PROOF","is_current_revision":snapshot.integration().record().current_revision_fingerprint.as_deref()==Some(reference.revision())});
            if let Some(semantic) = day {
                row["historical_day_semantic"] = semantic.to_record();
            } else {
                row["time_bar_capability"] = serde_json::json!({"provider_base_semantic":super::queries::semantic(1)?.to_record(),"minimum_window_minutes":1,"maximum_window_minutes":240,"derived_algorithm":"TIME_BAR@1"});
            }
            rows.push(row);
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
