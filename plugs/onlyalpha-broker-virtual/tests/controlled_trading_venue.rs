use onlyalpha_broker::{
    AccountPort, BrokerCommand, ConnectionPort, DispatchResult, Fact, OrderQueryPort, PositionPort,
    Scope, TradeQueryPort, TradingPort,
};
use onlyalpha_broker_virtual::VirtualBroker;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, value::OnlyMoney};
use serde_json::{Value, json};
use std::io::{BufRead, Write};

fn fill(venue: &mut VirtualBroker, command: &BrokerCommand) {
    venue.advance(0).unwrap();
    let mut bar = include_str!("../../../test-data/domain/fact-records-v1.jsonl")
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap())
        .find(|row| row["id"] == "bar").unwrap()["record"].clone();
    let request = &command.record()["request"];
    bar["bar_type"]["instrument_id"] = request["instrument_id"].clone();
    for field in ["open", "high", "low", "close"] {
        bar[field] = request["price"].clone();
    }
    venue.on_bar(1, &OnlyBar::from_record(&bar).unwrap()).unwrap();
}

fn evidence(fact: &Fact) -> Value {
    json!({"identity": fact.identity(), "fingerprint": fact.fingerprint(), "record": fact.record()})
}

fn observation(venue: &VirtualBroker, command: &BrokerCommand, conflicting: bool) -> Value {
    let scope = command.scope();
    let orders = venue.orders(scope, false).unwrap();
    let trades = venue.trades(scope, None).unwrap();
    let positions = venue.positions(scope).unwrap();
    assert_eq!((orders.len(), trades.len(), positions.len()), (1, 1, 1));
    let order = orders[0].record();
    assert_eq!(order["status"], "FILLED");
    assert_eq!(order["order"], command.order());
    assert_eq!(order["client"], command.client());
    assert_eq!(order["request"], command.record()["request"]);
    let cut = venue.checkpoint();
    let facts = cut["facts"].as_array().unwrap();
    assert_eq!(facts.len(), 2);
    let accepted = Fact::decode(&facts[0]).unwrap();
    assert_eq!(facts[0]["kind"], "ACCEPTED");
    assert_eq!(facts[0]["causation"], command.id());
    assert_eq!(facts[0]["payload"]["venue"], order["venue"]);
    let mut trade = trades[0].record();
    assert_eq!(facts[1], trade);
    assert_eq!(trade["causation"], command.order());
    assert_eq!(trade["payload"]["fill"]["venue_order_id"]["value"], order["venue"]);
    if conflicting {
        trade["payload"]["fill"]["price"]["value"] = json!("9.00");
    }
    let reported = Fact::decode(&trade).unwrap();
    assert_eq!(reported.identity(), trades[0].identity());
    assert_eq!(reported.fingerprint() != trades[0].fingerprint(), conflicting);
    json!({"accepted": evidence(&accepted), "trade": evidence(&reported),
        "cash": venue.account(scope).unwrap().record()["payload"]["ledger_cash"]["amount"],
        "quantity": positions[0].record()["payload"]["quantity"]["value"]})
}

#[test]
#[ignore = "由后端契约测试读取已编译插件的描述符"]
fn product_descriptor() {
    println!("VENUE_DESCRIPTOR {}", onlyalpha_broker_virtual::provider::descriptor());
}

#[test]
#[ignore = "由后端交易恢复测试通过标准输入输出驱动"]
fn controlled_venue() {
    let stdin = std::io::stdin();
    let mut lines = stdin.lock().lines();
    let init: Value = serde_json::from_str(&lines.next().unwrap().unwrap()).unwrap();
    let mut venue = VirtualBroker::new(
        Scope::decode(&init["scope"]).unwrap(),
        init["artifact"].as_str().unwrap(),
        OnlyMoney::from_record(&init["cash"]).unwrap(),
        &json!({}),
    ).unwrap();
    venue.connect().unwrap();
    venue.authenticate().unwrap();
    let mut dispatch_calls = 0;
    for line in lines {
        let request: Value = serde_json::from_str(&line.unwrap()).unwrap();
        let command = BrokerCommand::decode(&request["command"]).unwrap();
        let mut result = match request["action"].as_str().unwrap() {
            "SUBMIT" => {
                dispatch_calls += 1;
                assert_eq!(venue.dispatch(&command).unwrap(), DispatchResult::Received);
                fill(&mut venue, &command);
                json!({"outcome": "UNKNOWN"})
            }
            "QUERY" => observation(&venue, &command, false),
            "CONFLICTING_QUERY" => observation(&venue, &command, true),
            other => panic!("unexpected venue request {other}"),
        };
        result["dispatch_calls"] = json!(dispatch_calls);
        println!("VENUE_REPLY {result}");
        std::io::stdout().flush().unwrap();
    }
    assert_eq!(dispatch_calls, 1);
}
