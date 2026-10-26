//! Explicit local-developer request identity, separate from Source permissions.
//! Logical withdrawal must be fenced by the ingress physical write gate. This
//! module neither grants Command permission nor cancels an admitted Command.
use http::{HeaderMap, Method, Request, header::HeaderValue};
use onlyalpha_product_runtime::source_access::{Authority, Error, Session as CredentialSession};
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;
pub(crate) const ORIGIN: &str = "http://127.0.0.1:5173";
const HOST: &str = "127.0.0.1:5173";
const COOKIE: &str = "onlyalpha_dev_session";

pub struct Access {
    verifier: Authority,
    active: CredentialSession,
    credential: Zeroizing<String>,
}
/// Authenticated human identity only. Owning commands still require their
/// explicit operation policy and canonical admission. No Source session export.
#[derive(Clone)]
pub struct Session {
    credential_session: CredentialSession,
}
impl Session {
    pub(crate) fn metadata_session(&self) -> CredentialSession {
        self.credential_session.clone()
    }
    pub fn subject_id(&self) -> Result<&str, Error> {
        self.credential_session.subject_id()
    }
}
pub enum Admission {
    Navigation(HeaderValue),
    Health,
    Owner(Session),
}
impl Access {
    /// Generate a node-local operational credential using OS entropy. This
    /// supplies no canonical identity, Source grant, Command or LIVE right.
    pub fn generate() -> Result<Self, Error> {
        Self::with_entropy(getrandom::fill)
    }
    fn with_entropy(
        fill: impl FnOnce(&mut [u8]) -> Result<(), getrandom::Error>,
    ) -> Result<Self, Error> {
        use std::fmt::Write;
        let mut bytes = Zeroizing::new([0u8; 32]);
        fill(&mut bytes[..]).map_err(|_| Error::ProofUnavailable)?;
        let mut credential = Zeroizing::new(String::with_capacity(64));
        for byte in bytes.iter() {
            write!(&mut *credential, "{byte:02x}").map_err(|_| Error::ProofUnavailable)?;
        }
        Self::new(&credential)
    }
    /// The node must supply a fresh, separate CSPRNG-generated credential.
    /// This verifies syntax, not entropy or provenance, and supplies no default.
    pub fn new(credential: &str) -> Result<Self, Error> {
        if credential.len() != 64 {
            return Err(Error::InvalidConfiguration);
        }
        let digest: String = Sha256::digest(credential.as_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        // Only authentication, issuer membership and revocation are reused.
        // This verifier has no Source permissions and is never exposed.
        let verifier = Authority::new("local-developer", &digest, vec![])?;
        let authorization = Zeroizing::new(format!("Bearer {credential}"));
        let active = verifier
            .authenticate(&authorization)
            .map_err(|_| Error::InvalidConfiguration)?;
        Ok(Self {
            verifier,
            active,
            credential: Zeroizing::new(credential.to_owned()),
        })
    }
    pub(crate) fn check_active(&self) -> Result<(), Error> {
        self.verifier.check_session(&self.active)
    }
    pub fn check_session(&self, session: &Session) -> Result<(), Error> {
        self.verifier.check_session(&session.credential_session)
    }
    /// One-way logical cutoff only. The caller owns the shared physical send
    /// fence, wakeup and cleanup; this is not a transport drain acknowledgement.
    pub fn withdraw(&self) {
        self.verifier.withdraw();
    }
    pub fn admit<B>(&self, request: &Request<B>) -> Result<Admission, Error> {
        let path = crate::ingress::decoded_path(request.uri()).ok_or(Error::Forbidden)?;
        if request.uri().scheme().is_some()
            || request.uri().authority().is_some()
            || !path.starts_with('/')
            || path.contains("//")
            || path.contains('\\')
            || path.bytes().any(|byte| byte <= b' ' || byte == 127)
            || path.split('/').any(|part| matches!(part, "." | ".."))
        {
            return Err(Error::Forbidden);
        }
        let headers = request.headers();
        let origin = single(headers, "origin")?;
        let site = single(headers, "sec-fetch-site")?;
        let mode = single(headers, "sec-fetch-mode")?;
        let destination = single(headers, "sec-fetch-dest")?;
        let upgrade = single(headers, "upgrade")?;
        let stream = matches!(
            path.as_str(),
            "/api/v2/market-data/stream" | "/api/v2/chart/market-data/stream"
        ) || upgrade.is_some();
        let mutation = !matches!(*request.method(), Method::GET | Method::HEAD) || stream;
        if single(headers, "host")? != Some(HOST)
            || origin.is_some_and(|value| value != ORIGIN)
            || (mutation && origin != Some(ORIGIN))
            || !matches!(site, None | Some("none" | "same-origin"))
            || upgrade.is_some_and(|value| {
                !value.eq_ignore_ascii_case("websocket") || request.method() != Method::GET
            })
            || headers.keys().any(|key| {
                key == "forwarded" || key == "x-user" || key.as_str().starts_with("x-forwarded-")
            })
        {
            return Err(Error::Forbidden);
        }
        if headers.contains_key("authorization") {
            return Err(Error::Unauthorized);
        }
        let credential = cookie(headers)?;
        self.check_active()?;
        if [
            "/internal",
            "/api/v2/agent",
            "/api/v2/trading",
            "/api/v2/live",
        ]
        .iter()
        .any(|root| {
            path == *root
                || path
                    .strip_prefix(root)
                    .is_some_and(|suffix| suffix.starts_with('/'))
        }) {
            return Err(Error::Forbidden);
        }
        if request.method() == Method::GET
            && crate::routes::navigation(request.method(), &path)
            && request.uri().query().is_none_or(str::is_empty)
            && mode == Some("navigate")
            && destination == Some("document")
        {
            let value = Zeroizing::new(format!(
                "{COOKIE}={}; HttpOnly; SameSite=Strict; Path=/",
                self.credential.as_str()
            ));
            return Ok(Admission::Navigation(
                HeaderValue::from_str(&value).map_err(|_| Error::ProofUnavailable)?,
            ));
        }
        if request.method() == Method::GET
            && matches!(path.as_str(), "/health/live" | "/health/ready")
        {
            return Ok(Admission::Health);
        }
        let credential = credential.ok_or(Error::Unauthorized)?;
        let authorization = Zeroizing::new(format!("Bearer {credential}"));
        let credential_session = self.verifier.authenticate(&authorization)?;
        Ok(Admission::Owner(Session { credential_session }))
    }
}
fn single<'a>(headers: &'a HeaderMap, name: &str) -> Result<Option<&'a str>, Error> {
    let mut values = headers.get_all(name).iter();
    let Some(value) = values.next() else {
        return Ok(None);
    };
    if values.next().is_some() {
        return Err(Error::Forbidden);
    }
    value.to_str().map(Some).map_err(|_| Error::Forbidden)
}
fn cookie(headers: &HeaderMap) -> Result<Option<&str>, Error> {
    let mut values = headers.get_all("cookie").iter();
    let Some(value) = values.next() else {
        return Ok(None);
    };
    if values.next().is_some() {
        return Err(Error::Unauthorized);
    }
    let mut named = 0;
    let mut credential = None;
    for pair in value.to_str().map_err(|_| Error::Unauthorized)?.split(';') {
        let pair = pair.trim();
        let (name, value) = pair
            .split_once('=')
            .map_or((pair, None), |(name, value)| (name, Some(value)));
        if name == COOKIE {
            named += 1;
            if named > 1 {
                return Err(Error::Unauthorized);
            }
            credential = value;
        }
    }
    Ok(credential)
}

