use super::*;
fn reference() -> Value { serde_json::from_str(include_str!("../../../tests/application/fixtures/research_factor.json")).unwrap() }
#[test]
fn btc_defaults_write_actual_fixed_bindings_and_exact_factor_dependency() {
    let factor=reference()["revision"].clone();
    let value=btc_definition(&factor).unwrap().to_record();
    assert_eq!(value["factor_revision_dependencies"],json!([{"factor_id":factor["factor_id"],"revision_fingerprint":factor["revision_fingerprint"]}]));
    let nodes=value["calculations"].as_array().unwrap();
    assert_eq!(nodes.len(),3);
    assert!(nodes.iter().any(|node|node["type_reference"]["type_id"]=="onlyalpha.operator.delay" && node["parameters"]["period"]["value"]["value"]==20));
    assert!(nodes.iter().any(|node|node["type_reference"]["type_id"]=="onlyalpha.operator.rolling_mean" && node["parameters"]["period"]["value"]["value"]==20));
    for node in nodes {
        let reference=&node["type_reference"];
        assert_eq!(reference["semantic_version"],if reference["kind"]=="INDICATOR" {"2"} else {"1"});
    }
    assert_eq!(value["signals"]["entry"]["right"]["value"]["value"],"0.001");
    assert_eq!(value["signals"]["exit"]["right"]["value"]["value"],"0");
    assert_eq!(value["universe"]["instruments"],json!(["BTCUSDT.BINANCE"]));
}
#[test]
fn a_different_alias_or_contract_cannot_silently_choose_another_lookback() {
    use crate::application::private_assets::authoring::Draft as FactorDraft;
    for mode in ["period", "missing", "extra", "type", "output"] {
        let mut draft=reference()["draft"].clone();
        match mode {
            "period"=>{let value=draft["input_contract"].as_object_mut().unwrap().remove("close_lag_20").unwrap();draft["input_contract"]["close_lag_21"]=value;},
            "missing"=>{draft["input_contract"].as_object_mut().unwrap().remove("volume");},
            "extra"=>draft["input_contract"]["open"]=json!({"type":"DECIMAL","missing":true}),
            "type"=>draft["input_contract"]["close"]["type"]=json!("INTEGER"),
            _=>draft["output_contract"]["value"]["type"]=json!("INTEGER"),
        }
        let revision=FactorDraft::new(draft).unwrap().revision().unwrap();
        assert!(btc_definition(&revision).is_err(),"{mode}");
    }
}
#[test]
fn existing_strategy_defaults_are_reused_only_for_the_same_actual_definition() {
    let definition=btc_definition(&reference()["revision"]).unwrap();
    let draft=choose_draft(&definition,"private.strategy.btc_momentum",None).unwrap();
    assert_eq!(choose_draft(&definition,"private.strategy.btc_momentum",Some(&json!({"draft":draft}))).unwrap(),draft);
    let mut changed=draft.clone();changed["definition"]["signals"]["entry"]["right"]["value"]["value"]=json!("0.002");
    assert!(choose_draft(&definition,"private.strategy.btc_momentum",Some(&json!({"draft":changed}))).is_err());
}
