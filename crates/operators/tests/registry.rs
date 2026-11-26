use onlyalpha_operators::algebra::Operator;
use onlyalpha_operators::registry::{
    ExecutionShape, NUMERIC_POLICY, ParameterKind, REGISTRY, SEMANTIC_VERSION, StateCapability,
    TYPE_ID_PREFIX, WarmupRule, all, lookup,
};
use std::collections::BTreeSet;
use std::num::NonZeroUsize;

const EVERY_OPERATOR: [Operator; 29] = [
    Operator::Add,
    Operator::Subtract,
    Operator::Multiply,
    Operator::Divide,
    Operator::Abs,
    Operator::Sign,
    Operator::Log,
    Operator::Delay,
    Operator::Delta,
    Operator::RollingMean,
    Operator::RollingSum,
    Operator::RollingStd,
    Operator::RollingVar,
    Operator::RollingMin,
    Operator::RollingMax,
    Operator::RollingCovariance,
    Operator::RollingCorrelation,
    Operator::TSRank,
    Operator::Scale,
    Operator::DecayLinear,
    Operator::Where,
    Operator::RollingSlope,
    Operator::EMA,
    Operator::RMA,
    Operator::CumSum,
    Operator::CrossSectionPercentile,
    Operator::CrossSectionRank,
    Operator::CrossSectionZScore,
    Operator::CrossSectionDemean,
];

#[test]
fn registry_owns_one_row_per_operator_with_unique_identity() {
    assert_eq!(REGISTRY.len(), EVERY_OPERATOR.len());
    assert_eq!(all().len(), 29);
    let names = REGISTRY
        .iter()
        .map(|spec| spec.name)
        .collect::<BTreeSet<_>>();
    assert_eq!(names.len(), REGISTRY.len());
    for operator in EVERY_OPERATOR {
        assert_eq!(
            REGISTRY
                .iter()
                .filter(|spec| spec.operator == operator)
                .count(),
            1,
            "{operator:?} must have exactly one row"
        );
        assert_eq!(operator.spec().operator, operator);
        assert_eq!(Operator::from_type_id(&operator.type_id()), Some(operator));
    }
}

#[test]
fn canonical_type_ids_require_the_exact_prefix_and_name() {
    assert_eq!(TYPE_ID_PREFIX, "onlyalpha.operator.");
    assert_eq!(SEMANTIC_VERSION, "2");
    assert_eq!(NUMERIC_POLICY, "DECIMAL28_HALF_EVEN_Q12_V1");
    assert_eq!(
        Operator::RollingMean.type_id(),
        "onlyalpha.operator.rolling_mean"
    );
    assert_eq!(
        lookup("onlyalpha.operator.rolling_mean").map(|spec| spec.operator),
        Some(Operator::RollingMean)
    );
    assert!(lookup("rolling_mean").is_none());
    assert!(lookup("onlyalpha.operator.unknown").is_none());
    assert!(lookup("onlyalpha.operator.rolling_mean ").is_none());
    assert!(Operator::from_type_id("onlyalpha.operator.add").is_some());
}

#[test]
fn state_capabilities_follow_shape_and_warmup() {
    let count = |capability| {
        REGISTRY
            .iter()
            .filter(|spec| spec.state() == capability)
            .map(|spec| spec.name)
            .collect::<Vec<_>>()
    };
    let mut stateless = count(StateCapability::Stateless);
    stateless.sort_unstable();
    assert_eq!(
        stateless,
        [
            "abs", "add", "divide", "log", "multiply", "scale", "sign", "subtract", "where"
        ]
    );
    assert_eq!(count(StateCapability::Checkpointable).len(), 16);
    let mut research_only = count(StateCapability::ResearchOnly);
    research_only.sort_unstable();
    assert_eq!(
        research_only,
        [
            "cross_section_demean",
            "cross_section_percentile",
            "cross_section_rank",
            "cross_section_zscore"
        ]
    );
}

#[test]
fn minimum_observations_encode_warmup_without_off_by_one_ambiguity() {
    let three = NonZeroUsize::new(3);
    let observations = |operator: Operator| operator.spec().minimum_observations(three);
    assert_eq!(observations(Operator::Add), Some(1));
    assert_eq!(observations(Operator::Scale), Some(1));
    assert_eq!(observations(Operator::Delay), Some(4));
    assert_eq!(observations(Operator::Delta), Some(4));
    assert_eq!(observations(Operator::RollingMean), Some(3));
    assert_eq!(observations(Operator::RollingCorrelation), Some(3));
    assert_eq!(observations(Operator::DecayLinear), Some(3));
    assert_eq!(
        Operator::RollingMean.spec().minimum_observations(None),
        None
    );
    assert_eq!(Operator::Delay.spec().minimum_observations(None), None);
    assert_eq!(
        Operator::Delay.spec().warmup,
        WarmupRule::Lag,
        "lag operators read a strictly prior observation"
    );
    assert_eq!(Operator::RollingMean.spec().warmup, WarmupRule::Window);
    assert_eq!(Operator::Add.spec().warmup, WarmupRule::Current);
}

#[test]
fn parameter_shape_and_arity_match_the_numeric_kernel() {
    for spec in REGISTRY {
        let period = NonZeroUsize::new(3).filter(|_| spec.parameter == ParameterKind::Period);
        let kernel = onlyalpha_operators::algebra::Kernel::new(
            spec.operator,
            onlyalpha_operators::algebra::Parameters {
                period,
                ..Default::default()
            },
        )
        .unwrap_or_else(|error| panic!("{} rejected valid parameters: {error:?}", spec.name));
        assert_eq!(
            kernel.history_limit(),
            spec.minimum_observations(period).unwrap()
        );
        assert_eq!(spec.inputs, spec.operator.input_count());
        assert_eq!(
            spec.shape == ExecutionShape::CrossSection,
            spec.operator.is_cross_section()
        );
        assert_eq!(
            spec.parameter == ParameterKind::Period,
            spec.operator.needs_period()
        );
    }
}
