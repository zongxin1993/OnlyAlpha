//! Exact finite decimal comparison only; no arithmetic, quantization or effects.
//!
//! Borrowed fixed-point ASCII is an API representation, not a canonical identity format.
//! Other scalar families cannot inhabit this API:
//! ```compile_fail
//! use onlyalpha_predicates::decimal_predicate::DecimalPredicate;
//! let _ = DecimalPredicate::Eq.evaluate(&[Some(1.0), None]);
//! ```
use crate::predicate::PredicateError;
use std::cmp::Ordering;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DecimalOperand<'a> {
    negative: bool,
    integer: &'a str,
    fraction: &'a str,
}

impl<'a> DecimalOperand<'a> {
    pub fn parse(value: &'a str) -> Result<Self, PredicateError> {
        let magnitude = value.strip_prefix('-').unwrap_or(value);
        let (integer, fraction) = match magnitude.split_once('.') {
            Some((integer, fraction)) if !fraction.is_empty() => (integer, fraction),
            Some(_) => return Err(PredicateError::InvalidDecimal),
            None => (magnitude, ""),
        };
        if !(integer == "0" || integer.starts_with(|c: char| ('1'..='9').contains(&c)))
            || !integer.bytes().all(|b| b.is_ascii_digit())
            || !fraction.bytes().all(|b| b.is_ascii_digit())
        {
            return Err(PredicateError::InvalidDecimal);
        }
        let integer = integer.trim_start_matches('0');
        let fraction = fraction.trim_end_matches('0');
        Ok(Self {
            negative: value.starts_with('-') && !(integer.is_empty() && fraction.is_empty()),
            integer,
            fraction,
        })
    }

    fn compare(self, other: Self) -> Ordering {
        if self.negative != other.negative {
            return if self.negative {
                Ordering::Less
            } else {
                Ordering::Greater
            };
        }
        let magnitude = self
            .integer
            .len()
            .cmp(&other.integer.len())
            .then_with(|| self.integer.cmp(other.integer))
            // Trailing fractional zeros were removed at construction. If one
            // fraction is a prefix, the longer suffix must contain a nonzero digit.
            .then_with(|| self.fraction.cmp(other.fraction));
        if self.negative {
            magnitude.reverse()
        } else {
            magnitude
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DecimalPredicate {
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
}

impl DecimalPredicate {
    pub fn resolve(type_id: &str, version: &str) -> Result<Self, PredicateError> {
        let operation = match type_id {
            "onlyalpha.predicate.internal.compare.eq.decimal.refs" => Self::Eq,
            "onlyalpha.predicate.internal.compare.ne.decimal.refs" => Self::Ne,
            "onlyalpha.predicate.internal.compare.lt.decimal.refs" => Self::Lt,
            "onlyalpha.predicate.internal.compare.le.decimal.refs" => Self::Le,
            "onlyalpha.predicate.internal.compare.gt.decimal.refs" => Self::Gt,
            "onlyalpha.predicate.internal.compare.ge.decimal.refs" => Self::Ge,
            _ => return Err(PredicateError::UnknownType),
        };
        if version != crate::predicate::SEMANTIC_VERSION {
            return Err(PredicateError::UnknownVersion);
        }
        Ok(operation)
    }

    pub fn evaluate(
        self,
        operands: &[Option<DecimalOperand<'_>>],
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

/// One nullable reference compared against one required immutable finite literal.
///
/// A missing literal cannot inhabit this API:
/// ```compile_fail
/// use onlyalpha_predicates::decimal_predicate::DecimalLiteralPredicate;
/// let _ = DecimalLiteralPredicate::resolve(
///     "onlyalpha.predicate.internal.compare.eq.decimal.literal", "1", None, false);
/// ```
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DecimalLiteralPredicate<'a> {
    operation: DecimalPredicate,
    literal: DecimalOperand<'a>,
    literal_left: bool,
}

impl<'a> DecimalLiteralPredicate<'a> {
    pub fn resolve(
        type_id: &str,
        version: &str,
        literal: DecimalOperand<'a>,
        literal_left: bool,
    ) -> Result<Self, PredicateError> {
        let operation = match type_id {
            "onlyalpha.predicate.internal.compare.eq.decimal.literal" => DecimalPredicate::Eq,
            "onlyalpha.predicate.internal.compare.ne.decimal.literal" => DecimalPredicate::Ne,
            "onlyalpha.predicate.internal.compare.lt.decimal.literal" => DecimalPredicate::Lt,
            "onlyalpha.predicate.internal.compare.le.decimal.literal" => DecimalPredicate::Le,
            "onlyalpha.predicate.internal.compare.gt.decimal.literal" => DecimalPredicate::Gt,
            "onlyalpha.predicate.internal.compare.ge.decimal.literal" => DecimalPredicate::Ge,
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
        inputs: &[Option<DecimalOperand<'_>>],
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
