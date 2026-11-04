use onlyalpha_margin::{Manager, digest};
use serde_json::{Value, json};
use std::io::{Read, Write};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut bytes = vec![];
    std::io::stdin().take(33554433).read_to_end(&mut bytes)?;
    if bytes.len() > 33554432 {
        return Err("frame bound".into());
    }
    let input: Value = serde_json::from_slice(&bytes)?;
    let mut manager = Manager::new(input["config"].clone(), 32)?;
    if !input["checkpoint"].is_null() {
        manager.restore(&input["checkpoint"], &digest(&input["checkpoint"]))?;
    }
    let mut snapshots = vec![];
    for step in input["steps"].as_array().ok_or("steps")? {
        let n = manager.checkpoint()["records"]
            .as_array()
            .ok_or("records")?
            .len()
            + 1;
        let mut c = input["template"].clone();
        for k in ["action", "quantity", "amount", "maintenance"] {
            c[k] = step[k].clone();
        }
        c["id"] = json!(format!("command-{n}"));
        c["source_ref"] = json!(format!("source-{n}"));
        c["time"] = json!(n);
        c["source_trade"] = if matches!(c["action"].as_str(), Some("RESERVE" | "RELEASE_RESERVED"))
        {
            Value::Null
        } else {
            json!(format!("trade-{n}"))
        };
        if c["action"] != "RESERVE" {
            let old = manager.snapshots().into_iter().next().ok_or("state")?;
            c["reservation"] = old["id"].clone();
            c["before_hash"] = json!(digest(&old));
            c["expected_version"] = old["version"].clone();
        }
        if c["action"] == "RELEASE_OCCUPIED" {
            c["source_order"] = json!("closing-order");
        }
        let result = manager.apply(&c)?.record();
        snapshots.push(result["after"].clone());
    }
    serde_json::to_writer(
        std::io::stdout().lock(),
        &json!({"snapshots":snapshots,"checkpoint":manager.checkpoint()}),
    )?;
    std::io::stdout().write_all(b"\n")?;
    Ok(())
}
