use super::*;
use hyper::body::{Body as HttpBody, Bytes, Frame, SizeHint};
use onlyalpha_observability::{Config, Mode, Session};
use std::{
    collections::VecDeque,
    io::{self, Write},
    pin::Pin,
    sync::{Arc, Mutex},
    task::{Context, Poll},
};
use tracing::instrument::WithSubscriber;
#[derive(Clone, Default)]
struct Buffer(Arc<Mutex<Vec<u8>>>);
impl Write for Buffer {
    fn write(&mut self, b: &[u8]) -> io::Result<usize> {
        self.0.lock().unwrap().extend_from_slice(b);
        Ok(b.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
impl Buffer {
    fn rows(&self) -> Vec<serde_json::Value> {
        String::from_utf8(self.0.lock().unwrap().clone())
            .unwrap()
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect()
    }
}
struct Frames(VecDeque<Frame<Bytes>>);
impl HttpBody for Frames {
    type Data = Bytes;
    type Error = io::Error;
    fn poll_frame(
        mut self: Pin<&mut Self>,
        _: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Bytes>, io::Error>>> {
        Poll::Ready(self.0.pop_front().map(Ok))
    }
    fn is_end_stream(&self) -> bool {
        self.0.is_empty()
    }
    fn size_hint(&self) -> SizeHint {
        SizeHint::with_exact(
            self.0
                .iter()
                .filter_map(Frame::data_ref)
                .map(|d| d.len() as u64)
                .sum(),
        )
    }
}
fn request() -> Request<Body> {
    Request::builder()
        .uri("/api/v2/backtest/runs/00000000-0000-4000-8000-000000000001")
        .body(Body::empty())
        .unwrap()
}
#[tokio::test(flavor = "current_thread")]
async fn observed_body_preserves_size_hint_data_trailers_status_and_headers() {
    let buffer = Buffer::default();
    let session = Session::new(
        Config::new(Mode::Detail, "http-frames", 128),
        buffer.clone(),
    )
    .unwrap();
    async {
        let trace = begin(&request()).unwrap();
        let mut trailer = http::HeaderMap::new();
        trailer.insert("x-check", http::HeaderValue::from_static("opaque"));
        let body = Body::new(Frames(VecDeque::from([
            Frame::data(Bytes::from_static(b"abc")),
            Frame::trailers(trailer.clone()),
        ])));
        let reply = Response::builder()
            .status(202)
            .header("x-unchanged", "yes")
            .body(body)
            .unwrap();
        let hint = reply.body().size_hint().exact();
        let headers = reply.headers().clone();
        let mut observed = response(reply, trace);
        assert_eq!(observed.status(), 202);
        assert_eq!(observed.headers(), &headers);
        assert_eq!(observed.body().size_hint().exact(), hint);
        let first = std::future::poll_fn(|cx| Pin::new(observed.body_mut()).poll_frame(cx))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(first.into_data().unwrap(), Bytes::from_static(b"abc"));
        let second = std::future::poll_fn(|cx| Pin::new(observed.body_mut()).poll_frame(cx))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(second.into_trailers().unwrap(), trailer);
        assert!(observed.body().is_end_stream());
    }
    .with_subscriber(session.dispatch().clone())
    .await;
    assert!(session.close().shutdown_complete);
    assert!(
        buffer
            .rows()
            .iter()
            .any(|r| r["operation"] == "http.response.body"
                && r["event_kind"] == "operation_end"
                && r["bytes"] == 3
                && r["work_items"] == 2
                && r["outcome"] == "ok")
    );
}
#[test]
fn dropped_body_closes_server_operation_without_claiming_delivery() {
    let buffer = Buffer::default();
    let session =
        Session::new(Config::new(Mode::Detail, "http-drop", 128), buffer.clone()).unwrap();
    let reply = tracing::dispatcher::with_default(session.dispatch(), || {
        let trace = begin(&request()).unwrap();
        response(Response::new(Body::from("not delivered")), trace)
    });
    drop(reply);
    assert!(session.close().shutdown_complete);
    let rows = buffer.rows();
    assert!(rows.iter().any(|r| r["operation"] == "http.backtest.get"
        && r["event_kind"] == "operation_end"
        && r["outcome"] == "dropped"));
    assert!(
        !rows
            .iter()
            .any(|r| r["event_kind"] == "operation_end" && r["outcome"] == "ok")
    );
}
