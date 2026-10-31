//! Global operational identity and accepted-outcome binding (ADRs 0104/0124).
use onlyalpha_domain::time::OnlyUtcDateTime;
use std::{fmt, str::FromStr};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    InvalidCommandId,
    InvalidCommandKind,
    InvalidFingerprint,
    InvalidOutcomeKind,
    InvalidOutcomeId,
    InvalidAcceptedAt,
    AdmissionCorrupt,
    ReceiptCorrupt,
    BindingMismatch,
    Conflict,
    Unavailable,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::AdmissionCorrupt => "PRODUCT_COMMAND_ADMISSION_CORRUPT",
            Self::ReceiptCorrupt => "PRODUCT_COMMAND_RECEIPT_CORRUPT",
            Self::BindingMismatch => "PRODUCT_COMMAND_BINDING_MISMATCH",
            Self::Conflict => "PRODUCT_COMMAND_CONFLICT",
            Self::Unavailable => "PRODUCT_COMMAND_AUTHORITY_UNAVAILABLE",
            _ => "PRODUCT_COMMAND_INVALID",
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}

pub(crate) fn uuid4(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(index, b)| match index {
            8 | 13 | 18 | 23 => b == b'-',
            14 => b == b'4',
            19 => matches!(b, b'8' | b'9' | b'a' | b'b'),
            _ => b.is_ascii_digit() || (b'a'..=b'f').contains(&b),
        })
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct CommandId(String);
impl CommandId {
    pub fn new(value: &str) -> Result<Self, Error> {
        if !uuid4(value) {
            return Err(Error::InvalidCommandId);
        }
        Ok(Self(value.into()))
    }
    pub fn value(&self) -> &str {
        &self.0
    }
}

