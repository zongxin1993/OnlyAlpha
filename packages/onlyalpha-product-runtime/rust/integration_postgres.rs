//! Exact Integration history from the node-owned canonical PostgreSQL connection.
use crate::integration_catalog::AuthoringCatalog;
use crate::{
    command::{
        Admission, Binding, CommandKind, Error as CommandError, Outcome, OutcomeKind, Receipt,
    },
    integration_commands::{
        ClearSecret, CommandResult, CreateIntegration, Error as WriteError, PublishRevision,
        ResetDraftContract, SetLifecycle, UpdateDraft,
    },
    integration_configuration::Lifecycle,
    postgres::Commands,
};
use crate::{
    integration_configuration::{
        Draft, DraftRecord, Error, Integration, IntegrationId, IntegrationRecord, ObjectDocument,
        Revision, RevisionRecord, SecretBinding,
    },
    postgres,
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use onlyalpha_integration_contract::{Descriptor, IntegrationTypeId, authoring::Registration};
use onlyalpha_metadata_json as document_identity;
use tokio_postgres::{Client, IsolationLevel, Row, Transaction, types::FromSqlOwned};

/// A verified, single-snapshot metadata view. It confers no runtime readiness.
pub struct Snapshot {
    integration: Integration,
    draft: Option<(Draft, Vec<SecretBinding>)>,
    history: Vec<(Revision, Vec<SecretBinding>)>,
}
impl Snapshot {
    pub fn integration(&self) -> &Integration {
        &self.integration
    }
    pub fn draft(&self) -> Option<(&Draft, &[SecretBinding])> {
        self.draft
            .as_ref()
            .map(|(draft, bindings)| (draft, bindings.as_slice()))
    }
    pub fn history(&self) -> &[(Revision, Vec<SecretBinding>)] {
        &self.history
    }
}

pub struct Integrations<'a> {
    client: &'a mut Client,
}
impl<'a> Integrations<'a> {
    pub fn new(client: &'a mut Client) -> Self {
        Self { client }
    }
    /// Replay is independent of installed plugins and does not repeat old effects.
    pub async fn replay(
        &mut self,
        admission: &Admission,
        id: &IntegrationId,
        max_rows: usize,
        work: usize,
    ) -> Result<Option<CommandResult>, WriteError> {
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        let result = replay_in_transaction(&tx, admission, id, max_rows, work).await?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(result)
    }
    /// HTTP composition separately proves Owner permission and node mutation
    /// admission. Exact current authoring is selected after replay in this commit.
    pub async fn create(
        &mut self,
        command: &CreateIntegration,
        catalog: &AuthoringCatalog,
        now: OnlyUtcDateTime,
        work: usize,
    ) -> Result<CommandResult, WriteError> {
        let admission = command.admission(work)?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        if let Some(replay) =
            replay_in_transaction(&tx, &admission, &command.integration_id, 1, work).await?
        {
            tx.commit().await.map_err(|_| Error::Unavailable)?;
            return Ok(replay);
        }
        Commands::admit_exact_in_transaction(&tx, &admission).await?;
        let registration = catalog
            .get(&command.type_id)
            .ok_or(WriteError::TypeUnavailable)?;
        let descriptor = registration.descriptor();
        let owner = Integration::restore(IntegrationRecord {
            integration_id: command.integration_id.clone(),
            type_id: command.type_id.clone(),
            display_name: command.display_name.clone(),
            lifecycle: Lifecycle::Active,
            current_revision_fingerprint: None,
            created_at: now,
            updated_at: now,
        })?;
        let mut draft = DraftRecord {
            integration_id: command.integration_id.clone(),
            base_revision_fingerprint: None,
            type_descriptor_fingerprint: descriptor.fingerprint().into(),
            type_descriptor_document: ObjectDocument::new(descriptor.document().get(), work)?,
            public_configuration_document: ObjectDocument::new("{}", work)?,
            probe_configuration_document: None,
            draft_version: 1,
            draft_fingerprint: String::new(),
            created_at: now,
            updated_at: now,
        };
        draft.draft_fingerprint = Draft::derive_fingerprint(&draft, &[])?;
        let draft = Draft::restore(draft, &[])?;
        let draft = draft.record();
        let timestamp = postgres::system_time(now)?;
        tx.execute("INSERT INTO integration(integration_id,type_id,display_name,lifecycle_state,created_at,updated_at) VALUES($1::text::uuid,$2,$3,'ACTIVE',$4,$4)",&[&owner.record().integration_id.value(),&owner.record().type_id.value(),&owner.record().display_name,&timestamp]).await.map_err(|e|if e.code()==Some(&tokio_postgres::error::SqlState::UNIQUE_VIOLATION){Error::PersistenceConflict}else{Error::Unavailable})?;
        tx.execute("INSERT INTO integration_draft(integration_id,base_revision_fingerprint,type_descriptor_fingerprint,type_descriptor_document,public_configuration_document,probe_configuration_document,draft_version,draft_fingerprint,created_at,updated_at) VALUES($1::text::uuid,NULL,$2,$3::text::json,'{}'::json,NULL,1,$4,$5,$5)",&[&command.integration_id.value(),&draft.type_descriptor_fingerprint,&draft.type_descriptor_document.raw().get(),&draft.draft_fingerprint,&timestamp]).await.map_err(|_|Error::Unavailable)?;
        verify_draft_effect(&tx, owner.record(), draft, &[], &mut Rows(2), work).await?;
        let receipt = accepted(&admission, &command.integration_id, &now)?;
        Commands::put_verified_receipt_in_transaction(&tx, &receipt).await?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(CommandResult {
            receipt,
            replayed: false,
        })
    }
    pub async fn set_lifecycle(
        &mut self,
        command: &SetLifecycle,
        now: OnlyUtcDateTime,
        work: usize,
    ) -> Result<CommandResult, WriteError> {
        let admission = command.admission(work)?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        if let Some(replay) =
            replay_in_transaction(&tx, &admission, &command.integration_id, 1, work).await?
        {
            tx.commit().await.map_err(|_| Error::Unavailable)?;
            return Ok(replay);
        }
        // Admission's SourceHistory/frontier locks precede the owning head lock.
        Commands::admit_exact_in_transaction(&tx, &admission).await?;
        let row=tx.query_opt("SELECT integration_id::text,type_id,display_name,lifecycle_state,current_revision_fingerprint,created_at,updated_at FROM integration WHERE integration_id=$1::text::uuid FOR UPDATE",&[&command.integration_id.value()]).await.map_err(|_|Error::Unavailable)?.ok_or(WriteError::NotFound)?;
        let current = integration(&row)?;
        let current = current.record();
        if current.lifecycle != command.expected
            || !matches!(
                (current.lifecycle, command.target),
                (Lifecycle::Active, Lifecycle::Disabled | Lifecycle::Archived)
                    | (Lifecycle::Disabled, Lifecycle::Active | Lifecycle::Archived)
            )
        {
            return Err(WriteError::LifecycleConflict);
        }
        let mut next = current.clone();
        next.lifecycle = command.target;
        next.updated_at = now;
        let next = Integration::restore(next)?;
        let timestamp = postgres::system_time(now)?;
        if tx.execute("UPDATE integration SET lifecycle_state=$2,updated_at=$3 WHERE integration_id=$1::text::uuid AND lifecycle_state=$4",&[&command.integration_id.value(),&command.target.as_str(),&timestamp,&command.expected.as_str()]).await.map_err(|_|Error::Unavailable)?!=1{return Err(WriteError::LifecycleConflict)}
        let row=tx.query_opt("SELECT integration_id::text,type_id,display_name,lifecycle_state,current_revision_fingerprint,created_at,updated_at FROM integration WHERE integration_id=$1::text::uuid",&[&command.integration_id.value()]).await.map_err(|_|Error::Unavailable)?.ok_or(Error::PersistenceConflict)?;
        if integration(&row)?.record() != next.record() {
            return Err(Error::PersistenceConflict.into());
        }
        let receipt = accepted(&admission, &command.integration_id, &now)?;
        Commands::put_verified_receipt_in_transaction(&tx, &receipt).await?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(CommandResult {
            receipt,
            replayed: false,
        })
    }

