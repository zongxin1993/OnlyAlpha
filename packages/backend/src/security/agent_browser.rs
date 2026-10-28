//! Dedicated Agent-audience browser assertion. Never a backend/Source permission.
use crate::{
    application::factor_proposals::{self as proposal, GrantInput},
    security::{
        credentials::CredentialId,
        protected_files::{self, FilePolicy, ReadError},
    },
};
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use hmac::{Hmac, KeyInit, Mac};
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::path::Path;
use utoipa::ToSchema;
use zeroize::Zeroizing;
#[derive(Clone, Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct Connection {
    pub schema_version: u8,
    pub agent_url: String,
    pub grant_id: String,
    pub service_subject: String,
    pub credential_sha256: String,
}
#[derive(Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct AccessView {
    pub schema_version: u8,
    pub token: String,
    pub expires_at: u64,
    pub subject: String,
    pub agent_url: String,
    pub binding: String,
}
#[derive(Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ConnectionView {
    pub schema_version: u8,
    pub connection: Connection,
    pub grant_state: String,
}
pub struct Issuer {
    pub connection: Connection,
    key: Zeroizing<Vec<u8>>,
}
const INVALID: &str = "AGENT_BROWSER_CONFIGURATION_INVALID";
impl Issuer {
    pub fn load(root: &Path) -> Result<Option<Self>, &'static str> {
        let bytes = match protected_files::read_file(
            &root.join("agent-connection.json"),
            FilePolicy::Metadata,
        ) {
            Ok(b) => b,
            Err(ReadError::Missing) => return Ok(None),
            Err(_) => return Err(INVALID),
        };
        let connection: Connection = serde_json::from_slice(&bytes).map_err(|_| INVALID)?;
        let url = reqwest::Url::parse(&connection.agent_url).map_err(|_| INVALID)?;
        if connection.schema_version != 1
            || !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
            || url.path() != "/"
            || !(url.scheme() == "https"
                || url.scheme() == "http"
                    && matches!(url.host_str(), Some("127.0.0.1" | "localhost" | "[::1]")))
        {
            return Err(INVALID);
        }
        let validation = GrantInput {
            schema_version: 1,
            grant_id: connection.grant_id.clone(),
            service_subject: connection.service_subject.clone(),
            credential_sha256: connection.credential_sha256.clone(),
            proposal_limit: 100,
            expires_at: "2099-01-01T00:00:00Z".into(),
        };
        validation
            .validate("2000-01-01T00:00:00Z")
            .map_err(|_| INVALID)?;
        let key = protected_files::read_protected(&root.join("secrets/agent-browser-key"))
            .map_err(|_| INVALID)?;
        if key.len() != 32 {
            return Err(INVALID);
        }
        Ok(Some(Self { connection, key }))
    }
    pub fn access(&self, subject: &str, at: u64) -> Result<AccessView, &'static str> {
        let expires_at = at.checked_add(3600).ok_or(INVALID)?;
        let id = CredentialId::generate().map_err(|_| INVALID)?;
        let header = URL_SAFE_NO_PAD.encode(br#"{"alg":"HS256","typ":"JWT"}"#);
        let payload = json!({"v":1,"iss":"onlyalpha-backend-browser-v1","aud":"onlyalpha-agent","sub":subject,"kind":"human","scopes":["chat:read","chat:write","model:write"],"jti":id.value(),"exp":expires_at});
        let message = format!(
            "{header}.{}",
            URL_SAFE_NO_PAD.encode(serde_json::to_vec(&payload).map_err(|_| INVALID)?)
        );
        let mut mac = <Hmac<Sha256> as KeyInit>::new_from_slice(&self.key).map_err(|_| INVALID)?;
        mac.update(message.as_bytes());
        let token = format!(
            "{message}.{}",
            URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes())
        );
        let binding=proposal::pin(&self.connection.credential_sha256).and_then(|_|crate::application::factor_content::hash(&json!({"agent_url":self.connection.agent_url,"subject":subject,"issuer_sha256":Sha256::digest(self.key.as_slice()).iter().map(|b|format!("{b:02x}")).collect::<String>()})))?;
        Ok(AccessView {
            schema_version: 1,
            token,
            expires_at,
            subject: subject.into(),
            agent_url: self.connection.agent_url.clone(),
            binding,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn assertion_has_one_audience_and_no_backend_service_credential() {
        let issuer = Issuer {
            connection: Connection {
                schema_version: 1,
                agent_url: "http://127.0.0.1:5174".into(),
                grant_id: "00000000-0000-4000-8000-000000000001".into(),
                service_subject: "factor-chat".into(),
                credential_sha256: "a".repeat(64),
            },
            key: Zeroizing::new(vec![3; 32]),
        };
        let first = issuer.access("owner", 100).unwrap();
        let parts: Vec<_> = first.token.split('.').collect();
        let payload: serde_json::Value =
            serde_json::from_slice(&URL_SAFE_NO_PAD.decode(parts[1]).unwrap()).unwrap();
        assert_eq!(payload["aud"], "onlyalpha-agent");
        assert_eq!(payload["sub"], "owner");
        assert_eq!(payload["kind"], "human");
        assert_eq!(payload["exp"], 3700);
        assert_eq!(
            payload["scopes"],
            json!(["chat:read", "chat:write", "model:write"])
        );
        let mut mac = <Hmac<Sha256> as KeyInit>::new_from_slice(&[3; 32]).unwrap();
        mac.update(format!("{}.{}", parts[0], parts[1]).as_bytes());
        mac.verify_slice(&URL_SAFE_NO_PAD.decode(parts[2]).unwrap())
            .unwrap();
        let second = issuer.access("owner", 100).unwrap();
        assert_ne!(first.token, second.token);
        assert_eq!(first.binding, second.binding);
        assert_ne!(first.binding, issuer.access("other", 100).unwrap().binding);
        assert!(!first.token.contains(&issuer.connection.credential_sha256));
    }
}
