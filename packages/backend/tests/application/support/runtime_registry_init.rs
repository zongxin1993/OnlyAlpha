//! Faults on real publication and its original PG session; no business fixtures.
use crate::{
    bootstrap::{configuration, research_namespace},
    persistence::authority_session::AuthoritySession,
};
use std::path::Path;
pub async fn run(session: &mut AuthoritySession, root: &Path, phase: &str) {
    let schema = configuration::load_schema_history(
        Path::new(&std::env::var("ONLYALPHA_RUNTIME_INITIALIZE_TEST_SCHEMA").unwrap()),
        8 * 1024 * 1024,
    )
    .unwrap();
    let fault = match phase {
        "readback" => research_namespace::InitializationFault::Readback,
        "guard" => research_namespace::InitializationFault::Guard,
        _ => panic!("unknown controlled fault"),
    };
    assert!(!root.join("runtime").exists());
    research_namespace::fail_initialization_for_test(fault);
    assert_eq!(
        research_namespace::initialize_runtime_registry(root, &schema, session)
            .await
            .unwrap_err(),
        "RESEARCH_RUNTIME_INITIALIZATION_OUTCOME_UNKNOWN"
    );
    assert!(
        session.verify().await.is_err(),
        "the failed operation cannot reuse its old session"
    );
    let runtime = root.join("runtime");
    let names = std::fs::read_dir(&runtime)
        .unwrap()
        .map(|entry| entry.unwrap().file_name())
        .collect::<Vec<_>>();
    assert_eq!(names.len(), 2);
    assert_eq!(
        std::fs::read(runtime.join("generation-events.jsonl")).unwrap(),
        b""
    );
    assert_eq!(
        std::fs::read(runtime.join(".generation-authority.lock")).unwrap(),
        b""
    );
    println!("RUNTIME_INITIALIZATION_PUBLISHED_FAULT: PASS {phase}");
}
