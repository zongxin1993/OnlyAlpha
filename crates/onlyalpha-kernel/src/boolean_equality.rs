//! Exact nullable boolean equality; no normalization, runtime admission or effects.
//!
//! Other scalar families cannot inhabit this typed API:
//! ```compile_fail
//! use onlyalpha_kernel::boolean_equality::BooleanEqualityPredicate;
//! let _ = BooleanEqualityPredicate::Eq.evaluate(&[Some("text"), None]);
//! ```
use crate::predicate::PredicateError;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BooleanEqualityPredicate {
    Eq,
    Ne,
}

impl BooleanEqualityPredicate {
    pub fn resolve(type_id: &str, version: &str) -> Result<Self, PredicateError> {
        let operation = match type_id {
            "onlyalpha.predicate.internal.compare.eq.boolean.refs" => Self::Eq,
            "onlyalpha.predicate.internal.compare.ne.boolean.refs" => Self::Ne,
            _ => return Err(PredicateError::UnknownType),
        };
        if version != crate::predicate::SEMANTIC_VERSION {
            return Err(PredicateError::UnknownVersion);
        }
        Ok(operation)
    }

    pub fn evaluate(self, operands: &[Option<bool>]) -> Result<Option<bool>, PredicateError> {
        if operands.len() != 2 {
            return Err(PredicateError::InvalidArity);
        }
        Ok(operands[0]
            .zip(operands[1])
            .map(|(left, right)| match self {
                Self::Eq => left == right,
                Self::Ne => left != right,
            }))
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct BooleanLiteralEqualityPredicate {
    operation: BooleanEqualityPredicate,
    literal: bool,
    literal_left: bool,
}

impl BooleanLiteralEqualityPredicate {
    pub fn resolve(
        type_id: &str,
        version: &str,
        literal: bool,
        literal_left: bool,
    ) -> Result<Self, PredicateError> {
        let operation = match type_id {
            "onlyalpha.predicate.internal.compare.eq.boolean.literal" => {
                BooleanEqualityPredicate::Eq
            }
            "onlyalpha.predicate.internal.compare.ne.boolean.literal" => {
                BooleanEqualityPredicate::Ne
            }
            _ => return Err(PredicateError::UnknownType),
        };
        if version != crate::predicate::SEMANTIC_VERSION {
            return Err(PredicateError::UnknownVersion);
        }
        Ok(Self {
            operation,
            literal,
            literal_left,
        })
    }

    pub fn evaluate(self, inputs: &[Option<bool>]) -> Result<Option<bool>, PredicateError> {
        if inputs.len() != 1 {
            return Err(PredicateError::InvalidArity);
        }
        let operands = if self.literal_left {
            [Some(self.literal), inputs[0]]
        } else {
            [inputs[0], Some(self.literal)]
        };
        self.operation.evaluate(&operands)
    }
}
