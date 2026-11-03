//! Read-only authoring defaults from the selected confirmed Factor and Source.
//! These values grant neither Research admission nor a frozen trading revision.
use crate::{
    application::{factor_studies::Source, private_assets, private_strategy::{Definition,Draft}, strategy_research::Context},
    persistence::{factor_proposals, factor_studies::Studies, private_strategy_postgres::Strategies, research_preparation::Preparations, research_runtime::Registry},
    security::{human_access, ingress::{self,Release}},
    transport::{host::{Host,Failure,invalid,parameters,required,now},host_factor_studies::failed},
};
use axum::{Json,body::Body,response::{IntoResponse,Response}};
use http::Request;
use onlyalpha_domain::{base::OnlyDomainModel,market::OnlyBarSemantic};
use onlyalpha_market_data_construction::OnlyConstructionRecipe;
use serde_json::json;
use std::{sync::Arc,time::Instant};

pub(crate) fn research_context()->Result<Context,&'static str> {
    let statistics=["IC","RANK_IC"].map(|method|json!({"variable":{"kind":"VARIABLE","instance_key":"momentum","output_name":"value"},"target_instance_key":"forward_return",
        "definition":{"schema_version":1,"method":method,"minimum_observations":2,"pairing_policy":"PAIRWISE_COMPLETE","universe_policy":"OBSERVED_PAIRWISE","rank_tie_method":"AVERAGE","weighting":"EQUAL","numeric":{"representation":"DECIMAL","precision":38,"output_quantum":"0.000000000001","rounding":"ROUND_HALF_EVEN"}}}));
    Context::new(json!({"schema_version":1,"start":"2025-01-02T12:00:00Z","end":"2025-01-03T00:00:00Z",
        "targets":[{"instance_key":"forward_return","type_reference":{"kind":"TARGET","type_id":"onlyalpha.target.forward_return","semantic_version":"1"},"parameters":{"exit_offset":{"kind":"FIXED","value":{"type":"INTEGER","value":5}}},"published_outputs":["target_value"],"primary_output":null,"input_bindings":[{"input_name":"entry_price","source":"bar.close"},{"input_name":"exit_price","source":"bar.close"}]}],"statistics":statistics,"display_metadata":{}}))
}
impl Host {
    pub(crate) async fn strategy_creation_context(self:&Arc<Self>,request:Request<Body>,human:&human_access::Session,deadline:Instant)->Result<Response,Failure> {
        self.human_access.check_session(human)?;
        let owner=human.subject_id()?.to_owned();
        let query=parameters(request.uri())?;
        if request.method()!=http::Method::GET || query.len()<2 || query.len()>3
            || query.keys().any(|key|!matches!(key.as_str(),"factor_proposal_fingerprint"|"study_proposal_fingerprint"|"strategy_id")) {return Err(invalid());}
        let factor_pin=required(&query,"factor_proposal_fingerprint")?;
        let study_pin=required(&query,"study_proposal_fingerprint")?;
        if !crate::is_sha256_hex(factor_pin)||!crate::is_sha256_hex(study_pin) {return Err(invalid());}
        let (confirmed,factor,source,existing,state)= {
            let mut reader=self.reader.lock().await;
            let client=reader.as_mut().ok_or(Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
            let study=Studies::new(client).read(study_pin,&owner,None,&now()?.to_string()).await.map_err(failed)?;
            if study["snapshot"]["factor_proposal_fingerprint"]!=factor_pin {return Err(invalid());}
            let source:Source=serde_json::from_value(study["snapshot"]["advice"]["source"].clone()).map_err(|_|invalid())?;
            if study["snapshot"]["advice"]["timeframe_minutes"]!=1 || source.instrument_id!="BTCUSDT.BINANCE" || source.expected_type_id!="binance.spot.market_data" {return Err(invalid());}
            let tx=client.build_transaction().isolation_level(tokio_postgres::IsolationLevel::RepeatableRead).read_only(true).start().await.map_err(|_|Failure::unavailable("STRATEGY_CONTEXT_UNAVAILABLE"))?;
            crate::persistence::postgres::bounds(&tx).await.map_err(|_|Failure::unavailable("STRATEGY_CONTEXT_UNAVAILABLE"))?;
            let confirmed=factor_proposals::confirmed_strategy_research_input(&tx,factor_pin,&owner,true).await.map_err(failed)?;
            let factor_draft=private_assets::authoring::Draft::new(confirmed["snapshot"]["preview"]["draft"].clone()).map_err(|e|failed(e.code()))?;
            let expected=factor_draft.revision().map_err(|e|failed(e.code()))?;
            let factor=private_assets::factor_revision_in_transaction(&tx,factor_draft.factor_id(),expected["revision_fingerprint"].as_str().ok_or_else(invalid)?).await.map_err(|e|failed(e.code()))?;
            if factor!=expected {return Err(Failure::unavailable("RESEARCH_FACTOR_REVISION_MISMATCH"));}
            tx.commit().await.map_err(|_|Failure::unavailable("STRATEGY_CONTEXT_UNAVAILABLE"))?;
            let (existing,state)=if let Some(id)=query.get("strategy_id") {
                let state=match Strategies::new(client).read(id).await {Ok(value)=>Some(value),Err("PRIVATE_STRATEGY_NOT_FOUND")=>None,Err(error)=>return Err(failed(error))};
                let operations=Preparations::new(client).for_strategy(id,&owner).await.map_err(failed)?;
                (operations,state)
            }else{(Vec::new(),None)};
            (confirmed,factor,source,existing,state)
        };
        // Source permission is a distinct current observation, not inherited
        // from the old Study or Factor confirmation.
        {let issuer=self.issuer.lock().await;
            issuer.authority.check_session(&issuer.session).map_err(|_|Failure::unavailable("RESEARCH_SOURCE_ACCESS_DENIED"))?;
            if issuer.session.subject_id().map_err(|_|Failure::unavailable("RESEARCH_SOURCE_ACCESS_DENIED"))?!=owner {return Err(Failure::unavailable("RESEARCH_SOURCE_ACCESS_DENIED"));}
            issuer.session.require_selection(&source.selection().map_err(failed)?,crate::application::source_access::Permission::ClosedHistory).map_err(|_|Failure::unavailable("RESEARCH_SOURCE_ACCESS_DENIED"))?;
        }
        let preview=&confirmed["snapshot"]["preview"];
        let candidate=json!({"name":preview["name"],"purpose":preview["purpose"],"hypothesis":preview["hypothesis"],"expression":preview["expression"]});
        let compiled=crate::application::research_factor::compile(&candidate,&preview["draft"],&factor).map_err(failed)?;
        let semantic=OnlyBarSemantic::from_record(&json!({"schema_version":3,"formation":{"schema_version":1,"kind":"FIXED_DURATION","window_minutes":1,"stride_minutes":1,"alignment":"SESSION_START"},"price_type":"LAST","adjustment_policy":"RAW"})).map_err(|_|invalid())?;
        let definition=Definition::from_compiled_factor(&compiled,json!({"kind":"SINGLE_INSTRUMENT","instruments":[source.instrument_id]}),json!({"schema_version":2,"data_kind":"BAR","bar_semantic":semantic.to_record(),"construction_requirement":{"schema_version":1,"kind":"EXACT_RECIPE","policy":null,"recipe":OnlyConstructionRecipe::native(semantic).to_record()},"observation_admission":"FINAL_ONLY"})).map_err(failed)?;
        let draft=if let Some(state)=state {
            let stored=Draft::new(state["draft"].clone()).map_err(failed)?;
            if stored.record()["definition"]!=definition.to_record() {return Err(Failure::unavailable("RESEARCH_PREPARATION_STRATEGY_MISMATCH"));}
            stored.record().clone()
        }else{
            let mut entropy=[0_u8;16];
            getrandom::fill(&mut entropy).map_err(|_|Failure::unavailable("STRATEGY_CONTEXT_UNAVAILABLE"))?;
            let id=query.get("strategy_id").cloned().unwrap_or_else(||format!("private.strategy.btc_momentum_{}",entropy.iter().map(|v|format!("{v:02x}")).collect::<String>()));
            Draft::new(json!({"schema_version":1,"strategy_id":id,"semantic_version":"1","base_revision_fingerprint":null,"definition":definition.to_record(),"description":"BTCUSDT 一分钟价量动量多头","tags":[]})).map_err(failed)?.record().clone()
        };
        let runtime_root=self.research_preparation_config.runtime_root.clone();
        let active=tokio::task::spawn_blocking(move||Registry::inspect(&runtime_root)).await.map_err(|_|Failure::unavailable("RESEARCH_RUNTIME_UNAVAILABLE"))?.map_err(failed)?;
        // The formatter owns the original submission outcome/readiness read and
        // takes its own reader lock. The collection lock above is already gone.
        let mut preparations=Vec::with_capacity(existing.len());
        for operation in existing {
            if Instant::now()>=deadline {return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));}
            preparations.push(self.preparation_view(&operation,human).await.map_err(|error|failed(error.code()))?);
        }
        if Instant::now()>=deadline {return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));}
        self.human_access.check_session(human)?;
        let value=json!({"schema_version":1,"factor_name":preview["name"],"formula":preview["formula"],"factor_proposal_fingerprint":factor_pin,"study_proposal_fingerprint":study_pin,
            "draft":draft,"source":source,"research_context":research_context().map_err(failed)?.record(),"release_manifest_fingerprint":self.research_preparation_config.release_manifest_fingerprint,
            "expected_active_generation":active["active_for_new_work"],"initialize_fresh_runtime":false,"existing_preparations":preparations});
        Ok(ingress::attach(Json(value).into_response(),Release::Generation(human.metadata_session())))
    }
}