#[cfg(test)]
mod entropy_tests {
    use super::*;
    fn navigation() -> Request<()> {
        Request::builder()
            .uri("/")
            .header("host", HOST)
            .header("sec-fetch-mode", "navigate")
            .header("sec-fetch-dest", "document")
            .body(())
            .unwrap()
    }
    #[test]
    fn entropy_is_encoded_exactly_for_the_existing_bootstrap_and_issuer() {
        let access = Access::with_entropy(|bytes| {
            bytes.copy_from_slice(&[
                0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22,
                23, 24, 25, 26, 27, 28, 29, 30, 31,
            ]);
            Ok(())
        })
        .unwrap();
        let Admission::Navigation(header) = access.admit(&navigation()).unwrap() else {
            panic!("missing bootstrap");
        };
        assert_eq!(
            header,
            "onlyalpha_dev_session=000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f; HttpOnly; SameSite=Strict; Path=/"
        );
        let request = Request::builder().uri("/api/v2/integration-types").header("host", HOST)
            .header("cookie", "onlyalpha_dev_session=000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f").body(()).unwrap();
        let Admission::Owner(session) = access.admit(&request).unwrap() else {
            panic!("missing owner");
        };
        assert_eq!(session.subject_id().unwrap(), "local-developer");
        access.check_session(&session).unwrap();
        access.withdraw();
        assert!(matches!(
            access.admit(&navigation()),
            Err(Error::Unauthorized)
        ));
        assert!(matches!(
            access.check_session(&session),
            Err(Error::Unauthorized)
        ));
    }
    #[test]
    fn entropy_failure_has_no_fallback_credential_or_issuer() {
        let result = Access::with_entropy(|bytes| {
            bytes.fill(0x61);
            Err(getrandom::Error::UNSUPPORTED)
        });
        assert!(matches!(result, Err(Error::ProofUnavailable)));
    }
    #[test]
    fn actual_os_entropy_bootstraps_a_valid_session_without_exposing_a_secret_accessor() {
        let access = Access::generate().unwrap();
        let Admission::Navigation(header) = access.admit(&navigation()).unwrap() else {
            panic!("missing bootstrap");
        };
        let cookie = header.to_str().unwrap().split(';').next().unwrap();
        let value = cookie.strip_prefix("onlyalpha_dev_session=").unwrap();
        assert_eq!(value.len(), 64);
        assert!(
            value
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        );
        let request = Request::builder()
            .uri("/api/v2/integration-types")
            .header("host", HOST)
            .header("cookie", cookie)
            .body(())
            .unwrap();
        let Admission::Owner(session) = access.admit(&request).unwrap() else {
            panic!("missing owner");
        };
        access.check_session(&session).unwrap();
        assert!(matches!(
            Access::generate().unwrap().check_session(&session),
            Err(Error::Unauthorized)
        ));
    }
}
