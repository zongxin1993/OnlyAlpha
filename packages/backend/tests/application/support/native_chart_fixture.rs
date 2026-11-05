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
        database: std::env::var("ONLYALPHA_NATIVE_CHART_CLICKHOUSE_DATABASE").unwrap(),
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
    assert_eq!(caps["capabilities"].as_array().unwrap().len(), 14);
    verify_fixed_metadata_projection(&query, &source_session, &caps);
    let capability = caps["capabilities"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["type_id"] == "onlyalpha.indicator.sma" && c["semantic_version"] == "2")
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
    assert_eq!(evaluation["calculation"]["implementation_fingerprint"], capability["implementation_fingerprint"]);
    let wma = caps["capabilities"]
        .as_array().unwrap().iter()
        .find(|c| c["type_id"] == "onlyalpha.indicator.wma" && c["semantic_version"] == "2")
        .unwrap();
    let prepared = query.prepare(
        &app, resolved.as_ref(), &source_session,
        &mut store(business.client_mut().await.unwrap(), &ch),
        onlyalpha_backend::application::chart::ChartInput {
            raw: &chart_request(&history, wma, None).to_string(),
            preview_stream: None,
            clock_ns: NOW,
        },
    ).await.unwrap();
    assert!(prepared.cancellation().unwrap().is_some());
    let (weighted, fence) = prepared.execute().unwrap().into_parts().unwrap();
    fence.check().unwrap();
    assert_eq!(weighted["calculation"]["implementation_fingerprint"], wma["implementation_fingerprint"]);
    let points = weighted["series"][0]["points"].as_array().unwrap();
    assert_eq!(points.len(), 2000);
    assert_eq!(points[18]["readiness"], "PARTIAL");
    assert!(points[18]["value"].is_null());
    assert_eq!(points[19]["readiness"], "READY");
    assert!(points[19]["value"].is_string());

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

fn verify_fixed_metadata_projection(query: &ChartQuery, session: &Session, expected: &Value) {
    assert_eq!(&query.capabilities(session).unwrap(), expected);
    let closed = chart_query();
    closed.close().unwrap();
    assert!(closed.capabilities(session).is_err());
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
    let mut native_request = common.clone();
    native_request["calculations"] = json!(["sma", "wma", "roc", "rolling_return"].map(|family| {
        let capability = caps["capabilities"].as_array().unwrap().iter().find(|entry| {
            entry["type_id"] == format!("onlyalpha.indicator.{family}") && entry["semantic_version"] == "2"
        }).unwrap();
        chart_request(history, capability, None)["calculation"].clone()
    }));
    let mut unknown = native_request.clone();
    unknown["calculations"][0]["semantic_version"] = json!("1");
    assert!(matches!(
        query.prepare_temporary_batch_before(
            app, resolved, session, &unknown.to_string(), NOW, deadline()
        ).await,
        Err(onlyalpha_backend::application::chart::Error::Unavailable)
    ));
    let prepared = query.prepare_temporary_batch_before(
        app, resolved, session, &native_request.to_string(), NOW, deadline()
    ).await.unwrap();
    let cancellation = prepared.cancellation().unwrap().expect("owned Rust worker");
    assert_eq!(cancellation.state(), onlyalpha_calculation_bridge::ProcessState::Running);
    let (native_batch, fence) = prepared.execute().unwrap().into_parts().unwrap();
    assert_eq!(cancellation.state(), onlyalpha_calculation_bridge::ProcessState::Joined);
    fence.check().unwrap();
    let results = native_batch["results"].as_array().unwrap();
    assert_eq!(results.len(), 4);
    for result in results {
        assert_eq!(result["evaluation"]["query_status"], "DISPLAYABLE");
    }
    let roc = &results[2]["evaluation"]["series"][0]["points"];
    let rolling_return = &results[3]["evaluation"]["series"][0]["points"];
    assert_eq!(roc, rolling_return);
    let points = roc.as_array().unwrap();
    assert_eq!(points[19]["readiness"], "PARTIAL");
    assert!(points[19]["value"].is_null());
    assert_eq!(points[20]["readiness"], "READY");
    assert!(points[20]["value"].is_string());
    eprintln!("chart-vector: native SMA/WMA/ROC/rolling return batch completed in a Rust worker");

    let mut changed = native_request;
    changed["calculations"][2]["expected_implementation_fingerprint"] = json!("0".repeat(64));
    assert!(matches!(
        query.prepare_temporary_batch_before(
            app, resolved, session, &changed.to_string(), NOW, deadline()
        ).await,
        Err(onlyalpha_backend::application::chart::Error::Changed)
    ));

    for group in [
        &["ema", "rsi", "atr", "macd"][..],
        &["bollinger", "rolling_volatility", "zscore", "obv"][..],
        &["vwap", "stochastic"][..],
    ] {
        let mut request = common.clone();
        request["calculations"] = json!(group.iter().map(|family| {
            let capability = caps["capabilities"].as_array().unwrap().iter().find(|entry| {
                entry["type_id"] == format!("onlyalpha.indicator.{family}")
                    && entry["provider_id"] == "onlyalpha.indicator.native"
            }).unwrap();
            chart_request(history, capability, None)["calculation"].clone()
        }).collect::<Vec<_>>());
        let prepared = query.prepare_temporary_batch_before(
            app, resolved, session, &request.to_string(), NOW, deadline()
        ).await.unwrap();
        assert!(prepared.cancellation().unwrap().is_some());
        let (batch, fence) = prepared.execute().unwrap().into_parts().unwrap();
        fence.check().unwrap();
        let results = batch["results"].as_array().unwrap();
        assert_eq!(results.len(), group.len());
        for (result, family) in results.iter().zip(group) {
            let evaluation = &result["evaluation"];
            assert_eq!(evaluation["query_status"], "DISPLAYABLE", "{family}");
            assert_eq!(evaluation["calculation"]["type_id"], format!("onlyalpha.indicator.{family}"));
            for series in evaluation["series"].as_array().unwrap() {
                let points = series["points"].as_array().unwrap();
                assert_eq!(points.len(), 2000, "{family}");
                assert_eq!(points[1999]["readiness"], "READY", "{family}");
            }
        }
    }
    eprintln!("chart-vector: all fourteen native families evaluated over the controlled Source");

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
        let control = prepared.cancellation().unwrap().expect("owned Rust worker");
        let (value, fence) = prepared.execute().unwrap().into_parts().unwrap();
        assert_eq!(control.state(), onlyalpha_calculation_bridge::ProcessState::Joined);
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
    prepared.cancellation().unwrap().expect("Rust worker cancellation").cancel().unwrap();
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
    let first_control = first.cancellation().unwrap().expect("Rust worker cancellation");
    let second = query
        .prepare_temporary_batch_before(app, resolved, session, &raw, NOW, deadline())
        .await
        .unwrap();
    let second_control = second.cancellation().unwrap().expect("Rust worker cancellation");
    assert_eq!(first_control.state(), ProcessState::Running);
    assert_eq!(second_control.state(), ProcessState::Running);
    assert!(matches!(
        query
            .prepare_temporary_batch_before(app, resolved, session, &raw, NOW, deadline())
            .await,
        Err(onlyalpha_backend::application::chart::Error::Capacity)
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
    let replacement_control = replacement.cancellation().unwrap().expect("Rust worker cancellation");
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
