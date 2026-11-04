use onlyalpha_position::{Manager, ValuationEffect};
use serde_json::{Value, json};
use std::io::{self, Read};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut data = String::new();
    io::stdin().read_to_string(&mut data)?;
    let mut outputs = vec![];
    for line in data.lines() {
        let case: Value = serde_json::from_str(line)?;
        let config = json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"generation","currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"clusters":["a","b"],"instruments":[{"schema_version":1,"id":"BTCUSDT.BINANCE","price_precision":8,"quantity_precision":8,"multiplier":case["multiplier"]}]});
        let mut owner = Manager::new(config)?;
        for (n, t) in case["trades"]
            .as_array()
            .ok_or("trades")?
            .iter()
            .enumerate()
        {
            let command = json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"generation","command_id":format!("trade-{n}"),"cause":"a".repeat(64),"time":n+1,"op":"TRADE","payload":{"schema_version":1,"instrument":"BTCUSDT.BINANCE","cluster":t[0],"order":format!("order-{n}"),"trade":format!("trade-{n}"),"venue_trade":format!("venue-{n}"),"execution":format!("execution-{n}"),"sequence":n+1,"side":"BUY","position_side":"LONG","position_mode":"NETTING","price":t[1],"quantity":t[2],"fee":"0.00","bucket":"SETTLED","terminal_fill":false}});
            owner.apply(&command)?;
        }
        let intent = json!({"schema_version":1,"valuation":"v","version":1,"economic_version":0,"position_evidence":owner.checkpoint()?.1,"time":100,"marks":[{"schema_version":1,"instrument":"BTCUSDT.BINANCE","mark":case["mark"],"source_ref":"closed-bar","family":"CLOSED_BAR","version":1,"time":100,"as_of_sequence":100}]});
        let effect = owner.value(&intent)?;
        let replay = ValuationEffect::rederive(&effect.replay_input())?;
        assert_eq!(replay.record(), effect.record());
        let result = effect.record();
        outputs.push(json!({"case":case["case"],"market":result["market_value"],"unrealized":result["unrealized_pnl"]}));
    }
    println!("{}", serde_json::to_string(&outputs)?);
    Ok(())
}
