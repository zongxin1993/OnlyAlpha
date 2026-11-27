//! Canonical operator identity and semantic contract.
//!
//! One row per built-in operator owns the canonical type id, arity, parameter
//! shape, execution shape and warmup rule. Numeric semantics stay in
//! [`crate::algebra`]; this module adds no second implementation and no I/O.
use crate::algebra::Operator;
use std::num::NonZeroUsize;

pub const TYPE_ID_PREFIX: &str = "onlyalpha.operator.";
pub const SEMANTIC_VERSION: &str = "2";
pub const NUMERIC_POLICY: &str = "DECIMAL28_HALF_EVEN_Q12_V1";

/// Configurable parameter contract of one operator.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ParameterKind {
    None,
    /// Positive integer lookback `period`.
    Period,
    /// Decimal `factor`, defaulting to one.
    Factor,
    /// `HIGHER_IS_BETTER` / `LOWER_IS_BETTER` direction; ties are averaged.
    PercentileDirection,
}

/// Whether outputs are produced per series or across one bound event plane.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ExecutionShape {
    TimeSeries,
    CrossSection,
}

/// How many observations must precede the first output.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WarmupRule {
    /// First observation already produces an output; no cross-event state.
    Current,
    /// `period` observations inclusive of the current one.
    Window,
    /// `period` prior observations plus the current one.
    Lag,
    /// First non-null observation seeds a stateful recurrence.
    Recursive,
    /// First `period` non-null observations seed a stateful recurrence.
    SeededWindow,
}

/// What an execution engine must retain between events.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StateCapability {
    Stateless,
    Checkpointable,
    ResearchOnly,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct OpSpec {
    pub name: &'static str,
    pub operator: Operator,
    pub inputs: usize,
    pub parameter: ParameterKind,
    pub shape: ExecutionShape,
    pub warmup: WarmupRule,
}

impl OpSpec {
    pub fn type_id(self) -> String {
        format!("{TYPE_ID_PREFIX}{}", self.name)
    }

    /// Time-series kernels can carry state across events; a cross-section plane
    /// is only meaningful as one complete research batch.
    pub fn state(self) -> StateCapability {
        match self.shape {
            ExecutionShape::CrossSection => StateCapability::ResearchOnly,
            ExecutionShape::TimeSeries => match self.warmup {
                WarmupRule::Current => StateCapability::Stateless,
                WarmupRule::Window
                | WarmupRule::Lag
                | WarmupRule::Recursive
                | WarmupRule::SeededWindow => StateCapability::Checkpointable,
            },
        }
    }

    /// Number of observations, current one included, required before the first
    /// output. `None` means a period-based operator was given no period.
    pub fn minimum_observations(self, period: Option<NonZeroUsize>) -> Option<usize> {
        match self.warmup {
            WarmupRule::Current | WarmupRule::Recursive => Some(1),
            WarmupRule::Window | WarmupRule::SeededWindow => period.map(NonZeroUsize::get),
            WarmupRule::Lag => period.map(|p| p.get() + 1),
        }
    }
}

const fn spec(
    name: &'static str,
    operator: Operator,
    inputs: usize,
    parameter: ParameterKind,
    shape: ExecutionShape,
    warmup: WarmupRule,
) -> OpSpec {
    OpSpec {
        name,
        operator,
        inputs,
        parameter,
        shape,
        warmup,
    }
}

