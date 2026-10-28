//! OnlyAlpha backend product: Application, persistence and native ingress.
pub mod application;
pub mod bootstrap;
pub mod persistence;
pub mod security;
pub mod transport;
fn is_sha256_hex(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
pub mod workers;
