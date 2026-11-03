//! Controlled technical composition: no actual market, Freeze publication or Product Run grant.
use super::{DEADLINE, fixture, product_setup};
use onlyalpha_backend::workers::{backtest::{PreparedNextOpen, terminal_policy}, backtest_result::ObservedBacktest, trading_nodes::InstalledTradingNodes};
use onlyalpha_backtest::{Inputs, MarketInput, RunLoop, RunSpec, Source, Trading};
use onlyalpha_calculation_bridge::{ChartInstallation, StrategyPreparation, fingerprint};
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, numeric::OnlyDecimal, time::{OnlyTimestamp, OnlyUtcDateTime}};
use onlyalpha_market_data_pipeline::{construction::*, delivery::*, state::*, *};
use onlyalpha_plugin_binance::{spot_simulation::SpotRuleSnapshot, spot_source::spot_calendar};
use onlyalpha_strategy::Executor;
use serde_json::{Value, json};
use std::{error::Error, path::Path, sync::Arc};
const BAR_NS: i64 = 60_000_000_000;
type NativeRun = RunLoop<Trading<InstalledTradingNodes>>;
type Result<T> = std::result::Result<T, Box<dyn Error>>;
fn at(value: &str) -> Result<OnlyTimestamp> {
    Ok(OnlyTimestamp::from_datetime(value.parse::<OnlyUtcDateTime>()?))
}
fn rules() -> Result<SpotRuleSnapshot> {
    // A dated controlled snapshot, not historical or current venue-rule certification.
    let raw=json!({"symbol":"BTCUSDT","baseAsset":"BTC","quoteAsset":"USDT","status":"TRADING","isSpotTradingAllowed":true,"orderTypes":["LIMIT","MARKET"],"baseAssetPrecision":8,"quoteAssetPrecision":8,"baseCommissionPrecision":8,"quoteCommissionPrecision":8,"filters":[
        {"filterType":"PRICE_FILTER","minPrice":"0.01000000","maxPrice":"1000000.00000000","tickSize":"0.01000000"},
        {"filterType":"LOT_SIZE","minQty":"0.00001000","maxQty":"9000.00000000","stepSize":"0.00001000"},
        {"filterType":"MARKET_LOT_SIZE","minQty":"0.00000000","maxQty":"100.00000000","stepSize":"0.00000000"},
        {"filterType":"NOTIONAL","minNotional":"5.00000000","applyMinToMarket":true,"maxNotional":"9000000.00000000","applyMaxToMarket":false,"avgPriceMins":5}]});
    Ok(SpotRuleSnapshot::capture(raw,at("2026-11-01T00:00:00Z")?,"controlled-native-composition")?)
}
fn inputs(base: &Value, source: &str) -> Result<Inputs> {
    let initial=at("2025-01-02T23:40:00Z")?.to_unix_nanos();
    let mut rows=Vec::new();
    for index in 0..740 {
        // The next opening is distinct from both the prior and its own closing price.
        let (open,close):(u64,u64)=match index {0..=19=>(100000,100000),20=>(100000,100200),21=>(100100,99900),22=>(99800,99700),739=>(99700,100000),_=>(99700,99700)};
        let mut row=base.clone();
        for (name,value) in [("open",open),("high",open.max(close)),("low",open.min(close)),("close",close)] {
            row[name]=json!({"schema_version":1,"value":format!("{value}.00"),"precision":2});
        }
        row["volume"]=json!({"schema_version":1,"value":"100.00000","precision":5});
        let start=OnlyTimestamp::from_unix_nanos(&initial+index as i64*BAR_NS).to_datetime_exact()?;
        let end=OnlyTimestamp::from_unix_nanos(&initial+(index as i64+1)*BAR_NS).to_datetime_exact()?;
        row["bar_start"]=json!(start.to_string());
        for key in ["bar_end","ts_event","ts_init"] { row[key]=json!(end.to_string()); }
        row["trading_day"]=json!(start.date().to_string());row["session_type"]=json!("CONTINUOUS");
        rows.push(MarketInput::new(source,index+1,"controlled-native-v1",OnlyBar::from_record(&row)?)?);
    }
    Ok(Inputs::new(vec![Source::new(source,&"d".repeat(64),&"e".repeat(64),"controlled-native-v1",0,740)?],rows)?)
}
fn composition(case: &Value, installation: Arc<ChartInstallation>, artifact: &str) -> Result<(RunSpec,Inputs,Trading<InstalledTradingNodes>,PreparedNextOpen)> {
    let (source,program,definitions)=product_setup(case,artifact)?;
    let scope=program.scope().clone();
    let cfg=json!({"schema_version":2,"account_checkpoint_version":5,"engine":scope.engine.value(),"runtime":scope.runtime.value(),"account":"technical-account","gateway":"technical-gateway","generation":program.generation(),"runtime_kind":"BACKTEST","currency":{"schema_version":1,"code":"USDT","precision":8,"currency_type":"CRYPTO"},"initial_cash":"10000.00000000","capitals":{(scope.cluster.value()):"10000.00000000"},"profiles":{(scope.cluster.value()):{"schema_version":1,"revision":source.fingerprint(),"instruments":["BTCUSDT.BINANCE"],"rules":[]}},"instruments":[{"schema_version":1,"id":"BTCUSDT.BINANCE","price_precision":2,"quantity_precision":5,"multiplier":"1"}]});
    let pinned=inputs(&case["base"],program.source())?;
    let prepared=PreparedNextOpen::new(source,pinned,rules()?,cfg,at("2025-01-03T00:00:00Z")?,at("2025-01-03T12:00:00Z")?)?;
    assert_eq!(prepared.record()["strategy_fingerprint"],program.revision().fingerprint());
    let input=prepared.inputs().clone();
    let cfg=prepared.configuration().clone();
    let initial_ns=prepared.initial_ns().clone();
    let kernel=fingerprint(&std::fs::read(std::env::current_exe()?)?);
    let kind=input.records()[0].bar().bar_type().clone();
    let graph=OnlyConstructionGraph::new(vec![OnlyConstructionInput::Bar(kind.clone())],vec![])?;
    let calendar=spot_calendar()?;
    assert_eq!(calendar.to_record()["calendar_id"]["value"],"BINANCE-SPOT-24X7");
    for day in ["2025-01-02","2025-01-03"] {
        let day=onlyalpha_domain::time::OnlyTradingDay::from_record(&json!({"schema_version":1,"value":day}))?;
        assert!(calendar.is_effective_on(day));assert!(calendar.is_trading_day(day));
    }
    let pipeline=PipelineProgram::new(
        OnlyMarketDataStateScope::new(scope.engine,scope.runtime),program.generation(),128,
        vec![SourceProgram::new(program.source(),Arc::new(calendar),Arc::new(OnlyConstructionRegistry::default()),&kernel,graph.clone())?],
        vec![ClusterProgram{cluster:scope.cluster,subscription:OnlyBarSubscription::new("technical-native-strategy",vec![kind.clone()],graph,Some(kind),OnlyBarFreshness::LatestClosed)?}],vec![],&kernel,
    )?;
    let nodes=InstalledTradingNodes::new(installation,program.clone(),definitions,case["sources"].as_array().ok_or("sources")?.clone(),Arc::new(()),DEADLINE)?;
    let preparation=StrategyPreparation::new(pipeline,Executor::new(program,nodes)?)?;
    let participants=prepared.clone().into_participants(preparation)?;
    Ok((RunSpec{work_id:"technical-native-next-open".into(),configuration:cfg,kernel_artifact:kernel.clone(),driver_artifact:kernel,initial_ns},input,participants,prepared))
}
fn execution_inputs(trace: &Value) -> Vec<&Value> {
    trace["steps"].as_array().unwrap().iter().flat_map(|row|row["step"]["inputs"].as_array().unwrap()).collect()
}
fn fills(trace: &Value) -> Vec<&Value> {
    execution_inputs(trace).into_iter().filter(|row|row["op"]=="FILL").collect()
}
fn decimal(value: &Value) -> OnlyDecimal { value.as_str().unwrap().parse().unwrap() }
#[test]
fn installed_source_to_native_next_open_kernel_and_durable_recovery() -> Result<()> {
    let case=fixture()?;
    let artifact=std::env::var("ONLYALPHA_TRADING_TEST_ARTIFACT")?;
    let installation=Arc::new(ChartInstallation::open(Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?),&artifact)?);
    let root=std::env::temp_dir().join(format!("oa-installed-next-open-{}",std::process::id()));
    std::fs::create_dir(&root)?;
    let (spec,input,participants,_)=composition(&case,installation.clone(),&artifact)?;
    let durable_configuration=spec.configuration.clone();let durable_artifact=spec.kernel_artifact.clone();
    let mut run=RunLoop::create(&root,spec,input,participants)?;
    for _ in 0..40 { assert!(run.step()?); }
    let warm=run.trace()?;
    assert_eq!(warm["state"]["cursor"],20);assert_eq!(warm["state"]["phase"],"OPEN");
    assert!(fills(&warm).is_empty());
    assert_eq!(decimal(&run.state()?["account"]["snapshot"]["cash"]),"10000".parse()?);
    assert_eq!(run.state()?["execution"]["orders"].as_object().unwrap().len(),0);
    drop(warm);
    assert!(run.step()?); // first sample OPEN
    assert!(run.step()?); // actual SDK factor and native Predicate decision at first sample CLOSE
    let before=run.trace()?;
    let prior_preparation=before["state"]["participants"]["preparation"].clone();
    assert_eq!(before["state"]["participants"]["native"]["pending"]["side"],"BUY");
    assert_eq!(before["steps"][41]["step"]["cause"]["processing"]["processing"]["preparation"]["decisions"][0]["decision"]["entry"],true);
    assert!(fills(&before).is_empty());
    // An explicit deterministic failure after the complete opening step is durably Ready.
    let error=run.step_observed(&mut |phase,index,_| {
        if phase=="STEP_READY" && index==43 {Err(onlyalpha_backtest::Error("CONTROLLED_AFTER_OPEN".into()))} else {Ok(())}
    }).unwrap_err();
    assert_eq!(error.0,"CONTROLLED_AFTER_OPEN");
    drop(run);
    assert!(root.join("runtime.sqlite3").is_file());
    let (spec,input,participants,prepared)=composition(&case,installation,&artifact)?;
    let readonly_spec=spec.clone();let readonly_inputs=input.clone();
    let mut run:NativeRun=RunLoop::open(&root,spec,input,participants)?;
    assert!(ObservedBacktest::observe(&prepared,&run).is_err(),"running output cannot be published as a final observation");
    let opened=run.trace()?;
    assert_eq!(opened["state"]["cursor"],21);assert_eq!(opened["state"]["phase"],"CLOSE");
    assert_eq!(opened["state"]["clock_ns"],at("2025-01-03T00:01:00Z")?.to_unix_nanos().to_string());
    assert_eq!(opened["state"]["participants"]["preparation"],prior_preparation,"OPEN cannot expose the next closed HLCV to Strategy");
    assert_eq!(&opened["steps"].as_array().unwrap()[..42],before["steps"].as_array().unwrap());
    drop(before);drop(prior_preparation);
    let bought=fills(&opened);assert_eq!(bought.len(),1);
    assert_eq!(bought[0]["payload"]["price"],"100120.020000");assert_eq!(bought[0]["payload"]["price_precision"],6);
    assert_eq!(bought[0]["time"],at("2025-01-03T00:01:00Z")?.to_record()["unix_nanos"]);
    assert_eq!(decimal(&run.state()?["position"]["accounts"][0]["snapshot"]["quantity"]),"0.01".parse()?);
    drop(bought);drop(opened);
    assert!(run.step()?); // next closed bar is processed exactly once after recovered OPEN
    let closed=run.trace()?;
    assert_eq!(closed["state"]["cursor"],22);assert_eq!(closed["state"]["phase"],"OPEN");
    assert_eq!(fills(&closed).len(),1);
    assert_eq!(closed["state"]["participants"]["native"]["pending"]["side"],"SELL");
    drop(closed);
    assert!(run.step()?); // causal exit at the following opening
    let sold=run.trace()?;let trades=fills(&sold);assert_eq!(trades.len(),2);
    assert_eq!(trades[1]["payload"]["price"],"99780.040000");assert_eq!(trades[1]["payload"]["price_precision"],6);
    assert_eq!(trades[1]["time"],at("2025-01-03T00:02:00Z")?.to_record()["unix_nanos"]);
    drop(trades);drop(sold);
    run.run()?;
    let exhausted=run.trace_metadata()?;
    assert_eq!(exhausted["state"]["cursor"],740);assert_eq!(exhausted["state"]["clock_ns"],at("2025-01-03T12:00:00Z")?.to_unix_nanos().to_string());
    assert_eq!(exhausted["state"]["participants"]["native"]["pending"]["side"],"BUY");
    let mut fill_count=0;
    run.for_each_step(&mut |step,ready|{assert!(ready);fill_count+=step["inputs"].as_array().unwrap().iter().filter(|input|input["op"]=="FILL").count();Ok(())})?;
    assert_eq!(fill_count,2);drop(exhausted);
    run.close_input()?;
    let mut last=Value::Null;let mut admits=0;let mut cancels=0;
    run.for_each_step(&mut |step,ready|{
        assert!(ready);
        // Keep only the original stop fields needed by these assertions.
        last=json!({"cause":step["cause"],"input_finished":step["state"]["input_finished"],"pending":step["state"]["participants"]["native"]["pending"]});
        let inputs=step["inputs"].as_array().unwrap();
        admits+=inputs.iter().filter(|input|input["op"]=="ADMIT").count();
        cancels+=inputs.iter().filter(|input|input["op"]=="CANCEL").count();Ok(())
    })?;
    assert_eq!(last["cause"]["kind"],"INPUT_END");
    assert_eq!(last["cause"]["processing"]["signal"]["status"],"CANCELLED");
    assert_eq!(last["cause"]["processing"]["signal"]["reason"],"INPUT_EXHAUSTED");
    assert_eq!(last["input_finished"],true);assert!(last["pending"].is_null());
    assert_eq!(admits,2,"the final unsent signal must create no Order");assert_eq!(cancels,0);
    let mut events=Vec::new();run.deliver(|event| {events.push(event["event_id"].clone());Ok(())})?;
    let unique=events.iter().map(Value::to_string).collect::<std::collections::BTreeSet<_>>();assert_eq!(events.len(),unique.len());
    run.finish_input()?;
    let result=run.result()?;
    assert_eq!(result["execution_result"]["run"]["status"],"COMPLETED");
    assert_eq!(decimal(&result["execution_result"]["final_account"]["cash"]),"9994.60119940".parse()?);
    assert_eq!(decimal(&result["execution_result"]["final_account"]["fees"]),"1.99900060".parse()?);
    assert_eq!(decimal(&run.state()?["position"]["accounts"][0]["snapshot"]["quantity"]),"0".parse()?);
    assert_eq!(result["execution_result"]["trades"].as_array().unwrap().len(),2);
    let observed=ObservedBacktest::observe(&prepared,&run)?;
    assert_eq!(observed.result(),&result["execution_result"]);
    assert_eq!(observed.proof(),&result);
    assert_eq!(observed.trace(),&run.encoded_trace()?);
    assert_eq!(observed.preparation(),&prepared.record());
    let body=observed.record();
    assert_eq!(body["status"],"COMPLETED");assert_eq!(body["sample_bar_count"],720);
    assert_eq!(body["account_summary"],result["execution_result"]["runtime_performance"]["summary"]);
    assert_eq!(body["fill_count"],2);assert_eq!(body["roundtrip_count"],1,"CLUSTER closed cycle counted once; no ACCOUNT duplication or fills/2 heuristic");
    assert_eq!(body["final_positions"],result["execution_result"]["final_positions"]);
    let curve=body["close_curve"].as_array().ok_or("close curve")?;
    assert_eq!(curve.len(),720);
    assert_eq!(curve[0]["bar_start_ns"],at("2025-01-03T00:00:00Z")?.to_unix_nanos().to_string());
    assert_eq!(curve[719]["bar_end_ns"],at("2025-01-03T12:00:00Z")?.to_unix_nanos().to_string());
    assert_eq!(decimal(&curve[0]["nav"]),"10000".parse()?);
    assert_eq!(decimal(&curve[1]["nav"]),"9996.79859980".parse()?,"00:02 close cannot see the following 00:02 opening exit");
    assert_eq!(decimal(&curve[1]["drawdown"]),"-0.00032014".parse()?);
    assert_eq!(decimal(&curve[2]["nav"]),"9994.60119940".parse()?);
    assert_eq!(decimal(&curve[2]["drawdown"]),"-0.00053988".parse()?);
    let trace=run.trace_metadata()?;
    let pipeline_program=fingerprint(trace["binding"]["participants"]["pipeline"].to_string().as_bytes());
    let strategy_program=fingerprint(trace["binding"]["participants"]["program"].to_string().as_bytes());
    let verify_program=|state:&Value|{
        let preparation=&state["participants"]["preparation"];
        for (owner,version,program) in [("pipeline",3,&pipeline_program),("strategy",2,&strategy_program)] {
            assert_eq!(preparation[owner]["schema_version"],version);
            assert!(preparation[owner].get("program").is_none());
            assert_eq!(preparation[owner]["program_fingerprint"],*program);
        }
    };
    verify_program(&trace["binding"]["initial_state"]);
    let mut bars=0;let mut points=0;
    run.for_each_step(&mut |step,ready|{
        assert!(ready);verify_program(&step["state"]);
        if step["cause"]["kind"]=="BAR" {
            if bars>=20 {
                let point=curve.get(points).expect("each original sample close has a projected point");
                assert_eq!(point["execution_prefix"],step["execution_start"].as_u64().unwrap()+step["inputs"].as_array().unwrap().len() as u64);points+=1;
            }
            bars+=1;
        }Ok(())
    })?;
    assert_eq!(bars,740);assert_eq!(points,curve.len());drop(trace);
    assert_eq!(decimal(&curve[719]["drawdown"]),decimal(&body["account_summary"]["maximum_drawdown"]));
    let baseline=&body["baseline"];
    assert_eq!(baseline["kind"],"ANALYTICAL_ESTIMATE");
    assert_eq!(decimal(&baseline["entry_price"]["value"]),"100020".parse()?);
    assert_eq!(baseline["entry_price"]["precision"],6);
    assert_eq!(decimal(&baseline["quantity"]["value"]),"0.01".parse()?);
    assert_eq!(decimal(&baseline["entry_fee_quote"]["charges"]["amount"]),"1.00020000".parse()?);
    assert_eq!(baseline["entry_fee_quote"]["reference_policy"],"MODEL_NEXT_OPEN");
    assert_eq!(baseline["entry_fee_quote"]["venue_acceptance_proven"],false);
    assert_eq!(baseline["entry_fee_quote"]["rules_fingerprint"],prepared.record()["policy_binding"]["rules_fingerprint"]);
    assert_eq!(decimal(&baseline["final_equity"]),"9998.79980000".parse()?);
    assert_eq!(decimal(&baseline["net_pnl"]),"-1.20020000".parse()?);
    assert_eq!(decimal(&baseline["unrealized_pnl"]),"-0.20000000".parse()?);
    assert_eq!(decimal(&baseline["return_since_start"]),"-0.00012002".parse()?);
    assert!(baseline.get("order").is_none());assert!(baseline.get("trade").is_none());
    // A test-only unlinked spool preserves literal original bodies without
    // retaining the entire logical history or touching the journal directory.
    use std::io::{BufRead,Seek,Write};
    let spool_path=root.with_extension("original-steps.jsonl");
    let mut spool=std::fs::OpenOptions::new().read(true).write(true).create_new(true).open(&spool_path)?;
    std::fs::remove_file(spool_path)?; // The open descriptor is released on every exit, including panic.
    let mut final_step_count=0;let mut final_fills=0;
    {
        let mut writer=std::io::BufWriter::new(&mut spool);
        run.for_each_step(&mut |step,ready|{
            assert!(ready);final_step_count+=1;
            let output=|error:std::io::Error|onlyalpha_backtest::Error(error.to_string());
            writer.write_all(if ready{b"{\"ready\":true,\"step\":"}else{b"{\"ready\":false,\"step\":"}).map_err(output)?;
            serde_json::to_writer(&mut writer,step).map_err(|error|onlyalpha_backtest::Error(error.to_string()))?;
            writer.write_all(b"}\n").map_err(output)?;
            final_fills+=step["inputs"].as_array().unwrap().iter().filter(|input|input["op"]=="FILL").count();Ok(())
        })?;writer.flush()?;
    }
    assert_eq!(final_fills,2,"analytical baseline adds no Kernel facts");
    drop(observed);
    // A valid but different input pin is a value, never authority to relabel this journal.
    let (source,program,_)=product_setup(&case,&artifact)?;
    let mut foreign=prepared.inputs().record();foreign["sources"][0]["snapshot"]=json!("f".repeat(64));
    let foreign=PreparedNextOpen::new(source,Inputs::from_record(&foreign)?,rules()?,prepared.configuration().clone(),at("2025-01-03T00:00:00Z")?,at("2025-01-03T12:00:00Z")?)?;
    assert_eq!(foreign.record()["strategy_fingerprint"],program.revision().fingerprint());
    assert!(ObservedBacktest::observe(&foreign,&run).is_err());
    let final_trace=run.encoded_trace()?;let final_state=run.state()?;let final_proof=run.result()?;
    drop(run);
    let before=journal_cut(&root);
    let snapshot=onlyalpha_backtest::TerminalSnapshot::read(&root,readonly_spec,&readonly_inputs,terminal_policy)?;
    snapshot.verify_cut()?;snapshot.verify_encoded_trace(&final_trace)?;assert_eq!(snapshot.trace(),&final_trace);assert_eq!(snapshot.proof(),&final_proof);assert_eq!(snapshot.state(),&final_state);
    spool.rewind()?;let mut original=std::io::BufReader::new(&mut spool);let mut terminal_steps=0;
    snapshot.for_each_step(&mut |step,ready|{assert_original_step(&mut original,step,ready)?;terminal_steps+=1;Ok(())})?;
    assert_eq!(terminal_steps,final_step_count);assert!(original.fill_buf()?.is_empty());drop(original);
    assert_eq!(snapshot.result(),&final_proof["execution_result"]);assert_eq!(journal_cut(&root),before);drop(snapshot);
    // Read the same SQLite-owned end boundary without creating a second replay or book.
    let runtime=onlyalpha_runtime_persistence::Runtime::open(&root,durable_configuration,&durable_artifact)?;
    let refs=runtime.replay_refs()?;assert_eq!(refs.len(),final_step_count);
    spool.rewind()?;let mut original=std::io::BufReader::new(&mut spool);
    for reference in &refs {
        let step=runtime.read_replay_step(reference)?;assert_original_step(&mut original,&step,reference.ready())?;
    }
    assert!(original.fill_buf()?.is_empty());drop(original);
    runtime.verify_replay_refs(&refs)?;assert_eq!(runtime.state()?,final_state);
    drop(runtime);storage_measurements(&root,&final_trace)?;
    std::fs::remove_dir_all(root)?;
    Ok(())
}

