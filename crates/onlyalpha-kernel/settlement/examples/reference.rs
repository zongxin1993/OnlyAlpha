use onlyalpha_settlement::{Authority, compile, digest};
use serde_json::{Value, json};
use std::io::{self, Read};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut raw = String::new();
    io::stdin().take(33554433).read_to_string(&mut raw)?;
    if raw.len() > 33554432 {
        return Err("REFERENCE_FRAME_BOUND".into());
    }
    let request: Value = serde_json::from_str(&raw)?;
    let input = &request["fixture"];
    let i = compile(input.clone())?;
    let mut config = json!({"currency":input["currency"]});
    for k in [
        "engine",
        "runtime",
        "account",
        "gateway",
        "generation",
        "runtime_kind",
    ] {
        config[k] = input["scope"][k].clone();
    }
    let mut m = Authority::new(config, 8)?;
    if request["checkpoint"].is_null() {
        m.admit_order(
            input["scope"].clone(),
            input["order"].as_str().ok_or("order")?,
            input["side"].as_str().ok_or("side")?,
            input["quantity"].as_str().ok_or("quantity")?,
            0,
        )?;
        m.register(&i)?;
    } else {
        m.restore(&request["checkpoint"], &digest(&request["checkpoint"]))?;
        if m.snapshot(i.id())?["instruction"] != i.record() {
            return Err("REFERENCE_INPUT_BINDING".into());
        }
    }
    let initial = m.snapshot(i.id())?;
    let due = m.due("2026-12-31")?;
    let mut effects = vec![];
    for step in request["advances"].as_array().ok_or("advances")? {
        effects.push(
            m.mature(
                i.id(),
                step["day"].as_str().ok_or("day")?,
                step["time"].clone(),
                step["version"].as_u64().ok_or("version")?,
            )?
            .record(),
        );
    }
    println!(
        "{}",
        json!({"instruction":i.record(),"initial":initial,"due":due,"effects":effects,"checkpoint":m.checkpoint()})
    );
    Ok(())
}
