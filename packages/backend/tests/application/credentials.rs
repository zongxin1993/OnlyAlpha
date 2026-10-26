use onlyalpha_backend::application::integration_configuration::IntegrationId;
use onlyalpha_backend::security::credentials::{Context, CredentialId, Key, Secret, Slot};
use serde_json::Value;
fn vectors() -> Value {
    serde_json::from_str(include_str!("fixtures/credentials.json")).unwrap()
}
fn bytes(value: &str) -> Vec<u8> {
    value
        .as_bytes()
        .as_chunks::<2>()
        .0
        .iter()
        .map(|pair| u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap())
        .collect()
}
fn context(v: &Value) -> Context {
    Context::new(
        CredentialId::new(v["credential_id"].as_str().unwrap()).unwrap(),
        Slot::new(
            v["credential_kind"].as_str().unwrap(),
            v["subject_id"].as_str().unwrap(),
            v["secret_name"].as_str().unwrap(),
        )
        .unwrap(),
        v["generation"].as_i64().unwrap().try_into().unwrap(),
        1,
    )
    .unwrap()
}
#[test]
fn original_python_envelopes_and_keyed_intents_are_exact() {
    let all = vectors();
    let key = Key::new(&bytes(all["key"].as_str().unwrap())).unwrap();
    let integration = IntegrationId::new(all["integration_id"].as_str().unwrap()).unwrap();
    for v in all["cases"].as_array().unwrap() {
        let context = context(v);
        let ciphertext = bytes(v["ciphertext"].as_str().unwrap());
        let plaintext = key.decrypt(&context, &ciphertext, 100_000).unwrap();
        assert_eq!(plaintext.expose(), v["plaintext"].as_str().unwrap());
        assert_eq!(
            context.aad(100_000).unwrap(),
            v["aad"].as_str().unwrap().as_bytes()
        );
        assert_eq!(
            key.secret_commitment(
                &integration,
                v["secret_name"].as_str().unwrap(),
                &plaintext,
                100_000
            )
            .unwrap(),
            v["commitment"].as_str().unwrap()
        );
        let sealed = key.encrypt(&context, &plaintext, 100_000).unwrap();
        assert_eq!(sealed.len(), plaintext.expose().len() + 28);
        assert_eq!(
            key.decrypt(&context, &sealed, 100_000).unwrap().expose(),
            plaintext.expose()
        );
    }
}
#[test]
fn every_authenticated_context_dimension_and_tag_must_match() {
    let all = vectors();
    let key = Key::new(&bytes(all["key"].as_str().unwrap())).unwrap();
    let v = &all["cases"][0];
    let blob = bytes(v["ciphertext"].as_str().unwrap());
    for change in [
        "credential_id",
        "credential_kind",
        "subject_id",
        "secret_name",
        "generation",
    ] {
        let mut altered = v.clone();
        altered[change] = if change == "generation" {
            Value::from(2)
        } else {
            Value::from(match change {
                "credential_id" => "00000000-0000-4000-8000-000000000099",
                "credential_kind" => "OTHER_SECRET",
                "subject_id" => "another-owner",
                _ => "api_secret",
            })
        };
        assert_eq!(
            key.decrypt(&context(&altered), &blob, 100_000)
                .err()
                .unwrap()
                .code(),
            "CREDENTIAL_CIPHERTEXT_INVALID",
            "{change}"
        );
    }
    let ctx = context(v);
    for position in [0, 12, blob.len() - 1] {
        let mut altered = blob.clone();
        altered[position] ^= 1;
        assert_eq!(
            key.decrypt(&ctx, &altered, 100_000).err().unwrap().code(),
            "CREDENTIAL_CIPHERTEXT_INVALID"
        );
    }
    assert_eq!(
        Key::new(&[0; 32])
            .unwrap()
            .decrypt(&ctx, &blob, 100_000)
            .err()
            .unwrap()
            .code(),
        "CREDENTIAL_CIPHERTEXT_INVALID"
    );
    for size in [0, 12, 27] {
        assert_eq!(
            key.decrypt(&ctx, &blob[..size], 100_000)
                .err()
                .unwrap()
                .code(),
            "CREDENTIAL_CIPHERTEXT_INVALID"
        );
    }
    assert_eq!(
        key.decrypt(&ctx, &bytes(all["invalid_utf8"].as_str().unwrap()), 100_000)
            .err()
            .unwrap()
            .code(),
        "CREDENTIAL_CIPHERTEXT_INVALID"
    );
}
#[test]
fn slot_key_generation_and_resource_errors_never_produce_a_secret() {
    for value in ["", "has space", "has\u{1c}control", "has\u{a0}space"] {
        assert_eq!(
            Slot::new(value, "owner", "api_key").err().unwrap().code(),
            "CREDENTIAL_SLOT_INVALID"
        );
        assert!(Slot::new("INTEGRATION_SECRET", value, "api_key").is_err());
    }
    for field in ["", "Api-Key", "api.key", "é", "1a", "a\n"] {
        assert!(Slot::new("INTEGRATION_SECRET", "owner", field).is_err());
    }
    assert!(Slot::new("INTEGRATION_SECRET", "中文.owner", "a_1").is_ok());
    assert_eq!(
        Key::new(&[0; 31]).err().unwrap().code(),
        "CREDENTIAL_MASTER_KEY_INVALID"
    );
    assert!(Secret::new("").is_err());
    assert!(CredentialId::new("00000000-0000-1000-8000-000000000001").is_err());
    let all = vectors();
    let v = &all["cases"][0];
    let ctx = context(v);
    for generation in [0, -1] {
        assert_eq!(
            Context::new(
                ctx.credential_id().clone(),
                ctx.slot().clone(),
                generation,
                1
            )
            .err()
            .unwrap()
            .code(),
            "CREDENTIAL_GENERATION_CONFLICT"
        );
    }
    assert_eq!(
        Context::new(ctx.credential_id().clone(), ctx.slot().clone(), 1, 2)
            .err()
            .unwrap()
            .code(),
        "CREDENTIAL_KEY_VERSION_UNSUPPORTED"
    );
    let key = Key::new(&[b'k'; 32]).unwrap();
    let secret = Secret::new("controlled").unwrap();
    assert_eq!(
        key.encrypt(&ctx, &secret, 0).err().unwrap().code(),
        "CREDENTIAL_PERSISTENCE_UNAVAILABLE"
    );
    assert_eq!(
        key.decrypt(&ctx, &bytes(v["ciphertext"].as_str().unwrap()), 0)
            .err()
            .unwrap()
            .code(),
        "CREDENTIAL_PERSISTENCE_UNAVAILABLE"
    );
    assert_eq!(
        ctx.aad(0).err().unwrap().code(),
        "CREDENTIAL_PERSISTENCE_UNAVAILABLE"
    );
    let owner = IntegrationId::new(all["integration_id"].as_str().unwrap()).unwrap();
    assert_eq!(
        key.secret_commitment(&owner, "api_key", &secret, 0)
            .err()
            .unwrap()
            .code(),
        "CREDENTIAL_PERSISTENCE_UNAVAILABLE"
    );
}