#[test]
fn cancelled_native_prefix_observes_actual_holdings_without_a_full_interval_baseline() -> Result<()> {
    let case=fixture()?;
    let artifact=std::env::var("ONLYALPHA_TRADING_TEST_ARTIFACT")?;
    let installation=Arc::new(ChartInstallation::open(Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?),&artifact)?);
    let root=std::env::temp_dir().join(format!("oa-installed-next-open-cancel-{}",std::process::id()));
    std::fs::create_dir(&root)?;
    let (spec,input,participants,prepared)=composition(&case,installation,&artifact)?;
    let mut run=RunLoop::create(&root,spec,input,participants)?;
    for _ in 0..44 { assert!(run.step()?); }
    let before=run.trace()?;
    assert_eq!(before["state"]["cursor"],22);
    assert_eq!(before["state"]["participants"]["native"]["pending"]["side"],"SELL");
    assert_eq!(fills(&before).len(),1);
    let economic=run.state()?;
    run.cancel_input()?;
    assert_eq!(run.state()?,economic,"a pending signal is not an admitted Order");
    run.deliver(|_|Ok(()))?;
    run.terminate("CANCELLED",Some("USER_CANCELLED"))?;
    let observed=ObservedBacktest::observe(&prepared,&run)?;
    let body=observed.record();
    assert_eq!(body["status"],"CANCELLED");assert_eq!(body["sample_bar_count"],2);
    assert_eq!(observed.proof()["drained"],true);assert_eq!(observed.proof()["market_exhausted"],false);
    assert_eq!(body["fill_count"],1);assert_eq!(body["roundtrip_count"],0);
    assert_eq!(decimal(&body["account_summary"]["final_equity"]),"9996.79859980".parse()?);
    assert_eq!(decimal(&body["account_summary"]["unrealized_pnl"]),"-2.20020000".parse()?);
    assert_eq!(decimal(&body["account_summary"]["fees"]),"1.00120020".parse()?);
    assert!(body["baseline"].is_null(),"a cancelled prefix cannot report the unobserved final close of the full sample");
    assert_eq!(body["close_curve"].as_array().unwrap().len(),2);
    assert_eq!(body["close_curve"][1]["bar_end_ns"],at("2025-01-03T00:02:00Z")?.to_unix_nanos().to_string());
    assert_eq!(body["final_positions"],observed.result()["final_positions"]);
    assert_eq!(decimal(&body["final_positions"][0]["snapshot"]["quantity"]),"0.01".parse()?);
    let mut fills=0;let mut cancels=0;
    run.for_each_step(&mut |step,ready|{
        assert!(ready);let inputs=step["inputs"].as_array().unwrap();
        fills+=inputs.iter().filter(|input|input["op"]=="FILL").count();
        cancels+=inputs.iter().filter(|input|input["op"]=="CANCEL").count();Ok(())
    })?;
    assert_eq!(fills,1);assert_eq!(cancels,0);assert_eq!(observed.trace(),&run.encoded_trace()?);
    drop(run);std::fs::remove_dir_all(root)?;Ok(())
}


