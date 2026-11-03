//! Human observations use the original admitted Run and its owning evidence.
//! Financial values are projected from native owners; Web does not recompute them.
use crate::{
    application::{backtest_run::{self, CancelRequest}, source_access::{Reference, Selection}},
    persistence::{backtest_evidence::{self, BacktestReadContext, VerifiedEvidence}, backtest_run::{self as runs, Backtests, RunState, RunStatus}},
    security::{human_access, ingress::{self, Release}},
    transport::{host::{Failure, Host, invalid, now}, host_factor_studies::{failed, input}, research_wire::*},
};
use axum::{Json, body::Body, response::{IntoResponse, Response}};
use http::{Method, Request, StatusCode};
use onlyalpha_domain::{base::OnlyDomainModel, time::OnlyTimestamp};
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc, time::Instant};

const INVALID:&str="BACKTEST_RESULT_UNAVAILABLE";
struct FilledOpening {trade:String,side:String,fee:String,signal_time:String}
pub(super) fn worker_observation(status:Option<crate::workers::backtest_worker::Status>)->BacktestWorkerObservation {
    use crate::workers::backtest_worker::Status;
    use BacktestWorkerState::*;
    let (state,code,run_id)=match status {
        Some(Status::Starting)=>(Starting,None,None),
        Some(Status::Idle)=>(Idle,None,None),
        Some(Status::Running(run))=>(Running,None,Some(run)),
        Some(Status::Uncertain(code))=>(Unknown,Some(code.into()),None),
        Some(Status::Unavailable(code))=>(Unavailable,Some(code.into()),None),
        Some(Status::Stopped)=>(Stopped,None,None),
        None=>(Unavailable,Some("BACKTEST_SERVICE_UNAVAILABLE".into()),None),
    };
    BacktestWorkerObservation{state,code,run_id}
}
pub(super) fn require_worker(status:Option<crate::workers::backtest_worker::Status>)->Result<(),Failure> {
    use crate::workers::backtest_worker::Status;
    match status {
        Some(Status::Starting|Status::Idle|Status::Running(_))=>Ok(()),
        _=>Err(Failure::unavailable("BACKTEST_SERVICE_UNAVAILABLE")),
    }
}
fn text(value:&Value)->Result<String,Failure>{value.as_str().map(str::to_owned).ok_or_else(||failed(INVALID))}
fn number(value:&Value)->Result<u64,Failure>{value.as_u64().ok_or_else(||failed(INVALID))}
fn instant(value:&Value)->Result<String,Failure>{
    let n=text(value)?.parse::<bigdecimal::num_bigint::BigInt>().map_err(|_|failed(INVALID))?;
    OnlyTimestamp::from_unix_nanos(n).to_datetime_exact().map(|v|v.to_string()).map_err(|_|failed(INVALID))
}
fn run_view(run:&backtest_run::VerifiedRun,status:RunStatus,preparation:Option<String>,worker:Option<crate::workers::backtest_worker::Status>)->Result<BacktestRunView,Failure>{
    let state=match status.state {
        RunState::Queued|RunState::Running|RunState::CancelRequested=>BacktestReportState::Pending,
        RunState::Cancelled if !run.was_started()=>BacktestReportState::NotApplicable,
        _=>BacktestReportState::NotChecked,
    };
    Ok(BacktestRunView{schema_version:1,run_id:run.run_id().into(),strategy_fingerprint:text(&run.specification().record()["strategy_fingerprint"])?,state:status.state.as_str().into(),revision:status.revision.to_string(),accepted_at:text(&run.record()["accepted_at"])?,preparation_command_id:preparation,report_status:BacktestReportAvailability{state,code:None},worker_observation:Some(worker_observation(worker))})
}