macro_rules! text_enum {
    ($name:ident, $error:ident, {$($variant:ident => $text:literal),+ $(,)?}) => {
        #[derive(Clone, Copy, Debug, PartialEq, Eq)]
        pub enum $name {$($variant),+}
        impl $name {
            pub const ALL: &'static [Self] = &[$(Self::$variant),+];
            pub fn as_str(self) -> &'static str {match self {$(Self::$variant => $text),+}}
        }
        impl FromStr for $name {
            type Err = Error;
            fn from_str(value: &str) -> Result<Self, Error> {
                match value {$($text => Ok(Self::$variant)),+, _ => Err(Error::$error)}
            }
        }
    };
}
text_enum!(CommandKind, InvalidCommandKind, {
    CreateFactorStudyGrant => "CREATE_FACTOR_STUDY_GRANT",
    ContinueFactorStudy => "CONTINUE_FACTOR_STUDY",
    PrepareFactorResearch => "PREPARE_FACTOR_RESEARCH",
    CancelFactorResearchPreparation => "CANCEL_FACTOR_RESEARCH_PREPARATION",
    StageFactorStudy => "STAGE_FACTOR_STUDY", WithdrawFactorStudy => "WITHDRAW_FACTOR_STUDY",
    CreateProposalGrant => "CREATE_PROPOSAL_GRANT", RevokeProposalGrant => "REVOKE_PROPOSAL_GRANT",
    WithdrawFactorProposal => "WITHDRAW_FACTOR_PROPOSAL", StageFactorProposal => "STAGE_FACTOR_PROPOSAL", ConfirmFactorProposal => "CONFIRM_FACTOR_PROPOSAL",
    FactorChat => "FACTOR_CHAT",
    CreateResearchRun => "CREATE_RESEARCH_RUN", CancelResearchRun => "CANCEL_RESEARCH_RUN",
    FreezeStrategy => "FREEZE_STRATEGY", PromoteStrategy => "PROMOTE_STRATEGY",
    CreateBacktestRun => "CREATE_BACKTEST_RUN", CancelBacktestRun => "CANCEL_BACKTEST_RUN",
    EvaluateQualification => "EVALUATE_QUALIFICATION",
    CreateSymbolicSearchExperiment => "CREATE_SYMBOLIC_SEARCH_EXPERIMENT",
    CreateParameterSearchExperiment => "CREATE_PARAMETER_SEARCH_EXPERIMENT",
    AdvanceSearchExperiment => "ADVANCE_SEARCH_EXPERIMENT", CreateIntegration => "CREATE_INTEGRATION",
    UpdateIntegrationDraft => "UPDATE_INTEGRATION_DRAFT", SetIntegrationSecret => "SET_INTEGRATION_SECRET",
    ClearIntegrationSecret => "CLEAR_INTEGRATION_SECRET", ResetIntegrationDraftContract => "RESET_INTEGRATION_DRAFT_CONTRACT",
    PublishIntegrationRevision => "PUBLISH_INTEGRATION_REVISION", SetIntegrationLifecycle => "SET_INTEGRATION_LIFECYCLE",
    CreateChartCalculation => "CREATE_CHART_CALCULATION", SaveWatchlists => "SAVE_WATCHLISTS", SaveWorkspace => "SAVE_WORKSPACE",
    SavePrivateFactorDraft => "SAVE_PRIVATE_FACTOR_DRAFT", PublishPrivateFactorRevision => "PUBLISH_PRIVATE_FACTOR_REVISION",
    UpdatePrivateFactorDisplay => "UPDATE_PRIVATE_FACTOR_DISPLAY",
});
text_enum!(OutcomeKind, InvalidOutcomeKind, {
    FactorStudyOperation => "FACTOR_STUDY_OPERATION",
    ResearchPreparationOperation => "RESEARCH_PREPARATION_OPERATION",
    FactorProposalOperation => "FACTOR_PROPOSAL_OPERATION",
    FactorChatEvent => "FACTOR_CHAT_EVENT",
    ResearchRun => "RESEARCH_RUN", Strategy => "STRATEGY", StrategyPromotion => "STRATEGY_PROMOTION",
    BacktestRun => "BACKTEST_RUN", QualificationDecision => "QUALIFICATION_DECISION", SearchExperiment => "SEARCH_EXPERIMENT",
    Integration => "INTEGRATION", IntegrationRevision => "INTEGRATION_REVISION",
    ChartCalculationOperation => "CHART_CALCULATION_OPERATION", WatchlistRevision => "WATCHLIST_REVISION", WorkspaceRevision => "WORKSPACE_REVISION", PrivateFactorAuthoring => "PRIVATE_FACTOR_AUTHORING",
});
impl OutcomeKind {
    fn uses_uuid(self) -> bool {
        matches!(
            self,
            Self::ResearchRun
                | Self::BacktestRun
                | Self::Integration
                | Self::ChartCalculationOperation
        )
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Admission {
    id: CommandId,
    kind: CommandKind,
    fingerprint: String,
}
impl Admission {
    pub fn new(id: CommandId, kind: CommandKind, fingerprint: &str) -> Result<Self, Error> {
        if !crate::is_sha256_hex(fingerprint) {
            return Err(Error::InvalidFingerprint);
        }
        Ok(Self {
            id,
            kind,
            fingerprint: fingerprint.into(),
        })
    }
    pub fn id(&self) -> &CommandId {
        &self.id
    }
    pub fn kind(&self) -> CommandKind {
        self.kind
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Outcome {
    kind: OutcomeKind,
    id: String,
}
impl Outcome {
    pub fn new(kind: OutcomeKind, id: &str) -> Result<Self, Error> {
        if !(if kind.uses_uuid() {
            uuid4(id)
        } else {
            crate::is_sha256_hex(id)
        }) {
            return Err(Error::InvalidOutcomeId);
        }
        Ok(Self {
            kind,
            id: id.into(),
        })
    }
    pub fn kind(&self) -> OutcomeKind {
        self.kind
    }
    pub fn id(&self) -> &str {
        &self.id
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Receipt {
    admission: Admission,
    outcome: Outcome,
    accepted_at: OnlyUtcDateTime,
}
impl Receipt {
    pub fn new(admission: Admission, outcome: Outcome, accepted_at: &str) -> Result<Self, Error> {
        let accepted_at = accepted_at.parse().map_err(|_| Error::InvalidAcceptedAt)?;
        Ok(Self {
            admission,
            outcome,
            accepted_at,
        })
    }
    pub fn admission(&self) -> &Admission {
        &self.admission
    }
    pub fn outcome(&self) -> &Outcome {
        &self.outcome
    }
    pub fn accepted_at(&self) -> OnlyUtcDateTime {
        self.accepted_at
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Binding {
    None,
    Admitted(Admission),
    Accepted(Receipt),
}
/// A copied receipt intent is not proof that its owning Admission exists.
pub fn verify_binding(
    admission: Option<Admission>,
    receipt: Option<Receipt>,
) -> Result<Binding, Error> {
    match (admission, receipt) {
        (None, None) => Ok(Binding::None),
        (None, Some(_)) => Err(Error::ReceiptCorrupt),
        (Some(admission), None) => Ok(Binding::Admitted(admission)),
        (Some(admission), Some(receipt)) => {
            if &admission != receipt.admission() {
                return Err(Error::BindingMismatch);
            }
            Ok(Binding::Accepted(receipt))
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Put {
    Created,
    Reused,
}
