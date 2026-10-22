//! Independent existing Python Product command preimages.
use onlyalpha_integration_contract::IntegrationTypeId;
use onlyalpha_product_runtime::{
    command::CommandId,
    integration_commands::{CreateIntegration, SetLifecycle},
    integration_configuration::{IntegrationId, Lifecycle},
};
use serde_json::Value;
const WORK: usize = 1024 * 1024;
#[test]
fn typed_commands_keep_existing_python_intent_without_descriptor_time_or_transport() {
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/integration_commands.json")).unwrap();
    for v in cases {
        let cmd = CommandId::new(v["command_id"].as_str().unwrap()).unwrap();
        let p = &v["payload"];
        let id = IntegrationId::new(p["integration_id"].as_str().unwrap()).unwrap();
        let admission = if v["op"] == "create" {
            CreateIntegration::new(
                cmd,
                id,
                IntegrationTypeId::new(p["type_id"].as_str().unwrap()).unwrap(),
                p["display_name"].as_str().unwrap(),
            )
            .unwrap()
            .admission(WORK)
            .unwrap()
        } else {
            SetLifecycle::new(
                cmd,
                id,
                p["expected_lifecycle_state"]
                    .as_str()
                    .unwrap()
                    .parse::<Lifecycle>()
                    .unwrap(),
                p["lifecycle_state"]
                    .as_str()
                    .unwrap()
                    .parse::<Lifecycle>()
                    .unwrap(),
            )
            .admission(WORK)
            .unwrap()
        };
        assert_eq!(admission.fingerprint(), v["fingerprint"].as_str().unwrap());
    }
}
#[test]
fn blank_names_and_exhausted_identity_budget_never_admit_a_command() {
    let cmd = CommandId::new("00000000-0000-4000-8000-000000000001").unwrap();
    let id = IntegrationId::new("b52eb762-34cf-47d4-8cca-56ef93f0d2ac").unwrap();
    let ty = IntegrationTypeId::new("controlled.source").unwrap();
    for name in ["", "\u{a0}\u{1c}\t"] {
        assert!(CreateIntegration::new(cmd.clone(), id.clone(), ty.clone(), name).is_err());
    }
    let request = CreateIntegration::new(cmd, id, ty, "Source").unwrap();
    assert!(request.admission(0).is_err());
}
#[test]
fn draft_commands_keep_actual_frozen_python_document_strings_in_the_preimage() {
    use onlyalpha_product_runtime::{
        integration_commands::{ResetDraftContract, UpdateDraft},
        integration_configuration::ObjectDocument,
    };
    let fixture: Value =
        serde_json::from_str(include_str!("fixtures/integration_draft_commands.json")).unwrap();
    let cmd = CommandId::new("00000000-0000-4000-8000-000000000001").unwrap();
    let id = IntegrationId::new("b52eb762-34cf-47d4-8cca-56ef93f0d2ac").unwrap();
    for v in fixture["updates"].as_array().unwrap() {
        let public = ObjectDocument::new(v["public"].as_str().unwrap(), WORK).unwrap();
        let probe = v["probe"]
            .as_str()
            .map(|v| ObjectDocument::new(v, WORK).unwrap());
        let command = UpdateDraft::new(cmd.clone(), id.clone(), 3, public, probe).unwrap();
        assert_eq!(
            command.admission(WORK).unwrap().fingerprint(),
            v["fingerprint"].as_str().unwrap()
        );
    }
    let reset = ResetDraftContract::new(cmd.clone(), id.clone(), 3).unwrap();
    assert_eq!(
        reset.admission(WORK).unwrap().fingerprint(),
        fixture["reset"].as_str().unwrap()
    );
    for version in [0, -1] {
        assert!(
            UpdateDraft::new(
                cmd.clone(),
                id.clone(),
                version,
                ObjectDocument::new("{}", WORK).unwrap(),
                None
            )
            .is_err()
        );
        assert!(ResetDraftContract::new(cmd.clone(), id.clone(), version).is_err());
    }
}
#[test]
fn clear_and_publish_keep_original_python_command_preimages_before_catalog_validation() {
    use onlyalpha_product_runtime::integration_commands::{ClearSecret, PublishRevision};
    let cmd = CommandId::new("00000000-0000-4000-8000-000000000001").unwrap();
    let id = IntegrationId::new("b52eb762-34cf-47d4-8cca-56ef93f0d2ac").unwrap();
    let fixture: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/integration_publish_commands.json")).unwrap();
    for v in fixture {
        let version = i32::try_from(v["version"].as_i64().unwrap()).unwrap();
        let admission = if v["kind"] == "clear" {
            ClearSecret::new(
                cmd.clone(),
                id.clone(),
                version,
                v["field"].as_str().unwrap(),
            )
            .unwrap()
            .admission(WORK)
            .unwrap()
        } else {
            PublishRevision::new(cmd.clone(), id.clone(), version)
                .unwrap()
                .admission(WORK)
                .unwrap()
        };
        assert_eq!(admission.fingerprint(), v["fingerprint"].as_str().unwrap());
    }
    assert!(ClearSecret::new(cmd.clone(), id.clone(), 1, "").is_err());
    for version in [0, -1] {
        assert!(ClearSecret::new(cmd.clone(), id.clone(), version, "api_key").is_err());
        assert!(PublishRevision::new(cmd.clone(), id.clone(), version).is_err());
    }
}
#[test]
fn secret_intent_keeps_original_domain_separated_keyed_commitment() {
    use onlyalpha_product_runtime::{credentials::Key, integration_commands::SetSecret};
    let key = Key::new(&[b'k'; 32]).unwrap();
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/integration_secret_commands.json")).unwrap();
    for v in cases {
        let command = SetSecret::new(
            CommandId::new(v["command_id"].as_str().unwrap()).unwrap(),
            IntegrationId::new(v["integration_id"].as_str().unwrap()).unwrap(),
            v["version"].as_i64().unwrap().try_into().unwrap(),
            v["field_id"].as_str().unwrap(),
            v["secret"].as_str().unwrap(),
        )
        .unwrap();
        assert_eq!(
            command.admission(&key, WORK).unwrap().fingerprint(),
            v["fingerprint"].as_str().unwrap()
        );
        assert_ne!(
            command
                .admission(&Key::new(&[b'x'; 32]).unwrap(), WORK)
                .unwrap()
                .fingerprint(),
            v["fingerprint"].as_str().unwrap()
        );
    }
}

#[test]
fn invalid_secret_inputs_keep_the_existing_constructor_error() {
    use onlyalpha_product_runtime::integration_commands::SetSecret;
    for (version, field, secret) in [
        (0, "api_key", "controlled"),
        (-1, "api_key", "controlled"),
        (1, "", "controlled"),
        (1, "api_key", ""),
    ] {
        assert_eq!(
            SetSecret::new(
                CommandId::new("00000000-0000-4000-8000-000000000001").unwrap(),
                IntegrationId::new("b52eb762-34cf-47d4-8cca-56ef93f0d2ac").unwrap(),
                version,
                field,
                secret
            )
            .err()
            .unwrap()
            .code(),
            "INTEGRATION_CONFIGURATION_INVALID"
        );
    }
}
