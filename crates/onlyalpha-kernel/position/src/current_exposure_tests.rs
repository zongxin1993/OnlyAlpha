//! Current exposure reuses the original owner and omits only unrequested history.
use super::*;
fn config()->Value {json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"generation","currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"clusters":["a","b"],"instruments":[{"schema_version":1,"id":"BTCUSDT.BINANCE","price_precision":2,"quantity_precision":0,"multiplier":"1"}]})}
fn command(id:&str,op:&str,at:u64,payload:Value)->Value {json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"generation","command_id":id,"cause":"a".repeat(64),"time":at,"op":op,"payload":payload})}
fn trade(id:&str,cluster:Option<&str>,side:&str,price:&str,quantity:&str,at:u64,terminal:bool)->Value {command(id,"TRADE",at,json!({"schema_version":1,"instrument":"BTCUSDT.BINANCE","cluster":cluster,"order":format!("order-{}",cluster.unwrap_or("external")),"trade":id,"venue_trade":format!("v-{id}"),"execution":format!("x-{id}"),"sequence":at,"side":side,"position_side":"LONG","position_mode":"NETTING","price":price,"quantity":quantity,"fee":"0.00","bucket":"SETTLED","terminal_fill":terminal}))}
fn reserve(at:u64,quantity:&str)->Value {command(&format!("reserve-{at}"),"RESERVE",at,json!({"schema_version":1,"instrument":"BTCUSDT.BINANCE","cluster":"a","order":"order-a","quantity":quantity}))}
fn broker(at:u64,total:&str,available:&str,frozen:&str)->Value {command(&format!("broker-{at}"),"BROKER",at,json!({"schema_version":1,"instrument":"BTCUSDT.BINANCE","snapshot_id":format!("snapshot-{at}"),"sequence":at,"position_side":"LONG","total":total,"settled":total,"unsettled":"0","available":available,"frozen":frozen,"average":"10.00","quality":"VERIFIED"}))}
fn apply(m:&mut Manager,c:Value){assert_eq!(m.apply(&c).unwrap().status,Status::Applied);}
// The actual owner query used by both Execution callers.
fn current(m:&Manager)->Value {m.current_exposure()}
fn compare(m:&Manager)->Value {
    let full=m.state();let checkpoint=m.checkpoint().unwrap();
    let expected=json!({"accounts":full["accounts"],"allocations":full["allocations"]});
    let mut actual=current(m);assert_eq!(actual,expected);assert_eq!(actual.as_object().unwrap().len(),2);
    actual["accounts"]=json!([]);actual["allocations"]=json!([]);
    assert_eq!(m.state(),full);assert_eq!(m.checkpoint().unwrap(),checkpoint);
    let mut restored=Manager::new(config()).unwrap();restored.restore(&checkpoint.0,&checkpoint.1).unwrap();
    assert_eq!(current(&restored),expected);assert_eq!(restored.state(),full);assert_eq!(restored.checkpoint().unwrap(),checkpoint);
    expected
}
#[test]
fn current_exposure_retains_literal_accounts_allocations_and_never_mutates_source_data(){
    let mut m=Manager::new(config()).unwrap();assert_eq!(compare(&m),json!({"accounts":[],"allocations":[]}));
    apply(&mut m,trade("open-a",Some("a"),"BUY","10.00","2",1,false));
    apply(&mut m,trade("open-b",Some("b"),"BUY","20.00","3",2,false));
    apply(&mut m,trade("external",None,"BUY","10.00","1",3,false));
    let view=compare(&m);assert_eq!(view["accounts"][0]["snapshot"]["quantity"],"6");
    let allocations=view["allocations"].as_array().unwrap();assert_eq!(allocations.len(),3);
    let external=allocations.iter().find(|row|row["cluster"].is_null()).unwrap();assert_eq!(external["snapshot"]["available"],"0");
    assert!(m.cluster("a","BTCUSDT.BINANCE").is_ok());assert_eq!(m.unallocated("BTCUSDT.BINANCE").unwrap().unwrap(),external["snapshot"]);
    let before=current(&m);let checkpoint=m.checkpoint().unwrap();assert!(m.apply(&reserve(4,"3")).is_err());
    assert_eq!(current(&m),before);assert_eq!(m.checkpoint().unwrap(),checkpoint);
}
#[test]
fn current_exposure_preserves_reservations_broker_caps_restrictions_and_sticky_blocks(){
    let mut m=Manager::new(config()).unwrap();apply(&mut m,trade("open",Some("a"),"BUY","10.00","10",1,false));apply(&mut m,reserve(2,"4"));
    for (at,stage) in [(3,"SENT_TO_BROKER"),(4,"BROKER_ACKNOWLEDGED")]{apply(&mut m,command(&format!("stage-{at}"),"STAGE",at,json!({"schema_version":1,"order":"order-a","cluster":"a","stage":stage})));}
    apply(&mut m,broker(5,"10","6","4"));assert_eq!(compare(&m)["accounts"][0]["snapshot"]["available"],"6");
    apply(&mut m,command("restriction","RESTRICTION",6,json!({"schema_version":1,"instrument":"BTCUSDT.BINANCE","id":"restriction","quantity":"2","kind":"SUSPENDED","source":"market-rule","from":6,"until":8,"reason":"explicit"})));
    assert_eq!(compare(&m)["accounts"][0]["snapshot"]["available"],"4");apply(&mut m,command("expiry","TICK",8,json!({"schema_version":1})));
    assert_eq!(compare(&m)["accounts"][0]["snapshot"]["available"],"6");
    apply(&mut m,broker(9,"11","7","4"));assert_eq!(compare(&m)["accounts"][0]["snapshot"]["available"],"0");
    let mut stale=Manager::new(config()).unwrap();apply(&mut stale,trade("current",Some("a"),"BUY","10.00","2",10,false));
    assert_eq!(stale.apply(&trade("stale",Some("a"),"BUY","10.00","1",1,false)).unwrap().status,Status::Stale);
    assert_eq!(compare(&stale)["accounts"][0]["snapshot"]["available"],"0");
}
#[test]
fn current_exposure_avoids_complete_state_construction_as_retained_command_history_grows(){
    for count in [16,64] {
        let mut m=Manager::new(config()).unwrap();apply(&mut m,trade("open",Some("a"),"BUY","10.00","2",1,false));apply(&mut m,reserve(2,"2"));apply(&mut m,trade("close",Some("a"),"SELL","12.00","2",3,true));
        for at in 4..=count {apply(&mut m,command(&format!("clock-{at}"),"TICK",at,json!({"schema_version":1})));}
        let full=m.state();assert!(full["commands"].as_object().unwrap().len()>=count as usize);
        let expected=json!({"accounts":full["accounts"],"allocations":full["allocations"]});let checkpoint=m.checkpoint().unwrap();FULL_STATE_CONSTRUCTIONS.with(|value|value.set(0));
        for _ in 0..4 {assert_eq!(current(&m),expected);}
        assert_eq!(FULL_STATE_CONSTRUCTIONS.with(std::cell::Cell::get),0,"four current-only reads built retained full state at history {count}");
        assert_eq!(m.checkpoint().unwrap(),checkpoint);assert_eq!(m.state(),full);
    }
}
