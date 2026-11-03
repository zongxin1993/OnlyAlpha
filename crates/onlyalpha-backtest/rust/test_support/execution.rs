//! Existing independent three-fact vector shared by two native tests.
use crate::hash;
use serde_json::{Value,json};
const FIXTURE:&str=include_str!("../../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE:&str=include_str!("../../../../test-data/settlement/common-v1.json");
const ECONOMICS:&str=include_str!("../../../../test-data/execution/economics-v1.json");
pub(crate) fn configuration(modern:bool)->Value{
 let fixture:Value=serde_json::from_str(FIXTURE).unwrap();let economics:Value=serde_json::from_str(ECONOMICS).unwrap();
 let mut value=json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"a".repeat(64),"runtime_kind":"BACKTEST",
  "currency":fixture["fee_contract"]["binding"]["charge_currency"],"initial_cash":economics["initial_cash"],"capitals":{"cluster":economics["initial_cash"]},
  "profiles":{"cluster":{"schema_version":1,"revision":"revision","instruments":["600000.XSHG"],"rules":[]}},"instruments":[{"schema_version":1,"id":"600000.XSHG","price_precision":2,"quantity_precision":0,"multiplier":"1"}]});
 if modern{value["schema_version"]=json!(2);value["account_checkpoint_version"]=json!(5);}value
}
pub(crate) fn original_three_facts()->[Value;3]{
 let fixture:Value=serde_json::from_str(FIXTURE).unwrap();let economics:Value=serde_json::from_str(ECONOMICS).unwrap();let settlement:Value=serde_json::from_str(SETTLEMENT_FIXTURE).unwrap();
 let config=configuration(false);let order=&fixture["fee_contract"]["binding"]["order_id"]["value"];let trade=&economics["buy_fills"][0];
 // This existing independent vector's first Fill is one unit, so its exact
 // notional is its declared price; no arithmetic implementation is needed.
 assert_eq!(trade["quantity"],"1");let mut notional=fixture["fee_contract"]["funding"]["principal_reservation"].clone();notional["amount"]=trade["price"].clone();
 let none=json!({"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null});
 let admission=json!({"schema_version":1,"request":fixture["request"],"fee_contract":fixture["fee_contract"],"fee_budget":trade["charge_target"],
  "market":{"schema_version":1,"verdict":"ACCEPT","source_ref":"market-1","request_digest":hash(&fixture["request"]),"notional":fixture["fee_contract"]["funding"]["principal_reservation"],"rounding":"HALF_EVEN"},"order":order,"collateral":none});
 let mut fill=json!({"schema_version":1,"order":order,"trade":"trade-3","venue_trade":"venue-trade-3","venue_order":"venue-1","quantity":trade["quantity"],"price":trade["price"],"collateral":none,
  "fees":{"schema_version":1,"instruction":"fee-3","source_ref":"fee-source-3","policy":fixture["fee_contract"]["binding"]["fingerprint"],"order":order,"trade":"trade-3","currency":config["currency"],"charge_target":trade["charge_target"],"rebate_target":"0.00"},
  "settlement":{"schema_version":1,"instruction":"settlement-3","source_ref":"settlement-source-3","order":order,"trade":"trade-3","currency":config["currency"],"model":"CASH_SETTLEMENT","gross_notional":notional,"rounding":"HALF_EVEN","calendar":settlement["calendar"],"policy":settlement["policy"]},
  "valuation":{"schema_version":1,"source_ref":"valuation-source-3","currency":config["currency"],"mark":trade["price"]}});
 let scope=json!({"schema_version":1,"engine":config["engine"],"runtime":config["runtime"],"account":config["account"],"gateway":config["gateway"],"generation":config["generation"],"runtime_kind":config["runtime_kind"],"cluster":"cluster","revision":"revision","instrument":"600000.XSHG","request":fixture["request"]["request_id"]["value"]});
 for (key,family) in [("fees","ORDER_FEE_ACCRUAL"),("settlement","SETTLEMENT"),("valuation","VALUATION")]{let proof=&mut fill[key];proof["scope"]=scope.clone();proof["family"]=json!(family);proof["version"]=json!(3);proof["as_of_sequence"]=json!(3);proof["source_digest"]=json!(hash(proof));}
 let payloads=[("ADMIT",admission),("SUBMISSION",json!({"schema_version":1,"order":order,"outcome":"UNKNOWN"})),("FILL",fill)];
 std::array::from_fn(|index|{let (operation,payload)=&payloads[index];let sequence=index as u64+1;
  json!({"schema_version":1,"engine":config["engine"],"runtime":config["runtime"],"account":config["account"],"gateway":config["gateway"],"generation":config["generation"],"runtime_kind":config["runtime_kind"],
   "cluster":"cluster","revision":"revision","input_id":format!("input-{sequence}"),"time":sequence,"runtime_sequence":sequence,"trading_day":"2026-10-19","day_index":1,"source_ref":format!("source-{sequence}"),"op":operation,"payload":payload})
 })
}
