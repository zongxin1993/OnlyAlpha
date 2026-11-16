//! Compile the exact production owner graph in a separate test artifact. Private
//! publication/build fixtures remain absent from the shipped library API.
#[path = "../../src/application/mod.rs"]
pub mod application;
#[path = "../../src/bootstrap/mod.rs"]
pub mod bootstrap;
#[path = "../../src/persistence/mod.rs"]
pub mod persistence;
#[path = "../../src/security/mod.rs"]
pub mod security;
#[path = "../../src/transport/mod.rs"]
pub mod transport;
#[path = "../../src/workers/mod.rs"]
pub mod workers;
fn is_sha256_hex(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
use job_publication as subject;
pub use persistence::factor_build as factor_subject;
pub use persistence::job_publication;
#[path = "../../src/tests/factor_build_tests.rs"]
mod factor_build_tests;
#[path = "../../src/tests/job_publication_tests.rs"]
mod tests;
