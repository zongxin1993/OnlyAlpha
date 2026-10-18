use onlyalpha_domain::{
    base::OnlyDomainModel,
    execution::{OnlyOrderFill, OnlyOrderSnapshot},
    market::{OnlyBar, OnlyQuoteTick, OnlyReferencePriceFact},
};
#[test]
fn independent_facts_preserve_authority_and_reject_structural_mutations() {
    for line in include_str!("../../../../test-data/domain/fact-records-v1.jsonl").lines() {
        let row: serde_json::Value = serde_json::from_str(line).unwrap();
        let result = match row["type"].as_str().unwrap() {
            "OnlyOrderSnapshot" => {
                OnlyOrderSnapshot::from_record(&row["record"]).map(|fact| fact.to_record())
            }
            "OnlyOrderFill" => {
                OnlyOrderFill::from_record(&row["record"]).map(|fact| fact.to_record())
            }
            "OnlyBar" => OnlyBar::from_record(&row["record"]).map(|fact| fact.to_record()),
            "OnlyQuoteTick" => {
                OnlyQuoteTick::from_record(&row["record"]).map(|fact| fact.to_record())
            }
            "OnlyReferencePriceFact" => {
                OnlyReferencePriceFact::from_record(&row["record"]).map(|fact| fact.to_record())
            }
            _ => panic!("unrecognized shared vector type"),
        };
        if row.get("error").is_some() {
            assert!(result.is_err(), "{}", row["id"]);
        } else {
            assert_eq!(result.unwrap(), row["record"], "{}", row["id"]);
        }
    }
}
