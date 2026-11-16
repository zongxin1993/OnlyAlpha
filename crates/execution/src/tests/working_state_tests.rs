use super::*;
use crate::{components::DATA_FORKS, support};
#[test]
fn exclusive_admission_does_not_fork_all_owners_and_normal_rejection_is_atomic() {
    let mut owner = WorkingState::new(support::config()).unwrap();
    DATA_FORKS.with(|n| n.set(0));
    owner.apply(&support::open(1, "BUY")).unwrap();
    assert_eq!(
        DATA_FORKS.with(|n| n.get()),
        0,
        "exclusive admission must not create a whole composition copy"
    );
    let mut config = support::config();
    config["initial_cash"] = json!("1.00");
    config["capitals"]["cluster"] = json!("1.00");
    let mut owner = WorkingState::new(config).unwrap();
    let before = owner.state().unwrap();
    DATA_FORKS.with(|n| n.set(0));
    assert_eq!(
        owner.apply(&support::open(1, "BUY")).unwrap_err().0,
        "EXECUTION_RISK_DENIED"
    );
    assert_eq!(owner.state().unwrap(), before);
    assert_eq!(owner.sequence(), 0);
    assert_eq!(DATA_FORKS.with(|n| n.get()), 0);
}

#[test]
fn full_account_history_denies_new_admission_without_mutating_any_owner() {
    let mut cfg = support::config();
    cfg["instruments"][0]["quantity_precision"] = json!(2);
    let mut owner = WorkingState::new(cfg).unwrap();
    let mut opening = support::open(1, "BUY");
    opening["payload"]["request"]["quantity"] =
        json!({"schema_version":1,"value":"4.00","precision":2});
    opening["payload"]["market"]["request_digest"] = json!(hash(&opening["payload"]["request"]));
    owner.apply(&opening).unwrap();
    owner.apply(&support::stage(2, 1, "UNKNOWN")).unwrap();
    let mut n = 3;
    for _ in 0..64 {
        owner
            .apply(&support::fill(n, 1, "0.05", "10.00", "1.00"))
            .unwrap();
        n += 1;
    }
    owner
        .apply(&support::fill(n, 1, "0.80", "10.00", "1.00"))
        .unwrap();
    n += 1;
    let mut full = false;
    for _ in 0..300 {
        let cp: Value =
            serde_json::from_slice(&owner.owners.account.checkpoint().unwrap().0).unwrap();
        let bytes = cp["journal"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.to_string().len())
            .sum::<usize>();
        if bytes > 4 * 1024 * 1024 {
            full = true;
            break;
        }
        let marks = json!([{"schema_version":1,"instrument":"600000.XSHG","mark":"10.00","source_ref":format!("capacity-mark-{n}"),"family":"CLOSED_BAR","version":n,"time":n,"as_of_sequence":n}]);
        let payload = json!({"schema_version":1,"valuation":format!("memory-cap-{n}"),"version":n,"economic_version":owner.owners.account.snapshot()["economic_version"],"position_evidence":owner.owners.payload_digest(1).unwrap(),"marks":marks});
        owner
            .apply(&support::input(n, "VALUATION", payload))
            .unwrap();
        n += 1;
    }
    assert!(
        full,
        "the actual Account journal must reach the unchanged admission budget"
    );
    let mut next = support::open(n, "BUY");
    next["payload"]["order"] = json!(support::order(2));
    next["payload"]["request"]["request_id"]["value"] = json!("request-2");
    next["payload"]["request"]["quantity"] =
        json!({"schema_version":1,"value":"4.00","precision":2});
    next["payload"]["fee_contract"] = support::fixture()["second_fee_contract"].clone();
    use onlyalpha_domain::{
        base::OnlyDomainModel,
        fee::{OnlyOrderFeePolicyBinding, OnlyOrderFeePolicyBindingInput},
        time::OnlyTimestamp,
    };
    let original =
        OnlyOrderFeePolicyBinding::from_record(&next["payload"]["fee_contract"]["binding"])
            .unwrap();
    let rebound = OnlyOrderFeePolicyBinding::create(OnlyOrderFeePolicyBindingInput {
        runtime_id: original.runtime_id().clone(),
        account_id: original.account_id().clone(),
        cluster_id: original.cluster_id().clone(),
        order_id: original.order_id().clone(),
        instrument_id: original.instrument_id().clone(),
        market_product_id: original.market_product_id().clone(),
        market_product_version: original.market_product_version().clone(),
        market_fee_pack: original.market_fee_pack().clone(),
        broker_fee_contract: original.broker_fee_contract().clone(),
        applicability_scope: original.applicability_scope().clone(),
        order_fixed_schedules: original.order_fixed_schedules().clone(),
        fill_effective_families: original.fill_effective_families().clone(),
        charge_currency: original.charge_currency().clone(),
        bound_at: OnlyTimestamp::from_unix_nanos(n.into()),
        fingerprint: String::new(),
    })
    .unwrap();
    next["payload"]["fee_contract"]["binding"] = rebound.to_record();
    for key in ["expected", "maximum"] {
        next["payload"]["fee_contract"]["estimate"][key]["binding"] = rebound.to_record();
    }
    next["payload"]["fee_contract"]["funding"]["binding_fingerprint"] =
        json!(rebound.fingerprint());

    next["payload"]["fee_contract"]["funding"]["principal_reservation"]["amount"] = json!("40.00");
    next["payload"]["fee_contract"]["funding"]["total_reservation"]["amount"] = json!("40.00");
    next["payload"]["market"]["request_digest"] = json!(hash(&next["payload"]["request"]));
    let before = owner.state().unwrap();
    let prefix = owner.sequence();
    DATA_FORKS.with(|c| c.set(0));
    assert_eq!(
        owner.apply(&next).unwrap_err().0,
        "EXECUTION_ACCOUNT_CAPACITY_DENIED"
    );
    assert_eq!(owner.sequence(), prefix);
    assert_eq!(owner.state().unwrap(), before);
    assert_eq!(DATA_FORKS.with(|c| c.get()), 0);
}
