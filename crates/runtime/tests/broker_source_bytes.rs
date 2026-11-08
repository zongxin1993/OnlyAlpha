//! 原场所保持运行时，派发和观察必须逐字节核验实际读取的时钟。
use onlyalpha_broker::{Broker, BrokerCommand, CommandState, Connection, ConnectionPort, Journal};
use onlyalpha_broker_virtual::BoundVirtualActor;
use onlyalpha_runtime::{BoundBrokerJournal, Runtime};
use rusqlite::{Connection as Database, params};
use serde_json::{Value, json};

#[path = "support/perpetual_run.rs"]
mod perpetual_run;
use perpetual_run::{prepare_prefix, scenario, venue_bar, venue_config};

#[derive(Clone, Copy, Debug)]
enum Original {
    Clock,
    Bar,
    StreamAt,
}

impl Original {
    fn read(self, db: &Database) -> (i64, String) {
        let select = match self {
            Self::Clock | Self::Bar => {
                "SELECT sequence,input FROM source_steps WHERE json_extract(input,'$[0]') IN ('CLOCK','BAR') ORDER BY sequence DESC LIMIT 1"
            }
            Self::StreamAt => {
                "SELECT rowid,stream_at FROM source_facts WHERE json_extract(fact,'$.kind')='ACCEPTED'"
            }
        };
        db.query_row(select, [], |r| Ok((r.get(0)?, r.get(1)?)))
            .unwrap()
    }

    fn write(self, db: &Database, row: i64, raw: &str) {
        let update = match self {
            Self::Clock | Self::Bar => "UPDATE source_steps SET input=?1 WHERE sequence=?2",
            Self::StreamAt => "UPDATE source_facts SET stream_at=?1 WHERE rowid=?2",
        };
        assert_eq!(db.execute(update, params![raw, row]).unwrap(), 1);
    }
}

