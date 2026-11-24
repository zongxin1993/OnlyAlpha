//! Explicit local-developer request identity, separate from Source permissions.
//! Logical withdrawal must be fenced by the ingress physical write gate. This
//! module neither grants Command permission nor cancels an admitted Command.
use crate::application::source_access::{
    Authority, Error, Selection, Session as CredentialSession,
};
use http::{HeaderMap, Method, Request, header::HeaderValue};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::collections::VecDeque;
use std::sync::{
    Mutex,
    atomic::{AtomicBool, Ordering},
};
use zeroize::Zeroizing;
pub(crate) const ORIGIN: &str = "http://127.0.0.1:5173";
const HOST: &str = "127.0.0.1:5173";
pub(super) const COOKIE: &str = "onlyalpha_dev_session";

pub(crate) const SESSION_PATH: &str = "/api/v2/human/session";

pub(super) fn credential_digest(credential: &str) -> String {
    Sha256::digest(credential.as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

pub struct Access {
    mode: Mode,
}

enum Mode {
    Local {
        verifier: Authority,
        active: CredentialSession,
        credential: Zeroizing<String>,
    },
    Configured {
        subjects: Vec<Subject>,
        active: AtomicBool,
    },
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SubjectConfig {
    subject_id: String,
    credential_sha256: String,
    closed_history: Vec<HistoryScope>,
    #[serde(default)]
    frozen_strategy_fingerprints: Vec<String>,
}

#[derive(Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
struct HistoryScope {
    integration_id: String,
    revision_fingerprint: String,
    expected_type_id: String,
    source_id: String,
    environment: String,
}

impl HistoryScope {
    fn valid(&self) -> bool {
        crate::is_sha256_hex(&self.revision_fingerprint)
            && [
                &self.integration_id,
                &self.expected_type_id,
                &self.source_id,
                &self.environment,
            ]
            .into_iter()
            .all(|value| {
                !value.is_empty()
                    && value.len() <= 256
                    && value.trim() == value
                    && !value.contains('*')
                    && !value.chars().any(char::is_control)
            })
    }

    fn matches(&self, selection: &Selection) -> bool {
        let reference = selection.reference();
        self.integration_id == reference.integration_id()
            && self.revision_fingerprint == reference.revision()
            && Some(self.expected_type_id.as_str()) == reference.expected_type_id()
            && self.source_id == selection.source_id()
            && self.environment == selection.environment()
    }
}

struct Subject {
    config: SubjectConfig,
    login: Authority,
    sessions: Mutex<VecDeque<Authority>>,
}
/// Authenticated human identity only. Owning commands still require their
/// explicit operation policy and canonical admission. No Source session export.
#[derive(Clone)]
pub struct Session {
    credential_session: CredentialSession,
    can_logout: bool,
}
impl Session {
    pub fn can_logout(&self) -> bool {
        self.can_logout
    }
    pub(crate) fn metadata_session(&self) -> CredentialSession {
        self.credential_session.clone()
    }
    pub fn subject_id(&self) -> Result<&str, Error> {
        self.credential_session.subject_id()
    }
}
pub enum Admission {
    Navigation(HeaderValue),
    Login,
    Presentation,
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
        Self::new(&Self::credential(fill)?)
    }
    fn credential(
        fill: impl FnOnce(&mut [u8]) -> Result<(), getrandom::Error>,
    ) -> Result<Zeroizing<String>, Error> {
        use std::fmt::Write;
        let mut bytes = Zeroizing::new([0u8; 32]);
        fill(&mut bytes[..]).map_err(|_| Error::ProofUnavailable)?;
        let mut credential = Zeroizing::new(String::with_capacity(64));
        for byte in bytes.iter() {
            write!(&mut *credential, "{byte:02x}").map_err(|_| Error::ProofUnavailable)?;
        }
        Ok(credential)
    }
    fn cookie(credential: &str) -> Result<HeaderValue, Error> {
        let text = Zeroizing::new(format!(
            "{COOKIE}={credential}; HttpOnly; SameSite=Strict; Path=/"
        ));
        let mut header = HeaderValue::from_str(&text).map_err(|_| Error::ProofUnavailable)?;
        header.set_sensitive(true);
        Ok(header)
    }
    pub(crate) fn clear_cookie() -> HeaderValue {
        HeaderValue::from_str(&format!(
            "{COOKIE}=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/"
        ))
        .expect("static cookie syntax")
    }
    /// The node must supply a fresh, separate CSPRNG-generated credential.
    /// This verifies syntax, not entropy or provenance, and supplies no default.
    pub fn new(credential: &str) -> Result<Self, Error> {
        if credential.len() != 64 {
            return Err(Error::InvalidConfiguration);
        }
        let digest = credential_digest(credential);
        // Only authentication, issuer membership and revocation are reused.
        // This verifier has no Source permissions and is never exposed.
        let verifier = Authority::new("local-developer", &digest, vec![])?;
        let authorization = Zeroizing::new(format!("Bearer {credential}"));
        let active = verifier
            .authenticate(&authorization)
            .map_err(|_| Error::InvalidConfiguration)?;
        Ok(Self {
            mode: Mode::Local {
                verifier,
                active,
                credential: Zeroizing::new(credential.to_owned()),
            },
        })
    }
    pub(crate) fn configured(bytes: &[u8]) -> Result<Self, Error> {
        if bytes.len() > 32 * 1024 {
            return Err(Error::InvalidConfiguration);
        }
        let configs: Vec<SubjectConfig> =
            serde_json::from_slice(bytes).map_err(|_| Error::InvalidConfiguration)?;
        if configs.is_empty() || configs.len() > 32 {
            return Err(Error::InvalidConfiguration);
        }
        let mut subjects: Vec<Subject> = Vec::with_capacity(configs.len());
        for config in configs {
            if config.subject_id == "local-developer"
                || config.subject_id.len() > 128
                || config.subject_id.is_empty()
                || !config
                    .subject_id
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
                || subjects.iter().any(|s| {
                    s.config.subject_id == config.subject_id
                        || s.config.credential_sha256 == config.credential_sha256
                })
                || config.frozen_strategy_fingerprints.len() > 32
                || config
                    .frozen_strategy_fingerprints
                    .iter()
                    .enumerate()
                    .any(|(index, value)| {
                        !crate::is_sha256_hex(value)
                            || config.frozen_strategy_fingerprints[..index].contains(value)
                    })
                || config.closed_history.len() > 32
                || config
                    .closed_history
                    .iter()
                    .enumerate()
                    .any(|(index, scope)| {
                        !scope.valid() || config.closed_history[..index].contains(scope)
                    })
            {
                return Err(Error::InvalidConfiguration);
            }
            let login = Authority::new(&config.subject_id, &config.credential_sha256, vec![])?;
            subjects.push(Subject {
                config,
                login,
                sessions: Mutex::new(VecDeque::new()),
            });
        }
        Ok(Self {
            mode: Mode::Configured {
                subjects,
                active: AtomicBool::new(true),
            },
        })
    }
    fn subject(&self, id: &str) -> Option<&Subject> {
        let Mode::Configured { subjects, .. } = &self.mode else {
            return None;
        };
        subjects.iter().find(|s| s.config.subject_id == id)
    }
    pub(crate) fn local_operator(&self, subject: &str) -> bool {
        matches!(self.mode, Mode::Local { .. }) && subject == "local-developer"
    }
    pub(crate) fn closed_history_allowed(&self, subject: &str, selection: &Selection) -> bool {
        self.subject(subject).is_some_and(|subject| {
            subject
                .config
                .closed_history
                .iter()
                .any(|scope| scope.matches(selection))
        })
    }
    pub(crate) fn frozen_strategy_allowed(
        &self,
        subject: &str,
        strategy_fingerprint: &str,
    ) -> bool {
        self.subject(subject).is_some_and(|s| {
            s.config
                .frozen_strategy_fingerprints
                .iter()
                .any(|fp| fp == strategy_fingerprint)
        })
    }
    pub(crate) fn check_active(&self) -> Result<(), Error> {
        match &self.mode {
            Mode::Local {
                verifier, active, ..
            } => verifier.check_session(active),
            Mode::Configured { active, .. } if active.load(Ordering::Acquire) => Ok(()),
            _ => Err(Error::Unauthorized),
        }
    }
    pub fn check_session(&self, session: &Session) -> Result<(), Error> {
        self.check_active()?;
        match &self.mode {
            Mode::Local { verifier, .. } => verifier.check_session(&session.credential_session),
            Mode::Configured { .. } => {
                let subject = self
                    .subject(session.subject_id()?)
                    .ok_or(Error::Unauthorized)?;
                let sessions = subject
                    .sessions
                    .lock()
                    .map_err(|_| Error::ProofUnavailable)?;
                if sessions
                    .iter()
                    .any(|a| a.check_session(&session.credential_session).is_ok())
                {
                    Ok(())
                } else {
                    Err(Error::Unauthorized)
                }
            }
        }
    }
    fn authenticate_cookie(&self, credential: &str) -> Result<Session, Error> {
        let authorization = Zeroizing::new(format!("Bearer {credential}"));
        let session = match &self.mode {
            Mode::Local { verifier, .. } => verifier.authenticate(&authorization)?,
            Mode::Configured { subjects, .. } => {
                for subject in subjects {
                    let sessions = subject
                        .sessions
                        .lock()
                        .map_err(|_| Error::ProofUnavailable)?;
                    if let Some(session) = sessions
                        .iter()
                        .find_map(|a| a.authenticate(&authorization).ok())
                    {
                        return Ok(Session {
                            credential_session: session,
                            can_logout: true,
                        });
                    }
                }
                return Err(Error::Unauthorized);
            }
        };
        Ok(Session {
            credential_session: session,
            can_logout: false,
        })
    }
    pub(super) fn login(&self, authorization: &str) -> Result<(Session, HeaderValue), Error> {
        self.check_active()?;
        let Mode::Configured { subjects, .. } = &self.mode else {
            return Err(Error::Forbidden);
        };
        let subject = subjects
            .iter()
            .find(|s| s.login.authenticate(authorization).is_ok())
            .ok_or(Error::Unauthorized)?;
        let credential = Self::credential(getrandom::fill)?;
        let digest = credential_digest(&credential);
        let issuer = Authority::new(&subject.config.subject_id, &digest, vec![])?;
        let session =
            issuer.authenticate(&Zeroizing::new(format!("Bearer {}", credential.as_str())))?;
        let header = Self::cookie(&credential)?;
        let mut sessions = subject
            .sessions
            .lock()
            .map_err(|_| Error::ProofUnavailable)?;
        if sessions.len() == 16
            && let Some(oldest) = sessions.pop_front()
        {
            oldest.withdraw();
        }
        sessions.push_back(issuer);
        Ok((
            Session {
                credential_session: session,
                can_logout: true,
            },
            header,
        ))
    }
    pub(super) fn logout(&self, session: &Session) -> Result<(), Error> {
        self.check_session(session)?;
        let subject = self
            .subject(session.subject_id()?)
            .ok_or(Error::Forbidden)?;
        let mut sessions = subject
            .sessions
            .lock()
            .map_err(|_| Error::ProofUnavailable)?;
        for issuer in sessions.drain(..) {
            issuer.withdraw();
        }
        Ok(())
    }
    pub fn withdraw(&self) {
        match &self.mode {
            Mode::Local { verifier, .. } => verifier.withdraw(),
            Mode::Configured { subjects, active } => {
                active.store(false, Ordering::Release);
                for subject in subjects {
                    subject.login.withdraw();
                    for issuer in subject
                        .sessions
                        .lock()
                        .unwrap_or_else(std::sync::PoisonError::into_inner)
                        .drain(..)
                    {
                        issuer.withdraw();
                    }
                }
            }
        }
    }
    pub fn admit<B>(&self, request: &Request<B>) -> Result<Admission, Error> {
        let path = crate::security::ingress::decoded_path(request.uri()).ok_or(Error::Forbidden)?;
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
        self.check_active()?;
        let credential = cookie(headers)?;
        if path == SESSION_PATH {
            if request.uri().query().is_some() || stream {
                return Err(Error::Forbidden);
            }
            if matches!(*request.method(), Method::POST | Method::DELETE)
                && matches!(self.mode, Mode::Local { .. })
            {
                return Err(Error::Forbidden);
            }
            if request.method() == Method::POST {
                single(headers, "authorization")?.ok_or(Error::Unauthorized)?;
                return Ok(Admission::Login);
            }
        }
        if headers.contains_key("authorization") {
            return Err(Error::Unauthorized);
        }
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
            && crate::transport::routes::navigation(request.method(), &path)
            && request.uri().query().is_none_or(str::is_empty)
            && mode == Some("navigate")
            && destination == Some("document")
        {
            return match &self.mode {
                Mode::Local { credential, .. } => {
                    Ok(Admission::Navigation(Self::cookie(credential)?))
                }
                Mode::Configured { .. } => Ok(Admission::Presentation),
            };
        }
        if matches!(self.mode, Mode::Configured { .. })
            && matches!(*request.method(), Method::GET | Method::HEAD)
            && path.starts_with("/assets/")
        {
            return Ok(Admission::Presentation);
        }
        if request.method() == Method::GET
            && matches!(path.as_str(), "/health/live" | "/health/ready")
        {
            return Ok(Admission::Health);
        }
        let credential = credential.ok_or(Error::Unauthorized)?;
        Ok(Admission::Owner(self.authenticate_cookie(credential)?))
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
    fn only_configured_same_origin_login_accepts_an_authorization_header() {
        use serde_json::json;
        let config = json!([{ "subject_id":"owner", "credential_sha256":"f".repeat(64), "closed_history":[] }]);
        let configured = Access::configured(&serde_json::to_vec(&config).unwrap()).unwrap();
        let local = Access::generate().unwrap();
        assert!(matches!(
            configured.admit(&navigation()),
            Ok(Admission::Presentation)
        ));
        let asset = Request::builder()
            .uri("/assets/login.js")
            .header("host", HOST)
            .body(())
            .unwrap();
        assert!(matches!(
            configured.admit(&asset),
            Ok(Admission::Presentation)
        ));
        let make = |method: Method, path: &str, origin: &str| {
            Request::builder()
                .method(method)
                .uri(path)
                .header("host", HOST)
                .header("origin", origin)
                .header("authorization", "Bearer test")
                .body(())
                .unwrap()
        };
        let post = make(Method::POST, SESSION_PATH, ORIGIN);
        assert!(matches!(configured.admit(&post), Ok(Admission::Login)));
        assert!(matches!(local.admit(&post), Err(Error::Forbidden)));
        assert!(matches!(
            local.admit(&make(Method::DELETE, SESSION_PATH, ORIGIN)),
            Err(Error::Forbidden)
        ));
        assert!(matches!(
            configured.admit(&make(Method::POST, SESSION_PATH, "null")),
            Err(Error::Forbidden)
        ));
        assert!(matches!(
            configured.admit(&make(Method::GET, "/api/v2/integration-types", ORIGIN)),
            Err(Error::Unauthorized)
        ));
        let mut duplicate = post;
        duplicate.headers_mut().append(
            http::header::AUTHORIZATION,
            HeaderValue::from_static("Bearer second"),
        );
        assert!(matches!(
            configured.admit(&duplicate),
            Err(Error::Forbidden)
        ));
    }
    #[test]
    fn configured_grants_bind_the_exact_subject_strategy_and_integration_revision() {
        use crate::application::source_access::Reference;
        use serde_json::json;
        let revision = "a".repeat(64);
        let other = "b".repeat(64);
        let config = json!([{
            "subject_id": "owner-a", "credential_sha256": other,
            "closed_history": [{"integration_id":"bars", "expected_type_id":"provider",
                "source_id":"daily", "environment":"BACKTEST", "revision_fingerprint":revision}],
            "frozen_strategy_fingerprints":[other]
        }, {"subject_id":"owner-b", "credential_sha256":revision, "closed_history":[]}]);
        let access = Access::configured(&serde_json::to_vec(&config).unwrap()).unwrap();
        let select = |pin: &str| {
            Selection::new(
                Reference::new("bars", pin, Some("provider")).unwrap(),
                "daily",
                "BACKTEST",
            )
            .unwrap()
        };
        assert!(access.closed_history_allowed("owner-a", &select(&revision)));
        assert!(!access.closed_history_allowed("owner-a", &select(&other)));
        assert!(!access.closed_history_allowed("owner-b", &select(&revision)));
        assert!(access.frozen_strategy_allowed("owner-a", &other));
        assert!(!access.frozen_strategy_allowed("owner-b", &other));
        assert!(!access.local_operator("local-developer"));
        for (path, value) in [
            ("/0/subject_id", json!("local-developer")),
            ("/0/subject_id", json!("owner-b")),
            ("/0/credential_sha256", json!(revision)),
            ("/0/closed_history/0/revision_fingerprint", json!("*")),
            ("/0/frozen_strategy_fingerprints", json!([other, other])),
        ] {
            let mut invalid = config.clone();
            *invalid.pointer_mut(path).unwrap() = value;
            assert!(matches!(
                Access::configured(&serde_json::to_vec(&invalid).unwrap()),
                Err(Error::InvalidConfiguration)
            ));
        }
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
