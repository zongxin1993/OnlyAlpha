use onlyalpha_domain::{
    base::OnlyDomainModel,
    enums::{OnlyOffset, OnlyOrderSide},
    trading::{
        OnlyCloseScope, OnlyExecutionIntent, OnlyExposureConstraint, OnlyPositionEffect,
        OnlyPositionMode, OnlyPositionSide,
    },
};
#[test]
fn normalized_intents_preserve_direction_scope_and_strict_records() {
    use OnlyOffset::{Close, CloseToday, CloseYesterday, None, Open};
    use OnlyOrderSide::{Buy, Sell};
    for side in [Buy, Sell] {
        for offset in [None, Open, Close, CloseToday, CloseYesterday] {
            let intent = OnlyExecutionIntent::from_offset(side, offset, Option::None).unwrap();
            assert_eq!(intent.side(), side);
            assert_eq!(
                intent.reduces_exposure(),
                offset != Open && !(offset == None && side == Buy)
            );
            assert_eq!(
                intent.close_scope(),
                match offset {
                    CloseToday => OnlyCloseScope::Today,
                    CloseYesterday => OnlyCloseScope::Yesterday,
                    _ => OnlyCloseScope::Any,
                }
            );
            assert_eq!(
                OnlyExecutionIntent::from_json(&intent.to_json().unwrap()).unwrap(),
                intent
            );
        }
    }
    assert!(
        OnlyExecutionIntent::new(
            Buy,
            OnlyPositionSide::Short,
            OnlyPositionEffect::Open,
            OnlyCloseScope::Any,
            OnlyExposureConstraint::None,
            OnlyPositionMode::Netting
        )
        .is_err()
    );
    assert!(
        OnlyExecutionIntent::new(
            Buy,
            OnlyPositionSide::Long,
            OnlyPositionEffect::Open,
            OnlyCloseScope::Any,
            OnlyExposureConstraint::ReduceOnly,
            OnlyPositionMode::Netting
        )
        .is_err()
    );
    assert!(
        OnlyExecutionIntent::new(
            Sell,
            OnlyPositionSide::Flat,
            OnlyPositionEffect::Close,
            OnlyCloseScope::Any,
            OnlyExposureConstraint::None,
            OnlyPositionMode::Netting
        )
        .is_err()
    );
}
