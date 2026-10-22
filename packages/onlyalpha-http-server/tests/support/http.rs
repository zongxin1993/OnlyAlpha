//! Shared actual loopback HTTP test client; never a business acceptance shortcut.
use axum::body::{Body, to_bytes};
use http::{HeaderMap, StatusCode};
use hyper_util::rt::TokioIo;
use onlyalpha_http_server::ingress::LocalIngress;
use tokio::net::{TcpListener, TcpStream};
pub async fn request(
    ingress: &LocalIngress,
    listener: &TcpListener,
    method: &str,
    path: &str,
    headers: &[(&str, &str)],
    body: &str,
) -> (StatusCode, HeaderMap, Vec<u8>) {
    let stream = TcpStream::connect(listener.local_addr().unwrap())
        .await
        .unwrap();
    let (server, _) = listener.accept().await.unwrap();
    let owned = ingress.clone();
    let driver = tokio::spawn(async move { owned.serve_connection(server).await });
    let (mut sender, connection) = hyper::client::conn::http1::handshake(TokioIo::new(stream))
        .await
        .unwrap();
    let client = tokio::spawn(connection);
    let mut builder = http::Request::builder().method(method).uri(path);
    if !headers.iter().any(|(key, _)| *key == "host") {
        builder = builder.header("host", "127.0.0.1:5173");
    }
    for (key, value) in headers {
        builder = builder.header(*key, *value);
    }
    let response = sender
        .send_request(builder.body(Body::from(body.to_owned())).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let headers = response.headers().clone();
    let bytes = to_bytes(Body::new(response.into_body()), 8 * 1024 * 1024)
        .await
        .unwrap()
        .to_vec();
    drop(sender);
    driver.await.unwrap().unwrap();
    client.await.unwrap().unwrap();
    (status, headers, bytes)
}