pub static REGISTRY: [OpSpec; 30] = [
    spec(
        "add",
        Operator::Add,
        2,
        ParameterKind::None,
        ExecutionShape::TimeSeries,
        WarmupRule::Current,
    ),
    spec(
        "subtract",
        Operator::Subtract,
        2,
        ParameterKind::None,
        ExecutionShape::TimeSeries,
        WarmupRule::Current,
    ),
    spec(
        "multiply",
        Operator::Multiply,
        2,
        ParameterKind::None,
        ExecutionShape::TimeSeries,
        WarmupRule::Current,
    ),
    spec(
        "divide",
        Operator::Divide,
        2,
        ParameterKind::None,
        ExecutionShape::TimeSeries,
        WarmupRule::Current,
    ),
    spec(
        "abs",
        Operator::Abs,
        1,
        ParameterKind::None,
        ExecutionShape::TimeSeries,
        WarmupRule::Current,
    ),
    spec(
        "sign",
        Operator::Sign,
        1,
        ParameterKind::None,
        ExecutionShape::TimeSeries,
        WarmupRule::Current,
    ),
    spec(
        "log",
        Operator::Log,
        1,
        ParameterKind::None,
        ExecutionShape::TimeSeries,
        WarmupRule::Current,
    ),
    spec(
        "delay",
        Operator::Delay,
        1,
        ParameterKind::Period,
        ExecutionShape::TimeSeries,
        WarmupRule::Lag,
    ),
    spec(
        "delta",
        Operator::Delta,
        1,
        ParameterKind::Period,
        ExecutionShape::TimeSeries,
        WarmupRule::Lag,
    ),
    spec(
        "rolling_mean",
        Operator::RollingMean,
        1,
        ParameterKind::Period,
        ExecutionShape::TimeSeries,
        WarmupRule::Window,
    ),
    spec(
        "rolling_sum",
        Operator::RollingSum,
        1,
        ParameterKind::Period,
        ExecutionShape::TimeSeries,
        WarmupRule::Window,
    ),
    spec(
        "rolling_std",
        Operator::RollingStd,
        1,
        ParameterKind::Period,
        ExecutionShape::TimeSeries,
        WarmupRule::Window,
    ),
    spec(
        "rolling_var",
        Operator::RollingVar,
        1,
        ParameterKind::Period,
        ExecutionShape::TimeSeries,
        WarmupRule::Window,
    ),
    spec(
        "rolling_min",
        Operator::RollingMin,
        1,
        ParameterKind::Period,
        ExecutionShape::TimeSeries,
        WarmupRule::Window,
    ),
    spec(
        "rolling_max",
        Operator::RollingMax,
        1,
        ParameterKind::Period,
        ExecutionShape::TimeSeries,
        WarmupRule::Window,
    ),
    spec(
        "rolling_covariance",
        Operator::RollingCovariance,
        2,
        ParameterKind::Period,
        ExecutionShape::TimeSeries,
        WarmupRule::Window,
    ),
    spec(
        "rolling_correlation",
        Operator::RollingCorrelation,
        2,
        ParameterKind::Period,
        ExecutionShape::TimeSeries,
        WarmupRule::Window,
    ),
    spec(
        "ts_rank",
        Operator::TSRank,
        1,
        ParameterKind::Period,
        ExecutionShape::TimeSeries,
        WarmupRule::Window,
    ),
    spec(
        "scale",
        Operator::Scale,
        1,
        ParameterKind::Factor,
        ExecutionShape::TimeSeries,
        WarmupRule::Current,
    ),
    spec(
        "decay_linear",
        Operator::DecayLinear,
        1,
        ParameterKind::Period,
        ExecutionShape::TimeSeries,
        WarmupRule::Window,
    ),
    spec(
        "where",
        Operator::Where,
        3,
        ParameterKind::None,
        ExecutionShape::TimeSeries,
        WarmupRule::Current,
    ),
    spec(
        "rolling_slope",
        Operator::RollingSlope,
        1,
        ParameterKind::Period,
        ExecutionShape::TimeSeries,
        WarmupRule::Window,
    ),
    spec(
        "ema",
        Operator::EMA,
        1,
        ParameterKind::Period,
        ExecutionShape::TimeSeries,
        WarmupRule::Recursive,
    ),
    spec(
        "rma",
        Operator::RMA,
        1,
        ParameterKind::Period,
        ExecutionShape::TimeSeries,
        WarmupRule::SeededWindow,
    ),
    spec(
        "cumsum",
        Operator::CumSum,
        1,
        ParameterKind::None,
        ExecutionShape::TimeSeries,
        WarmupRule::Recursive,
    ),
    spec(
        "cross_section_percentile",
        Operator::CrossSectionPercentile,
        1,
        ParameterKind::PercentileDirection,
        ExecutionShape::CrossSection,
        WarmupRule::Current,
    ),
    spec(
        "cross_section_rank",
        Operator::CrossSectionRank,
        1,
        ParameterKind::None,
        ExecutionShape::CrossSection,
        WarmupRule::Current,
    ),
    spec(
        "cross_section_zscore",
        Operator::CrossSectionZScore,
        1,
        ParameterKind::None,
        ExecutionShape::CrossSection,
        WarmupRule::Current,
    ),
    spec(
        "cross_section_demean",
        Operator::CrossSectionDemean,
        1,
        ParameterKind::None,
        ExecutionShape::CrossSection,
        WarmupRule::Current,
    ),
    spec(
        "cross_section_correlation",
        Operator::CrossSectionCorrelation,
        2,
        ParameterKind::None,
        ExecutionShape::CrossSection,
        WarmupRule::Current,
    ),
];

pub fn all() -> &'static [OpSpec] {
    &REGISTRY
}

pub fn lookup(type_id: &str) -> Option<&'static OpSpec> {
    let name = type_id.strip_prefix(TYPE_ID_PREFIX)?;
    REGISTRY.iter().find(|spec| spec.name == name)
}

impl Operator {
    pub fn spec(self) -> &'static OpSpec {
        REGISTRY
            .iter()
            .find(|spec| spec.operator == self)
            .expect("every operator variant is registered")
    }

    pub fn type_id(self) -> String {
        self.spec().type_id()
    }

    pub fn from_type_id(type_id: &str) -> Option<Self> {
        lookup(type_id).map(|spec| spec.operator)
    }

    pub fn input_count(self) -> usize {
        self.spec().inputs
    }

    pub fn needs_period(self) -> bool {
        self.spec().parameter == ParameterKind::Period
    }

    pub fn is_cross_section(self) -> bool {
        self.spec().shape == ExecutionShape::CrossSection
    }
}
