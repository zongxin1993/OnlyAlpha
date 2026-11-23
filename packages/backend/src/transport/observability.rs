//! HTTP 诊断只观察 handler、body handoff 与原 WriteGate；不改变权限、超时或帧。
use axum::{body::Body, response::Response};
use http::Request;
use hyper::body::{Body as HttpBody, Bytes, Frame, SizeHint};
use onlyalpha_observability::{Correlation, Operation};
use std::{
    pin::Pin,
    task::{Context, Poll},
};

pub(crate) struct Stage(Option<Operation>);
impl Stage {
    pub(crate) fn new(operation: Operation) -> Self {
        Self(Some(operation))
    }
    pub(crate) fn span(&self) -> &tracing::Span {
        self.0.as_ref().expect("active diagnostic stage").span()
    }
    pub(crate) fn finish(&mut self, outcome: &'static str, items: u64, bytes: u64) {
        if let Some(operation) = self.0.take() {
            operation.finish(outcome, items, bytes);
        }
    }
}
impl Drop for Stage {
    fn drop(&mut self) {
        self.finish("dropped", 0, 0);
    }
}
pub(crate) struct RequestTrace {
    stage: Stage,
}
impl RequestTrace {
    pub(crate) fn span(&self) -> &tracing::Span {
        self.stage.span()
    }
}
pub(crate) fn begin(request: &Request<Body>) -> Option<RequestTrace> {
    if !tracing::enabled!(target:"onlyalpha.observability", tracing::Level::INFO)
        || !request.uri().path().starts_with("/api/v2/backtest/")
    {
        return None;
    }
    let run_id = request
        .uri()
        .path()
        .strip_prefix("/api/v2/backtest/runs/")
        .and_then(|tail| tail.split('/').next())
        .filter(|id| crate::application::command::uuid4(id))
        .map(str::to_owned);
    let request_id = request
        .extensions()
        .get::<crate::security::ingress::PhysicalConnection>()
        .map(|connection| format!("connection:{}", connection.diagnostic_id()));
    let operation = if request.method() == http::Method::GET {
        "http.backtest.get"
    } else {
        "http.backtest.command"
    };
    Some(RequestTrace {
        stage: Stage::new(Operation::root(
            "transport",
            operation,
            Correlation {
                request_id,
                run_id,
                ..Correlation::default()
            },
        )),
    })
}
pub(crate) fn response(response: Response, trace: RequestTrace) -> Response {
    let span = trace.span().clone();
    let stage = span
        .with_subscriber(|(_, dispatch)| {
            tracing::dispatcher::with_default(dispatch, || {
                span.in_scope(|| {
                    Stage::new(Operation::start(
                        "transport",
                        "http.response.body",
                        Correlation::default(),
                    ))
                })
            })
        })
        .expect("enabled request diagnostic subscriber");
    let (parts, inner) = response.into_parts();
    let mut observed = ObservedBody {
        inner,
        stage,
        trace,
        frames: 0,
        bytes: 0,
    };
    if observed.inner.is_end_stream() {
        observed.finish("ok");
    }
    Response::from_parts(parts, Body::new(observed))
}
struct ObservedBody {
    inner: Body,
    stage: Stage,
    trace: RequestTrace,
    frames: u64,
    bytes: u64,
}
impl ObservedBody {
    fn finish(&mut self, outcome: &'static str) {
        self.stage.finish(outcome, self.frames, self.bytes);
        self.trace.stage.finish(outcome, self.frames, self.bytes);
    }
}
impl HttpBody for ObservedBody {
    type Data = Bytes;
    type Error = axum::Error;
    fn poll_frame(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Bytes>, Self::Error>>> {
        let result = Pin::new(&mut self.inner).poll_frame(cx);
        match &result {
            Poll::Ready(Some(Ok(frame))) => {
                self.frames += 1;
                self.bytes += frame.data_ref().map_or(0, |bytes| bytes.len() as u64);
                if self.inner.is_end_stream() {
                    self.finish("ok");
                }
            }
            Poll::Ready(Some(Err(_))) => self.finish("failed"),
            Poll::Ready(None) => self.finish("ok"),
            Poll::Pending => {}
        }
        result
    }
    fn is_end_stream(&self) -> bool {
        self.inner.is_end_stream()
    }
    fn size_hint(&self) -> SizeHint {
        self.inner.size_hint()
    }
}
#[cfg(test)]
#[path = "../tests/http_observation.rs"]
mod tests;
