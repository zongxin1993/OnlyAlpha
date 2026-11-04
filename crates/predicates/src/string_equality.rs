//! Exact nullable string equality; no normalization, runtime admission or effects.
//!
//! Other scalar families cannot inhabit this typed API:
//! ```compile_fail
//! use onlyalpha_predicates::string_equality::StringEqualityPredicate;
//! let _ = StringEqualityPredicate::Eq.evaluate(&[Some(true), None]);
//! ```
use crate::predicate::PredicateError;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StringEqualityPredicate {
    Eq,
    Ne,
}

impl StringEqualityPredicate {
    pub fn resolve(type_id: &str, version: &str) -> Result<Self, PredicateError> {
        let operation = match type_id {
            "onlyalpha.predicate.internal.compare.eq.string.refs" => Self::Eq,
            "onlyalpha.predicate.internal.compare.ne.string.refs" => Self::Ne,
            _ => return Err(PredicateError::UnknownType),
        };
        if version != crate::predicate::SEMANTIC_VERSION {
            return Err(PredicateError::UnknownVersion);
        }
        Ok(operation)
    }

    pub fn evaluate(self, operands: &[Option<&str>]) -> Result<Option<bool>, PredicateError> {
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
pub struct StringLiteralEqualityPredicate<'a> {
    operation: StringEqualityPredicate,
    literal: &'a str,
    literal_left: bool,
}

impl<'a> StringLiteralEqualityPredicate<'a> {
    pub fn resolve(
        type_id: &str,
        version: &str,
        literal: &'a str,
        literal_left: bool,
    ) -> Result<Self, PredicateError> {
        let operation = match type_id {
            "onlyalpha.predicate.internal.compare.eq.string.literal" => StringEqualityPredicate::Eq,
            "onlyalpha.predicate.internal.compare.ne.string.literal" => StringEqualityPredicate::Ne,
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

    pub fn evaluate(self, inputs: &[Option<&str>]) -> Result<Option<bool>, PredicateError> {
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
