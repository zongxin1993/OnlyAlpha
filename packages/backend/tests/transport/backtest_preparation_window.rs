//! Actual complete graph geometry at the Host's Dataset handoff.
use super::*;
#[test]
fn backtest_bar_start_sample_has_exact_closed_event_axis_without_losing_the_last_close() {
    let original=crate::application::strategy_research::test_run_record();
    let graph=onlyalpha_calculation::product::Graph::from_record(&original["decision"]["decision_graph"],8*1024*1024).unwrap();
    let actual=backtest_dataset_event_window(&graph).unwrap();
    let ns=|s:&str|OnlyTimestamp::from_datetime(s.parse::<OnlyUtcDateTime>().unwrap()).unix_nanos().to_string().parse::<u64>().unwrap();
    let first=actual["dataset_event_start_ns"].as_str().unwrap().parse::<u64>().unwrap();
    let end=actual["dataset_event_end_ns"].as_str().unwrap().parse::<u64>().unwrap();
    assert_eq!(actual["warmup_bars"],20,"derive whole actual graph history, not an alias");
    assert_eq!(actual["observation_capacity"],720);
    assert_eq!(actual["dataset_observation_capacity"],740);
    assert_eq!(first,ns("2025-01-02T23:41:00Z"));
    assert_eq!(end,ns("2025-01-03T12:01:00Z"));
    assert_eq!((end-first)/BAR,740);
    assert_eq!(first-BAR,ns("2025-01-02T23:40:00Z"));
    assert_eq!(end-BAR,ns("2025-01-03T12:00:00Z"),"last event is noon; no noon-opened bar");
    assert_eq!(end-2*BAR,ns("2025-01-03T11:59:00Z"));
    assert!(end<ns("2025-01-05T00:00:00Z"));
}


#[test]
fn backtest_ready_observation_has_a_read_only_owner_interface() {
    // Structural boundary only: this test cannot manufacture an actual READY,
    // Host or execution grant and does not claim the runtime helper ran.
    fn query<'a>(host:&'a Host,original:&'a Operation,human:&'a human_access::Session)
        ->impl std::future::Future<Output=Result<()>>+'a {
        host.backtest_readiness_observation(original,human)
    }
    let _=query;
}

/// Requires the actual original READY and an actual Running Node. No value-test
/// seal is accepted. The full native fixture must call this owning helper before
/// it can claim writer independence; compiling it proves only the interface.
pub(crate) async fn ready_http_with_original_writer_held(
    running:&crate::bootstrap::workstation_startup::Running,
    listener:&tokio::net::TcpListener,preparation:&CommandId,
) {
    use axum::body::{Body,to_bytes};
    use hyper_util::rt::TokioIo;
    use http::{Request,StatusCode};
    let stream=tokio::net::TcpStream::connect(listener.local_addr().unwrap()).await.unwrap();
    let (socket,_)=listener.accept().await.unwrap();let ingress=running.ingress.clone();
    let server=tokio::spawn(async move{ingress.serve_connection(socket).await});
    let (mut sender,connection)=hyper::client::conn::http1::handshake(TokioIo::new(stream)).await.unwrap();
    let client=tokio::spawn(connection);
    // The normal navigation response supplies this Node's actual Human cookie.
    let navigation=Request::builder().uri("/").header("host","127.0.0.1:5173")
        .header("accept","text/html").header("sec-fetch-mode","navigate")
        .header("sec-fetch-dest","document").header("sec-fetch-site","none")
        .body(Body::empty()).unwrap();
    let navigation=sender.send_request(navigation).await.unwrap();assert_eq!(navigation.status(),StatusCode::OK);
    let cookie=navigation.headers().get(http::header::SET_COOKIE).unwrap().to_str().unwrap().split(';').next().unwrap().to_owned();
    to_bytes(Body::new(navigation.into_body()),8*1024*1024).await.unwrap();
    // This is the original mutex and original AuthoritySession. No transaction
    // or SDK response is injected; only the normal GET is allowed to progress.
    let original=running.host.writer.lock().await;assert!(original.is_some());
    let get=Request::builder().uri(format!("/api/v2/backtest/preparations/{}/ready",preparation.value()))
        .header("host","127.0.0.1:5173").header("cookie",cookie)
        .body(Body::empty()).unwrap();
    let observed=tokio::time::timeout(std::time::Duration::from_secs(2),async {
        let response=sender.send_request(get).await.map_err(|e|e.to_string())?;
        let status=response.status();let bytes=to_bytes(Body::new(response.into_body()),8*1024*1024).await.map_err(|e|e.to_string())?;
        let value:Value=serde_json::from_slice(&bytes).map_err(|e|e.to_string())?;
        Ok::<_,String>((status,value))
    }).await;
    let verified=matches!(&observed,Ok(Ok((status,value))) if *status==StatusCode::OK
        &&value["state"]=="READY"&&value["readiness"]["state"]=="VERIFIED"
        &&value["command_id"]==preparation.value()&&value["run_id"].is_null());
    let held=running.host.writer.try_lock().is_err();
    drop(original);drop(sender);server.await.unwrap().unwrap();client.await.unwrap().unwrap();
    assert!(held&&verified,"actual ready GET must finish and verify while the original writer remains held: {observed:?}");
}

