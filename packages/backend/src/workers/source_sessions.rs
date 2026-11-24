//! Read-only access to the Node's current Source session. This provider cannot
//! issue grants or refresh an already retained input session.
use crate::application::source_access::{Error, Session};
use std::{future::Future, pin::Pin, sync::Arc};

type Lookup = dyn Fn(String, Option<String>) -> Pin<Box<dyn Future<Output = Result<Session, Error>> + Send>>
    + Send
    + Sync;

#[derive(Clone)]
pub(crate) struct SourceSessions {
    lookup: Arc<Lookup>,
}
impl SourceSessions {
    pub(crate) fn new<F, Fut>(lookup: F) -> Self
    where
        F: Fn(String, Option<String>) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<Session, Error>> + Send + 'static,
    {
        Self { lookup: Arc::new(move |owner, strategy| Box::pin(lookup(owner, strategy))) }
    }

    pub(crate) async fn current(&self, owner: &str, backtest_strategy: Option<&str>) -> Result<Session, Error> {
        let session = (self.lookup)(owner.to_owned(), backtest_strategy.map(str::to_owned)).await?;
        if session.subject_id()? != owner {
            return Err(Error::Forbidden);
        }
        Ok(session)
    }
}