    pub async fn update_draft(
        &mut self,
        command: &UpdateDraft,
        catalog: &AuthoringCatalog,
        now: OnlyUtcDateTime,
        max_rows: usize,
        work: usize,
    ) -> Result<CommandResult, WriteError> {
        let admission = command.admission(work)?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        if let Some(replay) =
            replay_in_transaction(&tx, &admission, &command.integration_id, max_rows, work).await?
        {
            tx.commit().await.map_err(|_| Error::Unavailable)?;
            return Ok(replay);
        }
        Commands::admit_exact_in_transaction(&tx, &admission).await?;
        let mut budget = Rows(max_rows);
        let (owner, draft, bindings) =
            locked_draft(&tx, &command.integration_id, &mut budget, work).await?;
        let registration = authoring(&owner, &draft, command.expected_version, catalog)?;
        let descriptor = registration.descriptor();
        let (public, probe) = crate::integration_resolver::validate_draft(
            descriptor,
            &command.public,
            command.probe.as_ref(),
            work,
        )?;
        registration.validate_public_configuration(public.raw(), work)?;
        let mut next = draft.record().clone();
        next.public_configuration_document = public;
        next.probe_configuration_document = probe;
        next.draft_version = next
            .draft_version
            .checked_add(1)
            .ok_or(WriteError::DraftVersion)?;
        next.updated_at = now;
        next.draft_fingerprint = Draft::derive_fingerprint(&next, &bindings)?;
        replace_draft(&tx, command.expected_version, next.clone(), &bindings).await?;
        verify_draft_effect(&tx, owner.record(), &next, &bindings, &mut budget, work).await?;
        let receipt = accepted(&admission, &command.integration_id, &now)?;
        Commands::put_verified_receipt_in_transaction(&tx, &receipt).await?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(CommandResult {
            receipt,
            replayed: false,
        })
    }
    pub async fn reset_draft_contract(
        &mut self,
        command: &ResetDraftContract,
        catalog: &AuthoringCatalog,
        now: OnlyUtcDateTime,
        max_rows: usize,
        work: usize,
    ) -> Result<CommandResult, WriteError> {
        let admission = command.admission(work)?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        if let Some(replay) =
            replay_in_transaction(&tx, &admission, &command.integration_id, max_rows, work).await?
        {
            tx.commit().await.map_err(|_| Error::Unavailable)?;
            return Ok(replay);
        }
        Commands::admit_exact_in_transaction(&tx, &admission).await?;
        let mut budget = Rows(max_rows);
        let (owner, draft, _bindings) =
            locked_draft(&tx, &command.integration_id, &mut budget, work).await?;
        let descriptor = mutable(&owner, &draft, command.expected_version, catalog)?.descriptor();
        let mut next = draft.record().clone();
        next.base_revision_fingerprint = owner.record().current_revision_fingerprint.clone();
        next.type_descriptor_fingerprint = descriptor.fingerprint().into();
        next.type_descriptor_document = ObjectDocument::new(descriptor.document().get(), work)?;
        next.public_configuration_document = ObjectDocument::new("{}", work)?;
        next.probe_configuration_document = None;
        next.draft_version = next
            .draft_version
            .checked_add(1)
            .ok_or(WriteError::DraftVersion)?;
        next.updated_at = now;
        next.draft_fingerprint = Draft::derive_fingerprint(&next, &[])?;
        replace_draft(&tx, command.expected_version, next.clone(), &[]).await?;
        tx.execute(
            "DELETE FROM integration_draft_secret_binding WHERE integration_id=$1::text::uuid",
            &[&command.integration_id.value()],
        )
        .await
        .map_err(|_| Error::Unavailable)?;
        verify_draft_effect(&tx, owner.record(), &next, &[], &mut budget, work).await?;
        let receipt = accepted(&admission, &command.integration_id, &now)?;
        Commands::put_verified_receipt_in_transaction(&tx, &receipt).await?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(CommandResult {
            receipt,
            replayed: false,
        })
    }

