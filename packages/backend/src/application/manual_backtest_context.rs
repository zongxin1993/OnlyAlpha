//! Read-only, fixed-profile authoring defaults. No admission, work or frozen proof.
use crate::application::{private_strategy::{Definition,Draft},research_factor};
use onlyalpha_domain::{base::OnlyDomainModel,market::OnlyBarSemantic};
use onlyalpha_market_data_construction::OnlyConstructionRecipe;
use serde_json::{Value,json};
const INVALID:&str="BACKTEST_STRATEGY_CONTEXT_INVALID";
/// The approved BTC profile binds these four exact ports. Port names do not
/// authorize arbitrary historical inference; the bindings are saved explicitly.
pub(crate) fn btc_definition(factor:&Value)->Result<Definition,&'static str> {
    let bindings=json!({"close":{"input":"close","closed_only":true},
        "close_lag_20":{"input":"close","operator":"onlyalpha.operator.delay","semantic_version":"2","period":20,"closed_only":true},
        "volume":{"input":"volume","closed_only":true},
        "volume_mean_20":{"input":"volume","operator":"onlyalpha.operator.rolling_mean","semantic_version":"2","period":20,"closed_only":true}});
    let compiled=research_factor::compile_revision(factor,&bindings).map_err(|_|INVALID)?;
    let semantic=OnlyBarSemantic::from_record(&json!({"schema_version":3,"formation":{"schema_version":1,"kind":"FIXED_DURATION","window_minutes":1,"stride_minutes":1,"alignment":"SESSION_START"},"price_type":"LAST","adjustment_policy":"RAW"})).map_err(|_|INVALID)?;
    Definition::from_compiled_factor(&compiled,json!({"kind":"SINGLE_INSTRUMENT","instruments":["BTCUSDT.BINANCE"]}),json!({"schema_version":2,"data_kind":"BAR","bar_semantic":semantic.to_record(),"construction_requirement":{"schema_version":1,"kind":"EXACT_RECIPE","policy":null,"recipe":OnlyConstructionRecipe::native(semantic).to_record()},"observation_admission":"FINAL_ONLY"})).map_err(|_|INVALID)
}
pub(crate) fn choose_draft(definition:&Definition,id:&str,state:Option<&Value>)->Result<Value,&'static str> {
    if id.len()>4096 {return Err(INVALID);}
    crate::application::private_assets::id(id,"STRATEGY").map_err(|_|INVALID)?;
    if let Some(state)=state {
        let draft=Draft::new(state["draft"].clone()).map_err(|_|INVALID)?;
        if draft.strategy_id()!=id || draft.record()["definition"]!=definition.to_record(){return Err("BACKTEST_CONTEXT_STRATEGY_MISMATCH");}
        return Ok(draft.record().clone());
    }
    Ok(Draft::new(json!({"schema_version":1,"strategy_id":id,"semantic_version":"1","base_revision_fingerprint":null,"definition":definition.to_record(),"description":"BTCUSDT 一分钟价量动量多头","tags":[]})).map_err(|_|INVALID)?.record().clone())
}
#[cfg(test)]
mod tests;