// The wrapper adds fewer than 32 bytes to the existing 8 MiB Step bound.
// Take limits read_line before allocation; truncation/oversize cannot consume
// unbounded spool input or silently skip another original body.
fn assert_original_step(reader:&mut impl std::io::BufRead,step:&Value,ready:bool)->std::result::Result<(),onlyalpha_backtest::Error> {
    use std::io::{BufRead,Read};
    const ROW_BOUND:usize=8*1024*1024+32;
    let mut line=String::new();
    let size=reader.take((ROW_BOUND+1) as u64).read_line(&mut line).map_err(|error|onlyalpha_backtest::Error(error.to_string()))?;
    assert!(size>0&&size<=ROW_BOUND&&line.ends_with('\n'),"one complete bounded original Step is required");
    let original:Value=serde_json::from_str(&line).map_err(|error|onlyalpha_backtest::Error(error.to_string()))?;
    assert_eq!(original.as_object().unwrap().len(),2);assert_eq!(original["ready"],ready);
    assert_eq!(&original["step"],step,"the complete original Step Value must match, not only its digest or metadata");Ok(())
}

fn storage_measurements(root:&Path,trace:&Value)->Result<()> {
    struct Count(u64);
    impl std::io::Write for Count {
        fn write(&mut self,raw:&[u8])->std::io::Result<usize>{self.0+=raw.len() as u64;Ok(raw.len())}
        fn flush(&mut self)->std::io::Result<()>{Ok(())}
    }
    let mut bytes=Count(0);serde_json::to_writer(&mut bytes,trace)?;
    let python=Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?).join("bin/python");
    let output=std::process::Command::new(python).args(["-B","-I","-c",r#"
import json,sqlite3,sys
connection=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)
assert connection.execute('PRAGMA user_version').fetchone()[0]==4
result={}
for table,prefix in [('replay_steps','step'),('records','prepared')]:
    sizes=[json.loads(raw)['logical_size'] for (raw,) in connection.execute('SELECT payload FROM '+table)]
    result[prefix+'_count']=len(sizes);result[prefix+'_max_logical_bytes']=max(sizes,default=0)
    result[prefix+'_stored_bytes']=connection.execute('SELECT COALESCE(sum(length(CAST(payload AS BLOB))),0) FROM '+table).fetchone()[0]
print(json.dumps(result,sort_keys=True,separators=(',',':')));connection.close()
"#]).arg(root.join("runtime.sqlite3")).output()?;
    assert!(output.status.success(),"controlled read-only storage measurement failed");
    let mut measured:Value=serde_json::from_slice(&output.stdout)?;
    measured["trace_stored_bytes"]=json!(bytes.0);
    let peak=std::fs::read_to_string("/proc/self/status").ok().and_then(|status|status.lines().find(|line|line.starts_with("VmHWM:")).and_then(|line|line.split_whitespace().nth(1)).and_then(|value|value.parse::<u64>().ok()));
    measured["process_peak_rss_kib"]=json!(peak);
    eprintln!("NATIVE_REPLAY_STORAGE_MEASURE {measured}");Ok(())
}

