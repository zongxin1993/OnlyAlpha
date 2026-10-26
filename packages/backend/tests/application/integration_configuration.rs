//! Original controlled Python metadata vectors; no Product admission or Source permission.
use onlyalpha_backend::application::integration_configuration::{
    Draft, DraftRecord, Error, IntegrationId, ObjectDocument, Revision, RevisionRecord,
    RuntimeBinding, SecretBinding, binding_fingerprint,
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use onlyalpha_integration_contract::{Category, IntegrationTypeId};
use serde_json::Value;
const WORK: usize = 8 * 1024 * 1024;
fn now() -> OnlyUtcDateTime {
    "2026-09-20T00:00:00Z".parse().unwrap()
}
fn text<'a>(v: &'a Value, key: &str) -> &'a str {
    v[key].as_str().unwrap()
}
fn document(v: &Value, key: &str) -> ObjectDocument {
    ObjectDocument::new(text(v, key), WORK).unwrap()
}
fn optional(v: &Value, key: &str) -> Option<String> {
    v[key].as_str().map(str::to_owned)
}
fn bindings(v: &Value) -> Vec<SecretBinding> {
    v["bindings"]
        .as_array()
        .unwrap()
        .iter()
        .map(|b| {
            SecretBinding::new(
                text(b, "field_id"),
                text(b, "credential_id"),
                i32::try_from(b["credential_generation"].as_i64().unwrap()).unwrap(),
            )
            .unwrap()
        })
        .collect()
}
fn draft_record(v: &Value) -> DraftRecord {
    DraftRecord {
        integration_id: IntegrationId::new(text(v, "integration_id")).unwrap(),
        base_revision_fingerprint: None,
        type_descriptor_fingerprint: text(v, "descriptor_fingerprint").into(),
        type_descriptor_document: document(v, "descriptor"),
        public_configuration_document: document(v, "public"),
        probe_configuration_document: v["probe"]
            .as_str()
            .map(|s| ObjectDocument::new(s, WORK).unwrap()),
        draft_version: 1,
        draft_fingerprint: text(v, "draft_fingerprint").into(),
        created_at: now(),
        updated_at: now(),
    }
}
fn revision_record(v: &Value) -> RevisionRecord {
    RevisionRecord {
        revision_fingerprint: text(v, "revision_fingerprint").into(),
        integration_id: IntegrationId::new(text(v, "integration_id")).unwrap(),
        revision_sequence: 1,
        type_id: IntegrationTypeId::new(text(v, "type_id")).unwrap(),
        type_descriptor_fingerprint: text(v, "descriptor_fingerprint").into(),
        type_descriptor_document: document(v, "descriptor"),
        configuration_fingerprint: text(v, "configuration_fingerprint").into(),
        configuration_document: document(v, "public"),
        runtime_configuration_fingerprint: text(v, "runtime_fingerprint").into(),
        probe_configuration_fingerprint: optional(v, "probe_fingerprint"),
        probe_configuration_document: v["probe"]
            .as_str()
            .map(|s| ObjectDocument::new(s, WORK).unwrap()),
        secret_binding_fingerprint: text(v, "binding_fingerprint").into(),
        created_at: now(),
    }
}
fn vectors() -> Vec<Value> {
    serde_json::from_str(include_str!("fixtures/integration_configuration.json")).unwrap()
}

#[test]
fn original_python_draft_revision_and_binding_identities_match_without_json_value_projection() {
    for v in vectors() {
        let bindings = bindings(&v);
        assert_eq!(
            binding_fingerprint(&bindings).unwrap(),
            text(&v, "binding_fingerprint")
        );
        let draft = Draft::restore(draft_record(&v), &bindings).unwrap();
        assert_eq!(
            draft.record().type_descriptor_document.raw().get(),
            text(&v, "descriptor")
        );
        assert_eq!(
            draft.record().public_configuration_document.raw().get(),
            text(&v, "public")
        );
        let revision = Revision::restore(revision_record(&v), &bindings).unwrap();
        assert_eq!(
            onlyalpha_backend::application::integration_configuration::runtime_configuration_fingerprint(
                &revision.record().type_id,
                &revision.record().type_descriptor_document,
                &revision.record().configuration_document,
                &bindings,
            ).unwrap(),
            text(&v, "runtime_fingerprint"),
        );
        assert_eq!(
            revision.record().configuration_document.raw().get(),
            text(&v, "public")
        );
        let generation = "b".repeat(64);
        let binding =
            RuntimeBinding::from_revision(&revision, Category::DataSource, Some(&generation))
                .unwrap();
        assert_eq!(
            binding.fingerprint(),
            text(&v, "runtime_binding_fingerprint")
        );
    }
}

