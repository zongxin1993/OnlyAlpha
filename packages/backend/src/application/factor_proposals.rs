//! Immutable, unadmitted Agent input. Only Human confirmation reaches Authoring.
use crate::application::{
    command::CommandId,
    factor_content::{hash, preview},
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use utoipa::ToSchema;
pub type Result<T> = std::result::Result<T, &'static str>;
pub const INVALID: &str = "FACTOR_PROPOSAL_INVALID";
#[derive(Clone, Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct GrantInput {
    pub schema_version: u8,
    pub grant_id: String,
    pub service_subject: String,
    pub credential_sha256: String,
    pub proposal_limit: u32,
    pub expires_at: String,
}
#[derive(Clone, Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct Origin {
    pub session_id: String,
    pub event_fingerprint: String,
    pub result_fingerprint: String,
    pub workflow_fingerprint: String,
    pub model_revision: String,
}
#[derive(Clone, Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct StageInput {
    pub schema_version: u8,
    pub origin: Origin,
    pub candidate: Value,
    pub expected_draft_fingerprint: Option<String>,
    pub expected_display_fingerprint: Option<String>,
    pub expected_proposal_fingerprint: Option<String>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ConfirmInput {
    pub schema_version: u8,
    pub proposal_fingerprint: String,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct RevokeInput {
    pub schema_version: u8,
    pub grant_id: String,
}
// Exact command effects; live proposal queries are separate projections.
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct Operation {
    pub schema_version: u8,
    pub command_id: String,
    pub operation_fingerprint: String,
    pub effect: Value,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ProposalView {
    pub schema_version: u8,
    pub fingerprint: String,
    pub snapshot: Value,
    pub is_current: bool,
    pub withdrawn: bool,
    pub confirmation: Option<Operation>,
}
#[derive(Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct Context {
    pub schema_version: u8,
    pub owner: String,
    pub service_subject: String,
    pub factor_id: String,
    pub draft_fingerprint: Option<String>,
    pub display_fingerprint: Option<String>,
    pub proposal_fingerprint: Option<String>,
}
pub fn datetime(value: &str) -> Result<OnlyUtcDateTime> {
    value.parse().map_err(|_| INVALID)
}
pub fn id(value: &str) -> Result<()> {
    CommandId::new(value).map(|_| ()).map_err(|_| INVALID)
}
pub fn pin(value: &str) -> Result<()> {
    if crate::is_sha256_hex(value) {
        Ok(())
    } else {
        Err(INVALID)
    }
}
pub fn factor_id(owner: &str, service: &str, session: &str) -> Result<String> {
    id(session)?;
    Ok(format!(
        "private.factor.agent_{}",
        hash(&json!({"owner":owner,"service":service,"session":session}))?
    ))
}
impl GrantInput {
    pub fn validate(&self, at: &str) -> Result<()> {
        if self.schema_version != 1
            || !(1..=100).contains(&self.proposal_limit)
            || self.service_subject.is_empty()
            || self.service_subject.len() > 64
            || !self
                .service_subject
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || matches!(b, b'-' | b'_'))
            || datetime(&self.expires_at)? <= datetime(at)?
        {
            return Err(INVALID);
        }
        id(&self.grant_id)?;
        pin(&self.credential_sha256)
    }
}
impl StageInput {
    pub fn snapshot(
        &self,
        owner: &str,
        service: &str,
        grant: &str,
        command: &str,
    ) -> Result<Value> {
        if self.schema_version != 1 {
            return Err(INVALID);
        }
        id(command)?;
        id(&self.origin.session_id)?;
        for v in [
            &self.origin.event_fingerprint,
            &self.origin.result_fingerprint,
            &self.origin.workflow_fingerprint,
            &self.origin.model_revision,
        ] {
            pin(v)?
        }
        for v in [
            &self.expected_draft_fingerprint,
            &self.expected_display_fingerprint,
            &self.expected_proposal_fingerprint,
        ]
        .into_iter()
        .flatten()
        {
            pin(v)?
        }
        let fid = factor_id(owner, service, &self.origin.session_id)?;
        let p = preview(&self.candidate, &fid)?;
        Ok(
            json!({"schema_version":1,"owner":owner,"service_subject":service,"grant_fingerprint":grant,"command_id":command,"origin":self.origin,"factor_id":fid,"preview":p,"expected_draft_fingerprint":self.expected_draft_fingerprint,"expected_display_fingerprint":self.expected_display_fingerprint,"supersedes":self.expected_proposal_fingerprint}),
        )
    }
}
