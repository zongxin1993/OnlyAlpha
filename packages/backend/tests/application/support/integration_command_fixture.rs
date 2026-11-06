//! Test inputs use the actual command constructors and their admission identities.
use onlyalpha_backend::{
    application::{
        command::CommandId,
        integration_commands::{
            ClearSecret, CreateIntegration, PublishRevision, ResetDraftContract, SetLifecycle,
            SetSecret, UpdateDraft,
        },
        integration_configuration::{IntegrationId, Lifecycle, ObjectDocument},
    },
    security::credentials::Key,
};
use onlyalpha_integration_contract::IntegrationTypeId;
use serde_json::{Value, json};

pub(crate) fn response(request: &Value) -> Result<Value, Box<dyn std::error::Error>> {
    if request["op"] == "integration-fixture-records" {
        return record_fixture(request);
    }
    let work = 1_000_000;
    if request["op"] == "integration-fixture-fingerprint" {
        let document = ObjectDocument::new(request["document"].as_str().ok_or("document")?, work)?;
        return Ok(json!({"fingerprint": document.fingerprint()}));
    }
    let request = &request["request"];
    let command = CommandId::new(request["command_id"].as_str().ok_or("command id")?)?;
    let integration =
        IntegrationId::new(request["integration_id"].as_str().ok_or("integration id")?)?;
    let version = || -> Result<i32, Box<dyn std::error::Error>> {
        Ok(i32::try_from(
            request["expected_version"]
                .as_i64()
                .ok_or("expected version")?,
        )?)
    };
    let admission = match request["action"].as_str().ok_or("action")? {
        "create" => CreateIntegration::new(
            command,
            integration,
            IntegrationTypeId::new(request["type_id"].as_str().ok_or("type id")?)?,
            request["display_name"].as_str().ok_or("display name")?,
        )?
        .admission(work)?,
        "update" => UpdateDraft::new(
            command,
            integration,
            version()?,
            ObjectDocument::new(request["public"].as_str().ok_or("public document")?, work)?,
            request["probe"]
                .as_str()
                .map(|raw| ObjectDocument::new(raw, work))
                .transpose()?,
        )?
        .admission(work)?,
        "reset" => ResetDraftContract::new(command, integration, version()?)?.admission(work)?,
        "clear" => ClearSecret::new(
            command,
            integration,
            version()?,
            request["field_id"].as_str().ok_or("field")?,
        )?
        .admission(work)?,
        "publish" => PublishRevision::new(command, integration, version()?)?.admission(work)?,
        "set-secret" => SetSecret::new(
            command,
            integration,
            version()?,
            request["field_id"].as_str().ok_or("field")?,
            request["secret"].as_str().ok_or("secret")?,
        )?
        .admission(&Key::new(&[b'k'; 32])?, work)?,
        "lifecycle" => SetLifecycle::new(
            command,
            integration,
            request["expected"]
                .as_str()
                .ok_or("expected lifecycle")?
                .parse::<Lifecycle>()?,
            request["target"]
                .as_str()
                .ok_or("target lifecycle")?
                .parse::<Lifecycle>()?,
        )
        .admission(work)?,
        _ => return Err("unknown integration command fixture".into()),
    };
    Ok(json!({"kind": admission.kind().as_str(), "fingerprint": admission.fingerprint()}))
}