    pub async fn set_secret(
        &mut self,
        command: &crate::integration_commands::SetSecret,
        catalog: &AuthoringCatalog,
        key: &crate::credentials::Key,
        now: OnlyUtcDateTime,
        max_rows: usize,
        work: usize,
    ) -> Result<CommandResult, WriteError> {
        let admission = command.admission(key, work)?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        if let Some(replay) =
            replay_in_transaction(&tx, &admission, &command.integration_id, max_rows, work).await?
        {
            tx.commit().await.map_err(|_| Error::Unavailable)?;
            return Ok(replay);
        }
        Commands::admit_exact_in_transaction(&tx, &admission).await?;
        let mut budget = Rows(max_rows);
        let (owner, draft, bindings) =
            locked_draft(&tx, &command.integration_id, &mut budget, work).await?;
        let registration = authoring(&owner, &draft, command.expected_version, catalog)?;
        let descriptor = registration.descriptor();
        if !descriptor
            .fields()
            .iter()
            .any(|field| field.id() == command.field_id && field.secret())
        {
            return Err(WriteError::SecretField);
        }
        let mut next = draft.record().clone();
        next.draft_version = next
            .draft_version
            .checked_add(1)
            .ok_or(WriteError::DraftVersion)?;
        next.updated_at = now;
        let slot = crate::credentials::Slot::new(
            "INTEGRATION_SECRET",
            command.integration_id.value(),
            &command.field_id,
        )
        .map_err(|_| Error::PersistenceConflict)?;
        // Reserve both a possible current-slot row and the exact write proof.
        budget.consume(2)?;
        let credential = crate::credential_postgres::Credentials::set_slot_in_transaction(
            &tx,
            key,
            &slot,
            &command.plaintext,
            now,
            work,
        )
        .await
        .map_err(|error| {
            if error == crate::credentials::Error::Unavailable {
                Error::Unavailable
            } else {
                Error::PersistenceConflict
            }
        })?;
        let context = credential.context();
        let mut updated: Vec<_> = bindings
            .into_iter()
            .filter(|binding| binding.field_id() != command.field_id)
            .collect();
        updated.push(SecretBinding::new(
            &command.field_id,
            context.credential_id().value(),
            context.generation(),
        )?);
        updated.sort_by(|a, b| a.field_id().cmp(b.field_id()));
        next.draft_fingerprint = Draft::derive_fingerprint(&next, &updated)?;
        replace_draft(&tx, command.expected_version, next.clone(), &updated).await?;
        if tx.execute("INSERT INTO integration_draft_secret_binding(integration_id,field_id,credential_id,credential_generation) VALUES($1::text::uuid,$2,$3::text::uuid,$4) ON CONFLICT(integration_id,field_id) DO UPDATE SET credential_id=EXCLUDED.credential_id,credential_generation=EXCLUDED.credential_generation",&[&command.integration_id.value(),&command.field_id,&context.credential_id().value(),&context.generation()]).await.map_err(|_|Error::Unavailable)?!=1 {return Err(Error::PersistenceConflict.into())}
        verify_draft_effect(&tx, owner.record(), &next, &updated, &mut budget, work).await?;
        validate_bindings(
            &tx,
            &command.integration_id,
            descriptor,
            &updated,
            &mut budget,
        )
        .await?;
        let receipt = accepted(&admission, &command.integration_id, &now)?;
        Commands::put_verified_receipt_in_transaction(&tx, &receipt).await?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(CommandResult {
            receipt,
            replayed: false,
        })
    }

