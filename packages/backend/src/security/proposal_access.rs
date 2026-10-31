//! Presented service credentials are untrusted until the owning grant transaction validates them.
use crate::application::{
    command::CommandId,
    factor_proposals::{INVALID, Result},
};
use http::{HeaderMap, Method};
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
    pub(crate) fn request(headers: &HeaderMap, method: &Method, path: &str) -> Result<Self> {
        let values: Vec<_> = headers.get_all("authorization").iter().collect();
        if values.len() != 1
            || headers.keys().any(|k| {
                matches!(
                    k.as_str(),
                    "cookie"
                        | "origin"
                        | "forwarded"
                        | "x-user"
                        | "sec-fetch-site"
                        | "sec-fetch-mode"
                        | "sec-fetch-dest"
                ) || k.as_str().starts_with("x-forwarded-")
            })
            || headers.get("host").and_then(|h| h.to_str().ok()) != Some("127.0.0.1:5173")
            || !service_route(method, path)
        {
            return Err(INVALID);
        }
        Self::parse(
            values[0]
                .to_str()
                .map_err(|_| INVALID)?
                .strip_prefix("Bearer ")
                .ok_or(INVALID)?,
        )
    }
}
pub(crate) fn service_route(method: &Method, path: &str) -> bool {
    if method == Method::POST {
        return matches!(path, "/api/v2/factor-proposals" | "/api/v2/factor-studies")
            || path
                .strip_prefix("/api/v2/factor-studies/commands/")
                .and_then(|s| s.strip_suffix("/resolution"))
                .is_some_and(|id| CommandId::new(id).is_ok());
    }
    if method != Method::GET {
        return false;
    }
    if let Some(s) = path.strip_prefix("/api/v2/factor-proposal-context/") {
        return CommandId::new(s).is_ok();
    }
    if let Some(s) = path.strip_prefix("/api/v2/factor-proposals/commands/") {
        return CommandId::new(s).is_ok();
    }
    if let Some(s) = path.strip_prefix("/api/v2/factor-study-context/") {
        return crate::is_sha256_hex(s);
    }
    if let Some(s) = path.strip_prefix("/api/v2/factor-study-continuations/") {
        return CommandId::new(s).is_ok();
    }
    if let Some(s) = path.strip_prefix("/api/v2/factor-studies/commands/") {
        return CommandId::new(s).is_ok();
    }
    if let Some(s) = path.strip_prefix("/api/v2/factor-studies/") {
        return crate::is_sha256_hex(s);
    }
    path.strip_prefix("/api/v2/factor-proposals/")
        .is_some_and(crate::is_sha256_hex)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::security::human_access::{Access, Admission};
    #[test]
    fn presented_service_is_never_a_human_or_a_confirmation_permission() {
        let a = Access::new(&"a".repeat(64)).unwrap();
        let token = format!(
            "Bearer oa-proposal-v1.{}.{}",
            "12345678-1234-4234-8234-123456789abc",
            "a".repeat(64)
        );
        for (method, path, allowed) in [
            (Method::POST, "/api/v2/factor-proposals", true),
            (Method::POST, "/api/v2/factor-studies", true),
            (Method::POST, "/api/v2/factor-proposals/", false),
            (Method::POST, "/api/v2/factor-proposal-grants", false),
            (Method::POST, "/api/v2/factor-study-grants", false),
            (Method::POST, "/api/v2/factor-study-preparations", false),
            (Method::POST, "/api/v2/research/commands", false),
            (Method::GET, "/api/v2/agent/sessions", false),
        ] {
            let r = http::Request::builder()
                .method(method)
                .uri(path)
                .header("host", "127.0.0.1:5173")
                .header("authorization", &token)
                .body(())
                .unwrap();
            assert_eq!(matches!(a.admit(&r), Ok(Admission::Proposal(_))), allowed);
        }
        let pin = "a".repeat(64);
        for path in [
            format!("/api/v2/factor-study-context/{pin}"),
            format!("/api/v2/factor-studies/{pin}"),
            "/api/v2/factor-studies/commands/12345678-1234-4234-8234-123456789abc".into(),
        ] {
            assert!(service_route(&Method::GET, &path));
            assert!(!service_route(&Method::POST, &path));
        }
        assert!(!service_route(
            &Method::POST,
            &format!("/api/v2/factor-studies/{pin}/confirmation")
        ));
        assert!(!service_route(
            &Method::POST,
            &format!("/api/v2/factor-studies/{pin}/withdrawal")
        ));
        let r = http::Request::builder()
            .method(Method::POST)
            .uri("/api/v2/factor-proposals")
            .header("host", "127.0.0.1:5173")
            .header("authorization", &token)
            .header("cookie", "onlyalpha_dev_session=other")
            .body(())
            .unwrap();
        assert!(a.admit(&r).is_err());
    }
}
