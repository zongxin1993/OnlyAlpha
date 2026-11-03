//! Actual preparation/Command owners on an isolated DB. No Research/UI certification.
use crate::{application::{command::CommandId,factor_content::hash,strategy_research::StrategyPrepareInput},
    persistence::{authority_session::AuthoritySession,factor_proposals::Proposals,private_factor_postgres::Factors,
        private_strategy_postgres::Strategies,research_preparation::{self,Preparations,State}},
    security::proposal_access::Presented};
use serde_json::{Value,json};
use sha2::{Digest,Sha256};
const OWNER:&str="local-developer";
const AT:&str="2026-11-01T00:00:00Z";
fn command(n:u16)->CommandId {CommandId::new(&format!("00000000-0000-4000-8000-{n:012}")).unwrap()}
pub(super) async fn setup(session:&mut AuthoritySession)->StrategyPrepareInput {
    let client=session.client_mut().await.unwrap();
    let token=format!("oa-proposal-v1.{}.{}",command(6102).value(),"a".repeat(64));
    let digest=Sha256::digest(token.as_bytes()).iter().map(|v|format!("{v:02x}")).collect::<String>();
    Proposals::new(client).grant(&command(6101),OWNER,serde_json::from_value(json!({"schema_version":1,"grant_id":command(6102).value(),"service_subject":"discovery","credential_sha256":digest,"proposal_limit":3,"expires_at":"2027-01-01T00:00:00Z"})).unwrap(),AT).await.unwrap();
    let fixture:Value=serde_json::from_str(include_str!("../fixtures/research_factor.json")).unwrap();
    let staged=Proposals::new(client).stage(&command(6103),&Presented::parse(&token).unwrap(),serde_json::from_value(json!({"schema_version":1,"origin":{"session_id":command(6104).value(),"event_fingerprint":"b".repeat(64),"result_fingerprint":"c".repeat(64),"workflow_fingerprint":"d".repeat(64),"model_revision":"e".repeat(64)},"candidate":fixture["candidate"],"expected_draft_fingerprint":null,"expected_display_fingerprint":null,"expected_proposal_fingerprint":null})).unwrap(),AT).await.unwrap();
    let proposal=staged["effect"]["proposal_fingerprint"].as_str().unwrap();
    let confirmed=Proposals::new(client).confirm(&command(6105),OWNER,proposal,AT).await.unwrap();
    let factor=confirmed["effect"]["authoring"]["factor_id"].as_str().unwrap();
    let factor_revision=Factors::new(client).publish(&command(6106),factor,confirmed["effect"]["authoring"]["result"]["draft_fingerprint"].as_str().unwrap(),AT).await.unwrap();
    let seed:Value=serde_json::from_str(include_str!("../../../../../examples/private-assets/strategy/simple_momentum/strategy.json")).unwrap();
    let calculations:Value=serde_json::from_str(include_str!("../fixtures/strategy_calculations.json")).unwrap();
    let mut definition=seed["strategy"]["definition"].clone();
    definition["universe"]=json!({"kind":"SINGLE_INSTRUMENT","instruments":["BTCUSDT.BINANCE"]});
    definition["calculations"]=calculations["instances"].clone();
    for instance in definition["calculations"].as_array_mut().unwrap() {if instance["type_reference"]["kind"]=="FACTOR" {instance["type_reference"]["type_id"]=json!(factor);}}
    definition["factor_revision_dependencies"]=json!([{"factor_id":factor,"revision_fingerprint":factor_revision["result"]["revision"]["revision_fingerprint"]}]);
    definition["signals"]["entry"]["operator"]=json!(">=");definition["signals"]["entry"]["right"]["value"]["value"]=json!("0.001");
    let id="private.strategy.use_test_preparation";
    let draft=json!({"schema_version":1,"strategy_id":id,"base_revision_fingerprint":null,"semantic_version":"1","description":"Controlled preparation precondition","tags":[],"definition":definition});
    let saved=Strategies::new(client).save(&command(6107),OWNER,id,draft,None,AT).await.unwrap();
    let published=Strategies::new(client).publish(&command(6108),OWNER,id,saved["result"]["draft_fingerprint"].as_str().unwrap(),AT).await.unwrap();
    let reference:Value=serde_json::from_str(include_str!("../fixtures/strategy_specification.json")).unwrap();
    serde_json::from_value(json!({"schema_version":1,"profile":"BTC_SPOT_STRATEGY_RESEARCH_V1","strategy_id":id,
        "strategy_revision_fingerprint":published["result"]["revision"]["revision_fingerprint"],"definition_fingerprint":published["result"]["revision"]["definition_fingerprint"],
        "context":{"schema_version":1,"start":"2025-01-02T12:00:00Z","end":"2025-01-03T00:00:00Z","targets":[{"instance_key":"forward_return","type_reference":{"kind":"TARGET","type_id":"onlyalpha.target.forward_return","semantic_version":"1"},"parameters":{"exit_offset":{"kind":"FIXED","value":{"type":"INTEGER","value":5}}},"published_outputs":["target_value"],"primary_output":null,"input_bindings":[{"input_name":"entry_price","source":"bar.close"},{"input_name":"exit_price","source":"bar.close"}]}],"statistics":[{"variable":{"kind":"VARIABLE","instance_key":"momentum","output_name":"value"},"target_instance_key":"forward_return","definition":reference["specification"]["statistics"][0]["definition"]}],"display_metadata":{}},
        "source":{"integration_id":command(6109).value(),"integration_revision_fingerprint":"f".repeat(64),"expected_type_id":"binance.spot.market_data","source_id":"binance.spot","environment":"LIVE","instrument_id":"BTCUSDT.BINANCE"},
        "factor_proposal_fingerprint":proposal,"release_manifest_fingerprint":"1".repeat(64),"expected_active_generation":null,"initialize_fresh_runtime":false,"research_command_id":command(6111).value()})).unwrap()
}
pub(super) async fn run_phase(session:&mut AuthoritySession,phase:&str) {
    let input=setup(session).await;
    let client=session.client_mut().await.unwrap();
    if phase=="reject-pins" {
        for (offset,key,value) in [(0,"definition_fingerprint",json!("2".repeat(64))),(1,"strategy_revision_fingerprint",json!("3".repeat(64))),(2,"factor_proposal_fingerprint",json!("4".repeat(64))),(3,"source",{let mut s=serde_json::to_value(&input.source).unwrap();s["instrument_id"]=json!("ETHUSDT.BINANCE");s})] {
            let mut changed=serde_json::to_value(&input).unwrap();changed[key]=value;
            assert!(Preparations::new(client).accept_strategy(&command(6120+offset),OWNER,serde_json::from_value(changed).unwrap(),AT.parse().unwrap()).await.is_err(),"{key}");
        }
        assert_eq!(client.query_one("SELECT count(*) FROM research_preparation",&[]).await.unwrap().get::<_,i64>(0),0);
        assert_eq!(client.query_one("SELECT count(*) FROM product_command_admission WHERE command_kind='PREPARE_STRATEGY_RESEARCH'",&[]).await.unwrap().get::<_,i64>(0),0);
        return;
    }
    let original=Preparations::new(client).accept_strategy(&command(6110),OWNER,input.clone(),AT.parse().unwrap()).await.unwrap();
    assert_eq!(original.state,State::Accepted);
    assert_eq!(original.view()["strategy_id"],input.strategy_id);
    assert_eq!(original.view()["profile"],input.profile);
    assert!(original.accepted.get("study").is_none(),"a Strategy preparation cannot invent a Factor Study");
    assert_eq!(original.accepted["input"],serde_json::to_value(&input).unwrap());
    assert_eq!(original.accepted["contract"],"ONLYALPHA_ACCEPTED_STRATEGY_RESEARCH_PREPARATION_V1");
    if phase=="commit-no-reply" {std::process::exit(86);}
    let replay=Preparations::new(client).existing_strategy(&command(6110),OWNER,&input).await.unwrap().unwrap();
    assert_eq!(replay.accepted,original.accepted);assert_eq!(replay.revision,0);
    assert_eq!(Preparations::new(client).for_strategy(&input.strategy_id,OWNER).await.unwrap().len(),1);
    assert!(Preparations::new(client).existing_strategy(&command(6110),"other-human",&input).await.is_err());
    let mut changed=input.clone();changed.release_manifest_fingerprint="5".repeat(64);
    assert!(Preparations::new(client).existing_strategy(&command(6110),OWNER,&changed).await.is_err());
    let mut changed=input.clone();changed.context["display_metadata"]=json!({"title":"another retained input"});
    assert!(Preparations::new(client).existing_strategy(&command(6110),OWNER,&changed).await.is_err());
    // Replaying the exact accepted Command observes history even if consent is later withdrawn.
    Proposals::new(client).withdraw(&command(6112),OWNER,&input.factor_proposal_fingerprint,AT).await.unwrap();
    assert_eq!(Preparations::new(client).accept_strategy(&command(6110),OWNER,input.clone(),AT.parse().unwrap()).await.unwrap().accepted,original.accepted);
    let mut fresh=input.clone();fresh.research_command_id=command(6114).value().into();
    assert!(Preparations::new(client).accept_strategy(&command(6113),OWNER,fresh,AT.parse().unwrap()).await.is_err(),"withdrawal cannot grant new preparation");
    if phase=="replay" {return;}
    let cancelled=Preparations::new(client).cancel(&command(6115),&command(6110),OWNER,0,AT.parse().unwrap()).await.unwrap();
    assert_eq!(cancelled.state,State::Cancelled);
    assert_eq!(Preparations::new(client).cancel(&command(6115),&command(6110),OWNER,0,AT.parse().unwrap()).await.unwrap().view(),cancelled.view());
    let tx=client.transaction().await.unwrap();
    assert!(research_preparation::guard_submission(&tx,&original,&"a".repeat(64)).await.is_err(),"cancelled preparation cannot mint a Run");
    tx.rollback().await.unwrap();
    assert_eq!(Preparations::new(client).resume(&command(6110),OWNER,cancelled.revision).await.unwrap().state,State::Cancelled);
    let kind:String=client.query_one("SELECT command_kind FROM product_command_receipt WHERE command_id=$1::text::uuid",&[&command(6115).value()]).await.unwrap().get(0);
    assert_eq!(kind,"CANCEL_STRATEGY_RESEARCH_PREPARATION");
    assert_eq!(hash(&original.accepted).unwrap(),client.query_one("SELECT accepted_fingerprint FROM research_preparation WHERE command_id=$1::text::uuid",&[&command(6110).value()]).await.unwrap().get::<_,String>(0));
}
