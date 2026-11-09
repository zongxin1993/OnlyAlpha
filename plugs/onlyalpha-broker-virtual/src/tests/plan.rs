use super::*;
use serde_json::json;

#[test]
fn last_ratio_step_receives_the_full_rounding_remainder() {
    let policy = json!({"mode":"SCHEDULE","dispatch_mode":"ONE_PER_BAR","steps":[
        {"bar_offset":1,"ratio":"0.30"},{"bar_offset":2,"ratio":"0.40"},{"bar_offset":3,"ratio":"0.30"}
    ]});
    let quantity = json!({"schema_version":1,"value":"101","precision":0});
    assert_eq!(
        steps(&policy, &quantity).unwrap(),
        [(1, "30".into()), (2, "40".into()), (3, "31".into())]
    );
}

#[test]
fn quantity_maximum_and_whole_share_the_same_conserved_steps() {
    let q = json!({"schema_version":1,"value":"1000","precision":0});
    let cap = json!("300");
    let max = policy(&json!({}), &[&cap]).unwrap();
    assert_eq!(
        steps(&max, &q).unwrap(),
        [
            (1, "300".into()),
            (2, "300".into()),
            (3, "300".into()),
            (4, "100".into())
        ]
    );
    let whole = policy(&json!({}), &[]).unwrap();
    assert_eq!(steps(&whole, &q).unwrap(), [(1, "1000".into())]);
    let spec = json!({"mode":"SCHEDULE","steps":[{"bar_offset":1,"quantity":"300"},{"bar_offset":2,"quantity":"400"},{"bar_offset":3,"quantity":"300"}]});
    let by_quantity = policy(&spec, &[]).unwrap();
    assert_eq!(
        steps(&by_quantity, &q).unwrap(),
        [(1, "300".into()), (2, "400".into()), (3, "300".into())]
    );
    assert!(steps(&by_quantity, &json!({"value":"999","precision":0})).is_err());
    assert!(steps(&by_quantity, &json!({"value":"1001","precision":0})).is_err());
}

#[test]
fn configuration_rejects_ambiguous_and_unordered_steps() {
    for specs in [
        json!([]),
        json!([{"bar_offset":0,"ratio":"1"}]),
        json!([{"bar_offset":1,"ratio":"1","quantity":"10"}]),
        json!([{"bar_offset":1,"ratio":"0.4"},{"bar_offset":2,"ratio":"0.5"}]),
        json!([{"bar_offset":1,"ratio":"0.5"},{"bar_offset":2,"quantity":"50"}]),
        json!([{"bar_offset":2,"ratio":"0.5"},{"bar_offset":1,"ratio":"0.5"}]),
        json!([{"bar_offset":1,"ratio":"0.5"},{"bar_offset":1,"ratio":"0.5"}]),
        json!([{"bar_offset":1,"ratio":"1","unknown":true}]),
    ] {
        assert!(policy(&json!({"mode":"SCHEDULE","steps":specs}), &[]).is_err());
    }
    assert!(policy(&json!({"mode":"WHOLE"}), &[&json!("100")]).is_err());
    assert!(policy(&json!({"mode":"MAX_PER_BAR"}), &[]).is_err());
    assert!(policy(&json!({"unknown":true}), &[]).is_err());
    let p=policy(&json!({"mode":"SCHEDULE","steps":[{"bar_offset":1,"ratio":"0.1"},{"bar_offset":2,"ratio":"0.9"}]}),&[]).unwrap();
    assert!(steps(&p, &json!({"value":"1","precision":0})).is_err());
}