fn changed_text(raw: &str, reverse_bar_fields: bool) -> String {
    let parsed: Value = serde_json::from_str(raw).unwrap();
    let changed = if reverse_bar_fields {
        assert_eq!(parsed[0], "BAR");
        let bar = parsed[2].as_object().unwrap();
        let reversed = bar
            .iter()
            .rev()
            .map(|(k, v)| format!("{}:{v}", json!(k)))
            .collect::<Vec<_>>()
            .join(",");
        raw.replacen(&parsed[2].to_string(), &format!("{{{reversed}}}"), 1)
    } else {
        format!(" {raw}")
    };
    assert_ne!(raw, changed);
    assert_eq!(serde_json::from_str::<Value>(&changed).unwrap(), parsed);
    changed
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Action {
    Dispatch,
    Ingress,
}

fn hot_read(action: Action, original: Original, reverse_bar_fields: bool) -> String {
    let (cfg, inputs) = scenario();
    let (root, mut runtime) = prepare_prefix(&cfg, &inputs, 1);
    let (scope, cash, settings) = venue_config(&inputs);
    let binding = cfg["perpetual"]["execution_source_binding"]
        .as_str()
        .unwrap();
    let open_actor = || {
        BoundVirtualActor::open(
            &root.0,
            scope.clone(),
            &"f".repeat(64),
            cash.clone(),
            &settings,
            binding,
        )
    };
    let mut actor = open_actor().unwrap();
    actor.connect().unwrap();
    actor.authenticate().unwrap();
    let mut journal = BoundBrokerJournal::open(&root.0, binding).unwrap();
    let mut broker = Broker::recover(scope.clone(), &journal, 32).unwrap();
    broker.set_connection(Connection::Ready);
    broker.set_health(true, true, true);
    let admission = &inputs[1];
    runtime.apply(admission).unwrap();
    let owners = runtime.fork_ready().unwrap().0.checkpoint().unwrap();
    let order = &owners["components"][0]["state"]["orders"][0]["snapshot"];
    let at = admission["time"].as_i64().unwrap();
    let request = &admission["payload"]["request"];
    let command = BrokerCommand::decode(&json!({
        "schema_version":1,"scope":scope.record(),"operation":"SUBMIT",
        "command_id":"original-submit","order":admission["payload"]["order"],
        "client":order["client_order_id"]["value"],"request":request
    }))
    .unwrap();

    actor.advance(at).unwrap();
    if action == Action::Ingress {
        assert_eq!(
            journal
                .dispatch(&mut broker, &runtime, &mut actor, &command)
                .unwrap(),
            CommandState::Known
        );
        actor.advance(at).unwrap();
    }
    if matches!(original, Original::Bar) {
        actor.on_bar(1, &venue_bar(request, 1, at)).unwrap();
    }
    let ready = runtime.records().unwrap();
    assert!(
        ready
            .iter()
            .all(|row| row.prepared().input()["op"] != "FUNDING")
    );
    let head = actor.checkpoint();
    let db = Database::open(root.0.join("broker.sqlite3")).unwrap();
    let (row, raw) = original.read(&db);
    let parsed: Value = serde_json::from_str(&raw).unwrap();
    match original {
        Original::Clock => assert_eq!(parsed[0], "CLOCK"),
        Original::Bar => assert_eq!(parsed[0], "BAR"),
        Original::StreamAt => assert!(parsed.is_number()),
    }

    // 仅观察真实追加事务是否走到了写行语句，异常原文期间两种事件都不允许写入。
    let kind = match action {
        Action::Dispatch => "DISPATCHED",
        Action::Ingress => "INGRESS",
    };
    db.execute_batch(&format!(
        "CREATE TRIGGER reject_test_event BEFORE INSERT ON protocol_records
         WHEN json_extract(NEW.record,'$.event.kind')='{kind}'
         BEGIN SELECT RAISE(ABORT,'TEST_REACHED_APPEND'); END;"
    ))
    .unwrap();
    original.write(&db, row, &changed_text(&raw, reverse_bar_fields));
    let cold_rejected = open_actor().is_err();
    let err = match action {
        Action::Dispatch => journal
            .dispatch(&mut broker, &runtime, &mut actor, &command)
            .err(),
        Action::Ingress => actor.publish(&mut broker, &mut journal).err(),
    };
    original.write(&db, row, &raw);
    db.execute_batch("DROP TRIGGER reject_test_event").unwrap();
    assert!(cold_rejected);
    assert_eq!(actor.checkpoint(), head);
    assert_eq!(open_actor().unwrap().checkpoint(), head);
    assert_eq!(runtime.records().unwrap(), ready);
    assert!(
        journal
            .records()
            .unwrap()
            .iter()
            .all(|r| r.record()["event"]["kind"] != kind)
    );
    broker.refresh(&journal).unwrap();
    broker.set_connection(Connection::Ready);
    broker.set_health(true, true, true);
    match action {
        Action::Dispatch => {
            assert_eq!(
                broker.command_state(command.id()),
                Some(CommandState::Durable)
            );
            assert_eq!(
                journal
                    .dispatch(&mut broker, &runtime, &mut actor, &command)
                    .unwrap(),
                CommandState::Known
            );
        }
        Action::Ingress => {
            assert!(actor.publish(&mut broker, &mut journal).unwrap() > 0);
            assert!(
                broker
                    .pending()
                    .iter()
                    .any(|f| f.record()["kind"] == "ACCEPTED")
            );
        }
    }
    err.expect("guarded original operation must have failed")
        .to_string()
}

#[test]
fn hot_dispatch_requires_canonical_clock_or_bar_text() {
    let results = [
        (Original::Clock, false),
        (Original::Bar, false),
        (Original::Bar, true),
    ]
    .map(|(source, reverse)| hot_read(Action::Dispatch, source, reverse));
    assert_eq!(results, ["BROKER_SOURCE_NONCANONICAL_JSON"; 3]);
}

#[test]
fn hot_ingress_requires_canonical_clock_bar_and_stream_time_text() {
    let results = [
        (Original::Clock, false),
        (Original::Bar, false),
        (Original::Bar, true),
        (Original::StreamAt, false),
    ]
    .map(|(source, reverse)| hot_read(Action::Ingress, source, reverse));
    assert_eq!(results, ["BROKER_SOURCE_NONCANONICAL_JSON"; 4]);
}
