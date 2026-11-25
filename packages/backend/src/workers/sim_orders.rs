use crate::persistence::sim_venue::{SimJournal, SimVenue};
use onlyalpha_broker::{Broker, BrokerCommand, CommandState, Error, Journal, Operation};
use onlyalpha_execution::Prepared;
use onlyalpha_runtime::durability::RecoveryFacts;
use serde_json::{Value, json};
use std::collections::BTreeMap;

fn intent_conflict() -> Error {
    Error::new("SIM_ORIGINAL_INTENT_CONFLICT")
}

fn verify_original_request(plan: &Prepared, command: &BrokerCommand) -> Result<(), Error> {
    let input = plan.input();
    let payload = &input["payload"];
    let scope = command.scope().record();
    if scope.as_object().ok_or_else(intent_conflict)?.iter().any(|(key, value)| input.get(key) != Some(value))
        || payload["order"] != command.order()
    {
        return Err(intent_conflict());
    }
    let mut rows = plan.order_snapshot_data().as_array().ok_or_else(intent_conflict)?.iter()
        .filter(|row| row["snapshot"]["order_id"]["value"] == command.order());
    let row = rows.next().ok_or_else(intent_conflict)?;
    let snapshot = &row["snapshot"];
    if rows.next().is_some()
        || snapshot["client_order_id"]["value"] != command.client()
        || snapshot["account_id"]["value"] != scope["account"]
        || snapshot["cluster_id"]["value"] != input["cluster"]
    {
        return Err(intent_conflict());
    }
    let request = match command.operation() {
        Operation::Submit if input["op"] == "ADMIT" && snapshot["status"] == "SUBMITTED" && row["submission"] == "DISPATCHING" => {
            let mut request = payload["request"].as_object().cloned().ok_or_else(intent_conflict)?;
            request.insert("account_id".into(), snapshot["account_id"].clone());
            Value::Object(request)
        }
        Operation::Cancel if input["op"] == "CANCEL" && snapshot["status"] == "PENDING_CANCEL" => {
            json!({
                "schema_version": 1,
                "request_id": {"schema_version": 1, "value": payload["request_id"]},
                "order_id": snapshot["order_id"],
                "reason": payload["reason"],
                "metadata": {}
            })
        }
        _ => return Err(intent_conflict()),
    };
    if command.record()["request"] != request {
        return Err(intent_conflict());
    }
    Ok(())
}

pub(super) fn verify_original_intents(journal: &SimJournal, facts: &RecoveryFacts) -> Result<(), Error> {
    let mut ready: BTreeMap<_, _> = facts.records().iter()
        .filter(|record| record.ready())
        .map(|record| (record.prepared().id(), record.prepared()))
        .collect();
    for row in journal.records()? {
        let event = &row.record()["event"];
        if event["kind"] != "INTENT" {
            continue;
        }
        let intent = &event["intent"];
        let transaction = intent["transaction"].as_str().ok_or_else(intent_conflict)?;
        let plan = ready.remove(transaction).ok_or_else(intent_conflict)?;
        let command = BrokerCommand::decode(&intent["command"])?;
        if intent["payload_hash"] != plan.payload_fingerprint()
            || journal.dispatch_admission_time(command.id()).is_some_and(|at| at != &plan.input()["time"])
        {
            return Err(intent_conflict());
        }
        verify_original_request(plan, &command)?;
    }
    Ok(())
}

pub(super) fn recover_verified_orders(
    broker: &mut Broker,
    journal: &mut SimJournal,
    venue: &mut SimVenue,
    facts: &RecoveryFacts,
) -> Result<(), Error> {
    verify_original_intents(journal, facts)?;
    recover_original_orders(broker, journal, venue)
}

pub(super) fn recover_original_orders(
    broker: &mut Broker,
    journal: &mut SimJournal,
    venue: &mut SimVenue,
) -> Result<(), Error> {
    for command in journal.commands()? {
        match broker.command_state(command.id()) {
            Some(CommandState::Unknown | CommandState::Reconciling) => {
                venue.reconcile(broker, journal, command.id())?;
            }
            Some(CommandState::Durable | CommandState::Known | CommandState::Resolved) => {}
            None => return Err(Error::new("BROKER_COMMAND_MISSING")),
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "../tests/sim_original_intents_tests.rs"]
mod tests;