#[test]
fn each_original_component_and_reference_is_required_before_a_restored_identity_is_accepted() {
    let v = &vectors()[0];
    let bindings = bindings(v);
    for dimension in 0..7 {
        let mut record = draft_record(v);
        match dimension {
            0 => {
                record.integration_id =
                    IntegrationId::new("ba13b6b1-af9a-450f-833d-48f5002297dc").unwrap()
            }
            1 => record.base_revision_fingerprint = Some("b".repeat(64)),
            2 => record.type_descriptor_fingerprint = "b".repeat(64),
            3 => record.public_configuration_document = ObjectDocument::new("{}", WORK).unwrap(),
            4 => {
                record.probe_configuration_document = Some(ObjectDocument::new("{}", WORK).unwrap())
            }
            5 => record.draft_fingerprint = "b".repeat(64),
            _ => record.draft_version = 0,
        }
        assert!(matches!(
            Draft::restore(record, &bindings),
            Err(Error::PersistenceConflict)
        ));
    }
    for dimension in 0..10 {
        let mut record = revision_record(v);
        match dimension {
            0 => record.revision_fingerprint = "b".repeat(64),
            1 => {
                record.integration_id =
                    IntegrationId::new("ba13b6b1-af9a-450f-833d-48f5002297dc").unwrap()
            }
            2 => record.type_id = IntegrationTypeId::new("different.source").unwrap(),
            3 => record.type_descriptor_fingerprint = "b".repeat(64),
            4 => record.configuration_fingerprint = "b".repeat(64),
            5 => record.runtime_configuration_fingerprint = "b".repeat(64),
            6 => record.probe_configuration_fingerprint = Some("b".repeat(64)),
            7 => {
                record.probe_configuration_document = Some(ObjectDocument::new("{}", WORK).unwrap())
            }
            8 => record.secret_binding_fingerprint = "b".repeat(64),
            _ => record.revision_sequence = 0,
        }
        assert!(matches!(
            Revision::restore(record, &bindings),
            Err(Error::RevisionCorrupt)
        ));
    }
    let changed =
        [SecretBinding::new("api_key", "ba13b6b1-af9a-450f-833d-48f5002297dc", 2).unwrap()];
    assert!(matches!(
        Draft::restore(draft_record(v), &changed),
        Err(Error::PersistenceConflict)
    ));
    assert!(matches!(
        Revision::restore(revision_record(v), &changed),
        Err(Error::RevisionCorrupt)
    ));
}

#[test]
fn sequence_and_operational_time_are_not_revision_semantic_identity() {
    let v = &vectors()[0];
    let bindings = bindings(v);
    let mut record = revision_record(v);
    record.revision_sequence = 99;
    record.created_at = "9999-12-31T23:59:59.999999Z".parse().unwrap();
    let revision = Revision::restore(record, &bindings).unwrap();
    assert_eq!(
        revision.record().revision_fingerprint,
        text(v, "revision_fingerprint")
    );
    let mut record = draft_record(v);
    record.updated_at = "0001-01-01T00:00:00Z".parse().unwrap();
    assert!(matches!(
        Draft::restore(record, &bindings),
        Err(Error::PersistenceConflict)
    ));
}

