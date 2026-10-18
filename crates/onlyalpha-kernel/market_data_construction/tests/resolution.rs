mod support;
use onlyalpha_domain::base::OnlyDomainModel;
use onlyalpha_market_data_construction::*;
use serde_json::json;
use support::*;
fn context() -> OnlyConstructionResolutionContext {
    OnlyConstructionResolutionContext::new(
        "source",
        kind(A, 1).instrument_id().clone(),
        &"a".repeat(64),
        "calendar",
    )
    .unwrap()
}
fn cap(window: u32, origin: i64) -> OnlyConstructionCapability {
    OnlyConstructionCapability::new(
        kind(A, window).semantic().clone(),
        true,
        true,
        "calendar",
        Some(origin.into()),
    )
    .unwrap()
}
#[test]
fn exact_resolution_never_substitutes() {
    let target = kind(A, 3).semantic().clone();
    let resolved = OnlyConstructionResolutionPlan::resolve(
        target.clone(),
        &[cap(1, -1), cap(3, 0)],
        context(),
        OnlyConstructionRequirement::PreferExactNative,
    )
    .unwrap();
    assert!(resolved.recipe().is_native());
    let derived = OnlyConstructionResolutionPlan::resolve(
        target.clone(),
        &[cap(1, -1)],
        context(),
        OnlyConstructionRequirement::PreferExactNative,
    )
    .unwrap();
    assert!(!derived.recipe().is_native());
    assert_eq!(derived.grid_origin(), &59999999999i64.into());
    assert!(
        OnlyConstructionResolutionPlan::resolve(
            target.clone(),
            &[cap(1, 0)],
            context(),
            OnlyConstructionRequirement::Exact(OnlyConstructionRecipe::native(target.clone()))
        )
        .is_err()
    );
    assert!(
        OnlyConstructionResolutionPlan::resolve(
            target.clone(),
            &[cap(3, 0), cap(3, 0)],
            context(),
            OnlyConstructionRequirement::PreferExactNative
        )
        .is_err()
    );
    let record = derived.to_record();
    assert_eq!(
        OnlyConstructionResolutionPlan::from_record(&record).unwrap(),
        derived
    );
    let mut bad = record.clone();
    bad["grid_origin_ns"] = json!(true);
    assert!(OnlyConstructionResolutionPlan::from_record(&bad).is_err());
    let mut bad = record.clone();
    bad["target_semantic"] = cap(1, 0).semantic().to_record();
    assert!(OnlyConstructionResolutionPlan::from_record(&bad).is_err());
}
#[test]
fn construction_lineage_and_current_fields_are_strict() {
    let target = kind(A, 3).semantic().clone();
    let plan = OnlyConstructionResolutionPlan::resolve(
        target,
        &[cap(1, 0)],
        context(),
        OnlyConstructionRequirement::PreferExactNative,
    )
    .unwrap();
    assert!(OnlyConstructionIdentity::new(plan.clone(), "data", None, None, None).is_err());
    let base = OnlyConstructionBaseRevision::new("revision", &"b".repeat(64), "seal").unwrap();
    let identity = OnlyConstructionIdentity::new(plan, "data", None, Some(base), None).unwrap();
    let record = identity.to_record();
    assert_eq!(
        OnlyConstructionIdentity::from_record(&record).unwrap(),
        identity
    );
    let mut bad = record.clone();
    bad["base_seal_id"] = json!(null);
    assert!(OnlyConstructionIdentity::from_record(&bad).is_err());
    let mut bad = record;
    bad["extra"] = json!(0);
    assert!(OnlyConstructionIdentity::from_record(&bad).is_err());
    let native = OnlyConstructionResolutionPlan::resolve(
        kind(A, 3).semantic().clone(),
        &[cap(3, 0)],
        context(),
        OnlyConstructionRequirement::PreferExactNative,
    )
    .unwrap();
    assert!(
        OnlyConstructionIdentity::new(
            native,
            "data",
            None,
            Some(OnlyConstructionBaseRevision::new("r", &"b".repeat(64), "s").unwrap()),
            None
        )
        .is_err()
    );
}
#[test]
fn fixed_grid_ends_are_exact_and_budgeted() {
    let semantic = kind(A, 3).semantic().clone();
    assert_eq!(
        only_construction_expected_ends(
            &semantic,
            (-180000000000i64).into(),
            180000000000i64.into(),
            0.into(),
            10
        )
        .unwrap(),
        vec![0.into(), 180000000000i64.into()]
    );
    assert!(
        only_construction_expected_ends(&semantic, 0.into(), 1800000000000i64.into(), 0.into(), 2)
            .is_err()
    );
    assert!(
        only_construction_expected_ends(&semantic, 1.into(), 180000000000i64.into(), 0.into(), 10)
            .unwrap()
            .is_empty()
    );
}
#[test]
fn plan_reader_rejects_unnormalized_grid_even_with_valid_hash() {
    use sha2::{Digest, Sha256};
    let plan = OnlyConstructionResolutionPlan::resolve(
        kind(A, 3).semantic().clone(),
        &[cap(1, 0)],
        context(),
        OnlyConstructionRequirement::PreferExactNative,
    )
    .unwrap();
    let mut row = plan.to_record();
    row["grid_origin_ns"] = json!(60000000000i64);
    row.as_object_mut().unwrap().remove("fingerprint");
    let fingerprint: String = Sha256::digest(serde_json::to_vec(&row).unwrap())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    row["fingerprint"] = fingerprint.into();
    assert!(OnlyConstructionResolutionPlan::from_record(&row).is_err());
}
