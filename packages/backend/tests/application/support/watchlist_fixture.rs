//! Pure retained Watchlist fixture production using current public owners.
//! The caller may insert returned rows only as controlled test preconditions.
use onlyalpha_backend::application::{
    command::{Admission, CommandId, CommandKind, Outcome, OutcomeKind, Receipt},
    watchlists::Book,
};
use serde_json::{Value, json};
use std::error::Error;

pub fn produce(input: &Value) -> Result<Value, Box<dyn Error>> {
    let namespace = input["namespace_id"].as_str().ok_or("namespace")?;
    let representation = i16::try_from(input["representation"].as_u64().ok_or("representation")?)?;
    // Validate the exact original representation before deriving its own identity.
    Book::from_record(&input["book"], representation)?;
    let fingerprint = Book::record_fingerprint(namespace, &input["book"])?;
    let intent = Book::intent_fingerprint(
        namespace,
        input["expected_version"]
            .as_u64()
            .ok_or("expected version")?,
        &input["book"]["lists"],
    )?;
    let admission = Admission::new(
        CommandId::new(input["command_id"].as_str().ok_or("command id")?)?,
        input["kind"]
            .as_str()
            .ok_or("kind")?
            .parse::<CommandKind>()?,
        &intent,
    )?;
    let receipt = Receipt::new(
        admission.clone(),
        Outcome::new(OutcomeKind::WatchlistRevision, &fingerprint)?,
        input["accepted_at"].as_str().ok_or("accepted at")?,
    )?;
    Ok(json!({"fingerprint":fingerprint,"intent":intent,
        "admission":{"command_id":admission.id().value(),"command_kind":admission.kind().as_str(),
            "command_fingerprint":admission.fingerprint(),"schema_version":1},
        "receipt":{"command_id":receipt.admission().id().value(),"command_kind":receipt.admission().kind().as_str(),
            "command_fingerprint":receipt.admission().fingerprint(),"outcome_kind":receipt.outcome().kind().as_str(),
            "outcome_id":receipt.outcome().id(),"accepted_at":receipt.accepted_at().to_string(),"schema_version":1}}))
}