fn record_fixture(input: &Value) -> Result<Value, Box<dyn std::error::Error>> {
    use onlyalpha_backend::application::integration_configuration::{
        Draft, DraftRecord, Revision, RevisionRecord, SecretBinding, binding_fingerprint,
        runtime_configuration_fingerprint,
    };
    let work = 1_000_000;
    let id = IntegrationId::new(input["integration_id"].as_str().ok_or("integration id")?)?;
    let type_id = IntegrationTypeId::new(input["type_id"].as_str().ok_or("type id")?)?;
    let document = |key: &str| -> Result<ObjectDocument, Box<dyn std::error::Error>> {
        Ok(ObjectDocument::new(
            input[key].as_str().ok_or("document")?,
            work,
        )?)
    };
    let descriptor = document("descriptor")?;
    let public = document("public")?;
    let probe = input["probe"]
        .as_str()
        .map(|raw| ObjectDocument::new(raw, work))
        .transpose()?;
    let bindings = input["bindings"]
        .as_array()
        .ok_or("bindings")?
        .iter()
        .map(|binding| {
            Ok(SecretBinding::new(
                binding["field_id"].as_str().ok_or("field")?,
                binding["credential_id"].as_str().ok_or("credential")?,
                i32::try_from(
                    binding["credential_generation"]
                        .as_i64()
                        .ok_or("generation")?,
                )?,
            )?)
        })
        .collect::<Result<Vec<_>, Box<dyn std::error::Error>>>()?;
    let at = input["created_at"].as_str().ok_or("time")?.parse()?;
    if input["kind"] == "publication" {
        let descriptor = onlyalpha_integration_contract::Descriptor::from_json(
            input["descriptor"].as_str().ok_or("descriptor")?,
            work,
        )?;
        let publication =
            onlyalpha_backend::application::integration_resolver::resolve_publication(
                id,
                &descriptor,
                &public,
                probe.as_ref(),
                &bindings,
                work,
            )?;
        let revision = publication.into_revision(
            i32::try_from(input["revision_sequence"].as_i64().ok_or("sequence")?)?,
            at,
        )?;
        return Ok(revision_record_value(revision.record(), input));
    }
    if input["kind"] == "revision" {
        let mut record = RevisionRecord {
            revision_fingerprint: String::new(),
            integration_id: id,
            revision_sequence: i32::try_from(
                input["revision_sequence"].as_i64().ok_or("sequence")?,
            )?,
            type_id: type_id.clone(),
            type_descriptor_fingerprint: descriptor.fingerprint(),
            type_descriptor_document: descriptor.clone(),
            configuration_fingerprint: public.fingerprint(),
            runtime_configuration_fingerprint: runtime_configuration_fingerprint(
                &type_id,
                &descriptor,
                &public,
                &bindings,
            )?,
            configuration_document: public,
            probe_configuration_fingerprint: probe.as_ref().map(ObjectDocument::fingerprint),
            probe_configuration_document: probe,
            secret_binding_fingerprint: binding_fingerprint(&bindings)?,
            created_at: at,
        };
        record.revision_fingerprint = Revision::derive_fingerprint(&record)?;
        let revision = Revision::restore(record, &bindings)?;
        return Ok(revision_record_value(revision.record(), input));
    }
    if input["kind"] != "draft" {
        return Err("unknown Integration record fixture".into());
    }
    let mut record = DraftRecord {
        integration_id: id,
        base_revision_fingerprint: input["base_revision_fingerprint"]
            .as_str()
            .map(str::to_owned),
        type_descriptor_fingerprint: descriptor.fingerprint(),
        type_descriptor_document: descriptor,
        public_configuration_document: public,
        probe_configuration_document: probe,
        draft_version: i32::try_from(input["draft_version"].as_i64().ok_or("version")?)?,
        draft_fingerprint: String::new(),
        created_at: at,
        updated_at: at,
    };
    record.draft_fingerprint = Draft::derive_fingerprint(&record, &bindings)?;
    let draft = Draft::restore(record, &bindings)?;
    let r = draft.record();
    Ok(
        json!({"integration_id":r.integration_id.value(),"base_revision_fingerprint":r.base_revision_fingerprint,
        "type_descriptor_fingerprint":r.type_descriptor_fingerprint,"type_descriptor_document":r.type_descriptor_document.raw().get(),
        "public_configuration_document":r.public_configuration_document.raw().get(),
        "probe_configuration_document":r.probe_configuration_document.as_ref().map(|value|value.raw().get()),
        "draft_version":r.draft_version,"draft_fingerprint":r.draft_fingerprint,"created_at":input["created_at"],"updated_at":input["created_at"]}),
    )
}
fn revision_record_value(
    r: &onlyalpha_backend::application::integration_configuration::RevisionRecord,
    input: &Value,
) -> Value {
    json!({"revision_fingerprint":r.revision_fingerprint,"integration_id":r.integration_id.value(),"revision_sequence":r.revision_sequence,
        "type_id":r.type_id.value(),"type_descriptor_fingerprint":r.type_descriptor_fingerprint,
        "type_descriptor_document":r.type_descriptor_document.raw().get(),"configuration_fingerprint":r.configuration_fingerprint,
        "configuration_document":r.configuration_document.raw().get(),"runtime_configuration_fingerprint":r.runtime_configuration_fingerprint,
        "probe_configuration_fingerprint":r.probe_configuration_fingerprint,
        "probe_configuration_document":r.probe_configuration_document.as_ref().map(|value|value.raw().get()),
        "secret_binding_fingerprint":r.secret_binding_fingerprint,"created_at":input["created_at"]})
}
