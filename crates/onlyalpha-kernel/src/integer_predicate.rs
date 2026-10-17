//! Exact integer comparison only: no arithmetic, runtime admission, or effects.
//!
//! Canonical decimal spelling is a borrowed API representation, not a persistent identity format.
use crate::predicate::PredicateError;
use std::cmp::Ordering;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct IntegerOperand<'a>(&'a str);

impl<'a> IntegerOperand<'a> {
    pub fn parse(value: &'a str) -> Result<Self, PredicateError> {
        let digits = value.strip_prefix('-').unwrap_or(value);
        if value == "0"
            || (digits.starts_with(|c: char| ('1'..='9').contains(&c))
                && digits.bytes().all(|c| c.is_ascii_digit()))
        {
            Ok(Self(value))
        } else {
            Err(PredicateError::InvalidInteger)
        }
    }

    fn compare(self, other: Self) -> Ordering {
        let negative = self.0.starts_with('-');
        let other_negative = other.0.starts_with('-');
        if negative != other_negative {
            return if negative {
                Ordering::Less
            } else {
                Ordering::Greater
            };
        }
        let left = self.0.strip_prefix('-').unwrap_or(self.0);
        let right = other.0.strip_prefix('-').unwrap_or(other.0);
        let magnitude = left.len().cmp(&right.len()).then_with(|| left.cmp(right));
        if negative {
            magnitude.reverse()
        } else {
            magnitude
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum IntegerPredicate {
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
}

impl IntegerPredicate {
    pub fn resolve(type_id: &str, version: &str) -> Result<Self, PredicateError> {
        let operation = match type_id {
            "onlyalpha.predicate.internal.compare.eq.integer.refs" => Self::Eq,
            "onlyalpha.predicate.internal.compare.ne.integer.refs" => Self::Ne,
            "onlyalpha.predicate.internal.compare.lt.integer.refs" => Self::Lt,
            "onlyalpha.predicate.internal.compare.le.integer.refs" => Self::Le,
            "onlyalpha.predicate.internal.compare.gt.integer.refs" => Self::Gt,
            "onlyalpha.predicate.internal.compare.ge.integer.refs" => Self::Ge,
            _ => return Err(PredicateError::UnknownType),
        };
        if version != crate::predicate::SEMANTIC_VERSION {
            return Err(PredicateError::UnknownVersion);
        }
        Ok(operation)
    }

    pub fn evaluate(
        self,
        operands: &[Option<IntegerOperand<'_>>],
    ) -> Result<Option<bool>, PredicateError> {
        if operands.len() != 2 {
            return Err(PredicateError::InvalidArity);
        }
        let (Some(left), Some(right)) = (operands[0], operands[1]) else {
            return Ok(None);
        };
        let order = left.compare(right);
        Ok(Some(match self {
            Self::Eq => order == Ordering::Equal,
            Self::Ne => order != Ordering::Equal,
            Self::Lt => order == Ordering::Less,
            Self::Le => order != Ordering::Greater,
            Self::Gt => order == Ordering::Greater,
            Self::Ge => order != Ordering::Less,
        }))
    }
}

/// One nullable reference compared against one required, immutable literal.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct IntegerLiteralPredicate<'a> {
    operation: IntegerPredicate,
    literal: IntegerOperand<'a>,
    literal_left: bool,
}

impl<'a> IntegerLiteralPredicate<'a> {
    pub fn resolve(
        type_id: &str,
        version: &str,
        literal: IntegerOperand<'a>,
        literal_left: bool,
    ) -> Result<Self, PredicateError> {
        let operation = match type_id {
            "onlyalpha.predicate.internal.compare.eq.integer.literal" => IntegerPredicate::Eq,
            "onlyalpha.predicate.internal.compare.ne.integer.literal" => IntegerPredicate::Ne,
            "onlyalpha.predicate.internal.compare.lt.integer.literal" => IntegerPredicate::Lt,
            "onlyalpha.predicate.internal.compare.le.integer.literal" => IntegerPredicate::Le,
            "onlyalpha.predicate.internal.compare.gt.integer.literal" => IntegerPredicate::Gt,
            "onlyalpha.predicate.internal.compare.ge.integer.literal" => IntegerPredicate::Ge,
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

    pub fn evaluate(
        self,
        inputs: &[Option<IntegerOperand<'_>>],
    ) -> Result<Option<bool>, PredicateError> {
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
