//! Credential identity used by retained proposal evidence and reference fixtures.
use crate::application::{
    command::CommandId,
    factor_proposals::{INVALID, Result},
};
use sha2::{Digest, Sha256};
#[derive(Clone)]
pub struct Presented {
    pub(crate) grant_id: String,
    pub(crate) digest: String,
}
impl Presented {
    pub fn parse(token: &str) -> Result<Self> {
        let p: Vec<_> = token.split('.').collect();
        if p.len() != 3
            || p[0] != "oa-proposal-v1"
            || CommandId::new(p[1]).is_err()
            || p[2].len() != 64
            || !p[2]
                .bytes()
                .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
        {
            return Err(INVALID);
        }
        let digest = Sha256::digest(token.as_bytes())
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        Ok(Self {
            grant_id: p[1].into(),
            digest,
        })
    }
}