    pub async fn clear_secret(
        &mut self,
        command: &ClearSecret,
        catalog: &AuthoringCatalog,
        now: OnlyUtcDateTime,
        max_rows: usize,
        work: usize,
    ) -> Result<CommandResult, WriteError> {
        let admission = command.admission(work)?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        if let Some(replay) =
            replay_in_transaction(&tx, &admission, &command.integration_id, max_rows, work).await?
        {
            tx.commit().await.map_err(|_| Error::Unavailable)?;
            return Ok(replay);
        }
        Commands::admit_exact_in_transaction(&tx, &admission).await?;
        let mut budget = Rows(max_rows);
        let (owner, draft, bindings) =
            locked_draft(&tx, &command.integration_id, &mut budget, work).await?;
        let registration = authoring(&owner, &draft, command.expected_version, catalog)?;
        let descriptor = registration.descriptor();
        if !descriptor
            .fields()
            .iter()
            .any(|field| field.id() == command.field_id && field.secret())
        {
            return Err(WriteError::SecretField);
        }
        let remaining: Vec<_> = bindings
            .into_iter()
            .filter(|binding| binding.field_id() != command.field_id)
            .collect();
        let mut next = draft.record().clone();
        next.draft_version = next
            .draft_version
            .checked_add(1)
            .ok_or(WriteError::DraftVersion)?;
        next.updated_at = now;
        next.draft_fingerprint = Draft::derive_fingerprint(&next, &remaining)?;
        replace_draft(&tx, command.expected_version, next.clone(), &remaining).await?;
        tx.execute("DELETE FROM integration_draft_secret_binding WHERE integration_id=$1::text::uuid AND field_id=$2",&[&command.integration_id.value(),&command.field_id]).await.map_err(|_|Error::Unavailable)?;
        verify_draft_effect(&tx, owner.record(), &next, &remaining, &mut budget, work).await?;
        validate_bindings(
            &tx,
            &command.integration_id,
            descriptor,
            &remaining,
            &mut budget,
        )
        .await?;
        let receipt = accepted(&admission, &command.integration_id, &now)?;
        Commands::put_verified_receipt_in_transaction(&tx, &receipt).await?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(CommandResult {
            receipt,
            replayed: false,
        })
    }
    pub async fn publish_revision(
        &mut self,
        command: &PublishRevision,
        catalog: &AuthoringCatalog,
        now: OnlyUtcDateTime,
        max_rows: usize,
        work: usize,
    ) -> Result<CommandResult, WriteError> {
        let admission = command.admission(work)?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        if let Some(replay) =
            replay_in_transaction(&tx, &admission, &command.integration_id, max_rows, work).await?
        {
            tx.commit().await.map_err(|_| Error::Unavailable)?;
            return Ok(replay);
        }
        Commands::admit_exact_in_transaction(&tx, &admission).await?;
        let mut budget = Rows(max_rows);
        let (owner, draft, bindings) =
            locked_draft(&tx, &command.integration_id, &mut budget, work).await?;
        let registration = authoring(&owner, &draft, command.expected_version, catalog)?;
        let descriptor = registration.descriptor();
        if draft.record().base_revision_fingerprint != owner.record().current_revision_fingerprint {
            return Err(WriteError::BaseRevision);
        }
        let resolved = crate::integration_resolver::resolve_publication(
            command.integration_id.clone(),
            descriptor,
            &draft.record().public_configuration_document,
            draft.record().probe_configuration_document.as_ref(),
            &bindings,
            work,
        )?;
        registration.validate_public_configuration(resolved.public_configuration().raw(), work)?;
        let bindings = resolved.bindings().to_vec();
        let fingerprint = resolved.revision_fingerprint()?;
        let existing = exact_revision(&tx, &fingerprint, &mut budget, work).await?;
        if existing.as_ref().is_some_and(|revision| {
            revision.record().integration_id != command.integration_id
                || revision.record().type_id != owner.record().type_id
        }) {
            return Err(Error::RevisionCorrupt.into());
        }
        let (sequence, created_at) = if let Some(existing) = &existing {
            crate::integration_resolver::validate_reused_revision(existing, &bindings, work)?;
            (
                existing.record().revision_sequence,
                existing.record().created_at,
            )
        } else {
            let row=tx.query_one("SELECT max(revision_sequence) FROM integration_revision WHERE integration_id=$1::text::uuid",&[&command.integration_id.value()]).await.map_err(|_|Error::Unavailable)?;
            budget.consume(1)?;
            let maximum = row
                .try_get::<_, Option<i32>>(0)
                .map_err(|_| Error::PersistenceConflict)?
                .unwrap_or(0);
            (
                maximum.checked_add(1).ok_or(Error::PersistenceConflict)?,
                now,
            )
        };
        let revision = resolved.into_revision(sequence, created_at)?;
        if existing.is_none() {
            put_revision(&tx, &revision, &bindings, &mut budget, work).await?;
        }
        let record = revision.record();
        let mut expected_owner = owner.record().clone();
        expected_owner.current_revision_fingerprint = Some(record.revision_fingerprint.clone());
        expected_owner.updated_at = now;
        let timestamp = postgres::system_time(now)?;
        if tx.execute("UPDATE integration SET current_revision_fingerprint=$2,updated_at=$3 WHERE integration_id=$1::text::uuid",&[&command.integration_id.value(),&record.revision_fingerprint,&timestamp]).await.map_err(|_|Error::Unavailable)?!=1{return Err(WriteError::NotFound)}
        let mut next = draft.record().clone();
        next.base_revision_fingerprint = Some(record.revision_fingerprint.clone());
        next.public_configuration_document = record.configuration_document.clone();
        next.probe_configuration_document = record.probe_configuration_document.clone();
        next.draft_version = next
            .draft_version
            .checked_add(1)
            .ok_or(WriteError::DraftVersion)?;
        next.updated_at = now;
        next.draft_fingerprint = Draft::derive_fingerprint(&next, &bindings)?;
        replace_draft(&tx, command.expected_version, next.clone(), &bindings).await?;
        verify_draft_effect(&tx, &expected_owner, &next, &bindings, &mut budget, work).await?;
        validate_bindings(
            &tx,
            &command.integration_id,
            descriptor,
            &bindings,
            &mut budget,
        )
        .await?;
        let receipt = Receipt::new(
            admission,
            Outcome::new(
                OutcomeKind::IntegrationRevision,
                &record.revision_fingerprint,
            )?,
            &now.to_string(),
        )?;
        Commands::put_verified_receipt_in_transaction(&tx, &receipt).await?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(CommandResult {
            receipt,
            replayed: false,
        })
    }

    /// Product metadata remains readable without an installed provider. Runtime
    /// resolution separately verifies the exact published revision and bindings.
    pub async fn list_metadata(
        &mut self,
        type_id: Option<&IntegrationTypeId>,
        lifecycle: Option<crate::integration_configuration::Lifecycle>,
        max_rows: usize,
    ) -> Result<Vec<Integration>, Error> {
        let mut budget = Rows(max_rows);
        let limit = budget.limit()?;
        let tx = self
            .client
            .build_transaction()
            .read_only(true)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        postgres::bounds(&tx)
            .await
            .map_err(|_| Error::Unavailable)?;
        let type_id = type_id.map(IntegrationTypeId::value);
        let lifecycle = lifecycle.map(crate::integration_configuration::Lifecycle::as_str);
        let rows=tx.query("SELECT integration_id::text,type_id,display_name,lifecycle_state,current_revision_fingerprint,created_at,updated_at FROM integration WHERE ($1::text IS NULL OR type_id=$1) AND ($2::text IS NULL OR lifecycle_state=$2) ORDER BY created_at,integration_id LIMIT $3",&[&type_id,&lifecycle,&limit]).await.map_err(|_|Error::Unavailable)?;
        budget.consume(rows.len())?;
        let records = rows
            .iter()
            .map(integration)
            .collect::<Result<Vec<_>, _>>()?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(records)
    }
    /// Complete list/head/Draft/history relationships from one read-only snapshot.
    /// The total row budget includes list identities and every owning reader row.
    /// Unlike authoring admission, a type filter is an arbitrary exact string.
    pub async fn list_snapshots(
        &mut self,
        type_id: Option<&str>,
        lifecycle: Option<Lifecycle>,
        max_rows: usize,
        document_work: usize,
    ) -> Result<Vec<Snapshot>, Error> {
        let mut budget = Rows(max_rows);
        let limit = budget.limit()?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        postgres::bounds(&tx)
            .await
            .map_err(|_| Error::Unavailable)?;
        let lifecycle = lifecycle.map(Lifecycle::as_str);
        let rows = tx.query("SELECT integration_id::text FROM public.integration WHERE ($1::text IS NULL OR type_id=$1) AND ($2::text IS NULL OR lifecycle_state=$2) ORDER BY created_at,integration_id LIMIT $3", &[&type_id, &lifecycle, &limit]).await.map_err(|_| Error::Unavailable)?;
        budget.consume(rows.len())?;
        let mut snapshots = Vec::with_capacity(rows.len());
        for row in rows {
            let id = IntegrationId::new(&get::<String>(&row, "integration_id")?).map_err(stored)?;
            snapshots.push(
                read(&tx, &id, &mut budget, document_work)
                    .await?
                    .ok_or(Error::PersistenceConflict)?,
            );
        }
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(snapshots)
    }
    /// Limits bound total returned rows and work for each original JSON document.
    /// Exhaustion is unavailable, never absence, corruption or a partial history.
    pub async fn read(
        &mut self,
        id: &IntegrationId,
        max_rows: usize,
        document_work: usize,
    ) -> Result<Option<Snapshot>, Error> {
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        postgres::bounds(&tx)
            .await
            .map_err(|_| Error::Unavailable)?;
        let result = read(&tx, id, &mut Rows(max_rows), document_work).await?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(result)
    }
}

