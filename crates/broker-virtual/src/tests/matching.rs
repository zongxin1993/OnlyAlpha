use super::*;
use onlyalpha_domain::time::OnlyTimestamp;

fn scope(kind: &str) -> Scope {
    Scope::decode(&json!({"engine":"engine", "runtime":"runtime", "gateway":"virtual", "account":"account", "generation":"a".repeat(64), "runtime_kind":kind})).unwrap()
}

fn cash() -> OnlyMoney {
    OnlyMoney::from_record(&json!({"schema_version":1, "amount":"1000.00", "currency":{"schema_version":1,"code":"CNY","precision":2,"currency_type":"FIAT"}})).unwrap()
}

fn matching() -> Value {
    json!({"matching":{"type":"NEXT_OPEN_LONG_ONLY_V1", "buy_multiplier":"1.0002", "sell_multiplier":"0.9998"}})
}

fn venue(config: &Value) -> VirtualBroker {
    let mut venue = VirtualBroker::new(scope("BACKTEST"), &"b".repeat(64), cash(), config).unwrap();
    venue.connect().unwrap();
    venue.authenticate().unwrap();
    venue
}

fn actor() -> MemoryVirtualActor {
    let config = matching();
    let binding = digest(venue(&config).source_binding());
    let mut actor = MemoryVirtualActor::new(
        scope("BACKTEST"),
        &"b".repeat(64),
        cash(),
        &config,
        &binding,
    )
    .unwrap();
    actor.connect().unwrap();
    actor.authenticate().unwrap();
    actor
}

fn bar(minute: u8, open: &str) -> OnlyBar {
    let mut record = include_str!("../../../../test-data/domain/fact-records-v1.jsonl")
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap())
        .find(|row| row["id"] == "bar")
        .unwrap()["record"]
        .clone();
    record["open"]["value"] = json!(open);
    record["bar_start"] = json!(format!("2025-01-06T01:{minute:02}:00Z"));
    for field in ["bar_end", "ts_event", "ts_init"] {
        record[field] = json!(format!("2025-01-06T01:{:02}:00Z", minute + 1));
    }
    OnlyBar::from_record(&record).unwrap()
}

fn start(bar: &OnlyBar) -> i64 {
    OnlyTimestamp::from_datetime(*bar.bar_start())
        .to_unix_nanos()
        .try_into()
        .unwrap()
}

fn submit(id: &str, side: &str, instrument: &OnlyInstrumentId) -> BrokerCommand {
    let mut request = serde_json::from_str::<Value>(include_str!(
        "../../../../test-data/broker/domain-inputs.json"
    ))
    .unwrap()["request"]
        .clone();
    request["request_id"]["value"] = json!(id);
    request["instrument_id"] = instrument.to_record();
    request["order_type"] = json!("MARKET");
    request["price"] = Value::Null;
    request["side"] = json!(side);
    request["execution_intent"]["side"] = json!(side);
    if side == "SELL" {
        request["offset"] = json!("CLOSE");
        request["execution_intent"]["position_effect"] = json!("CLOSE");
    }
    BrokerCommand::decode(&json!({"schema_version":1,"scope":scope("BACKTEST").record(),"operation":"SUBMIT","command_id":id,"order":format!("order-{id}"),"client":format!("client-{id}"),"request":request})).unwrap()
}

#[test]
fn next_open_fills_each_side_in_full_at_the_open_and_replays_the_original_facts() {
    let cfg = matching();
    let mut venue = venue(&cfg);
    for (index, (minute, side, open, expected)) in [
        (30, "BUY", "10.00", "10.002000"),
        (31, "SELL", "10.25", "10.247950"),
    ]
    .into_iter()
    .enumerate()
    {
        let bar = bar(minute, open);
        let seq = index as u64 + 1;
        let at = start(&bar);
        let command = submit(side, side, bar.instrument_id());
        venue
            .on_open(seq, at, bar.instrument_id(), bar.open())
            .unwrap();
        assert_eq!(venue.state.facts.len(), 2 * index);
        assert_eq!(venue.dispatch(&command).unwrap(), DispatchResult::Received);
        let cut = venue.checkpoint();
        let facts = cut["facts"].as_array().unwrap();
        assert_eq!(facts.len(), 2 * index + 2);
        let accepted = &facts[2 * index];
        let trade = &facts[2 * index + 1];
        assert_eq!(accepted["kind"], "ACCEPTED");
        assert_eq!(trade["kind"], "TRADE");
        for fact in [accepted, trade] {
            assert_eq!(fact["payload"]["order"], command.order());
            assert_eq!(fact["ts_event"], at);
            assert_eq!(fact["ts_init"], at);
        }
        let fill = &trade["payload"]["fill"];
        assert_eq!(fill["reference_price"], bar.open().to_record());
        assert_eq!(
            fill["price"],
            json!({"schema_version":1,"value":expected,"precision":6})
        );
        assert_eq!(fill["quantity"], command.record()["request"]["quantity"]);
        for field in ["ts_event", "ts_init"] {
            assert_eq!(fill[field]["unix_nanos"], at);
        }
        assert_eq!(venue.dispatch(&command).unwrap(), DispatchResult::Received);
        assert_eq!(venue.checkpoint(), cut);
        assert_eq!(
            venue
                .dispatch(&submit(&format!("other-{side}"), side, bar.instrument_id()))
                .unwrap(),
            DispatchResult::Rejected
        );
        venue.on_bar(seq, &bar).unwrap();
        assert!(venue.now() > at);
        assert_eq!(venue.checkpoint()["facts"], cut["facts"]);
    }
    let cut = venue.checkpoint();
    let replayed = VirtualBroker::restore(
        scope("BACKTEST"),
        &"b".repeat(64),
        cash(),
        &cfg,
        &cut,
        &digest(&cut),
    )
    .unwrap();
    assert_eq!(replayed.checkpoint(), cut);
}