pub(crate) fn display_result(context:&BacktestReadContext,evidence:&VerifiedEvidence)->Result<BacktestResultView,Failure>{
    context.verify_cut().map_err(failed)?;evidence.verify_cut().map_err(failed)?;
    let run=context.run();let manifest=evidence.manifest().record();
    let observation=evidence.observation();let result=evidence.result();
    let preparation=&run.resolution()["preparation"];
    if manifest["backtest_run_id"]!=run.run_id() || manifest["specification_fingerprint"]!=run.specification_fingerprint()
        || manifest["admission_resolution_fingerprint"]!=run.admission_resolution_fingerprint()
        || manifest["result_fingerprint"]!=result["result_fingerprint"] || observation["status"]!=result["run"]["status"] {return Err(failed(INVALID));}
    let summary=&observation["account_summary"];
    let metrics=serde_json::from_value(json!({
        "initial_equity":summary["initial_equity"],"final_equity":summary["final_equity"],"return_since_start":summary["return_since_start"],
        "net_pnl":summary["net_pnl"],"realized_pnl":summary["realized_pnl"],"unrealized_pnl":summary["unrealized_pnl"],
        "fees":summary["fees"],"maximum_drawdown":summary["maximum_drawdown"],"fill_count":observation["fill_count"],"roundtrip_count":observation["roundtrip_count"]
    })).map_err(|_|failed(INVALID))?;
    let curve=observation["close_curve"].as_array().ok_or_else(||failed(INVALID))?.iter().map(|v|Ok(BacktestCurvePoint{at_ns:text(&v["bar_end_ns"])?,nav:text(&v["nav"])?,drawdown:v["drawdown"].as_str().map(str::to_owned)})).collect::<Result<Vec<_>,Failure>>()?;
    let baseline=if observation["baseline"].is_null(){None}else{let b=&observation["baseline"];Some(BacktestBaseline{final_equity:text(&b["final_equity"])?,net_pnl:text(&b["net_pnl"])?,return_since_start:text(&b["return_since_start"]) ?})};
    let mut openings=BTreeMap::new();
    evidence.for_each_step(&mut |step,ready| {
        if !ready{return Err(INVALID);}
        let cause=&step["cause"];let output=&cause["processing"]["processing"];
        if cause["kind"]=="OPEN" && output["status"]=="FILLED" {
            let order=output["order"].as_str().ok_or(INVALID)?.to_owned();
            let opening=FilledOpening{trade:output["trade"].as_str().ok_or(INVALID)?.into(),
                side:output["signal"]["side"].as_str().ok_or(INVALID)?.into(),
                fee:output["economic_evidence"]["charge_target"].as_str().ok_or(INVALID)?.into(),
                signal_time:output["signal"]["signal_time"].as_str().ok_or(INVALID)?.into()};
            if openings.insert(order,opening).is_some(){return Err(INVALID);}
        }
        Ok(())
    }).map_err(failed)?;
    let fills=result["trades"].as_array().ok_or_else(||failed(INVALID))?;
    if openings.len()!=fills.len(){return Err(failed(INVALID));}
    let mut trades=Vec::with_capacity(fills.len());
    for (ordinal,fact) in fills.iter().enumerate(){
        let input=&fact["input"];let payload=&input["payload"];let order=text(&payload["order"])?;
        let opening=openings.get(&order).ok_or_else(||failed(INVALID))?;
        let side=&opening.side;
        if input["op"]!="FILL" || payload["trade"].as_str()!=Some(opening.trade.as_str()) || !matches!(side.as_str(),"BUY"|"SELL"){return Err(failed(INVALID));}
        trades.push(BacktestTradeView{ordinal:ordinal as u64+1,time_ns:number(&input["time"])?.to_string(),side:side.clone(),quantity:text(&payload["quantity"])?,price:text(&payload["price"])?,fee:opening.fee.clone(),signal_time_ns:opening.signal_time.clone(),signal:if side=="BUY"{"满足开仓条件"}else{"满足平仓条件"}.into(),order_id:order,trade_id:text(&payload["trade"])?});
    }
    let positions=result["final_positions"].as_array().ok_or_else(||failed(INVALID))?.iter().map(|value|{
        let snapshot=&value["snapshot"];
        let state=text(&snapshot["status"])?;
        let instrument=text(&value["instrument"])?;
        if instrument!="BTCUSDT.BINANCE" || !matches!(state.as_str(),"OPEN"|"CLOSED"|"RECONCILING") {return Err(failed(INVALID));}
        let average_price=if snapshot["average"].is_null(){None}else{Some(text(&snapshot["average"]) ?)};
        Ok(BacktestPositionView{instrument,quantity:text(&snapshot["quantity"])?,average_price,state})
    }).collect::<Result<Vec<_>,Failure>>()?;
    let rule_time=OnlyTimestamp::from_record(&preparation["policy_binding"]["rules_snapshot"]["captured_at"]).map_err(|_|failed(INVALID))?.to_datetime_exact().map_err(|_|failed(INVALID))?.to_string();
    let value=BacktestResultView{schema_version:1,run_id:run.run_id().into(),strategy_fingerprint:text(&manifest["strategy_fingerprint"])?,evidence_fingerprint:evidence.manifest().fingerprint().into(),result_fingerprint:text(&result["result_fingerprint"])?,determinism_fingerprint:text(&result["determinism_fingerprint"])?,state:text(&observation["status"])?,
        sample:BacktestSample{instrument:"BTCUSDT".into(),start_at:instant(&preparation["window"]["sample_start_ns"])?,end_at:instant(&preparation["window"]["sample_end_ns"])?,quantity:text(&preparation["settings"]["policy"]["quantity"]["value"])?,rule_observed_at:rule_time},metrics,curve,baseline,trades,
        positions,limitations:vec!["样本较短，仅作探索，不能据此判断长期表现。".into(),"使用当前现货交易规则建模，不代表当时交易所的实际撮合与接单。".into(),"未平仓头寸按样本末尾收盘价估值；未读取保留样本。".into()]};
    context.verify_cut().map_err(failed)?;evidence.verify_cut().map_err(failed)?;Ok(value)
}

