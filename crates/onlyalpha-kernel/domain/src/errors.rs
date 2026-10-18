//! Domain-local failures; never infrastructure or transport errors.
use std::{error::Error, fmt};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OnlyDomainError {
    Validation(String),
    CurrencyMismatch(String),
    StateTransition(String),
    Serialization(String),
}

impl OnlyDomainError {
    pub const fn is_validation(&self) -> bool {
        matches!(self, Self::Validation(_) | Self::CurrencyMismatch(_))
    }
}

impl fmt::Display for OnlyDomainError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::Validation(message)
            | Self::CurrencyMismatch(message)
            | Self::StateTransition(message)
            | Self::Serialization(message) => message,
        };
        f.write_str(message)
    }
}

impl Error for OnlyDomainError {}

#[cfg(test)]
mod tests {
    use super::OnlyDomainError;

    #[test]
    fn validation_category_retains_currency_mismatch_without_swallowing_other_errors() {
        for (error, validation) in [
            (OnlyDomainError::Validation("invalid".into()), true),
            (
                OnlyDomainError::CurrencyMismatch("currencies differ".into()),
                true,
            ),
            (
                OnlyDomainError::StateTransition("transition denied".into()),
                false,
            ),
            (
                OnlyDomainError::Serialization("invalid payload".into()),
                false,
            ),
        ] {
            assert_eq!(error.is_validation(), validation);
            assert!(!error.to_string().is_empty());
        }
    }
}