fn integration(owner: &Row) -> Result<Integration, Error> {
    Integration::restore(IntegrationRecord {
        integration_id: IntegrationId::new(&get::<String>(owner, "integration_id")?)
            .map_err(stored)?,
        type_id: IntegrationTypeId::new(&get::<String>(owner, "type_id")?)
            .map_err(|_| Error::PersistenceConflict)?,
        display_name: get(owner, "display_name")?,
        lifecycle: get::<String>(owner, "lifecycle_state")?
            .parse()
            .map_err(stored)?,
        current_revision_fingerprint: get(owner, "current_revision_fingerprint")?,
        created_at: time(owner, "created_at")?,
        updated_at: time(owner, "updated_at")?,
    })
    .map_err(stored)
}

struct Rows(usize);
impl Rows {
    fn limit(&self) -> Result<i64, Error> {
        i64::try_from(self.0)
            .ok()
            .and_then(|n| n.checked_add(1))
            .ok_or(Error::Unavailable)
    }
    fn consume(&mut self, n: usize) -> Result<(), Error> {
        self.0 = self.0.checked_sub(n).ok_or(Error::Unavailable)?;
        Ok(())
    }
}
fn get<T: FromSqlOwned>(row: &Row, key: &str) -> Result<T, Error> {
    row.try_get(key).map_err(|_| Error::PersistenceConflict)
}
fn time(row: &Row, key: &str) -> Result<OnlyUtcDateTime, Error> {
    // The Domain reader rejects infinities and values outside canonical UTC.
    postgres::datetime(get(row, key)?).map_err(|_| Error::PersistenceConflict)
}
fn document(row: &Row, key: &str, work: usize) -> Result<ObjectDocument, Error> {
    ObjectDocument::new(&get::<String>(row, key)?, work).map_err(stored)
}
fn optional_document(row: &Row, key: &str, work: usize) -> Result<Option<ObjectDocument>, Error> {
    get::<Option<String>>(row, key)?
        .map(|value| ObjectDocument::new(&value, work).map_err(stored))
        .transpose()
}
fn stored(error: Error) -> Error {
    if error == Error::Unavailable {
        error
    } else {
        Error::PersistenceConflict
    }
}
fn descriptor_type(document: &ObjectDocument) -> Result<IntegrationTypeId, Error> {
    let fields = document_identity::object_fields(document.raw().get())
        .map_err(|_| Error::PersistenceConflict)?;
    let value: String = serde_json::from_str(
        fields
            .get("type_id")
            .ok_or(Error::PersistenceConflict)?
            .get(),
    )
    .map_err(|_| Error::PersistenceConflict)?;
    IntegrationTypeId::new(&value).map_err(|_| Error::PersistenceConflict)
}
async fn bindings(
    tx: &Transaction<'_>,
    owner: &str,
    draft: bool,
    rows: &mut Rows,
) -> Result<Vec<SecretBinding>, Error> {
    let sql = if draft {
        "SELECT field_id,credential_id::text,credential_generation FROM public.integration_draft_secret_binding WHERE integration_id=$1::text::uuid ORDER BY field_id LIMIT $2"
    } else {
        "SELECT field_id,credential_id::text,credential_generation FROM public.integration_revision_secret_binding WHERE revision_fingerprint=$1 ORDER BY field_id LIMIT $2"
    };
    let result = tx
        .query(sql, &[&owner, &rows.limit()?])
        .await
        .map_err(|_| Error::Unavailable)?;
    rows.consume(result.len())?;
    result
        .iter()
        .map(|row| {
            SecretBinding::new(
                &get::<String>(row, "field_id")?,
                &get::<String>(row, "credential_id")?,
                get(row, "credential_generation")?,
            )
            .map_err(stored)
        })
        .collect()
}
async fn read(
    tx: &Transaction<'_>,
    id: &IntegrationId,
    budget: &mut Rows,
    work: usize,
) -> Result<Option<Snapshot>, Error> {
    let owner=tx.query_opt("SELECT integration_id::text,type_id,display_name,lifecycle_state,current_revision_fingerprint,created_at,updated_at FROM public.integration WHERE integration_id=$1::text::uuid",&[&id.value()]).await.map_err(|_|Error::Unavailable)?;
    if owner.is_some() {
        budget.consume(1)?;
    }
    let draft=tx.query_opt("SELECT integration_id::text,base_revision_fingerprint,type_descriptor_fingerprint,type_descriptor_document::text,public_configuration_document::text,probe_configuration_document::text,draft_version,draft_fingerprint,created_at,updated_at FROM public.integration_draft WHERE integration_id=$1::text::uuid",&[&id.value()]).await.map_err(|_|Error::Unavailable)?;
    if draft.is_some() {
        budget.consume(1)?;
    }
    let draft_bindings = bindings(tx, id.value(), true, budget).await?;
    let history=tx.query("SELECT revision_fingerprint,integration_id::text,revision_sequence,type_id,type_descriptor_fingerprint,type_descriptor_document::text,configuration_fingerprint,configuration_document::text,runtime_configuration_fingerprint,probe_configuration_fingerprint,probe_configuration_document::text,secret_binding_fingerprint,created_at FROM public.integration_revision WHERE integration_id=$1::text::uuid ORDER BY revision_sequence,revision_fingerprint LIMIT $2",&[&id.value(),&budget.limit()?]).await.map_err(|_|Error::Unavailable)?;
    budget.consume(history.len())?;
    let Some(owner) = owner else {
        return if draft.is_none() && draft_bindings.is_empty() && history.is_empty() {
            Ok(None)
        } else {
            Err(Error::PersistenceConflict)
        };
    };
    let integration = integration(&owner)?;
    if integration.record().integration_id != *id {
        return Err(Error::PersistenceConflict);
    }
    let draft = match draft {
        Some(row) => {
            let draft = decode_draft(&row, &draft_bindings, work)?;
            if draft.record().integration_id != *id
                || descriptor_type(&draft.record().type_descriptor_document)?
                    != integration.record().type_id
            {
                return Err(Error::PersistenceConflict);
            }
            Some((draft, draft_bindings))
        }
        None if draft_bindings.is_empty() => None,
        None => return Err(Error::PersistenceConflict),
    };
    let mut verified = Vec::with_capacity(history.len());
    for row in history {
        let fingerprint: String = get(&row, "revision_fingerprint")?;
        let bindings = bindings(tx, &fingerprint, false, budget).await?;
        let revision = decode_revision(&row, &bindings, work)?;
        if revision.record().integration_id != *id
            || revision.record().type_id != integration.record().type_id
        {
            return Err(Error::RevisionCorrupt);
        }
        verified.push((revision, bindings));
    }
    for reference in [
        integration.record().current_revision_fingerprint.as_deref(),
        draft
            .as_ref()
            .and_then(|(draft, _)| draft.record().base_revision_fingerprint.as_deref()),
    ]
    .into_iter()
    .flatten()
    {
        if !verified
            .iter()
            .any(|(revision, _)| revision.record().revision_fingerprint == reference)
        {
            return Err(Error::RevisionCorrupt);
        }
    }
    Ok(Some(Snapshot {
        integration,
        draft,
        history: verified,
    }))
}

