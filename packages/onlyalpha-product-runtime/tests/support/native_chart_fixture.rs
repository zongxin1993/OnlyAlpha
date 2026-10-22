// Included under the existing native technical consumer; no Shipping route.
use super::*;

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
    eprintln!("chart-vector: output-complete");
    query.close().unwrap();
    query.drain().unwrap();
    business.close().await.unwrap();
}