fn journal_cut(root:&Path)->std::collections::BTreeMap<String,(u64,Vec<u8>)> {
    use std::os::unix::fs::MetadataExt;
    let mut result=std::collections::BTreeMap::new();
    for entry in std::fs::read_dir(root).unwrap(){let entry=entry.unwrap();let metadata=entry.metadata().unwrap();assert!(metadata.is_file());result.insert(entry.file_name().into_string().unwrap(),(metadata.ino(),std::fs::read(entry.path()).unwrap()));}
    result
}
fn journal_fault(root:&Path,mutation:u8) {
    let python=Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION").unwrap()).join("bin/python");
    let status=std::process::Command::new(python).args(["-B","-I","-c",r#"
import base64,hashlib,json,sqlite3,sys,zlib
connection=sqlite3.connect(sys.argv[1]);mutation=int(sys.argv[2])
def encode(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(v): return hashlib.sha256(encode(v).encode()).hexdigest()
assert connection.execute('PRAGMA user_version').fetchone()[0]==4
import ctypes,ctypes.util
lib=ctypes.CDLL(ctypes.util.find_library('zstd'))
lib.ZSTD_createCCtx.restype=ctypes.c_void_p;lib.ZSTD_createDCtx.restype=ctypes.c_void_p
lib.ZSTD_compressBound.argtypes=[ctypes.c_size_t];lib.ZSTD_compressBound.restype=ctypes.c_size_t
lib.ZSTD_compress_usingDict.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int];lib.ZSTD_compress_usingDict.restype=ctypes.c_size_t
lib.ZSTD_decompress_usingDict.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t];lib.ZSTD_decompress_usingDict.restype=ctypes.c_size_t
lib.ZSTD_isError.argtypes=[ctypes.c_size_t];lib.ZSTD_isError.restype=ctypes.c_uint
compression=lib.ZSTD_createCCtx();decompression=lib.ZSTD_createDCtx()
originals=dict(connection.execute('SELECT sequence,payload FROM replay_steps ORDER BY sequence').fetchall())
old_anchors={};new_anchors={}
def unpack(frame,dictionary):
    compressed=base64.b64decode(frame['data'],validate=True);bound=frame['logical_size'];assert 0<=bound<=8*1024*1024
    if frame['codec']=='ZLIB_CANONICAL_JSON_V1':return zlib.decompress(compressed)
    assert frame['codec']=='ZSTD_CANONICAL_JSON_DICTIONARY_V1'
    output=ctypes.create_string_buffer(bound+1)
    size=lib.ZSTD_decompress_usingDict(decompression,output,bound+1,compressed,len(compressed),dictionary,len(dictionary))
    assert not lib.ZSTD_isError(size) and size==bound
    return output.raw[:size]
def old_anchor(index):
    if index not in old_anchors:
        raw=originals[index];frame=json.loads(raw);assert frame['basis'] is None
        payload=unpack(frame,b'');assert hashlib.sha256(payload).hexdigest()==frame['logical_sha256']
        old_anchors[index]=(payload,hashlib.sha256(raw.encode()).hexdigest(),frame['logical_sha256'])
    return old_anchors[index]
def read_step(raw,updated=False):
    frame=json.loads(raw);dictionary=b''
    if frame['codec']=='ZSTD_CANONICAL_JSON_DICTIONARY_V1' and frame['basis'] is not None:
        basis=frame['basis'];index=basis['sequence']
        payload,physical,logical=new_anchors[index] if updated and index in new_anchors else old_anchor(index)
        assert basis['physical_sha256']==physical and basis['logical_sha256']==logical
        dictionary=payload
    payload=unpack(frame,dictionary)
    assert len(payload)==frame['logical_size']<=8*1024*1024
    assert hashlib.sha256(payload).hexdigest()==frame['logical_sha256']
    step=json.loads(payload);assert encode(step).encode()==payload
    return frame,step
def reseal(frame,step):
    payload=encode(step).encode();assert len(payload)<=8*1024*1024
    logical=hashlib.sha256(payload).hexdigest()
    if frame['codec']=='ZSTD_CANONICAL_JSON_DICTIONARY_V1':
        index=step['index'];base=(index-1)//16*16+1
        if index==base:dictionary=b'';basis=None
        else:
            dictionary,physical,base_logical=new_anchors[base] if base in new_anchors else old_anchor(base)
            basis={'sequence':base,'physical_sha256':physical,'logical_sha256':base_logical}
        output=ctypes.create_string_buffer(lib.ZSTD_compressBound(len(payload)))
        size=lib.ZSTD_compress_usingDict(compression,output,len(output),payload,len(payload),dictionary,len(dictionary),1)
        assert not lib.ZSTD_isError(size)
        compressed=output.raw[:size];frame['basis']=basis
    else:
        assert frame['codec']=='ZLIB_CANONICAL_JSON_V1';compressed=zlib.compress(payload,level=1)
    frame.update(logical_sha256=logical,logical_size=len(payload),data=base64.b64encode(compressed).decode(),summary={'kind':'REPLAY_STEP','index':step['index'],'previous':step['previous'],'execution_start':step['execution_start'],'input_fingerprints':[digest(v) for v in step['inputs']]})
    raw=encode(frame);physical=digest(frame)
    if frame['codec']=='ZSTD_CANONICAL_JSON_DICTIONARY_V1' and frame['basis'] is None:new_anchors[step['index']]=(payload,physical,logical)
    assert read_step(raw,updated=True)[1]==step
    return raw,physical,logical

if mutation==0:
    connection.execute('UPDATE records SET ready=0,delivered=0 WHERE sequence=(SELECT max(sequence) FROM records)')
elif mutation==1: connection.execute('UPDATE replay_steps SET ready=0 WHERE sequence=(SELECT max(sequence) FROM replay_steps)')
elif mutation==2: connection.execute('DELETE FROM replay_steps WHERE sequence=2')
elif mutation==3:
    n,raw=connection.execute('SELECT sequence,payload FROM replay_steps ORDER BY sequence DESC LIMIT 1').fetchone()
    frame,v=read_step(raw);v['state']['outcome']={'schema_version':1,'status':'COMPLETED','reason':None};v['cause']['outcome']=v['state']['outcome']
    raw,physical,logical=reseal(frame,v)
    connection.execute('UPDATE replay_steps SET payload=?,digest=? WHERE sequence=?',(raw,physical,n));connection.execute('UPDATE replay_binding SET last_hash=?',(logical,))
elif mutation==4:
    raw=connection.execute('SELECT payload FROM replay_binding').fetchone()[0];v=json.loads(raw);v['work_id']='foreign-original-work'
    identity={'work_id':v['work_id'],'configuration':json.loads(connection.execute('SELECT payload FROM meta').fetchone()[0])['configuration'],'artifact':v['kernel_artifact'],'driver_artifact':v['driver_artifact'],'input_pin':v['input_pin'],'participants':v['participants'],'initial_ns':v['initial_state']['clock_ns']}
    v['work']=digest(identity);previous=digest(v);connection.execute('UPDATE replay_binding SET payload=?,digest=?',(encode(v),previous))
    for n,raw in connection.execute('SELECT sequence,payload FROM replay_steps ORDER BY sequence').fetchall():
        frame,step=read_step(raw);step['previous']=previous;raw,physical,previous=reseal(frame,step);connection.execute('UPDATE replay_steps SET payload=?,digest=? WHERE sequence=?',(raw,physical,n))
    connection.execute('UPDATE replay_binding SET last_hash=?',(previous,))
elif mutation==5:
    n,raw=connection.execute('SELECT sequence,payload FROM checkpoints ORDER BY sequence DESC LIMIT 1').fetchone();v=json.loads(raw);v['source']='f'*64
    connection.execute('UPDATE checkpoints SET payload=?,digest=? WHERE sequence=?',(encode(v),digest(v),n))
elif mutation in (6,7,8,9,10):
    # Only the native causal output changes. Canonical execution facts and every
    # economic checkpoint remain byte-for-byte identical to the original run.
    records=connection.execute('SELECT * FROM records ORDER BY sequence').fetchall()
    checkpoints=connection.execute('SELECT * FROM checkpoints ORDER BY sequence').fetchall()
    previous=connection.execute('SELECT digest FROM replay_binding').fetchone()[0]
    changed=False
    for n,raw in connection.execute('SELECT sequence,payload FROM replay_steps ORDER BY sequence').fetchall():
        frame,step=read_step(raw)
        output=step['cause']['processing'].get('processing',{}) if isinstance(step['cause']['processing'],dict) else {}
        if not changed and step['cause']['kind']=='OPEN' and output.get('status')=='FILLED':
            if mutation==6: output['signal']['signal_time']=str(int(output['signal']['signal_time'])+1)
            elif mutation==7: output['execution_price']['value']='100120.030000'
            elif mutation==8: output['economic_evidence']['charge_target']='0.00000000'
            elif mutation==9: output['admission']['native_fee_estimate']['reservation_charge']='0.00000000'
            else: output['order']='foreign-order'
            changed=True
        step['previous']=previous;raw,physical,previous=reseal(frame,step)
        connection.execute('UPDATE replay_steps SET payload=?,digest=? WHERE sequence=?',(raw,physical,n))
    assert changed, 'fixture must contain a real filled opening'
    connection.execute('UPDATE replay_binding SET last_hash=?',(previous,))
    assert connection.execute('SELECT * FROM records ORDER BY sequence').fetchall()==records
    assert connection.execute('SELECT * FROM checkpoints ORDER BY sequence').fetchall()==checkpoints
connection.commit();connection.close()
"#]).arg(root.join("runtime.sqlite3")).arg(mutation.to_string()).status().unwrap();assert!(status.success());
}
#[test]
fn native_terminal_readonly_snapshot_verifies_cancelled_original_journal_and_rejects_splices() -> Result<()> {
    use onlyalpha_backtest::TerminalSnapshot;
    let case=fixture()?;let artifact=std::env::var("ONLYALPHA_TRADING_TEST_ARTIFACT")?;
    let installation=Arc::new(ChartInstallation::open(Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?),&artifact)?);
    let root=std::env::temp_dir().join(format!("oa-terminal-readonly-{}",std::process::id()));std::fs::create_dir(&root)?;
    let (spec,inputs,participants,prepared)=composition(&case,installation,&artifact)?;
    let mut run=RunLoop::create(&root,spec.clone(),inputs.clone(),participants)?;
    for _ in 0..44 {assert!(run.step()?);}
    let running=journal_cut(&root);assert!(TerminalSnapshot::read(&root,spec.clone(),&inputs,terminal_policy).is_err());assert_eq!(journal_cut(&root),running);
    run.cancel_input()?;run.deliver(|_|Ok(()))?;run.terminate("CANCELLED",Some("USER_CANCELLED"))?;
    let expected=ObservedBacktest::observe(&prepared,&run)?;let state=run.state()?;drop(run);
    let original=journal_cut(&root);let snapshot=TerminalSnapshot::read(&root,spec.clone(),&inputs,terminal_policy)?;
    snapshot.verify_cut()?;assert_eq!(snapshot.trace(),expected.trace());assert_eq!(snapshot.proof(),expected.proof());assert_eq!(snapshot.result(),expected.result());assert_eq!(snapshot.state(),&state);
    assert_eq!(snapshot.trace()["binding"]["schema_version"],2);assert_eq!(snapshot.trace()["binding"]["work_id"],spec.work_id);
    let projected=ObservedBacktest::from_terminal(&prepared,&snapshot)?;assert_eq!(projected.record(),expected.record());
    assert_eq!(journal_cut(&root),original,"read-only snapshot must not configure/recover/ack or create sidecars");drop(projected);drop(snapshot);
    for key in ["work","kernel","driver","configuration"] {
        let mut other=spec.clone();match key {"work"=>other.work_id="foreign-work".into(),"kernel"=>other.kernel_artifact="f".repeat(64),"driver"=>other.driver_artifact="f".repeat(64),_=>other.configuration["gateway"]=json!("foreign-gateway")};
        assert!(TerminalSnapshot::read(&root,other,&inputs,terminal_policy).is_err(),"{key}");assert_eq!(journal_cut(&root),original);
    }
    let mut foreign=inputs.record();foreign["sources"][0]["snapshot"]=json!("f".repeat(64));let foreign=Inputs::from_record(&foreign)?;
    assert!(TerminalSnapshot::read(&root,spec.clone(),&foreign,terminal_policy).is_err());assert_eq!(journal_cut(&root),original);
    for mutation in 0..11 {
        journal_fault(&root,mutation);let damaged=journal_cut(&root);
        assert!(TerminalSnapshot::read(&root,spec.clone(),&inputs,terminal_policy).is_err(),"rehashed fault {mutation}");assert_eq!(journal_cut(&root),damaged,"a rejected original journal cannot be healed");
        std::fs::write(root.join("runtime.sqlite3"),&original["runtime.sqlite3"].1)?;
    }
    for name in ["runtime.sqlite3-wal","runtime.sqlite3-shm","runtime.sqlite3-journal"] {
        std::fs::write(root.join(name),b"unresolved original sidecar")?;let damaged=journal_cut(&root);
        assert!(TerminalSnapshot::read(&root,spec.clone(),&inputs,terminal_policy).is_err());assert_eq!(journal_cut(&root),damaged);std::fs::remove_file(root.join(name))?;
    }
    let path=root.join("runtime.sqlite3");let missing=root.join("retained-unavailable.sqlite3");std::fs::rename(&path,&missing)?;
    let before=journal_cut(&root);assert!(TerminalSnapshot::read(&root,spec,&inputs,terminal_policy).is_err());assert_eq!(journal_cut(&root),before);std::fs::rename(missing,path)?;
    std::fs::remove_dir_all(root)?;Ok(())
}