fn accepted(
    admission: &Admission,
    id: &IntegrationId,
    now: &OnlyUtcDateTime,
) -> Result<Receipt, WriteError> {
    Ok(Receipt::new(
        admission.clone(),
        Outcome::new(OutcomeKind::Integration, id.value())?,
        &now.to_string(),
    )?)
}
async fn replay_in_transaction(
    tx: &Transaction<'_>,
    admission: &Admission,
    id: &IntegrationId,
    max_rows: usize,
    work: usize,
) -> Result<Option<CommandResult>, WriteError> {
    if !matches!(
        admission.kind(),
        CommandKind::CreateIntegration
            | CommandKind::SetIntegrationLifecycle
            | CommandKind::UpdateIntegrationDraft
            | CommandKind::ResetIntegrationDraftContract
            | CommandKind::SetIntegrationSecret
            | CommandKind::ClearIntegrationSecret
            | CommandKind::PublishIntegrationRevision
    ) {
        return Err(CommandError::Conflict.into());
    }
    Commands::lock_command(tx, admission.id()).await?;
    let binding = Commands::verify_binding_in_transaction(tx, admission.id()).await?;
    let receipt = match binding {
        Binding::None => return Ok(None),
        Binding::Admitted(bound) => {
            if bound != *admission {
                return Err(CommandError::Conflict.into());
            }
            return Err(WriteError::Unknown);
        }
        Binding::Accepted(receipt) => receipt,
    };
    if receipt.admission() != admission {
        return Err(CommandError::Conflict.into());
    }
    let publication = admission.kind() == CommandKind::PublishIntegrationRevision;
    if receipt.outcome().kind()
        != if publication {
            OutcomeKind::IntegrationRevision
        } else {
            OutcomeKind::Integration
        }
        || (!publication && receipt.outcome().id() != id.value())
    {
        return Err(CommandError::ReceiptCorrupt.into());
    }
    let mut budget = Rows(max_rows);
    let row=tx.query_opt("SELECT integration_id::text,type_id,display_name,lifecycle_state,current_revision_fingerprint,created_at,updated_at FROM integration WHERE integration_id=$1::text::uuid",&[&id.value()]).await.map_err(|_|Error::Unavailable)?.ok_or(CommandError::ReceiptCorrupt)?;
    budget.consume(1)?;
    let owner = integration(&row).map_err(|_| CommandError::ReceiptCorrupt)?;
    if publication {
        let revision = exact_revision(tx, receipt.outcome().id(), &mut budget, work)
            .await
            .map_err(|error| {
                if error == Error::Unavailable {
                    WriteError::Model(error)
                } else {
                    WriteError::Command(CommandError::ReceiptCorrupt)
                }
            })?
            .ok_or(CommandError::ReceiptCorrupt)?;
        if revision.record().integration_id != *id
            || revision.record().type_id != owner.record().type_id
        {
            return Err(CommandError::ReceiptCorrupt.into());
        }
    }
    Ok(Some(CommandResult {
        receipt,
        replayed: true,
    }))
}

