//! Stateless, nullable Boolean semantics from the version-1 Predicate Contract.
//!
//! Numeric operands cannot inhabit this API:
//! ```compile_fail
//! use onlyalpha_kernel::predicate::Predicate;
//! let _ = Predicate::And.evaluate(&[Some(1), Some(false)]);
//! ```

pub const SEMANTIC_VERSION: &str = "1";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Predicate {
    And,
    Or,
    Not,
    Eligibility,
    EntrySignal,
    ExitSignal,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PredicateError {
    UnknownType,
    UnknownVersion,
    InvalidArity,
    InvalidInteger,
    InvalidDecimal,
}

impl Predicate {
    pub fn resolve(type_id: &str, version: &str) -> Result<Self, PredicateError> {
        let operation = match type_id {
            "onlyalpha.predicate.internal.boolean.and" => Self::And,
            "onlyalpha.predicate.internal.boolean.or" => Self::Or,
            "onlyalpha.predicate.internal.boolean.not" => Self::Not,
            "onlyalpha.predicate.internal.terminal.eligibility" => Self::Eligibility,
            "onlyalpha.predicate.internal.terminal.entry_signal" => Self::EntrySignal,
            "onlyalpha.predicate.internal.terminal.exit_signal" => Self::ExitSignal,
            _ => return Err(PredicateError::UnknownType),
        };
        if version != SEMANTIC_VERSION {
            return Err(PredicateError::UnknownVersion);
        }
        Ok(operation)
    }

    pub const fn arity(self) -> usize {
        match self {
            Self::And | Self::Or => 2,
            _ => 1,
        }
    }

    pub fn evaluate(self, operands: &[Option<bool>]) -> Result<Option<bool>, PredicateError> {
        if operands.len() != self.arity() {
            return Err(PredicateError::InvalidArity);
        }
        let left = operands[0];
        Ok(match self {
            Self::And => match (left, operands[1]) {
                (Some(false), _) | (_, Some(false)) => Some(false),
                (Some(true), Some(true)) => Some(true),
                _ => None,
            },
            Self::Or => match (left, operands[1]) {
                (Some(true), _) | (_, Some(true)) => Some(true),
                (Some(false), Some(false)) => Some(false),
                _ => None,
            },
            Self::Not => left.map(|value| !value),
            Self::Eligibility | Self::EntrySignal | Self::ExitSignal => left,
        })
    }
}
