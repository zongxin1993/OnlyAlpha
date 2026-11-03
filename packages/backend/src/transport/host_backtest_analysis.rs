//! A Human may send a bounded signed projection of an actual completed result
//! to the existing Agent. This does not extend its proposal service credential.
use crate::{security::{human_access,ingress::{self,Release}},transport::host::{Host,Failure,invalid}};
use axum::{Json,body::{Body,to_bytes},response::{IntoResponse,Response}};
use http::{Method,Request};
use std::time::Instant;
impl Host {
    pub(crate) async fn backtest_analysis_context(&self,request:Request<Body>,human:human_access::Session,deadline:Instant)->Result<Response,Failure> {
        self.human_access.check_session(&human)?;
        if request.method()!=Method::POST||request.uri().query().is_some(){return Err(invalid());}
        let path=request.uri().path().to_owned();
        let id=path.strip_prefix("/api/v2/backtest/runs/").and_then(|s|s.strip_suffix("/analysis-context")).ok_or_else(invalid)?;
        if !crate::application::command::uuid4(id){return Err(invalid());}
        let body=to_bytes(request.into_body(),16).await.map_err(|_|invalid())?;
        if !body.is_empty() {
            let value:serde_json::Value=serde_json::from_slice(&body).map_err(|_|invalid())?;
            if value.as_object().is_none_or(|m|!m.is_empty()){return Err(invalid());}
        }
        if Instant::now()>=deadline{return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));}
        let (context,evidence)=self.backtest_result_owners(id,&human).await?;
        let issuer=self.agent_browser.as_ref().ok_or(Failure::unavailable("AGENT_BROWSER_NOT_CONFIGURED"))?;
        let at=std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_err(|_|Failure::unavailable("CLOCK_UNAVAILABLE"))?.as_secs();
        let value=issuer.backtest_analysis(&context,&evidence,human.subject_id()?,at).map_err(Failure::unavailable)?;
        if Instant::now()>=deadline{return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));}
        context.verify_cut().map_err(Failure::unavailable)?;evidence.verify_cut().map_err(Failure::unavailable)?;
        self.human_access.check_session(&human)?;
        let mut response=ingress::attach(Json(value).into_response(),Release::Generation(human.metadata_session()));
        response.headers_mut().insert("cache-control",http::HeaderValue::from_static("no-store"));Ok(response)
    }
}
