//! Temporary descriptor reuse never grants access or alters formal reference reads.
use super::*;
use crate::market_product::temporary::application_tests::{TemporaryFault, source_from};
use std::sync::atomic::Ordering;

fn query() -> InstrumentQuery {
    InstrumentQuery {
        query: "TEST".into(),
        asset_class: None,
        instrument_types: vec![],
        instrument_ids: vec!["TEST.TEST".into()],
        limit: 10,
    }
}
fn window(minutes: u16) -> WindowRequest {
    WindowRequest {
        instrument_id: "TEST.TEST".into(),
        semantic: semantic(minutes).unwrap(),
        before_ns: None,
        bar_count: 20,
        // Twenty complete 7m roots fit within one session and one Provider page.
        clock_ns: (20 * 1440 + 140) * 60_000_000_000,
    }
}
#[tokio::test(flavor = "current_thread")]
async fn exact_single_instrument_restore_avoids_a_full_catalogue_without_creating_a_partial_cache()
{
    let (_authority, session, resolved, calls) =
        source_from(None, Some(TemporaryFault::ExactReferenceRequiresSymbol));
    let app = Application::default();
    let deadline = Instant::now() + Duration::from_secs(10);
    let mut exact = query();
    exact.query.clear();
    let (value, fence) = app
        .instruments(&resolved, &session, &exact, deadline)
        .await
        .expect("restore already knows the exact symbol")
        .into_parts()
        .unwrap();
    fence.check().unwrap();
    assert_eq!(value["instruments"].as_array().unwrap().len(), 1);
    assert_eq!(value["instruments"][0]["instrument_id"], "TEST.TEST");
    assert_eq!(
        value.as_object().unwrap().len(),
        3,
        "the public instruments envelope is unchanged"
    );
    assert!(
        app.cache.lock().unwrap().is_empty(),
        "one descriptor cannot become a full catalogue"
    );
    app.reference(&resolved, &session, "TEST.TEST", deadline)
        .await
        .unwrap()
        .into_parts()
        .unwrap();
    assert_eq!(
        calls.load(Ordering::SeqCst),
        2,
        "formal reference remains fresh"
    );
    exact.query = "TEST".into();
    assert!(
        matches!(
            app.instruments(&resolved, &session, &exact, deadline).await,
            Err(Error::Source(SourceError::Unavailable))
        ),
        "filtered discovery still requests its original full catalogue"
    );
}

#[tokio::test(flavor = "current_thread")]
async fn exact_single_instrument_query_preserves_successful_absence_and_rejects_wrong_identity() {
    let (_authority, session, resolved, _calls) =
        source_from(None, Some(TemporaryFault::EmptyReference));
    let app = Application::default();
    let deadline = Instant::now() + Duration::from_secs(10);
    let mut exact = query();
    exact.query.clear();
    let result = app
        .instruments(&resolved, &session, &exact, deadline)
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    assert_eq!(result["instruments"], json!([]));
    assert!(matches!(
        app.reference(&resolved, &session, "TEST.TEST", deadline)
            .await,
        Err(Error::Corrupt)
    ));
    let (_authority, session, resolved, _calls) = source_from(None, None);
    exact.instrument_ids = vec!["MISSING.TEST".into()];
    assert!(matches!(
        app.instruments(&resolved, &session, &exact, deadline).await,
        Err(Error::Corrupt)
    ));
}
#[test]
fn catalogue_ttl_is_strict_and_reads_do_not_renew_it() {
    let at = Instant::now();
    let cache = Cache { at, rows: vec![] };
    assert!(!cache.current_at(at - Duration::from_nanos(1)));
    assert!(cache.current_at(at));
    assert!(cache.current_at(at + Duration::from_secs(60) - Duration::from_nanos(1)));
    assert!(!cache.current_at(at + Duration::from_secs(60)));
    assert!(!cache.current_at(at + Duration::from_secs(61)));
    assert_eq!(cache.at, at);
}

