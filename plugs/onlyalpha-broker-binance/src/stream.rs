use super::*;
use zeroize::Zeroizing;
pub(crate) fn subscribe_frame(
    keys: &Credentials,
    id: &str,
    timestamp: u64,
    window: u64,
) -> Result<Zeroizing<String>> {
    if !(1..=60000).contains(&window) {
        return Err(err("BINANCE_RECV_WINDOW"));
    }
    let payload = Zeroizing::new(format!(
        "apiKey={}&recvWindow={window}&timestamp={timestamp}",
        keys.key.as_str()
    ));
    let signature = keys.sign(payload.as_bytes())?;
    Ok(Zeroizing::new(json!({"id":id,"method":"userDataStream.subscribe.signature","params":{"apiKey":keys.key.as_str(),"timestamp":timestamp,"recvWindow":window,"signature":signature}}).to_string()))
}
pub(crate) fn subscription_id(id: &str, raw: &Value) -> Result<u64> {
    if raw["id"] != id || raw["status"] != 200 || !raw["error"].is_null() {
        return Err(err("BINANCE_SUBSCRIPTION_ACK"));
    }
    raw["result"]["subscriptionId"]
        .as_u64()
        .ok_or_else(|| err("BINANCE_SUBSCRIPTION_ID"))
}
pub(crate) fn terminated_subscription(id: u64, raw: &Value) -> Result<bool> {
    let e = &raw["event"];
    if e["e"] != "eventStreamTerminated" {
        return Ok(false);
    }
    if raw["subscriptionId"].as_u64() != Some(id)
        || raw.as_object().map(|o| o.len()) != Some(2)
        || e.as_object().map(|o| o.len()) != Some(2)
    {
        return Err(err("BINANCE_STREAM_SESSION"));
    }
    ns(&e["E"])?;
    Ok(true)
}
pub(crate) fn subscription_event(id: u64, raw: &Value) -> Result<&Value> {
    let event = &raw["event"];
    if raw["subscriptionId"].as_u64() != Some(id)
        || !matches!(
            event["e"].as_str(),
            Some("executionReport" | "outboundAccountPosition")
        )
    {
        return Err(err("BINANCE_STREAM_RECONCILIATION_REQUIRED"));
    }
    Ok(event)
}

use crate::private_http::{Budget, Native};
use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use tokio_tungstenite::{
    Connector, MaybeTlsStream, WebSocketStream,
    tungstenite::{Message, protocol::WebSocketConfig},
};
pub(crate) type Socket = WebSocketStream<MaybeTlsStream<tokio::net::TcpStream>>;
impl Native {
    pub(crate) fn open_socket(&self, id: &str, budget: &Budget) -> Result<Vec<u8>> {
        self.socket.borrow_mut().take();
        let (socket, reply) = self.sync(budget, async {
            let config = WebSocketConfig::default()
                .read_buffer_size(16 * 1024)
                .write_buffer_size(16 * 1024)
                .max_write_buffer_size(self.limit + 16 * 1024)
                .max_message_size(Some(self.limit))
                .max_frame_size(Some(self.limit));
            let (mut socket, _) = tokio_tungstenite::connect_async_tls_with_config(
                self.ws.as_str(),
                Some(config),
                true,
                Some(Connector::Rustls(Arc::clone(&self.tls))),
            )
            .await
            .map_err(|_| err("BINANCE_WS_CONNECT"))?;
            let request = subscribe_frame(&self.keys, id, self.timestamp()?, self.window)?;
            socket
                .send(Message::Text(request.as_str().into()))
                .await
                .map_err(|_| err("BINANCE_WS_SEND"))?;
            let reply = next_text(&mut socket).await?;
            Ok((socket, reply))
        })?;
        self.socket.replace(Some(socket));
        Ok(reply)
    }
    pub(crate) fn read_socket(&self, b: &Budget) -> Result<Vec<u8>> {
        let mut socket = self
            .socket
            .borrow_mut()
            .take()
            .ok_or_else(|| err("BINANCE_WS_DISCONNECTED"))?;
        let raw = self.sync(b, next_text(&mut socket))?;
        self.socket.replace(Some(socket));
        Ok(raw)
    }
}
async fn next_text(socket: &mut Socket) -> Result<Vec<u8>> {
    loop {
        match socket.next().await {
            Some(Ok(Message::Text(s))) => return Ok(s.as_bytes().to_vec()),
            Some(Ok(Message::Ping(_))) => {
                socket.flush().await.map_err(|_| err("BINANCE_WS_PONG"))?
            }
            Some(Ok(Message::Pong(_))) => (),
            _ => return Err(err("BINANCE_WS_DISCONNECTED")),
        }
    }
}
