//! Read-only access to the Node's current Source session. This provider cannot
//! issue grants or refresh an already retained input session.
use crate::application::source_access::{Error, Session};
use std::{future::Future, pin::Pin, sync::Arc};

type Lookup = dyn Fn() -> Pin<Box<dyn Future<Output = Result<Session, Error>> + Send>>
    + Send
    + Sync;

#[derive(Clone)]
pub(crate) struct SourceSessions {
    lookup: Arc<Lookup>,
}
impl SourceSessions {
    pub(crate) fn new<F, Fut>(lookup: F) -> Self
    where
        F: Fn() -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<Session, Error>> + Send + 'static,
    {
        Self { lookup: Arc::new(move || Box::pin(lookup())) }
    }

    pub(crate) async fn current(&self) -> Result<Session, Error> {
        (self.lookup)().await
    }
}