impl Host {
    pub(crate) async fn strategy_workflows(self:&Arc<Self>,request:Request<Body>,human:&human_access::Session,deadline:Instant)->Result<Response,Failure> {
        self.human_access.check_session(human)?;
        if request.method()!=http::Method::GET || request.uri().query().is_some() {return Err(invalid());}
        let owner=human.subject_id()?.to_owned();
        let base="/api/v2/strategy-workflows";
        let path=request.uri().path();
        let selected=if path==base {None} else {
            let encoded=path.strip_prefix(base).and_then(|s|s.strip_prefix('/')).filter(|s|!s.is_empty()&&!s.contains('/')).ok_or_else(invalid)?;
            Some(percent_encoding::percent_decode_str(encoded).decode_utf8().map_err(|_|invalid())?.into_owned())
        };
        // Owning readers verify each actual revision and original preparation.
        // This display query never enters preparation, source selection or a writer.
        let original={
            let mut reader=self.reader.lock().await;
            let client=reader.as_mut().ok_or(Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
            let ids=if let Some(id)=selected.as_ref(){vec![id.clone()]}else{
                Strategies::new(client).list().await.map_err(failed)?["entries"].as_array().ok_or_else(invalid)?.iter()
                    .map(|v|v["strategy_id"].as_str().map(str::to_owned).ok_or_else(invalid)).collect::<Result<Vec<_>,_>>()?
            };
            let mut items=Vec::new();
            for id in ids {
                if Instant::now()>=deadline {return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));}
                let authoring=Strategies::new(client).read(&id).await.map_err(failed)?;
                let preparations=Preparations::new(client).for_strategy(&id,&owner).await.map_err(failed)?;
                let backtests=Preparations::new(client).for_strategy_backtests(&id,&owner).await.map_err(failed)?;
                items.push((id,authoring,preparations,backtests));
            }
            items
        };
        let mut items=Vec::with_capacity(original.len());let mut size=0usize;
        for (id,authoring,operations,backtests) in original {
            let mut preparations=Vec::with_capacity(operations.len());
            for operation in operations {
                if Instant::now()>=deadline {return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));}
                preparations.push(self.preparation_view(&operation,human).await.map_err(|error|failed(error.code()))?);
            }
            let mut backtest_preparations=Vec::with_capacity(backtests.len());
            for operation in backtests {
                if Instant::now()>=deadline {return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));}
                backtest_preparations.push(self.preparation_view(&operation,human).await.map_err(|error|failed(error.code()))?);
            }
            let item=json!({"schema_version":1,"strategy_id":id,"authoring":authoring,"preparations":preparations,"backtest_preparations":backtest_preparations});
            size=size.checked_add(item.to_string().len()).filter(|s|*s<=8*1024*1024).ok_or(Failure::unavailable("STRATEGY_HISTORY_UNAVAILABLE"))?;
            items.push(item);
        }
        let value=if selected.is_some(){items.pop().ok_or_else(invalid)?}else{json!({"schema_version":1,"items":items})};
        self.human_access.check_session(human)?;
        if Instant::now()>=deadline {return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));}
        Ok(ingress::attach(Json(value).into_response(),Release::Generation(human.metadata_session())))
    }
}
