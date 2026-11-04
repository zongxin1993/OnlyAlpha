use onlyalpha_broker::Fact;
use serde_json::{Value, json};
use std::io::{self, Read};
fn main() {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).unwrap();
    let cases: Value = serde_json::from_str(&input).unwrap();
    let result = cases
        .as_array()
        .unwrap()
        .iter()
        .map(|v| {
            let f = Fact::decode(&v["fact"]).unwrap();
            json!({"identity":f.identity(),"fingerprint":f.fingerprint()})
        })
        .collect::<Vec<_>>();
    println!("{}", json!(result));
}