#[test]
fn identity_and_secret_boundaries_do_not_accept_coercion_or_plaintext() {
    for invalid in [
        "",
        "BINANCE",
        "b52eb76234cf47d48cca56ef93f0d2ac",
        "B52EB762-34CF-47D4-8CCA-56EF93F0D2AC",
    ] {
        assert!(IntegrationId::new(invalid).is_err());
    }
    for invalid in [
        "",
        "latest.source",
        "a.latest",
        "a..b",
        "A.b",
        "a-b",
        "a_",
        "a.*",
    ] {
        assert!(IntegrationTypeId::new(invalid).is_err());
    }
    let id = "ba13b6b1-af9a-450f-833d-48f5002297dc";
    for generation in [0, -1] {
        assert!(SecretBinding::new("api_key", id, generation).is_err());
    }
    for field in ["", "ApiKey", "api-key", " key "] {
        assert!(SecretBinding::new(field, id, 1).is_err());
    }
    let duplicate = [
        SecretBinding::new("api_key", id, 1).unwrap(),
        SecretBinding::new("api_key", id, 2).unwrap(),
    ];
    assert!(binding_fingerprint(&duplicate).is_err());
    for raw in [
        "[]",
        "true",
        "null",
        r#"{"a":1,"\u0061":2}"#,
        r#"{"n":1e9999}"#,
    ] {
        assert!(ObjectDocument::new(raw, WORK).is_err());
    }
    let v = &vectors()[0];
    let bindings = bindings(v);
    for probe in [false, true] {
        let mut record = draft_record(v);
        let secret = ObjectDocument::new(r#"{"api_key":"CONTROLLED_TEST_SECRET"}"#, WORK).unwrap();
        if probe {
            record.probe_configuration_document = Some(secret);
        } else {
            record.public_configuration_document = secret;
        }
        assert!(matches!(
            Draft::restore(record, &bindings),
            Err(Error::InvalidDocument)
        ));
    }
}

#[test]
fn integration_head_shape_and_binding_metadata_do_not_infer_runtime_readiness() {
    use onlyalpha_backend::application::integration_configuration::{
        Integration, IntegrationRecord, Lifecycle,
    };
    let id = IntegrationId::new("b52eb762-34cf-47d4-8cca-56ef93f0d2ac").unwrap();
    let record = IntegrationRecord {
        integration_id: id,
        type_id: IntegrationTypeId::new("controlled.source").unwrap(),
        display_name: " Controlled source ".into(),
        lifecycle: Lifecycle::Active,
        current_revision_fingerprint: None,
        created_at: now(),
        updated_at: now(),
    };
    assert_eq!(
        Integration::restore(record.clone())
            .unwrap()
            .record()
            .display_name,
        " Controlled source "
    );
    for name in ["", " ", "\u{1c}\u{85}"] {
        let mut bad = record.clone();
        bad.display_name = name.into();
        assert!(matches!(
            Integration::restore(bad),
            Err(Error::PersistenceConflict)
        ));
    }
    let mut bad = record.clone();
    bad.current_revision_fingerprint = Some("latest".into());
    assert!(Integration::restore(bad).is_err());
    let mut bad = record;
    bad.updated_at = "0001-01-01T00:00:00Z".parse().unwrap();
    assert!(Integration::restore(bad).is_err());
    for state in [Lifecycle::Active, Lifecycle::Disabled, Lifecycle::Archived] {
        assert_eq!(state.as_str().parse::<Lifecycle>().unwrap(), state);
    }
    for invalid in ["active", "UNKNOWN", " ACTIVE "] {
        assert!(invalid.parse::<Lifecycle>().is_err());
    }
    let v = &vectors()[0];
    let bindings = bindings(v);
    let revision = Revision::restore(revision_record(v), &bindings).unwrap();
    for generation in ["", "latest", &"g".repeat(64)] {
        assert!(matches!(
            RuntimeBinding::from_revision(&revision, Category::DataSource, Some(generation)),
            Err(Error::RuntimeBindingInvalid)
        ));
    }
    let first = SecretBinding::new("api_key", "ba13b6b1-af9a-450f-833d-48f5002297dc", 1).unwrap();
    let second = SecretBinding::new("token", "b52eb762-34cf-47d4-8cca-56ef93f0d2ac", 2).unwrap();
    assert_eq!(
        binding_fingerprint(&[first.clone(), second.clone()]).unwrap(),
        binding_fingerprint(&[second, first]).unwrap()
    );
}

#[test]
fn declared_secret_metadata_is_typed_and_revisions_reject_plaintext_before_projection() {
    let v = &vectors()[0];
    let bindings = bindings(v);
    for probe in [false, true] {
        let mut record = revision_record(v);
        let secret = ObjectDocument::new(r#"{"api_key":"CONTROLLED_TEST_SECRET"}"#, WORK).unwrap();
        if probe {
            record.probe_configuration_document = Some(secret);
        } else {
            record.configuration_document = secret;
        }
        assert!(matches!(
            Revision::restore(record, &bindings),
            Err(Error::InvalidDocument)
        ));
    }
    let mut record = draft_record(v);
    let descriptor=ObjectDocument::new(r#"{"schema_version":1,"type_id":"controlled.source","configuration_contract":{"fields":[{"field_id":"api_key","secret":{"$serde_json::private::RawValue":"true"}}]}}"#,WORK).unwrap();
    record.type_descriptor_fingerprint = descriptor.fingerprint();
    record.type_descriptor_document = descriptor;
    assert!(matches!(
        Draft::restore(record, &bindings),
        Err(Error::InvalidDocument)
    ));
}

#[test]
fn historical_revision_identity_keeps_its_original_opaque_runtime_projection() {
    let v = &vectors()[0];
    let oracle: serde_json::Value = serde_json::from_str(include_str!(
        "fixtures/integration_opaque_runtime_revision.json"
    ))
    .unwrap();
    let bindings = bindings(v);
    let mut record = revision_record(v);
    record.revision_sequence = 11;
    record.runtime_configuration_fingerprint =
        oracle["runtime_fingerprint"].as_str().unwrap().into();
    record.revision_fingerprint = oracle["revision_fingerprint"].as_str().unwrap().into();
    assert_eq!(
        Revision::derive_fingerprint(&record).unwrap(),
        record.revision_fingerprint
    );
    let revision = Revision::restore(record, &bindings).unwrap();
    assert_eq!(
        revision.record().runtime_configuration_fingerprint,
        "b".repeat(64)
    );
}
