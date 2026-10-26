// Included under the existing native technical consumer; no Shipping route.
use super::*;
use onlyalpha_domain::base::OnlyDomainModel;

#[test]
fn export_vector() {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap()
        .block_on(Box::pin(produce()));
}

async fn produce() {
    eprintln!("chart-vector: setup");
    let http = Http::start();
    let mut business = session().await;
    let authoring = AuthoringCatalog::new(vec![spot_authoring(WORK).unwrap()]).unwrap();
    let id = IntegrationId::new(&uid(401)).unwrap();
    Integrations::new(business.client_mut().await.unwrap())
        .create(
            &CreateIntegration::new(
                CommandId::new(&uid(402)).unwrap(),
                id.clone(),
                IntegrationTypeId::new("binance.spot.market_data").unwrap(),
                "Synthetic native chart vector",
            )
            .unwrap(),
            &authoring,
            AT.parse().unwrap(),
            WORK,
        )
        .await
        .unwrap();
    Integrations::new(business.client_mut().await.unwrap())
        .publish_revision(
            &PublishRevision::new(CommandId::new(&uid(403)).unwrap(), id.clone(), 1).unwrap(),
            &authoring,
            AT.parse().unwrap(),
            1000,
            WORK,
        )
        .await
        .unwrap();
    let snapshot = Integrations::new(business.client_mut().await.unwrap())
        .read(&id, 1000, WORK)
        .await
        .unwrap()
        .unwrap();
    let reference = Reference::new(
        id.value(),
        snapshot
            .integration()
            .record()
            .current_revision_fingerprint
            .as_ref()
            .unwrap(),
        Some("binance.spot.market_data"),
    )
    .unwrap();
    let selection =
        Selection::new(reference.clone(), "binance.spot.market_data.live", "GLOBAL").unwrap();
    let authority = Authority::new(
        "synthetic-chart-vector",
        &sha(b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
        vec![Grant::new(selection.clone(), vec![Permission::ClosedHistory]).unwrap()],
    )
    .unwrap();
    let source_session = authority
        .authenticate("Bearer aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        .unwrap();
    let factory =
        spot_source::test_support::controlled_factory(&http.url, "ws://127.0.0.1:1", 1000);
    let executable = std::fs::read(std::env::current_exe().unwrap()).unwrap();
    let resolver = Resolver::new(
        vec![Installed::from_executable(factory, &executable).unwrap()],
        spot_source::test_support::trust(),
        Arc::new(FixedClock(std::sync::atomic::AtomicI64::new(NOW))),
    )
    .unwrap();
    let resolved = Arc::new(
        resolver
            .resolve(&snapshot, &reference, &source_session, None)
            .unwrap(),
    );
    let human = Arc::new(Human {
        selection,
        active: AtomicBool::new(true),
    });
    let app = Application::default();
    let ch = ClickHouse::new(ClickHouseConfig {
        url: std::env::var("ONLYALPHA_TEST_CLICKHOUSE_URL").unwrap(),
        database: "onlyalpha_test_chart_query_vector".into(),
        user: std::env::var("ONLYALPHA_TEST_CLICKHOUSE_USER").unwrap_or("default".into()),
        password: std::env::var("ONLYALPHA_TEST_CLICKHOUSE_PASSWORD").unwrap_or_default(),
        timeout: Duration::from_secs(5),
        tls_roots_pem: vec![],
        max_bytes: WORK,
        max_rows: 100_000,
    })
    .unwrap();
    ch.assert_server().await.unwrap();
    eprintln!("chart-vector: setup-complete");
    let root = std::env::var("ONLYALPHA_NATIVE_MARKET_WAL").unwrap();
    let mut wal = Wal::new(Path::new(&root), WORK).unwrap();
    let end = 1_767_225_600_000_000_000i64; // Explicit 2026-01-01, after the browser fake-clock adversary.
    let semantic = semantic(15);
    let mut cursor = end - 2000 * 900_000_000_000i64;
    let mut chunk = 0;
    while cursor < end {
        // Respect the owning seven-day acquisition cap; the window still spans all 2000 bars.
        let chunk_end = (cursor + 7 * 24 * 60 * 60 * 1_000_000_000i64).min(end);
        let capture_id = format!("chart-vector-{chunk}");
        eprintln!("chart-vector: chunk={chunk} authority");
        let mut work = {
            let client = business.client_mut().await.unwrap();
            eprintln!("chart-vector: chunk={chunk} prepare");
            app.prepare_acquisition(
                resolved.clone(),
                source_session.clone(),
                human.clone(),
                &mut store(client, &ch),
                AcquisitionRequest {
                    instrument_id: "BTCUSDT.BINANCE",
                    semantic: &semantic,
                    start_ns: cursor,
                    end_ns: chunk_end,
                    clock_ns: NOW,
                    admitted_at: AT,
                },
            )
            .await
            .unwrap()
        };
        eprintln!("chart-vector: chunk={chunk} lease");
        let execution = lease(work.id()).await;
        eprintln!("chart-vector: chunk={chunk} start");
        work.start(
            &mut store(business.client_mut().await.unwrap(), &ch),
            &execution,
            AT,
        )
        .await
        .unwrap();
        eprintln!("chart-vector: chunk={chunk} capture");
        let segments = work
            .capture(
                &app,
                &mut wal,
                CaptureRequest {
                    segment_id: &capture_id,
                    capture_id: &capture_id,
                    created_at: AT,
                    deadline: deadline(),
                },
                &execution,
            )
            .await
            .unwrap();
        eprintln!("chart-vector: chunk={chunk} publish");
        let (completed, fence) = work
            .publish(
                &mut store(business.client_mut().await.unwrap(), &ch),
                &wal,
                &segments,
                AT,
            )
            .await
            .unwrap()
            .into_parts()
            .unwrap();
        fence.check().unwrap();
        assert_eq!(completed["status"], "COMPLETE");
        drop(segments);
        eprintln!("chart-vector: chunk={chunk} close");
        execution.close().await.unwrap();
        eprintln!("chart-vector: chunk={chunk} complete");
        cursor = chunk_end;
        chunk += 1;
    }
    eprintln!("chart-vector: window");
    let (history, fence) = app
        .window(
            &resolved,
            &source_session,
            &mut store(business.client_mut().await.unwrap(), &ch),
            &WindowRequest {
                instrument_id: "BTCUSDT.BINANCE".into(),
                semantic,
                before_ns: Some(end),
                bar_count: 2000,
                clock_ns: NOW,
            },
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap();
    fence.check().unwrap();
    assert_eq!(history["coverage"]["status"], "COMPLETE");
    assert_eq!(history["bars"].as_array().unwrap().len(), 2000);
    let query = chart_query();
    eprintln!("chart-vector: capabilities");
    let caps = query.capabilities(&source_session).unwrap();
    verify_fixed_metadata_projection(&query, &source_session, &caps);
    let capability = caps["capabilities"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["type_id"] == "onlyalpha.indicator.sma")
        .unwrap();
    let request = chart_request(&history, capability, None);
    eprintln!("chart-vector: evaluate");
    let (evaluation, fence) = evaluate_chart(
        &query,
        &app,
        &resolved,
        &source_session,
        &mut business,
        &ch,
        &request,
        None,
    )
    .await
    .into_parts()
    .unwrap();
    fence.check().unwrap();
    assert_eq!(evaluation["query_status"], "DISPLAYABLE");
    assert_eq!(evaluation["authority"], "DISPLAY_ONLY");
    std::fs::write(
        std::env::var("ONLYALPHA_NATIVE_CHART_VECTOR").unwrap(),
        serde_json::to_vec(
            &json!({"capability":capability,"history":history,"evaluation":evaluation}),
        )
        .unwrap(),
    )
    .unwrap();
    verify_temporary_batch(
        &query,
        &app,
        &resolved,
        &source_session,
        &authority,
        &caps,
        &history,
    )
    .await;
    eprintln!("chart-vector: output-complete");
    query.close().unwrap();
    query.drain().unwrap();
    business.close().await.unwrap();
}

// Technical regression using the actual sealed SDK and native metadata API.
// Metadata declarations do not promise that another worker can currently launch.
fn verify_fixed_metadata_projection(query: &ChartQuery, session: &Session, expected: &Value) {
    use std::{fs, os::unix::fs::PermissionsExt, path::PathBuf};
    struct RestoreMode(PathBuf, fs::Permissions);
    impl Drop for RestoreMode {
        fn drop(&mut self) {
            fs::set_permissions(&self.0, self.1.clone()).unwrap();
        }
    }
    let root = PathBuf::from(std::env::var("ONLYALPHA_NATIVE_CHART_INSTALLATION").unwrap());
    let interpreter = root.join("bin/python");
    let restore = RestoreMode(
        interpreter.clone(),
        fs::metadata(&interpreter).unwrap().permissions(),
    );
    fs::set_permissions(&interpreter, fs::Permissions::from_mode(0o444)).unwrap();
    let warm = query.capabilities(session);
    assert!(
        warm.is_ok(),
        "fixed metadata must not launch another worker: {warm:?}"
    );
    assert_eq!(&warm.unwrap(), expected);
    // An uninitialized query must still perform the actual bootstrap. Failure
    // cannot publish a partially admitted projection or masquerade as support.
    let cold = chart_query();
    assert!(cold.capabilities(session).is_err());
    drop(restore);
    assert_eq!(&cold.capabilities(session).unwrap(), expected);
    cold.close().unwrap();
    assert!(cold.capabilities(session).is_err());
    eprintln!("chart-vector: fixed metadata/no-worker/init-failure/shutdown relations proved");
}

// Controlled Source and real sealed algorithm process; not Shipping UI evidence.
async fn verify_temporary_batch(
    query: &ChartQuery,
    app: &Application,
    resolved: &Resolved,
    session: &Session,
    authority: &Authority,
    caps: &Value,
    history: &Value,
) {
    let window_request = WindowRequest {
        instrument_id: history["instrument_id"].as_str().unwrap().into(),
        semantic: OnlyBarSemantic::from_record(&history["bar_semantic"]).unwrap(),
        before_ns: Some(
            history["resolved_end_ns"]
                .as_str()
                .unwrap()
                .parse()
                .unwrap(),
        ),
        bar_count: 2000,
        clock_ns: NOW,
    };
    let page = uid(8500);
    let mut window = Value::Null;
    for _batch in 0..3 {
        window = app
            .temporary_window(resolved, session, &window_request, &page, deadline())
            .await
            .unwrap()
            .into_parts()
            .unwrap()
            .0;
        if window["coverage"]["status"] == "COMPLETE" {
            break;
        }
    }
    assert_eq!(window["coverage"]["status"], "COMPLETE");
    let calculations = ["sma", "bollinger", "macd", "rsi"].map(|family| {
        let capability = caps["capabilities"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["type_id"] == format!("onlyalpha.indicator.{family}"))
            .unwrap();
        chart_request(history, capability, None)["calculation"].clone()
    });
    let common = json!({"schema_version":2,"source_kind":"TEMPORARY_MARKET_DATA","page_id":page,
        "source_reference":{"integration_id":window["source_selection"]["integration_id"],"integration_revision_fingerprint":window["source_selection"]["integration_revision_fingerprint"],"expected_type_id":window["source_selection"]["type_id"]},
        "instrument_id":window["instrument_id"],"bar_semantic":window["bar_semantic"],
        "window":{"anchor_kind":"BEFORE_TIME","before_ns":window["resolved_end_ns"],"target_bar_count":2000},"expected_window_fingerprint":window["window_fingerprint"]});
    verify_two_owned_chart_workers(app, resolved, session, &common, &calculations).await;
    let mut singles = Vec::new();
    for calculation in &calculations {
        let mut request = common.clone();
        request["calculation"] = calculation.clone();
        let (value, fence) = query
            .prepare_temporary_before(
                app,
                resolved,
                session,
                &request.to_string(),
                NOW,
                deadline(),
            )
            .await
            .unwrap()
            .execute()
            .unwrap()
            .into_parts()
            .unwrap();
        fence.check().unwrap();
        singles.push(value);
    }
    for order in [[0, 1, 2, 3], [3, 2, 1, 0], [0, 1, 0, 1]] {
        let mut request = common.clone();
        request["calculations"] = json!(order.map(|i| calculations[i].clone()));
        let prepared = query
            .prepare_temporary_batch_before(
                app,
                resolved,
                session,
                &request.to_string(),
                NOW,
                deadline(),
            )
            .await
            .unwrap();
        // Existing process must serve all calculations. A new request must
        // still launch a new process, even while a fixed declaration exists.
        use std::os::unix::fs::PermissionsExt;
        let interpreter =
            std::path::PathBuf::from(std::env::var("ONLYALPHA_NATIVE_CHART_INSTALLATION").unwrap())
                .join("bin/python");
        let permissions = std::fs::metadata(&interpreter).unwrap().permissions();
        std::fs::set_permissions(&interpreter, std::fs::Permissions::from_mode(0o444)).unwrap();
        let result = prepared.execute();
        let fresh = query
            .prepare_temporary_batch_before(
                app,
                resolved,
                session,
                &request.to_string(),
                NOW,
                deadline(),
            )
            .await;
        std::fs::set_permissions(&interpreter, permissions).unwrap();
        assert!(
            fresh.is_err(),
            "every later request must spawn its own worker"
        );
        query.drain().unwrap();
        let (value, fence) = result.unwrap().into_parts().unwrap();
        fence.check().unwrap();
        for (index, original) in order.into_iter().enumerate() {
            assert_eq!(value["results"][index]["request_index"], index);
            assert_eq!(value["results"][index]["status"], "EVALUATED");
            assert_eq!(value["results"][index]["evaluation"], singles[original]);
        }
    }
    let mut request = common.clone();
    request["calculations"] = json!(calculations);
    request["calculations"][1]["typed_parameters"]["period"]["value"] = json!(0);
    let (value, fence) = query
        .prepare_temporary_batch_before(
            app,
            resolved,
            session,
            &request.to_string(),
            NOW,
            deadline(),
        )
        .await
        .unwrap()
        .execute()
        .unwrap()
        .into_parts()
        .unwrap();
    fence.check().unwrap();
    assert_eq!(value["results"][1]["status"], "REJECTED");
    assert_eq!(value["results"][1]["error"], "CHART_STUDY_REQUEST_INVALID");
    for index in [0, 2, 3] {
        assert_eq!(value["results"][index]["evaluation"], singles[index]);
    }
    request["calculations"] = json!(calculations);
    request["calculations"][3]["expected_implementation_fingerprint"] = json!("0".repeat(64));
    assert!(
        query
            .prepare_temporary_batch_before(
                app,
                resolved,
                session,
                &request.to_string(),
                NOW,
                deadline()
            )
            .await
            .is_err()
    );
    query.drain().unwrap();
    request["calculations"] = json!(calculations);
    let prepared = query
        .prepare_temporary_batch_before(
            app,
            resolved,
            session,
            &request.to_string(),
            NOW,
            deadline(),
        )
        .await
        .unwrap();
    prepared.cancellation().unwrap().cancel().unwrap();
    assert!(prepared.execute().is_err());
    query.drain().unwrap();
    let prepared = query
        .prepare_temporary_batch_before(
            app,
            resolved,
            session,
            &request.to_string(),
            NOW,
            deadline(),
        )
        .await
        .unwrap();
    authority.withdraw();
    assert!(prepared.execute().is_err());
    query.drain().unwrap();
    eprintln!(
        "chart-vector: batch matches isolated singles/order/repeat/item rejection/shared failure/cancellation/withdrawal"
    );
}

// Prepared requests retain actual isolated processes at a deterministic barrier.
// This is technical lifecycle evidence, not a Shipping UI performance sample.
async fn verify_two_owned_chart_workers(
    app: &Application,
    resolved: &Resolved,
    session: &Session,
    common: &Value,
    calculations: &[Value; 4],
) {
    use onlyalpha_calculation_bridge::ProcessState;
    let query = chart_query();
    let expected = query.capabilities(session).unwrap();
    let mut request = common.clone();
    request["calculations"] = json!(calculations);
    let raw = request.to_string();
    let first = query
        .prepare_temporary_batch_before(app, resolved, session, &raw, NOW, deadline())
        .await
        .unwrap();
    let first_control = first.cancellation().unwrap();
    let second = query
        .prepare_temporary_batch_before(app, resolved, session, &raw, NOW, deadline())
        .await
        .unwrap();
    let second_control = second.cancellation().unwrap();
    assert_eq!(first_control.state(), ProcessState::Running);
    assert_eq!(second_control.state(), ProcessState::Running);
    assert!(matches!(
        query
            .prepare_temporary_batch_before(app, resolved, session, &raw, NOW, deadline())
            .await,
        Err(onlyalpha_product_runtime::chart::Error::Capacity)
    ));
    first_control.cancel().unwrap();
    assert_eq!(first_control.state(), ProcessState::Joined);
    assert_eq!(second_control.state(), ProcessState::Running);
    assert_eq!(query.process_state(), ProcessState::Running);
    assert_eq!(query.capabilities(session).unwrap(), expected);
    assert!(first.execute().is_err());
    let replacement = query
        .prepare_temporary_batch_before(app, resolved, session, &raw, NOW, deadline())
        .await
        .unwrap();
    let replacement_control = replacement.cancellation().unwrap();
    query.close().unwrap();
    assert_eq!(second_control.state(), ProcessState::Joined);
    assert_eq!(replacement_control.state(), ProcessState::Joined);
    assert_eq!(query.process_state(), ProcessState::Joined);
    assert!(second.execute().is_err());
    assert!(replacement.execute().is_err());
    assert!(query.capabilities(session).is_err());
    eprintln!(
        "chart-vector: two actual owned workers/third bounded/independent cancellation/metadata overlap/drain proved"
    );
}
