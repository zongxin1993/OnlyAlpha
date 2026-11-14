//! Compile the exact production modules in a test artifact to keep private
//! fixture construction out of the shipped library and out of ordinary --lib tests.
pub use onlyalpha_backend::{application, bootstrap, persistence};
#[path = "../../src/persistence/job_publication.rs"]
pub mod job_publication;
use job_publication as subject;
#[path = "../../src/persistence/factor_build.rs"]
pub mod factor_subject;
#[path = "../../src/tests/job_publication_tests.rs"]
mod tests;