impl Host {
    pub(crate) async fn backtest_result_owners(&self,run:&str,human:&human_access::Session)->Result<(Arc<BacktestReadContext>,VerifiedEvidence),Failure>{
        self.human_access.check_session(human)?;let owner=human.subject_id()?;
        let config=&self.research_preparation_config;
        let context={let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or_else(||failed("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
            backtest_evidence::read_context(client,self.inputs.namespace(),&config.research_root,&config.runtime_root,run,Some(owner)).await.map_err(failed)?};
        let store=backtest_evidence::Store::open(&self.backtest_root,&config.research_root,&config.runtime_root).map_err(failed)?;
        let evidence=store.read_verified(&context).map_err(failed)?.ok_or_else(||failed("BACKTEST_RESULT_NOT_READY"))?;
        self.human_access.check_session(human)?;Ok((context,evidence))
    }

    pub(crate) async fn backtest_product(self:&Arc<Self>,request:Request<Body>,human:human_access::Session,deadline:Instant)->Result<Response,Failure>{
        self.human_access.check_session(&human)?;
        if request.uri().query().is_some(){return Err(invalid());}
        let path=request.uri().path().to_owned();let method=request.method().clone();let owner=human.subject_id()?.to_owned();
        if path=="/api/v2/backtest/runs" && method==Method::GET {
            let rows={let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or_else(||failed("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
                runs::recent_snapshots(client,self.inputs.namespace(),&owner).await.map_err(failed)?};
            let worker=self.backtest_worker_status().await;
            let items=rows.into_iter().map(|(run,status)|run_view(&run,status,None,worker.clone())).collect::<Result<Vec<_>,_>>()?;
            self.human_access.check_session(&human)?;
            return Ok(ingress::attach(Json(BacktestRunInventory{schema_version:1,items}).into_response(),Release::Generation(human.metadata_session())));
        }
        let tail=path.strip_prefix("/api/v2/backtest/runs/").ok_or_else(invalid)?;
        let (id,action)=tail.split_once('/').unwrap_or((tail,""));
        if !crate::application::command::uuid4(id){return Err(invalid());}
        if Instant::now()>=deadline{return Err(failed("REQUEST_DEADLINE_EXPIRED"));}
        if method==Method::POST && action=="cancellation" {
            let (command,body)=input(request).await?;
            let body:BacktestCancellationInput=serde_json::from_value(body).map_err(|_|invalid())?;body.validate(id).map_err(failed)?;
            let (run,_)={let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or_else(||failed("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;runs::read_snapshot(client,self.inputs.namespace(),id,Some(&owner)).await.map_err(failed)?};
            let selected=&run.resolution()["source_selection"];
            let reference=Reference::new(&text(&selected["integration_id"])?,&text(&selected["revision_fingerprint"])?,selected["expected_type_id"].as_str()).map_err(|_|invalid())?;
            let selection=Selection::new(reference,&text(&selected["source_id"])?,&text(&selected["environment"]) ?).map_err(|_|invalid())?;
            let (authority,source_session)={let held=self.issuer.lock().await;(held.authority.clone(),held.session.clone())};
            let context=backtest_run::Context{human_authority:&self.human_access,human:&human,source_authority:&authority,source:&source_session,selection:&selection};
            let cancel=CancelRequest::new(command,id).map_err(failed)?;
            {let mut writer=self.writer.lock().await;let session=writer.as_mut().ok_or_else(||failed("PRODUCT_AUTHORITY_UNAVAILABLE"))?;Backtests::new(session,self.inputs.namespace()).request_cancel(&cancel,&context,now()?).await.map_err(failed)?;}
            self.wake_backtest_after_commit();
            let (run,status)={let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or_else(||failed("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;runs::read_snapshot(client,self.inputs.namespace(),id,Some(&owner)).await.map_err(failed)?};
            self.human_access.check_session(&human)?;
            return Ok(ingress::attach(Json(run_view(&run,status,None,self.backtest_worker_status().await)?).into_response(),Release::Generation(human.metadata_session())));
        }
        if method!=Method::GET{return Err(invalid());}
        if action.is_empty(){
            let (run,status)={let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or_else(||failed("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;runs::read_snapshot(client,self.inputs.namespace(),id,Some(&owner)).await.map_err(failed)?};
            let mut view=run_view(&run,status,None,self.backtest_worker_status().await)?;
            if status.state.terminal() && !(status.state==RunState::Cancelled&&!run.was_started()){
                match self.backtest_result_owners(id,&human).await {
                    Ok((context,_))=>{view.preparation_command_id=Some(context.original_operation().command.value().into());view.report_status=BacktestReportAvailability{state:BacktestReportState::Verified,code:None};},
                    Err(_)=>view.report_status=BacktestReportAvailability{state:BacktestReportState::Unavailable,code:Some(INVALID.into())},
                }
            }
            self.human_access.check_session(&human)?;
            return Ok(ingress::attach(Json(view).into_response(),Release::Generation(human.metadata_session())));
        }
        let (context,evidence)=self.backtest_result_owners(id,&human).await?;
        let response=if action=="result" {Json(display_result(&context,&evidence)?).into_response()}
            else if action=="evidence"{Json(BacktestEvidenceView{schema_version:1,run_id:id.into(),manifest:evidence.manifest().record().clone()}).into_response()}
            else if let Some(name)=action.strip_prefix("evidence/artifacts/"){
                let (bytes,media)=evidence.artifact(name).map_err(failed)?;
                Response::builder().status(StatusCode::OK).header("content-type",media).header("content-disposition","attachment").body(Body::from(bytes)).map_err(|_|failed(INVALID))?
            }else{return Err(invalid());};
        if Instant::now()>=deadline{return Err(failed("REQUEST_DEADLINE_EXPIRED"));}
        context.verify_cut().map_err(failed)?;evidence.verify_cut().map_err(failed)?;self.human_access.check_session(&human)?;
        Ok(ingress::attach(response,Release::Generation(human.metadata_session())))
    }
}

#[cfg(test)]
#[path="../../tests/transport/backtest_worker_observation.rs"]
mod worker_observation_tests;