#[tokio::test(flavor = "current_thread")]
async fn missing_descriptor_is_not_a_substitute_for_a_mismatched_provider_reply() {
    let (_authority, session, resolved, calls) = source_from(None, None);
    let app = Application::default();
    let deadline = Instant::now() + Duration::from_secs(10);
    app.instruments(&resolved, &session, &query(), deadline)
        .await
        .unwrap()
        .into_parts()
        .unwrap();
    let mut request = window(1);
    request.instrument_id = "MISSING.TEST".into();
    assert!(matches!(
        app.temporary_window(
            &resolved,
            &session,
            &request,
            "00000000-0000-4000-8000-000000000101",
            deadline
        )
        .await,
        Err(Error::Corrupt)
    ));
    assert_eq!(
        calls.load(Ordering::SeqCst),
        0,
        "no history requested for a mismatched descriptor"
    );
}
#[tokio::test(flavor = "current_thread")]
async fn selected_catalog_descriptor_avoids_a_second_reference_without_renewal_or_formal_reuse() {
    for minutes in [1, 7] {
        let (authority, session, resolved, calls) = source_from(
            None,
            Some(TemporaryFault::ReferenceUnavailableAfterDiscovery),
        );
        let app = Application::default();
        let deadline = Instant::now() + Duration::from_secs(10);
        app.instruments(&resolved, &session, &query(), deadline)
            .await
            .unwrap()
            .into_parts()
            .unwrap();
        let before = app.cache.lock().unwrap().values().next().unwrap().at;
        let result = app
            .temporary_window(
                &resolved,
                &session,
                &window(minutes),
                "00000000-0000-4000-8000-000000000101",
                deadline,
            )
            .await
            .expect("the selected current descriptor removes redundant Provider reference I/O");
        assert_eq!(result.parts().unwrap().0["coverage"]["status"], "COMPLETE");
        assert_eq!(
            calls.load(Ordering::SeqCst),
            2,
            "one discovery and one history page"
        );
        assert_eq!(
            app.cache.lock().unwrap().values().next().unwrap().at,
            before
        );
        assert!(
            matches!(
                app.reference(&resolved, &session, "TEST.TEST", deadline)
                    .await,
                Err(Error::Source(SourceError::Unavailable))
            ),
            "formal reference still performs fresh I/O"
        );
        authority.withdraw();
        assert!(matches!(result.into_parts(), Err(Error::Forbidden)));
        assert!(matches!(
            app.temporary_window(
                &resolved,
                &session,
                &window(minutes),
                "00000000-0000-4000-8000-000000000102",
                deadline
            )
            .await,
            Err(Error::Forbidden)
        ));
    }
}

#[tokio::test(flavor = "current_thread")]
async fn expired_or_cross_bound_catalog_never_substitutes_for_a_fresh_exact_reference() {
    for case in ["expired", "artifact", "binding", "missing", "poisoned"] {
        let (_authority, session, mut resolved, calls) = source_from(
            None,
            Some(TemporaryFault::ReferenceUnavailableAfterDiscovery),
        );
        let app = Application::default();
        let deadline = Instant::now() + Duration::from_secs(10);
        app.instruments(&resolved, &session, &query(), deadline)
            .await
            .unwrap()
            .into_parts()
            .unwrap();
        let mut request = window(1);
        match case {
            "expired" => {
                app.cache.lock().unwrap().values_mut().next().unwrap().at =
                    Instant::now() - Duration::from_secs(61)
            }
            "artifact" => resolved.artifact = "1".repeat(64),
            "binding" => {
                let mut record = resolved.binding.record().clone();
                record.type_descriptor_fingerprint = "1".repeat(64);
                resolved.binding =
                    crate::integration_configuration::RuntimeBinding::new(record).unwrap();
            }
            "missing" => request.instrument_id = "MISSING.TEST".into(),
            "poisoned" => {
                let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    let _held = app.cache.lock().unwrap();
                    panic!("controlled cache-lock failure");
                }));
            }
            _ => unreachable!(),
        }
        assert!(
            matches!(
                app.temporary_window(
                    &resolved,
                    &session,
                    &request,
                    "00000000-0000-4000-8000-000000000101",
                    deadline
                )
                .await,
                Err(Error::Source(SourceError::Unavailable)) | Err(Error::Unavailable)
            ),
            "{case}"
        );
        assert_eq!(
            calls.load(Ordering::SeqCst),
            if case == "poisoned" { 1 } else { 2 },
            "{case}"
        );
    }
}
