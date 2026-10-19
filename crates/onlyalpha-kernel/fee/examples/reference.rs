use onlyalpha_fee::{Catalog, Manager, digest};
use serde_json::{Value, json};
use std::{
    io::{self, Read},
    str::FromStr,
};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut bytes = String::new();
    io::stdin().read_to_string(&mut bytes)?;
    let v: Value = serde_json::from_str(&bytes)?;
    let f = &v["fixture"];
    let catalog = Catalog::new(f["catalog"].clone())?;
    let binding = catalog.bind(f["subject"].clone(), 1)?;
    let mut config = f["subject"].clone();
    config.as_object_mut().ok_or("subject")?.retain(|k, _| {
        [
            "engine",
            "runtime",
            "account",
            "gateway",
            "runtime_kind",
            "generation",
        ]
        .contains(&k.as_str())
    });
    let mut m = Manager::new(config, 64)?;
    if !v["checkpoint"].is_null() {
        m.restore(&v["checkpoint"], &digest(&v["checkpoint"]))?;
    }
    let mut results = Vec::new();
    for s in f["steps"]
        .as_array()
        .ok_or("steps")?
        .iter()
        .skip(v["offset"].as_u64().unwrap_or(0) as usize)
        .take(v["count"].as_u64().unwrap_or(u64::MAX) as usize)
    {
        let a = catalog.assess(
            &binding,
            s["day"].as_u64().ok_or("day")?,
            s["trade"].as_str().ok_or("trade")?,
            bigdecimal::num_bigint::BigInt::from_str(&s["time"].to_string())?,
            s["fill"].clone(),
            s["cumulative"].clone(),
            None,
        )?;
        results.push(m.apply(&a)?.record());
    }
    println!(
        "{}",
        json!({"applications":results,"checkpoint":m.checkpoint()})
    );
    Ok(())
}
