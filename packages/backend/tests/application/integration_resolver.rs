//! Existing Python resolver oracle, never a Product command or runtime admission.
use onlyalpha_backend::application::integration_configuration::{
    IntegrationId, ObjectDocument, SecretBinding,
};
use onlyalpha_backend::application::integration_resolver::{
    Error, resolve_publication, validate_draft,
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use onlyalpha_integration_contract::Descriptor;
use serde_json::{Value, json};
const WORK: usize = 8 * 1024 * 1024;
fn vectors() -> Vec<Value> {
    serde_json::from_str(include_str!("fixtures/integration_resolver.json")).unwrap()
}
fn bindings(v: &Value) -> Vec<SecretBinding> {
    v["bindings"]
        .as_array()
        .unwrap()
        .iter()
        .map(|b| {
            SecretBinding::new(
                b["field_id"].as_str().unwrap(),
                b["credential_id"].as_str().unwrap(),
                i32::try_from(b["credential_generation"].as_i64().unwrap()).unwrap(),
            )
            .unwrap()
        })
        .collect()
}
fn binding_records(bindings: &[SecretBinding]) -> Value {
    json!(bindings.iter().map(|b|json!({"field_id":b.field_id(),"credential_id":b.credential_id().value(),"credential_generation":b.generation()})).collect::<Vec<_>>())
}
#[test]
fn draft_validation_matches_existing_python_without_laundering_original_primitives() {
    for (index, v) in vectors().iter().enumerate() {
        let descriptor = Descriptor::from_json(v["descriptor"].as_str().unwrap(), WORK).unwrap();
        let public = ObjectDocument::new(v["public"].as_str().unwrap(), WORK).unwrap();
        let probe = v["probe"]
            .as_str()
            .map(|raw| ObjectDocument::new(raw, WORK).unwrap());
        let actual = match validate_draft(&descriptor, &public, probe.as_ref(), WORK) {
            Err(error) => json!({"error":error.code()}),
            Ok((public, probe)) => {
                json!({"public":public.raw().get(),"probe":probe.as_ref().map(|value|value.raw().get())})
            }
        };
        assert_eq!(actual, v["draft"], "draft {index}");
    }
}
#[test]
fn publication_defaults_probe_secrets_and_all_original_revision_identities_match_python() {
    for (index, v) in vectors().iter().enumerate() {
        let descriptor = Descriptor::from_json(v["descriptor"].as_str().unwrap(), WORK).unwrap();
        let public = ObjectDocument::new(v["public"].as_str().unwrap(), WORK).unwrap();
        let probe = v["probe"]
            .as_str()
            .map(|raw| ObjectDocument::new(raw, WORK).unwrap());
        let bindings = bindings(v);
        let id = IntegrationId::new("b52eb762-34cf-47d4-8cca-56ef93f0d2ac").unwrap();
        let actual = match resolve_publication(
            id,
            &descriptor,
            &public,
            probe.as_ref(),
            &bindings,
            WORK,
        ) {
            Err(error) => json!({"error":error.code()}),
            Ok(publication) => {
                assert_eq!(
                    publication.revision_fingerprint().unwrap(),
                    v["publication"]["revision_fingerprint"].as_str().unwrap()
                );
                let bindings = binding_records(publication.bindings());
                let now: OnlyUtcDateTime = "2026-09-20T00:00:00Z".parse().unwrap();
                let revision = publication.into_revision(1, now).unwrap();
                let revision = revision.record();
                json!({"public":revision.configuration_document.raw().get(),"probe":revision.probe_configuration_document.as_ref().map(|value|value.raw().get()),"configuration_fingerprint":revision.configuration_fingerprint,"probe_fingerprint":revision.probe_configuration_fingerprint,"binding_fingerprint":revision.secret_binding_fingerprint,"runtime_fingerprint":revision.runtime_configuration_fingerprint,"revision_fingerprint":revision.revision_fingerprint,"bindings":bindings})
            }
        };
        assert_eq!(actual, v["publication"], "publication {index}");
    }
}
#[test]
fn exhausted_output_work_never_returns_a_partial_normalization_or_publication() {
    let v = &vectors()[0];
    let descriptor = Descriptor::from_json(v["descriptor"].as_str().unwrap(), WORK).unwrap();
    let public = ObjectDocument::new("{}", WORK).unwrap();
    assert!(matches!(
        validate_draft(&descriptor, &public, None, 0),
        Err(Error::Unavailable)
    ));
    let id = IntegrationId::new("b52eb762-34cf-47d4-8cca-56ef93f0d2ac").unwrap();
    assert!(matches!(
        resolve_publication(id, &descriptor, &public, None, &bindings(v), 0),
        Err(Error::Unavailable)
    ));
    assert!(validate_draft(&descriptor, &public, None, WORK).is_ok());
}
