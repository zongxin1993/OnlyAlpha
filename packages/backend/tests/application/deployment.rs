use onlyalpha_backend::bootstrap::deployment::{Error, SemanticStoreId};
const ID: &str = "550e8400-e29b-41d4-a716-446655440000";
#[test]
fn namespace_identity_is_exact_and_not_a_command_or_path_identity() {
    let id = SemanticStoreId::new(ID).unwrap();
    assert_eq!(id.value(), ID);
    assert_eq!(
        SemanticStoreId::from_document(&format!(r#"{{"schema_version":1,"store_id":"{ID}"}}"#))
            .unwrap(),
        id
    );
    for invalid in [
        ID.to_uppercase(),
        ID.replace("41d4", "11d4"),
        ID.replace("a716", "7716"),
        ID.replace('-', ""),
        format!(" {ID}"),
        String::new(),
    ] {
        assert_eq!(SemanticStoreId::new(&invalid), Err(Error::Corrupt));
    }
}
#[test]
fn strict_document_does_not_launder_duplicate_or_wrong_kind_proof() {
    let valid = format!(r#"{{"schema_version":1,"store_id":"{ID}"}}"#);
    for invalid in [
        "null".into(),
        "[]".into(),
        "{}".into(),
        r#"{"schema_version":2,"unexpected":"x"}"#.into(),
        r#"{"schema_version":2,"store_id":"x","unexpected":0}"#.into(),
        valid.replace("schema_version\":1", "schema_version\":true"),
        valid.replace("schema_version\":1", "schema_version\":1.0"),
        valid.replace("schema_version\":1", "schema_version\":1e0"),
        valid.replace("schema_version\":1", "schema_version\":\"1\""),
        valid.replace(
            "schema_version\":1",
            "schema_version\":1,\"schema_version\":1",
        ),
        valid.replace("schema_version\":1", "schema_version\":1,\"unknown\":0"),
        valid.replace(&format!("\"{ID}\""), "null"),
        valid.replace(&format!("\"{ID}\""), "1"),
        format!("{valid} null"),
    ] {
        assert_eq!(
            SemanticStoreId::from_document(&invalid),
            Err(Error::Corrupt),
            "{invalid}"
        );
    }
    for version in ["0", "2", "-1", "1234567890123456789012345678901234567890"] {
        assert_eq!(
            SemanticStoreId::from_document(
                &valid.replace("schema_version\":1", &format!("schema_version\":{version}"))
            ),
            Err(Error::Unsupported)
        );
    }
    assert_eq!(
        SemanticStoreId::from_document(&" ".repeat(32769)),
        Err(Error::Unavailable)
    );
}
