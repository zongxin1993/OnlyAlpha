//! Compile the exact production modules in a test artifact to keep private
//! fixture construction out of the shipped library and out of ordinary --lib tests.
pub use onlyalpha_backend::{bootstrap, workers};
pub mod application {
    pub use crate::factor_service_subject as factor_build;
    pub use onlyalpha_backend::application::*;
}
pub mod persistence {
    pub use crate::factor_subject as factor_build;
    pub use crate::job_publication;
    pub use onlyalpha_backend::persistence::*;
}
#[path = "../../src/application/factor_build.rs"]
pub mod factor_service_subject;
#[path = "../../src/persistence/job_publication.rs"]
pub mod job_publication;
use job_publication as subject;
#[path = "../../src/persistence/factor_build.rs"]
pub mod factor_subject;
#[path = "../../src/tests/job_publication_tests.rs"]
mod tests;

#[path = "../../src/tests/factor_build_tests.rs"]
mod factor_build_tests;