#[test]
fn finite_source_records_each_open_and_close_once_even_after_redelivery() {
    let mut actor = actor();
    let bar = bar(30, "10.00");
    let at = start(&bar);
    actor
        .on_open(1, at, bar.instrument_id(), bar.open())
        .unwrap();
    actor
        .on_open(1, at, bar.instrument_id(), bar.open())
        .unwrap();
    actor.on_bar(1, &bar).unwrap();
    let closed_at = actor.now();
    actor
        .on_open(1, at, bar.instrument_id(), bar.open())
        .unwrap();
    actor.on_bar(1, &bar).unwrap();
    assert_eq!(actor.now(), closed_at);
    let completed = actor.finish().unwrap();
    let trace = completed.source_trace();
    assert_eq!(trace.len(), 2);
    assert_eq!(
        trace[0].record()["action"],
        json!({"kind":"OPEN","sequence":1,"bar_start":at,"instrument":bar.instrument_id().to_record(),"open":bar.open().to_record()})
    );
    assert_eq!(trace[0].record()["born"], json!([]));
    assert_eq!(
        trace[1].record()["action"],
        json!({"kind":"BAR_REFERENCE","sequence":1,"content":digest(&bar.to_record())})
    );
}

#[test]
fn incomplete_or_conflicting_open_and_close_prevent_finite_completion() {
    let first = bar(30, "10.00");
    let changed_price = bar(30, "10.25");
    let at = start(&first);
    let opened = || {
        let mut actor = actor();
        actor
            .on_open(1, at, first.instrument_id(), first.open())
            .unwrap();
        actor
    };
    assert!(opened().finish().is_err());
    let mut conflict = opened();
    assert_eq!(
        conflict.on_open(1, at, first.instrument_id(), changed_price.open()),
        Err(Error::new("VIRTUAL_OPEN_CONFLICT"))
    );
    assert_eq!(
        conflict.on_bar(1, &first),
        Err(Error::new("VIRTUAL_MEMORY_FAILED"))
    );
    for wrong_bar in [changed_price, bar(31, "10.00")] {
        let mut actor = opened();
        assert_eq!(
            actor.on_bar(1, &wrong_bar),
            Err(Error::new("VIRTUAL_OPEN_CLOSE_CONFLICT"))
        );
        assert!(actor.finish().is_err());
    }
    assert!(opened().on_bar(2, &first).is_err());
    assert!(actor().on_bar(1, &first).is_err());
}

#[test]
fn next_open_requires_a_backtest_and_an_exclusive_execution_price_and_fill_policy() {
    let cfg = matching();
    assert_eq!(
        VirtualBroker::new(scope("SIM"), &"b".repeat(64), cash(), &cfg).err(),
        Some(Error::new("VIRTUAL_OPEN_REQUIRES_BACKTEST"))
    );
    for (field, value) in [
        ("maximum_fill_quantity", json!("1")),
        ("latency", json!({"fill_ns":1})),
        ("slippage", json!({"type":"FIXED","price_offset":"0.01"})),
    ] {
        let mut invalid = cfg.clone();
        invalid[field] = value;
        assert_eq!(
            Config::parse(&invalid).err(),
            Some(Error::new("VIRTUAL_OPEN_CONFIGURATION"))
        );
    }
    for (field, value) in [
        ("buy_multiplier", "0.9"),
        ("sell_multiplier", "1.1"),
        ("sell_multiplier", "0"),
    ] {
        let mut invalid = cfg.clone();
        invalid["matching"][field] = json!(value);
        assert_eq!(
            Config::parse(&invalid).err(),
            Some(Error::new("VIRTUAL_OPEN_MULTIPLIER"))
        );
    }
}

#[test]
fn next_bar_market_order_matches_on_the_next_closed_bar_with_fixed_slippage() {
    let mut venue = venue(
        &json!({"matching":{"type":"NEXT_BAR"}, "slippage":{"type":"FIXED","price_offset":"0.25"}}),
    );
    let first = bar(30, "10.00");
    let next = bar(31, "10.25");
    assert!(
        venue
            .on_open(1, start(&first), first.instrument_id(), first.open())
            .is_err()
    );
    venue.on_bar(1, &first).unwrap();
    assert_eq!(
        venue
            .dispatch(&submit("ordinary", "BUY", first.instrument_id()))
            .unwrap(),
        DispatchResult::Received
    );
    venue.advance(venue.now()).unwrap();
    assert_eq!(venue.state.facts.len(), 1);
    assert_eq!(venue.state.facts[0].record()["kind"], "ACCEPTED");
    venue.on_bar(2, &next).unwrap();
    assert_eq!(venue.state.facts.len(), 2);
    let trade = venue.state.facts[1].record();
    assert_eq!(trade["kind"], "TRADE");
    let at: i64 = OnlyTimestamp::from_datetime(*next.ts_event())
        .to_unix_nanos()
        .try_into()
        .unwrap();
    assert!(at > start(&next));
    assert_eq!(trade["ts_event"], at);
    assert_eq!(
        trade["payload"]["fill"]["reference_price"],
        next.open().to_record()
    );
    assert_eq!(trade["payload"]["fill"]["price"]["value"], "10.50000000");
}