fn decode_draft(row: &Row, bindings: &[SecretBinding], work: usize) -> Result<Draft, Error> {
    let record = DraftRecord {
        integration_id: IntegrationId::new(&get::<String>(row, "integration_id")?)
            .map_err(stored)?,
        base_revision_fingerprint: get(row, "base_revision_fingerprint")?,
        type_descriptor_fingerprint: get(row, "type_descriptor_fingerprint")?,
        type_descriptor_document: document(row, "type_descriptor_document", work)?,
        public_configuration_document: document(row, "public_configuration_document", work)?,
        probe_configuration_document: optional_document(row, "probe_configuration_document", work)?,
        draft_version: get(row, "draft_version")?,
        draft_fingerprint: get(row, "draft_fingerprint")?,
        created_at: time(row, "created_at")?,
        updated_at: time(row, "updated_at")?,
    };
    Draft::restore(record, bindings).map_err(stored)
}
fn decode_revision(row: &Row, bindings: &[SecretBinding], work: usize) -> Result<Revision, Error> {
    Revision::restore(
        RevisionRecord {
            revision_fingerprint: get(row, "revision_fingerprint")?,
            integration_id: IntegrationId::new(&get::<String>(row, "integration_id")?)
                .map_err(stored)?,
            revision_sequence: get(row, "revision_sequence")?,
            type_id: IntegrationTypeId::new(&get::<String>(row, "type_id")?)
                .map_err(|_| Error::RevisionCorrupt)?,
            type_descriptor_fingerprint: get(row, "type_descriptor_fingerprint")?,
            type_descriptor_document: document(row, "type_descriptor_document", work)?,
            configuration_fingerprint: get(row, "configuration_fingerprint")?,
            configuration_document: document(row, "configuration_document", work)?,
            runtime_configuration_fingerprint: get(row, "runtime_configuration_fingerprint")?,
            probe_configuration_fingerprint: get(row, "probe_configuration_fingerprint")?,
            probe_configuration_document: optional_document(
                row,
                "probe_configuration_document",
                work,
            )?,
            secret_binding_fingerprint: get(row, "secret_binding_fingerprint")?,
            created_at: time(row, "created_at")?,
        },
        bindings,
    )
    .map_err(|error| {
        if error == Error::Unavailable {
            error
        } else {
            Error::RevisionCorrupt
        }
    })
}
fn mutable<'c>(
    owner: &Integration,
    draft: &Draft,
    version: i32,
    catalog: &'c AuthoringCatalog,
) -> Result<&'c Registration, WriteError> {
    if owner.record().lifecycle == Lifecycle::Archived {
        return Err(WriteError::Archived);
    }
    if draft.record().draft_version != version {
        return Err(WriteError::DraftVersion);
    }
    catalog
        .get(&owner.record().type_id)
        .ok_or(WriteError::TypeUnavailable)
}
async fn locked_draft(
    tx: &Transaction<'_>,
    id: &IntegrationId,
    budget: &mut Rows,
    work: usize,
) -> Result<(Integration, Draft, Vec<SecretBinding>), WriteError> {
    let owner=tx.query_opt("SELECT integration_id::text,type_id,display_name,lifecycle_state,current_revision_fingerprint,created_at,updated_at FROM integration WHERE integration_id=$1::text::uuid FOR UPDATE",&[&id.value()]).await.map_err(|_|Error::Unavailable)?.ok_or(WriteError::NotFound)?;
    budget.consume(1)?;
    let owner = integration(&owner)?;
    let row=tx.query_opt("SELECT integration_id::text,base_revision_fingerprint,type_descriptor_fingerprint,type_descriptor_document::text,public_configuration_document::text,probe_configuration_document::text,draft_version,draft_fingerprint,created_at,updated_at FROM integration_draft WHERE integration_id=$1::text::uuid FOR UPDATE",&[&id.value()]).await.map_err(|_|Error::Unavailable)?.ok_or(WriteError::DraftNotFound)?;
    budget.consume(1)?;
    let bindings = bindings(tx, id.value(), true, budget).await?;
    let draft = decode_draft(&row, &bindings, work)?;
    // A metadata hash can alias a numeric default and a string. New admission
    // and the post-write proof both require the actual stored typed declaration.
    // Historical reads/replay intentionally do not pass through this writer.
    let declaration =
        Descriptor::from_json(draft.record().type_descriptor_document.raw().get(), work).map_err(
            |error| match error {
                onlyalpha_integration_contract::Error::Unavailable => Error::Unavailable,
                _ => Error::PersistenceConflict,
            },
        )?;
    if draft.record().integration_id != *id
        || declaration.id() != &owner.record().type_id
        || declaration.fingerprint() != draft.record().type_descriptor_fingerprint
    {
        return Err(Error::PersistenceConflict.into());
    }
    // Prove only the exact selected references; history length cannot make an
    // otherwise bounded authoring command require a whole-history traversal.
    let references: std::collections::BTreeSet<_> = [
        owner.record().current_revision_fingerprint.as_deref(),
        draft.record().base_revision_fingerprint.as_deref(),
    ]
    .into_iter()
    .flatten()
    .collect();
    for fingerprint in references {
        let row=tx.query_opt("SELECT revision_fingerprint,integration_id::text,revision_sequence,type_id,type_descriptor_fingerprint,type_descriptor_document::text,configuration_fingerprint,configuration_document::text,runtime_configuration_fingerprint,probe_configuration_fingerprint,probe_configuration_document::text,secret_binding_fingerprint,created_at FROM integration_revision WHERE revision_fingerprint=$1",&[&fingerprint]).await.map_err(|_|Error::Unavailable)?.ok_or(Error::RevisionCorrupt)?;
        budget.consume(1)?;
        let selected_bindings = self::bindings(tx, fingerprint, false, budget).await?;
        let revision = decode_revision(&row, &selected_bindings, work)?;
        if revision.record().integration_id != *id
            || revision.record().type_id != owner.record().type_id
        {
            return Err(Error::RevisionCorrupt.into());
        }
    }
    Ok((owner, draft, bindings))
}
async fn replace_draft(
    tx: &Transaction<'_>,
    expected: i32,
    next: DraftRecord,
    bindings: &[SecretBinding],
) -> Result<(), WriteError> {
    let draft = Draft::restore(next, bindings)?;
    let next = draft.record();
    let now = postgres::system_time(next.updated_at)?;
    let probe = next
        .probe_configuration_document
        .as_ref()
        .map(|v| v.raw().get());
    let changed=tx.execute("UPDATE integration_draft SET base_revision_fingerprint=$2,type_descriptor_fingerprint=$3,type_descriptor_document=$4::text::json,public_configuration_document=$5::text::json,probe_configuration_document=$6::text::json,draft_version=$7,draft_fingerprint=$8,updated_at=$9 WHERE integration_id=$1::text::uuid AND draft_version=$10",&[&next.integration_id.value(),&next.base_revision_fingerprint,&next.type_descriptor_fingerprint,&next.type_descriptor_document.raw().get(),&next.public_configuration_document.raw().get(),&probe,&next.draft_version,&next.draft_fingerprint,&now,&expected]).await.map_err(|_|Error::Unavailable)?;
    if changed != 1 {
        return Err(WriteError::DraftVersion);
    }
    Ok(())
}

