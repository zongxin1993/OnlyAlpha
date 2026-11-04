use onlyalpha_event::*;
#[test]
fn publication_counts_are_exact_and_conserved() {
    let large = "184467440737095516160000".parse().unwrap();
    let input = OnlyRuntimeEventPublicationInput {
        route: OnlyRuntimeEventRoute::ExternalDirect,
        disposition: OnlyRuntimeEventDisposition::Published,
        attempted: large,
        published: "184467440737095516160000".parse().unwrap(),
        staged: 0u32.into(),
        suppressed: 0u32.into(),
        rejected: 0u32.into(),
        error: None,
    };
    let result = OnlyRuntimeEventPublicationResult::new(input.clone()).unwrap();
    assert_eq!(
        result.counts().attempted.to_string(),
        "184467440737095516160000"
    );
    let mut invalid = input;
    invalid.rejected = 1u32.into();
    assert!(OnlyRuntimeEventPublicationResult::new(invalid).is_err());
}