/// Technical owning integration helper. The caller must supply two real READY
/// operations from the actual Host chain: one original Accepted submission and
/// one original NotSubmitted command. No caller JSON can create either seal.
/// Compiling this helper alone does not prove its actual PG assertions ran.
pub(crate) async fn stopped_worker_preserves_accepted_replay_and_refuses_new_submission(
    host:&Arc<Host>,human:&human_access::Session,accepted:&Operation,fresh:&Operation,
) {
    assert!(accepted.request.is_backtest()&&fresh.request.is_backtest());
    assert_ne!(accepted.request.future_command(),fresh.request.future_command());
    let expected=accepted.outputs["ready"]["preparation_fingerprint"].as_str().unwrap();
    let future=CommandId::new(accepted.request.future_command()).unwrap();
    let fresh_expected=fresh.outputs["ready"]["preparation_fingerprint"].as_str().unwrap();
    let fresh_future=CommandId::new(fresh.request.future_command()).unwrap();
    let namespace=namespace(&host.research_preparation_config).unwrap();
    let accepted_request=Host::backtest_create_request(accepted).unwrap();
    let fresh_request=Host::backtest_create_request(fresh).unwrap();
    let original={
        let mut reader=host.reader.lock().await;let client=reader.as_mut().unwrap();
        assert!(matches!(crate::persistence::backtest_run::creation_outcome_readonly(client,&namespace,&fresh_request,&fresh.owner).await.unwrap(),CreationOutcome::NotSubmitted));
        match crate::persistence::backtest_run::creation_outcome_readonly(client,&namespace,&accepted_request,&accepted.owner).await.unwrap(){CreationOutcome::Accepted(run)=>run,_=>panic!("actual original Accepted command is required")}
    };
    {
        let mut held=host.backtest.lock().await;
        held.as_mut().expect("actual Infrastructure-started worker is required").drain().await.unwrap();
    }
    assert_eq!(host.backtest_worker_status().await,Some(crate::workers::backtest_worker::Status::Stopped));
    assert!(!host.wake_backtest_after_commit());
    assert_eq!(host.require_backtest_worker().await.unwrap_err().code(),"BACKTEST_SERVICE_UNAVAILABLE");
    let replay=host.confirm_backtest_preparation(human.clone(),&accepted.command,expected,&future).await.unwrap();
    assert_eq!(replay["run_id"],original.run_id(),"accepted original Command replay precedes worker availability");
    let refused=host.confirm_backtest_preparation(human.clone(),&fresh.command,fresh_expected,&fresh_future).await.unwrap_err();
    assert_eq!(refused.code(),"BACKTEST_SERVICE_UNAVAILABLE");
    let mut reader=host.reader.lock().await;let client=reader.as_mut().unwrap();
    assert!(matches!(crate::persistence::backtest_run::creation_outcome_readonly(client,&namespace,&fresh_request,&fresh.owner).await.unwrap(),CreationOutcome::NotSubmitted),"refusal cannot admit a global Command or enqueue a new Run");
    let replay=match crate::persistence::backtest_run::creation_outcome_readonly(client,&namespace,&accepted_request,&accepted.owner).await.unwrap(){CreationOutcome::Accepted(run)=>run,_=>panic!("original accepted command disappeared")};
    assert_eq!(replay.record(),original.record());
    assert_eq!(replay.specification_fingerprint(),original.specification_fingerprint());
    assert_eq!(replay.admission_resolution_fingerprint(),original.admission_resolution_fingerprint());
}


#[test]
fn only_the_original_running_confirmation_keeps_an_absent_future_outcome_unknown() {
    use State::*;
    assert!(backtest_confirmation_in_progress(Running, "CONFIRMING"));
    for state in [Accepted, InputPending, Ready, Blocked, Unknown, CancelRequested, Cancelled] {
        assert!(!backtest_confirmation_in_progress(state, "CONFIRMING"), "{state:?}");
    }
    for phase in ["ACCEPTED", "VALIDATING", "INPUTS", "READY_FOR_HUMAN_CONFIRMATION", "STOPPED", "CANCELLATION", "OWNER_DRAINED"] {
        assert!(!backtest_confirmation_in_progress(Running, phase), "{phase}");
    }
}