fn authoring<'c>(
    owner: &Integration,
    draft: &Draft,
    version: i32,
    catalog: &'c AuthoringCatalog,
) -> Result<&'c Registration, WriteError> {
    let registration = mutable(owner, draft, version, catalog)?;
    if draft.record().type_descriptor_fingerprint != registration.descriptor().fingerprint() {
        return Err(WriteError::TypeChanged);
    }
    Ok(registration)
}
async fn validate_bindings(
    tx: &Transaction<'_>,
    id: &IntegrationId,
    descriptor: &Descriptor,
    bindings: &[SecretBinding],
    budget: &mut Rows,
) -> Result<(), WriteError> {
    let mut seen = std::collections::BTreeSet::new();
    for binding in bindings {
        if !seen.insert(binding.field_id())
            || !descriptor
                .fields()
                .iter()
                .any(|field| field.id() == binding.field_id() && field.secret())
        {
            return Err(Error::InvalidBinding.into());
        }
        let row=tx.query_opt("SELECT credential_kind,subject_id,secret_name,generation FROM product_credential WHERE credential_id=$1::text::uuid FOR SHARE",&[&binding.credential_id().value()]).await.map_err(|_|Error::Unavailable)?.ok_or(Error::InvalidBinding)?;
        budget.consume(1)?;
        if get::<String>(&row, "credential_kind")? != "INTEGRATION_SECRET"
            || get::<String>(&row, "subject_id")? != id.value()
            || get::<String>(&row, "secret_name")? != binding.field_id()
            || get::<i32>(&row, "generation")? != binding.generation()
        {
            return Err(Error::InvalidBinding.into());
        }
    }
    Ok(())
}
async fn exact_revision(
    tx: &Transaction<'_>,
    fingerprint: &str,
    budget: &mut Rows,
    work: usize,
) -> Result<Option<Revision>, Error> {
    let row=tx.query_opt("SELECT revision_fingerprint,integration_id::text,revision_sequence,type_id,type_descriptor_fingerprint,type_descriptor_document::text,configuration_fingerprint,configuration_document::text,runtime_configuration_fingerprint,probe_configuration_fingerprint,probe_configuration_document::text,secret_binding_fingerprint,created_at FROM integration_revision WHERE revision_fingerprint=$1",&[&fingerprint]).await.map_err(|_|Error::Unavailable)?;
    if row.is_some() {
        budget.consume(1)?;
    }
    let bindings = bindings(tx, fingerprint, false, budget).await?;
    match row {
        Some(row) => decode_revision(&row, &bindings, work).map(Some),
        None if bindings.is_empty() => Ok(None),
        None => Err(Error::RevisionCorrupt),
    }
}
async fn put_revision(
    tx: &Transaction<'_>,
    revision: &Revision,
    bindings: &[SecretBinding],
    budget: &mut Rows,
    work: usize,
) -> Result<(), WriteError> {
    let record = revision.record();
    let now = postgres::system_time(record.created_at)?;
    let probe = record
        .probe_configuration_document
        .as_ref()
        .map(|doc| doc.raw().get());
    let inserted=tx.execute("INSERT INTO integration_revision(revision_fingerprint,integration_id,revision_sequence,type_id,type_descriptor_fingerprint,type_descriptor_document,configuration_fingerprint,configuration_document,runtime_configuration_fingerprint,probe_configuration_fingerprint,probe_configuration_document,secret_binding_fingerprint,created_at) VALUES($1,$2::text::uuid,$3,$4,$5,$6::text::json,$7,$8::text::json,$9,$10,$11::text::json,$12,$13) ON CONFLICT DO NOTHING",&[&record.revision_fingerprint,&record.integration_id.value(),&record.revision_sequence,&record.type_id.value(),&record.type_descriptor_fingerprint,&record.type_descriptor_document.raw().get(),&record.configuration_fingerprint,&record.configuration_document.raw().get(),&record.runtime_configuration_fingerprint,&record.probe_configuration_fingerprint,&probe,&record.secret_binding_fingerprint,&now]).await.map_err(|_|Error::Unavailable)?;
    if inserted == 1 {
        for binding in bindings {
            tx.execute("INSERT INTO integration_revision_secret_binding(revision_fingerprint,field_id,credential_id,credential_generation) VALUES($1,$2,$3::text::uuid,$4)",&[&record.revision_fingerprint,&binding.field_id(),&binding.credential_id().value(),&binding.generation()]).await.map_err(|_|Error::Unavailable)?;
        }
    }
    let actual = exact_revision(tx, &record.revision_fingerprint, budget, work)
        .await?
        .ok_or(Error::RevisionCorrupt)?;
    let actual = actual.record();
    if actual.integration_id != record.integration_id
        || actual.type_id != record.type_id
        || actual.revision_sequence != record.revision_sequence
        || actual.created_at != record.created_at
        || actual.type_descriptor_document.raw().get()
            != record.type_descriptor_document.raw().get()
        || actual.configuration_document.raw().get() != record.configuration_document.raw().get()
        || actual
            .probe_configuration_document
            .as_ref()
            .map(|doc| doc.raw().get())
            != record
                .probe_configuration_document
                .as_ref()
                .map(|doc| doc.raw().get())
    {
        return Err(Error::RevisionCorrupt.into());
    }
    Ok(())
}

// Admission cannot rely on an affected-row count. Restore the actual owner,
// Draft and exact selected relations after all writes, before the Receipt.
async fn verify_draft_effect(
    tx: &Transaction<'_>,
    expected_owner: &IntegrationRecord,
    expected: &DraftRecord,
    expected_bindings: &[SecretBinding],
    budget: &mut Rows,
    work: usize,
) -> Result<(), WriteError> {
    let (owner, draft, bindings) = locked_draft(tx, &expected.integration_id, budget, work)
        .await
        .map_err(|error| match error {
            WriteError::NotFound | WriteError::DraftNotFound => {
                WriteError::Model(Error::PersistenceConflict)
            }
            other => other,
        })?;
    let actual = draft.record();
    if owner.record() != expected_owner
        || bindings != expected_bindings
        || actual.draft_fingerprint != expected.draft_fingerprint
        || actual.draft_version != expected.draft_version
        || actual.created_at != expected.created_at
        || actual.updated_at != expected.updated_at
        || actual.type_descriptor_document.raw().get()
            != expected.type_descriptor_document.raw().get()
        || actual.public_configuration_document.raw().get()
            != expected.public_configuration_document.raw().get()
        || actual
            .probe_configuration_document
            .as_ref()
            .map(|doc| doc.raw().get())
            != expected
                .probe_configuration_document
                .as_ref()
                .map(|doc| doc.raw().get())
    {
        return Err(Error::PersistenceConflict.into());
    }
    Ok(())
}
