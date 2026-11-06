//! Historical test data production through the actual immutable Rust owners.
//! This helper performs no database writes and grants no admission or credentials.
use onlyalpha_backend::application::integration_configuration::{
    Draft, DraftRecord, IntegrationId, ObjectDocument, Revision, RevisionRecord, SecretBinding,
    binding_fingerprint, runtime_configuration_fingerprint,
};
use onlyalpha_integration_contract::IntegrationTypeId;
use serde_json::{Value, json};
use std::error::Error;

pub fn produce(input: &Value) -> Result<Value, Box<dyn Error>> {
    let document = |key: &str| -> Result<ObjectDocument, Box<dyn Error>> {
        Ok(ObjectDocument::new(
            input[key].as_str().ok_or("document")?,
            1_000_000,
        )?)
    };
    if input["op"] == "integration-fixture-fingerprint" {
        return Ok(json!({"fingerprint":document("document")?.fingerprint()}));
    }
    let id = IntegrationId::new(input["integration_id"].as_str().ok_or("integration id")?)?;
    let bindings = [SecretBinding::new(
        "api_key",
        input["credential_id"].as_str().ok_or("credential id")?,
        3,
    )?];
    let descriptor = document("descriptor_document")?;
    let type_id = IntegrationTypeId::new("binance.spot.market_data")?;
    let created_at = "2026-09-20T00:00:00.123400Z".parse()?;
    let mut revisions = Vec::new();
    for item in input["revisions"].as_array().ok_or("revisions")? {
        let configuration = ObjectDocument::new(
            item["configuration_document"]
                .as_str()
                .ok_or("configuration")?,
            1_000_000,
        )?;
        let probe = item["probe_configuration_document"]
            .as_str()
            .map(|raw| ObjectDocument::new(raw, 1_000_000))
            .transpose()?;
        let mut record = RevisionRecord {
            revision_fingerprint: String::new(),
            integration_id: id.clone(),
            revision_sequence: i32::try_from(
                item["revision_sequence"].as_u64().ok_or("sequence")?,
            )?,
            type_id: type_id.clone(),
            type_descriptor_fingerprint: descriptor.fingerprint(),
            type_descriptor_document: descriptor.clone(),
            configuration_fingerprint: configuration.fingerprint(),
            runtime_configuration_fingerprint: runtime_configuration_fingerprint(
                &type_id,
                &descriptor,
                &configuration,
                &bindings,
            )?,
            configuration_document: configuration,
            probe_configuration_fingerprint: probe.as_ref().map(ObjectDocument::fingerprint),
            probe_configuration_document: probe,
            secret_binding_fingerprint: binding_fingerprint(&bindings)?,
            created_at,
        };
        record.revision_fingerprint = Revision::derive_fingerprint(&record)?;
        let revision = Revision::restore(record, &bindings)?;
        let r = revision.record();
        revisions.push(json!({"revision_fingerprint":r.revision_fingerprint,"revision_sequence":r.revision_sequence,
            "type_id":r.type_id.value(),"type_descriptor_fingerprint":r.type_descriptor_fingerprint,
            "type_descriptor_document":r.type_descriptor_document.raw().get(),
            "configuration_fingerprint":r.configuration_fingerprint,"configuration_document":r.configuration_document.raw().get(),
            "runtime_configuration_fingerprint":r.runtime_configuration_fingerprint,
            "probe_configuration_fingerprint":r.probe_configuration_fingerprint,
            "probe_configuration_document":r.probe_configuration_document.as_ref().map(|p|p.raw().get()),
            "secret_binding_fingerprint":r.secret_binding_fingerprint}));
    }
    let draft = if input["draft"] == true {
        let base = revisions
            .first()
            .and_then(|r| r["revision_fingerprint"].as_str())
            .map(str::to_owned);
        let mut record = DraftRecord {
            integration_id: id,
            base_revision_fingerprint: base,
            type_descriptor_fingerprint: descriptor.fingerprint(),
            type_descriptor_document: descriptor,
            public_configuration_document: ObjectDocument::new(
                r#"{"name":"Draft","timeout_seconds":1.0}"#,
                1_000_000,
            )?,
            probe_configuration_document: Some(ObjectDocument::new("{}", 1_000_000)?),
            draft_version: 2,
            draft_fingerprint: String::new(),
            created_at,
            updated_at: created_at,
        };
        record.draft_fingerprint = Draft::derive_fingerprint(&record, &bindings)?;
        let draft = Draft::restore(record, &bindings)?;
        let r = draft.record();
        json!({"base_revision_fingerprint":r.base_revision_fingerprint,"type_descriptor_fingerprint":r.type_descriptor_fingerprint,
            "type_descriptor_document":r.type_descriptor_document.raw().get(),
            "public_configuration_document":r.public_configuration_document.raw().get(),
            "probe_configuration_document":r.probe_configuration_document.as_ref().map(|p|p.raw().get()),
            "draft_version":r.draft_version,"draft_fingerprint":r.draft_fingerprint})
    } else {
        Value::Null
    };
    Ok(json!({"revisions":revisions,"draft":draft}))
}
